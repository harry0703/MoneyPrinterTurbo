"""영상 소재 캐시의 통계, 미리보기, 정리 서비스."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Iterator

from loguru import logger

from app.utils import utils


# 온라인 소재는 URL 의 MD5 를 안정적인 파일명으로 쓴다. 캐시 관리는 이 명명 형식만
# 받아들여, 사용자가 실수로 디렉터리에 넣어 둔 영상·설명 파일·기타 업무 파일을
# 캐시로 오인해 삭제하지 않도록 한다.
_VIDEO_CACHE_FILE_PATTERN = re.compile(r"^vid-[0-9a-f]{32}\.mp4$")
_SECONDS_PER_DAY = 24 * 60 * 60


@dataclass(frozen=True)
class VideoCacheStats:
    """캐시 디렉터리의 가벼운 통계 결과. 파일 시스템 메타데이터만 담는다."""

    file_count: int = 0
    total_size: int = 0
    oldest_mtime: float | None = None
    newest_mtime: float | None = None


@dataclass(frozen=True)
class VideoCacheCleanupResult:
    """한 번의 정리 실행 결과. 일부 파일 삭제 실패를 허용한다."""

    deleted_count: int = 0
    deleted_size: int = 0
    failed_count: int = 0


@dataclass(frozen=True)
class _VideoCacheEntry:
    """스캔 단계에서 보관하는 최소 파일 정보. 정리할 때 영상을 열거나 해석하지 않기 위해서다."""

    path: str
    name: str
    size: int
    mtime: float


def video_cache_dir() -> str:
    """프로젝트가 관리하는 기본 영상 캐시 디렉터리를 반환한다."""

    return os.path.realpath(utils.storage_dir("cache_videos"))


def _iter_video_cache_entries() -> Iterator[_VideoCacheEntry]:
    """
    기본 캐시 디렉터리의 첫 번째 계층을 순차적으로 스캔한다.

    ``os.scandir`` 을 쓰는 이유는 캐시가 수만 개 파일에 이를 때 디렉터리 순회가 돌려주는
    메타데이터를 재사용하기 위해서다. ``Path.iterdir`` 뒤에 파일 타입을 다시 조회하지
    않아도 된다. 여기서는 재귀하지 않고, 영상을 열지도 않으며, FFmpeg 도 호출하지 않는다.
    따라서 소요 시간은 영상 총 용량이 아니라 파일 개수에 선형으로 비례한다.
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
                # 심볼릭 링크를 따라가지 않아, 정리 로직이 기본 캐시 디렉터리 경계를 넘지 않게 한다.
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
    """캐시 디렉터리가 비어 있더라도 잘못된 정리 파라미터는 일관되게 거부해야 한다."""
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
    전체 캐시를 집계하거나, 수정 시각이 지정한 일수보다 오래된 정리 대상 캐시를 미리 본다.

    ``max_age_days=None`` 은 전체 캐시를 뜻한다. 집계 과정은 디렉터리 항목의 크기와
    수정 시각만 읽고 영상 내용은 읽지 않으므로, 캐시 총 용량이 커도 용량에 비례하는
    I/O 가 발생하지 않는다.
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
    기본 영상 캐시를 정리하고, 사용자에게 보여 줄 수 있는 요약 결과를 반환한다.

    화면에서 미리 보는 시점과 실제로 정리를 누르는 시점 사이에 시간이 꽤 벌어질 수
    있으므로, 실행할 때 다시 스캔하고 판단해야 하며 예전 후보 목록을 재사용하면 안 된다.
    삭제는 파일 단위로 오류를 견딘다. 개별 파일이 사용 중이거나 권한이 부족하면 경고를
    남기고 계속 진행해, 수백 개 중 하나의 문제 파일 때문에 정리 전체가 실패하지 않게 한다.
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

    # 스캔하면서 바로 삭제하고, 전체 후보 목록을 메모리에 들고 있지 않는다. 디렉터리가
    # 수십만 개 파일로 늘어나도 정리 과정의 추가 메모리는 상수 수준으로 유지된다.
    # 실행 중에는 동일한 now 를 쓰는데, 정리가 오래 걸릴 때 기준 시각이 계속 움직여
    # 후보 범위를 예측할 수 없게 되는 것을 막기 위해서다.
    for entry in _iter_video_cache_entries():
        if not _is_cleanup_candidate(entry, max_age_days, now):
            continue
        candidate_count += 1
        candidate_size += entry.size
        try:
            # entry.path 는 기본 디렉터리 첫 계층의 scandir 에서 나온다. 삭제 전에 상위 디렉터리와
            # 파일명을 한 번 더 검증해, 나중에 스캔 로직을 고칠 때 삭제 가능 범위가 의도치 않게
            # 넓어지는 것을 막는다.
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
