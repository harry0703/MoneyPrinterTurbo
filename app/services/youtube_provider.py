from __future__ import annotations

import importlib
import os
import shutil
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse, urlunparse

from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect
from app.utils import utils

_YOUTUBE_SEARCH_LIMIT = 20
_YOUTUBE_MIN_DURATION_SECONDS = 20
_YOUTUBE_MAX_DURATION_SECONDS = 5 * 60
_PREFERRED_ASPECT_RATIO = 16 / 9


def _load_yt_dlp():
    try:
        return importlib.import_module("yt_dlp")
    except Exception as exc:
        logger.error(
            "youtube provider is unavailable because yt-dlp could not be imported: "
            f"error={type(exc).__name__}, detail={exc}"
        )
        return None


def _get_tls_verify() -> bool:
    tls_verify = config.app.get("tls_verify", True)
    if isinstance(tls_verify, str):
        tls_verify = tls_verify.strip().lower() not in {"0", "false", "no", "off"}
    return bool(tls_verify)


def _get_proxy_url() -> str:
    proxy = config.proxy or {}
    for key in ("https", "http", "all"):
        value = proxy.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _build_yt_dlp_options() -> dict[str, Any]:
    """
    Provide yt-dlp with explicit runtime locations when the workspace already has
    them available.

    yt-dlp enables only Deno by default for JavaScript extraction. This project
    ships with Node in the workspace, so we prefer Node to avoid repeated JS
    runtime warnings. We also reuse the ffmpeg binary bundled with imageio-ffmpeg
    when available, so yt-dlp can merge formats without requiring a system ffmpeg.
    """
    options: dict[str, Any] = {}

    node_path = shutil.which("node")
    if node_path:
        options["js_runtimes"] = {"node": {"path": node_path}}

    ffmpeg_location = str(config.app.get("ffmpeg_path", "") or "").strip()
    if not ffmpeg_location:
        try:
            import imageio_ffmpeg

            ffmpeg_location = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg_location = ""

    if ffmpeg_location:
        options["ffmpeg_location"] = ffmpeg_location

    return options


def _safe_public_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _normalize_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _video_id_from_url(video_url: str) -> str:
    parsed = urlparse(str(video_url or "").strip())
    if parsed.scheme and parsed.netloc:
        query = parse_qs(parsed.query)
        video_id = query.get("v", [""])[0].strip()
        if video_id:
            return video_id
        path_parts = [part for part in parsed.path.split("/") if part]
        if "shorts" in path_parts and path_parts[-1]:
            return path_parts[-1]
        if path_parts and path_parts[-1]:
            return path_parts[-1]
    return str(video_url or "").strip()


def _canonical_watch_url(info: dict[str, Any]) -> str | None:
    video_id = str(info.get("id") or "").strip()
    if not video_id:
        return None
    return f"https://www.youtube.com/watch?v={video_id}"


def _creator_info(info: dict[str, Any]) -> dict[str, str] | None:
    creator: dict[str, str] = {}
    creator_id = info.get("channel_id") or info.get("uploader_id")
    creator_name = info.get("channel") or info.get("uploader")
    creator_page = _safe_public_url(
        info.get("channel_url") or info.get("uploader_url") or info.get("url")
    )
    if creator_id not in (None, ""):
        creator["id"] = str(creator_id)
    if creator_name not in (None, ""):
        creator["name"] = str(creator_name)
    if creator_page:
        creator["profile_page"] = creator_page
    return creator or None


def _is_short_form(info: dict[str, Any]) -> bool:
    webpage_url = str(info.get("webpage_url") or info.get("original_url") or "")
    title = str(info.get("title") or "")
    duration = _normalize_int(info.get("duration")) or 0

    if "/shorts/" in webpage_url.lower() or "/shorts/" in title.lower():
        return True
    if "#shorts" in title.lower():
        return True
    return duration > 0 and duration < _YOUTUBE_MIN_DURATION_SECONDS


def _is_livestream(info: dict[str, Any]) -> bool:
    live_status = str(info.get("live_status") or "").lower()
    if info.get("is_live"):
        return True
    return live_status in {"is_live", "is_upcoming"}


def _is_restricted(info: dict[str, Any]) -> bool:
    availability = str(info.get("availability") or "").lower()
    if info.get("is_private"):
        return True
    if availability in {
        "private",
        "premium_only",
        "subscriber_only",
        "needs_auth",
        "unavailable",
    }:
        return True
    age_limit = _normalize_int(info.get("age_limit")) or 0
    return age_limit > 0


def _best_video_format(info: dict[str, Any]) -> dict[str, Any] | None:
    formats = info.get("formats")
    if not isinstance(formats, list):
        return None

    def format_score(fmt: dict[str, Any]) -> tuple[int, int, int, int, int]:
        width = _normalize_int(fmt.get("width")) or 0
        height = _normalize_int(fmt.get("height")) or 0
        ext = str(fmt.get("ext") or "").lower()
        vcodec = str(fmt.get("vcodec") or "").lower()
        return (
            height,
            width,
            1 if ext == "mp4" else 0,
            1 if vcodec != "none" else 0,
            (
                -_normalize_int(fmt.get("format_id"))
                if str(fmt.get("format_id") or "").isdigit()
                else 0
            ),
        )

    video_formats = [
        fmt
        for fmt in formats
        if isinstance(fmt, dict)
        and str(fmt.get("vcodec") or "").lower() != "none"
    ]
    if not video_formats:
        return None
    return max(video_formats, key=format_score)


def _best_dimensions(info: dict[str, Any]) -> tuple[int, int, str | None]:
    best_format = _best_video_format(info)
    if best_format:
        width = _normalize_int(best_format.get("width")) or 0
        height = _normalize_int(best_format.get("height")) or 0
        format_id = best_format.get("format_id")
        return width, height, str(format_id) if format_id not in (None, "") else None

    width = _normalize_int(info.get("width")) or 0
    height = _normalize_int(info.get("height")) or 0
    format_id = info.get("format_id")
    return width, height, str(format_id) if format_id not in (None, "") else None


def _aspect_score(width: int, height: int) -> float:
    if width <= 0 or height <= 0:
        return 0.0
    aspect_ratio = width / height
    delta = abs(aspect_ratio - _PREFERRED_ASPECT_RATIO)
    return max(0.0, 1.0 - delta)


def _candidate_score(info: dict[str, Any]) -> tuple[float, int, int, int]:
    width, height, _ = _best_dimensions(info)
    duration = _normalize_int(info.get("duration")) or 0
    score = 0.0

    if height >= 1080:
        score += 100_000.0
    score += float(height) * 1_000.0
    score += float(width) * 10.0
    score += _aspect_score(width, height) * 25_000.0
    if width >= height:
        score += 5_000.0
    if 20 <= duration <= _YOUTUBE_MAX_DURATION_SECONDS:
        score += float(duration)
    if duration > 180:
        score += 250.0
    return score, height, width, duration


def _prepare_source_info(
    info: dict[str, Any],
    *,
    search_term: str,
) -> dict[str, Any]:
    width, height, format_id = _best_dimensions(info)
    asset_id = str(info.get("id") or "").strip()
    source_page = _safe_public_url(
        info.get("webpage_url")
        or info.get("original_url")
        or _canonical_watch_url(info)
    )
    source_info: dict[str, Any] = {
        "provider": "youtube",
        "search_term": search_term,
        "asset_id": asset_id or None,
        "source_page": source_page,
        "creator": _creator_info(info),
        "rendition": {
            "id": format_id or "bestvideo+bestaudio/best",
            "width": width or None,
            "height": height or None,
        },
    }
    return {key: value for key, value in source_info.items() if value not in (None, "")}


@dataclass(frozen=True)
class _ResolvedCandidate:
    info: dict[str, Any]
    score: tuple[float, int, int, int]


class _YoutubeDLLogger:
    def debug(self, msg):
        logger.debug(f"yt-dlp: {msg}")

    def info(self, msg):
        logger.info(f"yt-dlp: {msg}")

    def warning(self, msg):
        logger.warning(f"yt-dlp: {msg}")

    def error(self, msg):
        logger.error(f"yt-dlp: {msg}")


class YoutubeProvider:
    def __init__(self, search_limit: int = _YOUTUBE_SEARCH_LIMIT) -> None:
        self.search_limit = search_limit

    def search(
        self,
        search_term: str,
        minimum_duration: int,
        video_aspect: VideoAspect = VideoAspect.portrait,
    ) -> list[MaterialInfo]:
        del video_aspect
        yt_dlp = _load_yt_dlp()
        if yt_dlp is None:
            return []

        effective_min_duration = max(
            _YOUTUBE_MIN_DURATION_SECONDS, int(minimum_duration or 0)
        )
        query = f"ytsearch{self.search_limit}:{search_term}"
        logger.info(
            f"searching videos on youtube: term={search_term!r}, query={query!r}"
        )

        try:
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "nocheckcertificate": not _get_tls_verify(),
                "proxy": _get_proxy_url() or None,
                "logger": _YoutubeDLLogger(),
            }
            ydl_opts.update(_build_yt_dlp_options())
            with yt_dlp.YoutubeDL(
                ydl_opts
            ) as ydl:
                response = ydl.extract_info(query, download=False)
        except Exception as exc:
            logger.error(
                "youtube search failed: "
                f"error={type(exc).__name__}, detail={exc}"
            )
            return []

        entries = response.get("entries") if isinstance(response, dict) else None
        if not isinstance(entries, list) or not entries:
            logger.info(f"youtube search returned no entries for term={search_term!r}")
            return []

        resolved: list[_ResolvedCandidate] = []
        seen_video_ids: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue

            video_id = str(entry.get("id") or "").strip()
            if not video_id or video_id in seen_video_ids:
                continue
            seen_video_ids.add(video_id)

            if _is_short_form(entry) or _is_livestream(entry) or _is_restricted(entry):
                continue

            webpage_url = str(entry.get("webpage_url") or "").strip()
            if not webpage_url:
                webpage_url = _canonical_watch_url(entry) or ""
            if not webpage_url:
                continue

            try:
                ydl_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "noplaylist": True,
                    "nocheckcertificate": not _get_tls_verify(),
                    "proxy": _get_proxy_url() or None,
                    "logger": _YoutubeDLLogger(),
                }
                ydl_opts.update(_build_yt_dlp_options())
                with yt_dlp.YoutubeDL(
                    ydl_opts
                ) as ydl:
                    detailed = ydl.extract_info(webpage_url, download=False)
            except Exception as exc:
                logger.warning(
                    "youtube video metadata fetch failed: "
                    f"video_id={video_id}, error={type(exc).__name__}, detail={exc}"
                )
                continue

            if not isinstance(detailed, dict):
                continue

            duration = _normalize_int(detailed.get("duration")) or 0
            if duration < effective_min_duration or duration > _YOUTUBE_MAX_DURATION_SECONDS:
                continue
            if (
                _is_short_form(detailed)
                or _is_livestream(detailed)
                or _is_restricted(detailed)
            ):
                continue

            candidate = _ResolvedCandidate(
                info=detailed,
                score=_candidate_score(detailed),
            )
            resolved.append(candidate)

        if not resolved:
            logger.info(f"youtube search found no eligible videos for term={search_term!r}")
            return []

        resolved.sort(key=lambda item: item.score, reverse=True)
        best = resolved[0].info
        width, height, format_id = _best_dimensions(best)
        logger.info(
            "youtube selected video: "
            f"title={best.get('title')!r}, "
            f"video_id={best.get('id')!r}, "
            f"duration={_normalize_int(best.get('duration')) or 0}s, "
            f"resolution={width}x{height}, "
            f"format={format_id or 'unknown'}"
        )

        items: list[MaterialInfo] = []
        for candidate in resolved:
            info = candidate.info
            duration = _normalize_int(info.get("duration")) or 0
            if duration < effective_min_duration or duration > _YOUTUBE_MAX_DURATION_SECONDS:
                continue

            item = MaterialInfo()
            item.provider = "youtube"
            item.url = str(info.get("webpage_url") or _canonical_watch_url(info) or "")
            item.duration = duration
            item.source_info = _prepare_source_info(info, search_term=search_term)
            if item.url:
                items.append(item)

        return items

    def download(self, video_url: str, save_dir: str = "") -> str:
        yt_dlp = _load_yt_dlp()
        if yt_dlp is None:
            return ""

        save_dir = save_dir or utils.storage_dir("cache_videos")
        os.makedirs(save_dir, exist_ok=True)

        video_id = _video_id_from_url(video_url)
        video_hash = utils.md5(video_id or str(video_url))
        video_path = os.path.join(save_dir, f"vid-{video_hash}.mp4")
        if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
            logger.info(f"youtube video already exists: {video_path}")
            return video_path

        video_prefix = os.path.splitext(video_path)[0]
        logger.info(
            "downloading youtube video: "
            f"video_id={video_id or 'unknown'}, save_path={video_path}"
        )

        ydl_opts: dict[str, Any] = {
            "format": "bv*+ba/b",
            "merge_output_format": "mp4",
            "remuxvideo": "mp4",
            "outtmpl": f"{video_prefix}.%(ext)s",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": not _get_tls_verify(),
            "logger": _YoutubeDLLogger(),
        }
        ydl_opts.update(_build_yt_dlp_options())
        proxy_url = _get_proxy_url()
        if proxy_url:
            ydl_opts["proxy"] = proxy_url

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.download([video_url])
        except Exception as exc:
            logger.error(
                "youtube download failed: "
                f"video_id={video_id or 'unknown'}, "
                f"error={type(exc).__name__}, detail={exc}"
            )
            return ""

        if result != 0:
            logger.error(
                f"youtube download failed: video_id={video_id or 'unknown'}, "
                f"result_code={result}"
            )
            return ""

        if not os.path.exists(video_path) or os.path.getsize(video_path) <= 0:
            logger.error(
                f"youtube download completed without a valid file: {video_path}"
            )
            return ""

        clip = None
        try:
            clip = VideoFileClip(video_path)
            if clip.duration > 0 and clip.fps > 0:
                logger.success(f"youtube video saved: {video_path}")
                return video_path
        except Exception as exc:
            logger.warning(
                f"invalid youtube video file: {video_path} => {str(exc)}"
            )
            try:
                os.remove(video_path)
            except Exception as remove_error:
                logger.warning(
                    "failed to remove invalid youtube video file: "
                    f"{video_path}, error: {str(remove_error)}"
                )
        finally:
            if clip is not None:
                try:
                    clip.close()
                except Exception as close_error:
                    logger.warning(
                        "failed to close youtube video clip: "
                        f"{video_path}, error: {str(close_error)}"
                    )

        return ""

    def get_video(self, item: MaterialInfo, save_dir: str = "") -> str:
        return self.download(item.url, save_dir=save_dir)
