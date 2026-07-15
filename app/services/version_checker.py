"""检查 MoneyPrinterTurbo 是否存在可用的新正式版本。"""

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
# 更新检查只是辅助功能，网络异常不能明显拖慢本地 WebUI。连接与读取分别限制
# 超时时间，既允许 GitHub 在普通网络下完成响应，也避免离线环境长时间等待。
RELEASE_CHECK_TIMEOUT: Final = (1.0, 2.0)
RELEASE_CHECK_HEADERS: Final = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "MoneyPrinterTurbo-Version-Checker",
}
UPDATE_CHECK_CACHE_TTL_SECONDS: Final = 12 * 60 * 60


def _parse_version(value: str) -> Version:
    """兼容 GitHub 常用的 ``v1.2.3`` 标签并转换为可比较版本。"""
    normalized = str(value or "").strip()
    if normalized.lower().startswith("v"):
        normalized = normalized[1:]
    return Version(normalized)


def get_available_update(current_version: str) -> str | None:
    """
    返回高于当前版本的最新正式版本；没有更新或检查失败时返回 ``None``。

    GitHub 的 ``releases/latest`` 接口会自动排除草稿和预发布版本，因此这里不再
    重复实现发布状态筛选。WebUI 通过 ``AsyncUpdateChecker`` 在后台调用本函数；
    网络、响应格式或版本标签异常时只记录日志并降级为“不显示通知”，不影响
    视频生成等核心功能。
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
        # 更新检查失败属于可恢复的非核心异常。保留异常类型和信息便于定位代理、
        # DNS、GitHub 限流或响应损坏问题，同时避免在 WebUI 中打扰普通用户。
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
    """后台版本检查的即时状态，供 WebUI 无阻塞地读取。"""

    complete: bool
    available_version: str | None = None


class AsyncUpdateChecker:
    """
    在后台线程中执行版本检查，并缓存最近一次结果。

    Streamlit 会在任意控件交互后从头执行页面脚本。如果直接在标题区域访问
    GitHub，首次打开或缓存失效时会阻塞整个页面。这里将网络请求放入守护线程，
    页面只读取当前快照；检查完成后由 WebUI 的短期 fragment 刷新一次结果。

    结果无论是“发现更新”还是“没有更新/网络失败”都会缓存，避免 GitHub
    不可访问时每次 rerun 都重新请求。锁只保护内存状态，不包裹网络请求，因而
    不会阻塞其它会话读取检查状态。
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
        """立即返回检查快照；缓存过期时在后台启动一次新检查。"""
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

            # 版本发生变化或缓存过期时，旧结果不应继续展示。先清空状态再启动
            # 新线程，使调用方在检查期间得到明确的 pending 快照。
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
            # get_available_update 已处理预期的网络和数据异常。此处是后台线程的
            # 最后保护边界，必须记录完整堆栈，避免意外异常静默终止后永久 pending。
            logger.exception(
                "unexpected error while checking for a MoneyPrinterTurbo update"
            )
            available_version = None

        with self._lock:
            # 极少数情况下运行期间版本可能变化。旧线程不得覆盖新版本的状态。
            if self._current_version != current_version:
                return
            self._available_version = available_version
            self._completed_at = self._clock()
            self._checking = False


_ASYNC_UPDATE_CHECKER = AsyncUpdateChecker()


def poll_available_update(current_version: str) -> UpdateCheckSnapshot:
    """读取全局后台检查器状态，避免不同 Streamlit 会话重复请求 GitHub。"""
    return _ASYNC_UPDATE_CHECKER.poll(current_version)
