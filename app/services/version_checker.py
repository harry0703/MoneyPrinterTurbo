"""MoneyPrinterTurbo 의 새 정식 버전이 있는지 확인한다."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

import requests
from loguru import logger
from packaging.version import InvalidVersion, Version


LATEST_RELEASE_API_URL: Final = (
    "https://api.github.com/repos/harry0703/MoneyPrinterTurbo/releases/latest"
)
LATEST_RELEASE_PAGE_URL: Final = (
    "https://github.com/harry0703/MoneyPrinterTurbo/releases/latest"
)
# 업데이트 확인은 보조 기능이므로, 네트워크 이상이 로컬 WebUI 를 눈에 띄게 느리게 해서는
# 안 된다. 연결과 읽기에 각각 타임아웃을 걸어, 보통 네트워크에서는 GitHub 가 응답을
# 마칠 수 있게 하면서 오프라인 환경에서 오래 기다리는 일도 막는다.
RELEASE_CHECK_TIMEOUT: Final = (1.0, 2.0)
RELEASE_CHECK_HEADERS: Final = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "MoneyPrinterTurbo-Version-Checker",
}
UPDATE_CHECK_CACHE_TTL_SECONDS: Final = 12 * 60 * 60


def _parse_version(value: str) -> Version:
    """GitHub 에서 흔히 쓰는 ``v1.2.3`` 태그를 받아 비교 가능한 버전으로 변환한다."""
    normalized = str(value or "").strip()
    if normalized.lower().startswith("v"):
        normalized = normalized[1:]
    return Version(normalized)


def get_available_update(current_version: str) -> str | None:
    """
    현재 버전보다 높은 최신 정식 버전을 반환한다. 업데이트가 없거나 확인에 실패하면
    ``None`` 을 반환한다.

    GitHub 의 ``releases/latest`` 엔드포인트는 초안과 사전 릴리스를 자동으로 제외하므로,
    여기서 릴리스 상태 필터링을 중복 구현하지 않는다. WebUI 는 ``AsyncUpdateChecker`` 를
    통해 이 함수를 백그라운드에서 호출한다. 네트워크, 응답 형식, 버전 태그에 이상이 있으면
    로그만 남기고 '알림을 표시하지 않음' 으로 기능을 낮추며, 영상 생성 같은 핵심 기능에는
    영향을 주지 않는다.
    """
    try:
        installed_version = _parse_version(current_version)
    except InvalidVersion:
        logger.warning(
            f"skip update check because current version is invalid: {current_version!r}"
        )
        return None

    try:
        response = requests.get(
            LATEST_RELEASE_API_URL,
            headers=RELEASE_CHECK_HEADERS,
            timeout=RELEASE_CHECK_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        # 업데이트 확인 실패는 복구 가능한 비핵심 예외다. 예외 종류와 정보를 남겨 두면
        # 프록시, DNS, GitHub 요청 제한, 응답 손상 문제를 찾기 쉬우면서도 WebUI 에서
        # 일반 사용자를 방해하지 않는다.
        logger.debug(
            "GitHub release check failed: "
            f"error_type={type(exc).__name__}, error={exc}"
        )
        return None

    if not isinstance(payload, dict):
        logger.debug(
            "GitHub release check returned an invalid payload: "
            f"payload_type={type(payload).__name__}"
        )
        return None

    tag_name = payload.get("tag_name", "")
    try:
        latest_version = _parse_version(tag_name)
    except InvalidVersion:
        logger.warning(
            f"skip update notification because release tag is invalid: {tag_name!r}"
        )
        return None

    if latest_version <= installed_version:
        return None

    normalized_latest_version = str(latest_version)
    logger.info(
        "MoneyPrinterTurbo update available: "
        f"current={installed_version}, latest={normalized_latest_version}"
    )
    return normalized_latest_version


@dataclass(frozen=True)
class UpdateCheckSnapshot:
    """백그라운드 버전 확인의 현재 상태. WebUI 가 블로킹 없이 읽어 간다."""

    complete: bool
    available_version: str | None = None


class AsyncUpdateChecker:
    """
    백그라운드 스레드에서 버전 확인을 수행하고 가장 최근 결과를 캐시한다.

    Streamlit 은 어떤 위젯을 조작하든 페이지 스크립트를 처음부터 다시 실행한다. 제목
    영역에서 GitHub 에 직접 접근하면 첫 실행이나 캐시 만료 때 페이지 전체가 멈춘다.
    여기서는 네트워크 요청을 데몬 스레드에 넣고 페이지는 현재 스냅샷만 읽는다. 확인이
    끝나면 WebUI 의 단기 fragment 가 결과를 한 번 갱신한다.

    '업데이트 발견' 이든 '업데이트 없음/네트워크 실패' 든 결과는 모두 캐시한다. GitHub 에
    접근할 수 없을 때 rerun 마다 다시 요청하는 것을 막기 위해서다. 락은 메모리 상태만
    보호하고 네트워크 요청을 감싸지 않으므로, 다른 세션이 확인 상태를 읽는 것을 막지 않는다.
    """

    def __init__(
        self,
        check: Callable[[str], str | None] = get_available_update,
        ttl_seconds: float = UPDATE_CHECK_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._check = check
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._current_version: str | None = None
        self._available_version: str | None = None
        self._completed_at: float | None = None
        self._checking = False

    def poll(self, current_version: str) -> UpdateCheckSnapshot:
        """확인 스냅샷을 즉시 반환한다. 캐시가 만료됐으면 백그라운드에서 새 확인을 한 번 시작한다."""
        normalized_current_version = str(current_version or "").strip()
        now = self._clock()

        with self._lock:
            cache_is_fresh = (
                self._current_version == normalized_current_version
                and self._completed_at is not None
                and now - self._completed_at < self._ttl_seconds
            )
            if cache_is_fresh:
                return UpdateCheckSnapshot(
                    complete=True,
                    available_version=self._available_version,
                )

            if (
                self._checking
                and self._current_version == normalized_current_version
            ):
                return UpdateCheckSnapshot(complete=False)

            # 버전이 바뀌었거나 캐시가 만료됐으면 예전 결과를 계속 보여 주면 안 된다.
            # 상태를 먼저 비우고 새 스레드를 시작해, 확인이 진행되는 동안 호출자가 명확한
            # pending 스냅샷을 받게 한다.
            self._current_version = normalized_current_version
            self._available_version = None
            self._completed_at = None
            self._checking = True

            worker = threading.Thread(
                target=self._run_check,
                args=(normalized_current_version,),
                name="mpt-version-check",
                daemon=True,
            )
            worker.start()

        return UpdateCheckSnapshot(complete=False)

    def _run_check(self, current_version: str) -> None:
        try:
            available_version = self._check(current_version)
        except Exception:
            # get_available_update 이 예상되는 네트워크·데이터 예외는 이미 처리했다. 여기는
            # 백그라운드 스레드의 마지막 보호 경계이므로 스택 전체를 기록해야 한다. 그러지
            # 않으면 예기치 못한 예외로 조용히 종료된 뒤 영원히 pending 으로 남는다.
            logger.exception(
                "unexpected error while checking for a MoneyPrinterTurbo update"
            )
            available_version = None

        with self._lock:
            # 아주 드물게 실행 중 버전이 바뀔 수 있다. 예전 스레드가 새 버전의 상태를 덮어써서는 안 된다.
            if self._current_version != current_version:
                return
            self._available_version = available_version
            self._completed_at = self._clock()
            self._checking = False


_ASYNC_UPDATE_CHECKER = AsyncUpdateChecker()


def poll_available_update(current_version: str) -> UpdateCheckSnapshot:
    """전역 백그라운드 체커 상태를 읽는다. 서로 다른 Streamlit 세션이 GitHub 에 중복 요청하는 것을 막는다."""
    return _ASYNC_UPDATE_CHECKER.poll(current_version)
