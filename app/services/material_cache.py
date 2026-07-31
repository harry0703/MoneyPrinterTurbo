"""온라인 소재 검색 결과의 디스크 캐시."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

from loguru import logger

from app.models.schema import MaterialInfo, VideoAspect
from app.utils import utils


MATERIAL_SEARCH_CACHE_TTL_SECONDS = 24 * 60 * 60
_CACHE_FORMAT_VERSION = 2
_CACHE_CLEANUP_INTERVAL_SECONDS = 60 * 60
_CACHE_FILE_PATTERN = re.compile(r"^[0-9a-f]{64}\.json$")

# API 는 기본적으로 여러 영상 작업이 동시에 실행되는 것을 허용한다. 고정 개수의 락 샤드를
# 쓰면 같은 검색 조건이 하나의 락을 공유하면서도, 키워드마다 Lock 을 영구 보관해 메모리가
# 계속 늘어나는 것을 피할 수 있다. 이 락은 현재 프로세스 안의 동시 요청을 합치는 역할만
# 한다. 프로세스 간 쓰기의 무결성은 여전히 임시 파일과 os.replace 가 보장한다.
_CACHE_LOCKS = tuple(threading.Lock() for _ in range(256))
_cleanup_state_lock = threading.Lock()
_last_cleanup_monotonic: float | None = None


def _safe_public_url(value) -> str | None:
    """공개 페이지 URL 의 쿼리 파라미터와 사용자 자격 증명을 제거해, 캐시에 토큰이 저장되지 않게 한다."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _cached_source_info(item: MaterialInfo) -> dict | None:
    """
    화이트리스트에 따라 디스크에 저장할 출처 정보를 구성한다.

    검색 키워드는 이미 캐시 키에 들어 있으므로 캐시 내용에 평문으로 다시 쓰지 않고, 읽을 때
    호출 파라미터로 복원한다. 다운로드 URL 은 ``MaterialInfo.url`` 이 따로 보관한다. 여기서는
    공개 소재 페이지, 작성자 공개 페이지, 안정적인 업무 식별자만 허용해 임의의 확장 필드가
    디스크 캐시에 들어가지 않게 한다.
    """
    source = item.source_info
    if not isinstance(source, dict) or not source:
        return None

    cached: dict = {
        "provider": str(source.get("provider") or item.provider),
    }
    asset_id = source.get("asset_id")
    source_page = _safe_public_url(source.get("source_page"))
    if asset_id not in (None, ""):
        cached["asset_id"] = str(asset_id)
    if source_page:
        cached["source_page"] = source_page

    raw_creator = source.get("creator")
    if isinstance(raw_creator, dict):
        creator = {}
        creator_id = raw_creator.get("id")
        creator_name = raw_creator.get("name")
        creator_page = _safe_public_url(raw_creator.get("profile_page"))
        if creator_id not in (None, ""):
            creator["id"] = str(creator_id)
        if creator_name not in (None, ""):
            creator["name"] = str(creator_name)
        if creator_page:
            creator["profile_page"] = creator_page
        if creator:
            cached["creator"] = creator

    raw_rendition = source.get("rendition")
    if isinstance(raw_rendition, dict):
        rendition = {}
        for field in ("id", "width", "height"):
            value = raw_rendition.get(field)
            if value not in (None, ""):
                rendition[field] = str(value) if field == "id" else value
        if rendition:
            cached["rendition"] = rendition
    return cached


def _cache_dir() -> Path:
    """
    모든 실행 진입점이 공유하는 소재 검색 캐시 디렉터리를 반환한다.

    캐시는 WebUI 세션이나 프로세스 메모리가 아니라 ``storage`` 아래에 있어야 한다. 그래야
    WebUI, API, CLI 는 물론 Docker 재시작 이후의 작업도 같은 결과를 재사용할 수 있다.
    """
    return Path(utils.storage_dir("cache_material_search", create=True))


def _cache_key(
    provider: str,
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect | str,
) -> str:
    """
    검색 결과에 영향을 주는 업무 파라미터로 안정적인 파일명을 만든다.

    API 키는 인증만 담당하고 공개 검색 결과에는 영향을 주지 않으므로, 캐시 키나 캐시 내용에
    써서는 안 된다. SHA-256 을 쓰면 키워드가 파일명에 그대로 드러나지 않으면서 경로 길이도
    일정하게 유지된다.
    """
    aspect_value = getattr(video_aspect, "value", video_aspect)
    cache_key = json.dumps(
        {
            "provider": str(provider).strip().lower(),
            "search_term": str(search_term).strip(),
            "minimum_duration": int(minimum_duration),
            "video_aspect": str(aspect_value),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(cache_key.encode("utf-8")).hexdigest()


def _cache_path(
    provider: str,
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect | str,
) -> Path:
    digest = _cache_key(
        provider=provider,
        search_term=search_term,
        minimum_duration=minimum_duration,
        video_aspect=video_aspect,
    )
    return _cache_dir() / f"{digest}.json"


def get_material_search_cache_lock(
    provider: str,
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect | str,
) -> threading.Lock:
    """현재 검색 조건에 해당하는 프로세스 내 락 샤드를 반환한다."""
    digest = _cache_key(
        provider=provider,
        search_term=search_term,
        minimum_duration=minimum_duration,
        video_aspect=video_aspect,
    )
    return _CACHE_LOCKS[int(digest[:8], 16) % len(_CACHE_LOCKS)]


def _remove_invalid_cache(cache_path: Path) -> None:
    """만료됐거나 해석할 수 없는 캐시 파일 하나를 삭제한다. 실패해도 소재 검색 주 흐름에는 영향을 주지 않는다."""
    try:
        cache_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning(
            f"failed to remove invalid material search cache: "
            f"file={cache_path.name}, error={exc}"
        )


def load_material_search_cache(
    provider: str,
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect | str,
    *,
    now: float | None = None,
) -> list[MaterialInfo] | None:
    """
    아직 24 시간 유효 기간 안에 있는 소재 검색 결과를 읽는다.

    ``None`` 은 캐시 미스를 뜻하며 원격 API 를 호출해야 한다. 빈 목록은 유효한 캐시로
    반환하지 않는다. 네트워크 오류나 상위 서비스 이상이 잘못 캐시되어 이후 작업을 계속
    막는 것을 피하기 위해서다.
    """
    if str(provider).strip().lower() == "coverr":
        # Coverr 의 다운로드 주소에는 API 키에 묶인 서명 JWT 가 들어 있다. 이 주소는 현재
        # 요청에만 쓰이며 디스크 캐시에 들어가서는 안 된다. 같은 조건을 조회할 때 예전
        # 버전이 남겼을 수 있는 캐시도 함께 지운다.
        try:
            _remove_invalid_cache(
                _cache_path(
                    provider=provider,
                    search_term=search_term,
                    minimum_duration=minimum_duration,
                    video_aspect=video_aspect,
                )
            )
        except Exception as exc:
            logger.warning(
                "failed to remove disabled Coverr material search cache: "
                f"error={type(exc).__name__}, detail={exc}"
            )
        return None

    try:
        cache_path = _cache_path(
            provider=provider,
            search_term=search_term,
            minimum_duration=minimum_duration,
            video_aspect=video_aspect,
        )
    except Exception as exc:
        # 캐시 디렉터리 생성이나 경로 해석 예외가 원격 소재 검색을 막아서는 안 된다. 여기서는
        # 예외 종류와 정보를 온전히 남겨 권한이나 마운트 문제를 짚기 쉽게 하면서, 캐시
        # 미스로 간주하고 주 흐름을 이어 간다.
        logger.warning(
            "failed to prepare material search cache: "
            f"operation=read, error={type(exc).__name__}, detail={exc}"
        )
        return None
    try:
        stat_result = cache_path.stat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning(
            f"failed to inspect material search cache: "
            f"file={cache_path.name}, error={exc}"
        )
        return None

    current_time = time.time() if now is None else now
    cache_age = current_time - stat_result.st_mtime
    # 시스템 시각이 되돌아갔거나 파일을 다른 머신에서 복사해 오면 mtime 이 미래일 수 있다.
    # 이때 캐시를 오래도록 신선한 데이터로 취급해서는 안 되며, 바로 무효화하고 원격을
    # 다시 호출하는 편이 더 안전하다.
    if cache_age < 0 or cache_age >= MATERIAL_SEARCH_CACHE_TTL_SECONDS:
        _remove_invalid_cache(cache_path)
        return None

    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            payload = json.load(cache_file)

        if (
            not isinstance(payload, dict)
            or payload.get("version") != _CACHE_FORMAT_VERSION
            or not isinstance(payload.get("items"), list)
            or not payload["items"]
        ):
            raise ValueError("invalid cache payload")

        items = []
        for raw_item in payload["items"]:
            if not isinstance(raw_item, dict):
                raise ValueError("invalid material item")
            item_provider = raw_item.get("provider")
            item_url = raw_item.get("url")
            item_duration = raw_item.get("duration")
            source_info = raw_item.get("source_info")
            if (
                not isinstance(item_provider, str)
                or not item_provider
                or not isinstance(item_url, str)
                or not item_url
                or isinstance(item_duration, bool)
                or not isinstance(item_duration, (int, float))
                or item_duration <= 0
                or not isinstance(source_info, dict)
                or not source_info
            ):
                raise ValueError("invalid material fields")
            source_info = dict(source_info)
            source_info["search_term"] = search_term
            items.append(
                MaterialInfo(
                    provider=item_provider,
                    url=item_url,
                    duration=int(item_duration),
                    source_info=source_info,
                )
            )
    except (OSError, ValueError, TypeError) as exc:
        logger.warning(
            f"failed to load material search cache: file={cache_path.name}, error={exc}"
        )
        _remove_invalid_cache(cache_path)
        return None

    logger.info(
        f"material search cache hit: provider={provider}, "
        f"term={search_term!r}, items={len(items)}"
    )
    return items


def save_material_search_cache(
    provider: str,
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect | str,
    items: Iterable[MaterialInfo],
) -> bool:
    """
    성공한 비어 있지 않은 소재 검색 결과를 원자적으로 저장한다.

    여러 작업이 같은 키워드를 동시에 검색할 수 있다. 같은 디렉터리의 고유 임시 파일에 먼저
    쓴 뒤 ``os.replace`` 로 게시하면, 읽는 프로세스는 온전한 예전 파일이거나 온전한 새 파일만
    보게 된다. 쓰는 프로세스 둘이 동시에 끝나더라도 최종 내용은 같은 캐시 키에 대응하는
    올바른 결과다.
    """
    if str(provider).strip().lower() == "coverr":
        return False

    temp_path = None
    try:
        serialized_items = []
        for item in items:
            source_info = _cached_source_info(item)
            if not item.url or item.duration <= 0 or not source_info:
                continue
            serialized_items.append(
                {
                    "provider": item.provider,
                    "url": item.url,
                    "duration": int(item.duration),
                    "source_info": source_info,
                }
            )
        if not serialized_items:
            return False

        cache_path = _cache_path(
            provider=provider,
            search_term=search_term,
            minimum_duration=minimum_duration,
            video_aspect=video_aspect,
        )
        cleanup_expired_material_search_cache()
        payload = {
            "version": _CACHE_FORMAT_VERSION,
            "items": serialized_items,
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=cache_path.parent,
            prefix=f".{cache_path.stem}-",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(
                payload,
                temp_file,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            temp_file.flush()
            os.fsync(temp_file.fileno())

        os.replace(temp_path, cache_path)
        return True
    except Exception as exc:
        logger.warning(
            "failed to save material search cache: "
            f"error={type(exc).__name__}, detail={exc}"
        )
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        return False


def cleanup_expired_material_search_cache(
    *,
    now: float | None = None,
    force: bool = False,
) -> int:
    """
    다시 조회되지 않은 만료 검색 캐시를 낮은 빈도로 정리한다.

    정상 쓰기 경로는 디렉터리를 시간당 최대 한 번만 스캔해, 검색할 때마다 선형 디렉터리
    순회가 발생하지 않게 한다. ``force`` 는 테스트나 명시적 유지보수 호출 전용이다.
    SHA-256 이름의 JSON 파일만 삭제하며, 사용자가 디렉터리에 넣어 둔 다른 파일은 건드리지 않는다.
    """
    global _last_cleanup_monotonic

    monotonic_now = time.monotonic()
    with _cleanup_state_lock:
        if (
            not force
            and _last_cleanup_monotonic is not None
            and monotonic_now - _last_cleanup_monotonic
            < _CACHE_CLEANUP_INTERVAL_SECONDS
        ):
            return 0
        _last_cleanup_monotonic = monotonic_now

    try:
        cache_dir = _cache_dir()
        entries = os.scandir(cache_dir)
    except Exception as exc:
        logger.warning(
            "failed to scan material search cache: "
            f"error={type(exc).__name__}, detail={exc}"
        )
        return 0

    current_time = time.time() if now is None else now
    deleted_count = 0
    failed_count = 0
    with entries:
        for entry in entries:
            if not _CACHE_FILE_PATTERN.fullmatch(entry.name):
                continue
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                cache_age = current_time - entry.stat(follow_symlinks=False).st_mtime
                if 0 <= cache_age < MATERIAL_SEARCH_CACHE_TTL_SECONDS:
                    continue
                os.unlink(entry.path)
                deleted_count += 1
            except OSError as exc:
                failed_count += 1
                logger.warning(
                    "failed to delete material search cache file: "
                    f"file={entry.name}, error={exc}"
                )

    if deleted_count or failed_count:
        logger.info(
            "finished cleaning material search cache: "
            f"deleted={deleted_count}, failed={failed_count}"
        )
    return deleted_count
