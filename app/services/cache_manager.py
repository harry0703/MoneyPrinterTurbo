"""视频素材缓存的统计、预览和清理服务。"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Iterator

from loguru import logger

from app.utils import utils


# 在线素材使用 URL 的 MD5 作为稳定文件名。缓存管理只接受该命名格式，避免把
# 用户误放到目录中的视频、说明文件或其它业务文件当作缓存删除。
_VIDEO_CACHE_FILE_PATTERN = re.compile(r"^vid-[0-9a-f]{32}\.mp4$")
_SECONDS_PER_DAY = 24 * 60 * 60


@dataclass(frozen=True)
class VideoCacheStats:
    """缓存目录的轻量统计结果，只包含文件系统元数据。"""

    file_count: int = 0
    total_size: int = 0
    oldest_mtime: float | None = None
    newest_mtime: float | None = None


@dataclass(frozen=True)
class VideoCacheCleanupResult:
    """一次清理的执行结果，允许部分文件删除失败。"""

    deleted_count: int = 0
    deleted_size: int = 0
    failed_count: int = 0


@dataclass(frozen=True)
class _VideoCacheEntry:
    """扫描阶段保存的最小文件信息，避免清理时打开或解析视频。"""

    path: str
    name: str
    size: int
    mtime: float


def video_cache_dir() -> str:
    """返回项目管理的默认视频缓存目录。"""

    return os.path.realpath(utils.storage_dir("cache_videos"))


def _iter_video_cache_entries() -> Iterator[_VideoCacheEntry]:
    """
    顺序扫描默认缓存目录第一层。

    使用 ``os.scandir`` 是为了在缓存达到数万文件时复用目录遍历返回的元数据，
    避免 ``Path.iterdir`` 后再次查询文件类型。这里不递归、不打开视频，也不调用
    FFmpeg，因此耗时主要与文件数量线性相关，而不是与视频总容量相关。
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
                # 不跟随符号链接，确保清理逻辑不会越过默认缓存目录边界。
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
    """即使缓存目录为空，也应稳定拒绝无效清理参数。"""
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
    统计全部缓存，或预览修改时间早于指定天数的可清理缓存。

    ``max_age_days=None`` 表示全部缓存。统计过程只读取目录项的大小和修改时间，
    不读取视频内容，因此即使缓存总容量很大也不会产生与容量成比例的 I/O。
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
    清理默认视频缓存，并返回可向用户展示的汇总结果。

    页面预览与真正点击清理之间可能间隔较久，所以执行时必须重新扫描和判断，
    不能复用旧候选列表。删除采用逐文件容错：单个文件被占用或权限不足时记录
    警告并继续，避免几百个文件中一个异常文件导致整次清理失败。
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

    # 边扫描边删除，不在内存中保留完整候选列表。即使目录增长到几十万个文件，
    # 清理过程的额外内存仍保持常量级；执行时使用统一 now，避免长清理过程中
    # 截止时间不断移动而产生不可预测的候选范围。
    for entry in _iter_video_cache_entries():
        if not _is_cleanup_candidate(entry, max_age_days, now):
            continue
        candidate_count += 1
        candidate_size += entry.size
        try:
            # entry.path 来自默认目录的第一层 scandir；删除前再次校验父目录和
            # 文件名，防止未来修改扫描逻辑时意外扩大可删除范围。
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
