"""Statistics, preview, and cleanup service for the footage cache."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Iterator

from loguru import logger

from app.utils import utils


# Online footage uses the URL's MD5 as a stable file name. Cache management accepts only that
# naming scheme so videos, readme files, or other business files the user put in the directory are never deleted as cache.
_VIDEO_CACHE_FILE_PATTERN = re.compile(r"^vid-[0-9a-f]{32}\.mp4$")
_SECONDS_PER_DAY = 24 * 60 * 60


@dataclass(frozen=True)
class VideoCacheStats:
    """Lightweight statistics of the cache directory, containing only filesystem metadata."""

    file_count: int = 0
    total_size: int = 0
    oldest_mtime: float | None = None
    newest_mtime: float | None = None


@dataclass(frozen=True)
class VideoCacheCleanupResult:
    """Result of one cleanup run; individual file deletions may fail."""

    deleted_count: int = 0
    deleted_size: int = 0
    failed_count: int = 0


@dataclass(frozen=True)
class _VideoCacheEntry:
    """Minimal file info saved during the scan so cleanup never opens or parses videos."""

    path: str
    name: str
    size: int
    mtime: float


def video_cache_dir() -> str:
    """Return the default video cache directory managed by the project."""

    return os.path.realpath(utils.storage_dir("cache_videos"))


def _iter_video_cache_entries() -> Iterator[_VideoCacheEntry]:
    """
    Scan the first level of the default cache directory sequentially.

    ``os.scandir`` is used to reuse the metadata returned by the directory walk when the
    cache reaches tens of thousands of files, instead of querying file types again after
    ``Path.iterdir``. No recursion, no opening videos, and no FFmpeg calls, so the cost
    scales linearly with file count rather than total video capacity.
    """

    cache_dir = video_cache_dir()
    try:
        entries = os.scandir(cache_dir)
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.warning(
            f"failed to scan video cache directory: path={cache_dir}, error={exc}"
        )
        return

    with entries:
        for entry in entries:
            if not _VIDEO_CACHE_FILE_PATTERN.fullmatch(entry.name):
                continue

            try:
                # Do not follow symlinks so cleanup logic never crosses the default cache directory boundary.
                if not entry.is_file(follow_symlinks=False):
                    continue
                stat_result = entry.stat(follow_symlinks=False)
            except OSError as exc:
                logger.warning(
                    f"failed to inspect video cache file: file={entry.name}, error={exc}"
                )
                continue

            yield _VideoCacheEntry(
                path=entry.path,
                name=entry.name,
                size=stat_result.st_size,
                mtime=stat_result.st_mtime,
            )


def _is_cleanup_candidate(
    entry: _VideoCacheEntry,
    max_age_days: int | None,
    now: float,
) -> bool:
    if max_age_days is None:
        return True
    return entry.mtime < now - max_age_days * _SECONDS_PER_DAY


def _validate_max_age_days(max_age_days: int | None) -> None:
    """Reject invalid cleanup parameters even when the cache directory is empty."""
    if max_age_days is None:
        return
    if (
        isinstance(max_age_days, bool)
        or not isinstance(max_age_days, int)
        or max_age_days <= 0
    ):
        raise ValueError("max_age_days must be a positive integer or None")


def get_video_cache_stats(max_age_days: int | None = None) -> VideoCacheStats:
    """
    Count all cached files, or preview the cleanable cache whose modification time is older
    than the given number of days.

    ``max_age_days=None`` means the whole cache. Counting reads only each entry's size and
    modification time, never video content, so even a huge cache incurs no capacity-proportional I/O.
    """

    _validate_max_age_days(max_age_days)
    now = time.time()
    file_count = 0
    total_size = 0
    oldest_mtime = None
    newest_mtime = None

    for entry in _iter_video_cache_entries():
        if not _is_cleanup_candidate(entry, max_age_days, now):
            continue
        file_count += 1
        total_size += entry.size
        oldest_mtime = (
            entry.mtime if oldest_mtime is None else min(oldest_mtime, entry.mtime)
        )
        newest_mtime = (
            entry.mtime if newest_mtime is None else max(newest_mtime, entry.mtime)
        )

    return VideoCacheStats(
        file_count=file_count,
        total_size=total_size,
        oldest_mtime=oldest_mtime,
        newest_mtime=newest_mtime,
    )


def clean_video_cache(max_age_days: int | None = None) -> VideoCacheCleanupResult:
    """
    Clean the default video cache and return a summary presentable to users.

    A page preview and the actual cleanup click can be far apart in time, so execution must
    re-scan and re-decide instead of reusing the old candidate list. Deletion is per-file
    fault-tolerant: when one file is locked or lacks permissions, log a warning and continue
    so one bad file among hundreds cannot fail the entire cleanup.
    """

    _validate_max_age_days(max_age_days)
    now = time.time()
    logger.info(
        f"start cleaning video cache: max_age_days={max_age_days}"
    )

    candidate_count = 0
    candidate_size = 0
    deleted_count = 0
    deleted_size = 0
    failed_count = 0
    cache_dir = video_cache_dir()

    # Delete while scanning without keeping a full candidate list in memory. Even if the directory
    # grows to hundreds of thousands of files, the cleanup keeps constant extra memory; a unified
    # "now" is used for the run so the cutoff does not drift mid-cleanup into unpredictable ranges.
    for entry in _iter_video_cache_entries():
        if not _is_cleanup_candidate(entry, max_age_days, now):
            continue
        candidate_count += 1
        candidate_size += entry.size
        try:
            # entry.path comes from a first-level scandir of the default directory; re-validate the parent
            # directory and file name before deletion so future scan-logic changes cannot widen the deletable scope.
            if (
                os.path.realpath(os.path.dirname(entry.path)) != cache_dir
                or not _VIDEO_CACHE_FILE_PATTERN.fullmatch(entry.name)
                or os.path.islink(entry.path)
            ):
                raise ValueError("cache file is outside the managed directory")
            os.unlink(entry.path)
            deleted_count += 1
            deleted_size += entry.size
        except (OSError, ValueError) as exc:
            failed_count += 1
            logger.warning(
                f"failed to delete video cache file: file={entry.name}, error={exc}"
            )

    logger.info(
        "finished cleaning video cache: "
        f"candidates={candidate_count}, candidate_bytes={candidate_size}, "
        f"deleted={deleted_count}, deleted_bytes={deleted_size}, failed={failed_count}"
    )
    return VideoCacheCleanupResult(
        deleted_count=deleted_count,
        deleted_size=deleted_size,
        failed_count=failed_count,
    )
