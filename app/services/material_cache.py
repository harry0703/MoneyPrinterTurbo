"""在线素材搜索结果的磁盘缓存。"""

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

# API 默认允许多个视频任务并发执行。固定数量的锁分片可以让相同搜索条件共用
# 一个锁，同时避免按关键词永久保存 Lock 导致内存持续增长。它只负责合并当前
# 进程内的并发请求；跨进程写入仍由临时文件和 os.replace 保证完整性。
_CACHE_LOCKS = tuple(threading.Lock() for _ in range(256))
_cleanup_state_lock = threading.Lock()
_last_cleanup_monotonic: float | None = None


def _safe_public_url(value) -> str | None:
    """移除公开页面 URL 的查询参数和用户凭据，避免缓存意外保存 token。"""
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
    按白名单构造可落盘的来源信息。

    搜索关键词已经包含在缓存键中，不再明文写入缓存内容；读取时由调用参数
    恢复。下载 URL 由 ``MaterialInfo.url`` 单独保存，这里只允许公开素材页、
    作者公开页和稳定业务标识，避免任意扩展字段进入磁盘缓存。
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
    返回所有运行入口共用的素材搜索缓存目录。

    缓存必须位于 ``storage`` 下，而不是 WebUI session 或进程内存中，才能让
    WebUI、API、CLI 以及 Docker 重启后的任务复用同一份结果。
    """
    return Path(utils.storage_dir("cache_material_search", create=True))


def _cache_key(
    provider: str,
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect | str,
) -> str:
    """
    根据会影响搜索结果的业务参数生成稳定文件名。

    API Key 只负责鉴权，不影响公开搜索结果，因此不能写入缓存键或缓存内容。
    使用 SHA-256 可以避免关键词直接出现在文件名中，同时保持路径长度固定。
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
    """返回当前搜索条件对应的进程内锁分片。"""
    digest = _cache_key(
        provider=provider,
        search_term=search_term,
        minimum_duration=minimum_duration,
        video_aspect=video_aspect,
    )
    return _CACHE_LOCKS[int(digest[:8], 16) % len(_CACHE_LOCKS)]


def _remove_invalid_cache(cache_path: Path) -> None:
    """删除已经过期或无法解析的单个缓存文件，失败时不影响素材搜索主流程。"""
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
    读取仍在 24 小时有效期内的素材搜索结果。

    ``None`` 表示缓存未命中，需要请求远端 API；空列表不作为有效缓存返回，
    避免网络错误或上游异常被误缓存后持续阻断后续任务。
    """
    if str(provider).strip().lower() == "coverr":
        # Coverr 的下载地址包含绑定 API Key 的签名 JWT。它只用于当前请求，
        # 不能进入磁盘缓存；查询相同条件时顺带删除旧版本可能留下的缓存。
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
        # 缓存目录创建、路径解析等异常不能阻断远端素材搜索。这里保留完整异常
        # 类型和信息，便于定位权限或挂载问题，同时按缓存未命中继续主流程。
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
    # 系统时间回拨或文件从其它机器复制后，mtime 可能落在未来。此时不能把
    # 缓存长期视为新鲜数据，直接失效并重新请求远端更可靠。
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
    原子保存一次成功的非空素材搜索结果。

    多个任务可能并发搜索相同关键词。先写入同目录唯一临时文件，再通过
    ``os.replace`` 发布，可以保证读进程只会看到完整旧文件或完整新文件；
    即使两个写进程同时完成，最终内容也都是同一缓存键对应的合法结果。
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
    低频清理没有再次被查询到的过期搜索缓存。

    正常写入路径每小时最多扫描一次目录，避免每次搜索都产生线性目录遍历；
    ``force`` 仅供测试或显式维护调用。只删除 SHA-256 命名的 JSON 文件，不会
    触碰用户放入目录的其它文件。
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
