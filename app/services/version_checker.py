"""Check whether MoneyPrinterTurbo has a newer stable release available."""

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
# Update checks are auxiliary; network problems must not visibly slow the local WebUI. Connection and
# read timeouts are bounded separately so GitHub can answer on normal networks while offline environments do not wait long.
RELEASE_CHECK_TIMEOUT: Final = (1.0, 2.0)
RELEASE_CHECK_HEADERS: Final = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "MoneyPrinterTurbo-Version-Checker",
}
UPDATE_CHECK_CACHE_TTL_SECONDS: Final = 12 * 60 * 60


def _parse_version(value: str) -> Version:
    """Accept GitHub's usual ``v1.2.3`` tags and convert them into comparable versions."""
    normalized = str(value or "").strip()
    if normalized.lower().startswith("v"):
        normalized = normalized[1:]
    return Version(normalized)


def get_available_update(current_version: str) -> str | None:
    """
    Return the newest stable version above the current one, or ``None`` when there is no update
    or the check fails.

    GitHub's ``releases/latest`` endpoint already excludes drafts and prereleases, so release
    filtering is not reimplemented here. The WebUI calls this via ``AsyncUpdateChecker`` in the
    background; network, response-format, or version-tag errors are only logged and degrade to
    "show no notification" without affecting core features like video generation.
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
        # A failed update check is a recoverable, non-core exception. Keep the exception type and message for
        # diagnosing proxy, DNS, GitHub rate limiting, or corrupted responses, while never disturbing ordinary WebUI users.
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
    """Instantaneous state of the background version check, readable by the WebUI without blocking."""

    complete: bool
    available_version: str | None = None


class AsyncUpdateChecker:
    """
    Run the version check in a background thread and cache the latest result.

    Streamlit re-executes the page script after any widget interaction. Accessing GitHub directly
    in the title area would block the whole page on first open or cache expiry. The network request
    goes to a daemon thread here and the page reads only the current snapshot; once the check
    finishes, the WebUI's short-lived fragment refreshes the result once.

    Both "update found" and "no update / network failed" outcomes are cached so an unreachable
    GitHub is not re-requested on every rerun. The lock guards only in-memory state and never wraps
    the network request, so it cannot block other sessions from reading the check state.
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
        """Return the check snapshot immediately; start one new background check when the cache has expired."""
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

            # When the version changes or the cache expires, the old result must not keep showing. Clear state before
            # starting the new thread so callers get an explicit pending snapshot during the check.
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
            # get_available_update already handles expected network and data exceptions. This is the background
            # thread's last line of defense — the full stack must be logged so an unexpected exception never silently ends in a permanent pending.
            logger.exception(
                "unexpected error while checking for a MoneyPrinterTurbo update"
            )
            available_version = None

        with self._lock:
            # In rare cases the version may change at runtime. Old threads must not overwrite the new version's state.
            if self._current_version != current_version:
                return
            self._available_version = available_version
            self._completed_at = self._clock()
            self._checking = False


_ASYNC_UPDATE_CHECKER = AsyncUpdateChecker()


def poll_available_update(current_version: str) -> UpdateCheckSnapshot:
    """Read the global background checker state so different Streamlit sessions do not duplicate GitHub requests."""
    return _ASYNC_UPDATE_CHECKER.poll(current_version)
