import base64
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import io
import math
import os
import random
import tempfile
import threading
import time
import uuid
import warnings
from pathlib import Path
from typing import Any, Callable, List
from urllib.parse import quote_plus, urlencode, urlsplit, urlunsplit

import requests
from loguru import logger

from app.utils.request_logging import trace_http_call
from moviepy.video.io.VideoFileClip import VideoFileClip
from PIL import Image, UnidentifiedImageError

from app.config import config
from app.models.schema import ImageMotion, MaterialInfo, VideoAspect, VideoConcatMode
from app.services import (
    codex_image,
    generation_progress,
    infistar_video,
    jalapeno_video,
    material_cache,
    material_upload,
    metaso_minimax,
    muapi,
    ofox,
    task_artifacts,
    useapi,
    video,
    volcengine_seedance,
)
from app.utils import logging_utils, utils

# Thread-safe counter for API key rotation
_api_key_counter = 0
_api_key_lock = threading.Lock()

# A provider URL can point to an unexpectedly large object or never-ending stream.
# Short stock and generated clips should stay well below this conservative cap.
MAX_VIDEO_DOWNLOAD_BYTES = 512 * 1024 * 1024

# Serial by default, matching the old behavior; stock material concurrency can be raised in config if needed.
_DEFAULT_MATERIAL_CONCURRENCY = 1


def _get_material_concurrency() -> int:
    try:
        concurrency = int(config.app.get("material_concurrency", _DEFAULT_MATERIAL_CONCURRENCY))
    except (TypeError, ValueError):
        concurrency = _DEFAULT_MATERIAL_CONCURRENCY
    return max(1, min(8, concurrency))


class _OpenAIImageDecodeError(ValueError):
    """The bytes returned by a compatible API can't be decoded as an image; local file write failures are not included."""


class OpenAIImagePaidResultError(RuntimeError):
    """A paid image request cannot provide a usable local video material."""


class OpenAIImageUnconfirmedError(OpenAIImagePaidResultError):
    """A paid image request may have succeeded without returning a response."""


class UseAPIImageMaterialError(OpenAIImagePaidResultError):
    """Stop the useapi.net image loop; keeps the job ID when one is known."""

    def __init__(self, message: str, task_id: str = ""):
        super().__init__(message)
        self.task_id = task_id


class CodexImageMaterialError(OpenAIImagePaidResultError):
    """Stop the image loop while retaining a translatable, sanitized error."""

    def __init__(self, error):
        self.key = error.key
        self.params = error.params
        messages = {
            "codex.image.save_failed": "Could not save the generated Codex image. Generation stopped without retrying.",
            "codex.image.render_failed": "Could not render the generated Codex image. Generation stopped without retrying.",
        }
        super().__init__(messages.get(self.key, str(error)))


def _safe_public_url(value: Any) -> str | None:
    """
    Keep only publicly displayable HTTP(S) page URLs, removing query parameters and credentials.

    Material download URLs may carry API Keys, signed JWTs or temporary tokens. The task manifest only needs
    to help users get back to the provider's public material page and must not store auth parameters; URLs with user info
    are also rejected, so content like ``https://user:pass@example.com`` is never written to disk.
    """
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


def _creator_info(value: Any) -> dict[str, str] | None:
    """Extract unified public fields from the different author structures of each provider."""
    if isinstance(value, str) and value.strip():
        return {"name": value.strip()}
    if not isinstance(value, dict):
        return None

    creator: dict[str, str] = {}
    creator_id = value.get("id")
    creator_name = value.get("name") or value.get("username")
    creator_page = _safe_public_url(
        value.get("url") or value.get("profile_url") or value.get("profile_page")
    )
    if creator_id is not None:
        creator["id"] = str(creator_id)
    if creator_name:
        creator["name"] = str(creator_name)
    if creator_page:
        creator["profile_page"] = creator_page
    return creator or None


def _material_source_record(item: MaterialInfo, local_path: str) -> dict[str, Any]:
    """
    Build a lightweight source record for a successfully downloaded material.

    ``source_info`` may come from the cache or even from an externally constructed ``MaterialInfo``, so it
    can't be written as-is. Rebuild it from an allowlist here, keeping only the public page, business identifiers and dimensions,
    and recording only the local filename, so user directories or Docker mount paths don't end up in task files.
    """
    source = item.source_info if isinstance(item.source_info, dict) else {}
    record: dict[str, Any] = {
        "provider": str(item.provider or source.get("provider") or ""),
        "local_file": Path(local_path).name,
        "duration": int(item.duration),
    }

    search_term = source.get("search_term")
    asset_id = source.get("asset_id")
    source_page = _safe_public_url(source.get("source_page"))
    if isinstance(search_term, str) and search_term.strip():
        record["search_term"] = search_term.strip()
    if asset_id not in (None, ""):
        record["asset_id"] = str(asset_id)
    if source_page:
        record["source_page"] = source_page

    creator = _creator_info(source.get("creator"))
    if creator:
        record["creator"] = creator

    raw_rendition = source.get("rendition")
    if isinstance(raw_rendition, dict):
        rendition = {}
        for field in ("id", "width", "height"):
            value = raw_rendition.get(field)
            if value not in (None, ""):
                rendition[field] = str(value) if field == "id" else value
        if rendition:
            record["rendition"] = rendition
    return record


def _persist_material_sources(
    task_id: str,
    material_sources: list[dict[str, Any]],
) -> None:
    """
    Add the sources of materials that were actually downloaded successfully to the task manifest.

    The task record is an auxiliary feature: it must not change the video download function's return value, and a write failure
    must not interrupt the main video flow. ``patch_script_data`` handles atomic replacement and exception logging; here we only
    log the count on success, to confirm the task's provenance info was saved.
    """
    try:
        saved = task_artifacts.patch_script_data(
            task_id,
            material_sources=material_sources,
        )
        if saved:
            logger.info(
                f"saved material source records: "
                f"task_id={task_id}, count={len(material_sources)}"
            )
    except Exception as exc:
        # task_artifacts is already designed to degrade on failure, but keep a last layer of isolation here,
        # so future implementation changes or directory resolution errors can't accidentally affect the material download return value.
        logger.warning(
            "failed to persist material source records: "
            f"task_id={task_id}, error={type(exc).__name__}, detail={exc}"
        )


def _get_tls_verify() -> bool:
    # TLS certificate verification is on by default, preventing man-in-the-middle tampering during material search and download.
    # Only where explicitly needed, such as corporate proxies or self-signed certificates, can users
    # temporarily disable it by setting `tls_verify = false` in `config.toml`.
    tls_verify = config.app.get("tls_verify", True)
    if isinstance(tls_verify, str):
        tls_verify = tls_verify.strip().lower() not in ("0", "false", "no", "off")

    if not tls_verify:
        logger.warning(
            "TLS certificate verification is disabled by config.app.tls_verify=false. "
            "Only use this in trusted proxy environments."
        )

    return bool(tls_verify)


def get_api_key(cfg_key: str):
    api_keys = config.app.get(cfg_key)
    if not api_keys:
        raise ValueError(
            f"\n\n##### {cfg_key} is not set #####\n\n"
            f"Please set it in the config.toml file: {config.config_file}\n"
        )

    # if only one key is provided, return it
    if isinstance(api_keys, str):
        return api_keys

    global _api_key_counter
    with _api_key_lock:
        _api_key_counter += 1
        return api_keys[_api_key_counter % len(api_keys)]


def _redact_secret(message: str, secret: str) -> str:
    """
    Minimally redact exception text that is about to be logged.

    requests connection exceptions may contain the full request URL, and the Pixabay API Key is passed as a query
    parameter. Replace both the raw and URL-encoded values here, keeping network error info for troubleshooting
    while keeping the key out of log files.
    """
    safe_message = str(message)
    if not secret:
        return safe_message

    safe_message = safe_message.replace(secret, "***")
    encoded_secret = quote_plus(secret)
    if encoded_secret != secret:
        safe_message = safe_message.replace(encoded_secret, "***")
    return safe_message


def _redact_request_error(error: Exception, *secrets: str) -> str:
    """
    Keep troubleshooting info from network exceptions while removing API Keys and proxy credentials.

    Logging only the exception type loses key context such as DNS, certificate or timeout details; logging the raw exception
    may echo the full request URL. A single entry point lets all three material providers use the same redaction rules.
    """
    safe_message = str(error)
    for secret in secrets:
        safe_message = _redact_secret(safe_message, str(secret or ""))
    for proxy_url in config.proxy.values():
        safe_message = _redact_secret(safe_message, str(proxy_url))
    return safe_message


def _is_cloudflare_challenge(response: requests.Response) -> bool:
    """
    Detect an HTML Challenge returned by Cloudflare instead of treating it as Pixabay JSON.

    Cloudflare usually sets `cf-mitigated: challenge`; some deployments only return HTML containing
    "Just a moment" or challenge-platform, so content markers are kept as a fallback.
    The response body is only inspected in memory and not logged, to avoid recording large, useless chunks of HTML.
    """
    headers = getattr(response, "headers", {}) or {}
    if str(headers.get("cf-mitigated", "")).lower() == "challenge":
        return True

    content_type = str(headers.get("content-type", "")).lower()
    if "text/html" not in content_type:
        return False

    body = str(getattr(response, "text", "")).lower()
    return "just a moment" in body or "/cdn-cgi/challenge-platform/" in body


def _stock_search_results(
    provider: str, response: Any, results_key: str
) -> list | None:
    """
    Return the result list of a Pexels or Coverr search response.

    When the search failed, log why and return None. As in the Pixabay search,
    the log gets the status and content type but not the response body, and a
    401 names the setting that holds the rejected key.
    """
    status_code = int(getattr(response, "status_code", 200))
    headers = getattr(response, "headers", {}) or {}
    content_type = str(headers.get("content-type", "")) or "unknown"
    if status_code == 401:
        logger.error(
            f"{provider} rejected the API key: status=401. "
            f"Check {provider}_api_keys in config.toml."
        )
        return None
    if status_code == 429:
        logger.error(
            f"{provider} API rate limit exceeded: "
            f"status=429, retry_after={headers.get('retry-after') or 'unknown'}"
        )
        return None
    if status_code >= 400:
        logger.error(
            f"{provider} search request failed: "
            f"status={status_code}, content_type={content_type}"
        )
        return None
    try:
        body = response.json()
    except ValueError:
        logger.error(
            f"{provider} returned an unexpected non-JSON response: "
            f"status={status_code}, content_type={content_type}"
        )
        return None
    if not isinstance(body, dict) or not isinstance(body.get(results_key), list):
        logger.error(f"{provider} video search returned an unsupported response")
        return None
    return body[results_key]


def _matches_video_aspect(
    width: Any,
    height: Any,
    video_aspect: VideoAspect,
    *,
    is_vertical: Any = None,
) -> bool:
    """
    Decide whether a remote material matches the target frame orientation.

    The response fields of Pexels, Pixabay and Coverr aren't uniform, so width and height are used first for a reliable decision;
    when some historical Coverr responses lack dimensions, the explicit ``is_vertical`` boolean is used as a fallback.
    Materials whose orientation can't be confirmed are skipped, so portrait tasks don't mix in landscape materials and get black bars in the final video.
    """
    aspect = VideoAspect(video_aspect)
    try:
        normalized_width = int(float(width))
        normalized_height = int(float(height))
    except (OverflowError, TypeError, ValueError):
        normalized_width = 0
        normalized_height = 0

    if normalized_width > 0 and normalized_height > 0:
        if aspect == VideoAspect.portrait:
            return normalized_height > normalized_width
        if aspect == VideoAspect.landscape:
            return normalized_width > normalized_height
        return normalized_width == normalized_height

    if isinstance(is_vertical, bool) and aspect != VideoAspect.square:
        return is_vertical == (aspect == VideoAspect.portrait)
    return False


def _filter_materials_by_aspect(
    items: List[MaterialInfo],
    video_aspect: VideoAspect,
) -> List[MaterialInfo]:
    """
    Re-validate orientation for cached results.

    The material search cache is kept for up to 24 hours, and caches written before the upgrade may contain mismatched-orientation materials.
    Filtering at the unified cache entry makes the fix take effect immediately and also guards against third-party Providers or old caches
    missing remote filtering. Old entries whose rendition dimensions can't be read are treated as unverified and skipped.
    """
    aspect = VideoAspect(video_aspect)
    if aspect == VideoAspect.square:
        # Pixabay and Coverr rarely provide native square materials. Square output keeps the existing behavior,
        # accepting usable candidates and leaving cropping to the composition stage, so 1:1 tasks don't end up with no materials after the upgrade.
        return list(items)

    filtered_items = []
    for item in items:
        source_info = item.source_info if isinstance(item.source_info, dict) else {}
        rendition = source_info.get("rendition")
        rendition = rendition if isinstance(rendition, dict) else {}
        if _matches_video_aspect(
            rendition.get("width"),
            rendition.get("height"),
            aspect,
        ):
            filtered_items.append(item)
    return filtered_items


def search_videos_pexels(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()
    api_key = get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    }
    # Build URL
    params = {"query": search_term, "per_page": 20}
    if aspect != VideoAspect.square:
        params["orientation"] = aspect.name
    query_url = f"https://api.pexels.com/v1/videos/search?{urlencode(params)}"
    logger.info(f"searching videos on pexels: term={search_term!r}")

    try:
        r = trace_http_call(
            "GET", requests.get,
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        videos = _stock_search_results("pexels", r, "videos")
        if videos is None:
            return []
        video_items = []
        # loop through each video in the result
        for v in videos:
            if not isinstance(v, dict):
                continue
            duration = v.get("duration")
            # check if video has desired minimum duration
            if (
                isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or not math.isfinite(duration)
                or duration < minimum_duration
            ):
                continue
            video_files = v.get("video_files")
            if not isinstance(video_files, list):
                continue
            # Prefer the smallest rendition that can fill the output canvas.
            # Square output can crop either orientation, as other providers do.
            renditions = []
            for video in video_files:
                if not isinstance(video, dict):
                    continue
                try:
                    w = int(video.get("width"))
                    h = int(video.get("height"))
                except (OverflowError, TypeError, ValueError):
                    continue
                video_url = video.get("link")
                if not isinstance(video_url, str) or not video_url:
                    continue
                if (
                    (aspect == VideoAspect.square or _matches_video_aspect(w, h, aspect))
                    and w >= video_width
                    and h >= video_height
                ):
                    renditions.append((w * h, video, w, h, video_url))
            if renditions:
                _, video, w, h, video_url = min(renditions, key=lambda candidate: candidate[0])
                item = MaterialInfo()
                item.provider = "pexels"
                item.url = video_url
                item.duration = duration
                item.source_info = {
                    "provider": "pexels",
                    "search_term": search_term,
                    "asset_id": (
                        str(v.get("id")) if v.get("id") is not None else None
                    ),
                    "source_page": _safe_public_url(v.get("url")),
                    "creator": _creator_info(v.get("user")),
                    "rendition": {
                        "id": (
                            str(video.get("id"))
                            if video.get("id") is not None
                            else None
                        ),
                        "width": w,
                        "height": h,
                    },
                }
                video_items.append(item)
        return video_items
    except Exception as e:
        logger.error(
            "pexels video search failed: "
            f"error={type(e).__name__}, detail={_redact_request_error(e, api_key)}"
        )

    return []


def _pixabay_rendition_area(rendition: tuple[str, Any]) -> float:
    """Sort key for the files of a Pixabay video: pixel count, malformed last."""
    _, video = rendition
    try:
        return int(video["width"]) * int(video["height"])
    except (KeyError, OverflowError, TypeError, ValueError):
        return math.inf


def search_videos_pixabay(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)

    video_width, video_height = aspect.to_resolution()

    api_key = get_api_key("pixabay_api_keys")
    # Build URL
    params = {
        "q": search_term,
        "video_type": "all",  # Accepted values: "all", "film", "animation"
        "per_page": 50,
        "key": api_key,
    }
    query_url = f"https://pixabay.com/api/videos/?{urlencode(params)}"
    logger.info(
        f"searching videos on pixabay: term={search_term!r}, "
        f"proxy_enabled={bool(config.proxy)}"
    )

    try:
        r = trace_http_call(
            "GET", requests.get,
            query_url, proxies=config.proxy, verify=_get_tls_verify(), timeout=(30, 60)
        )
        status_code = int(getattr(r, "status_code", 200))
        headers = getattr(r, "headers", {}) or {}
        content_type = str(headers.get("content-type", ""))
        retry_after = headers.get("retry-after")
        cf_ray = headers.get("cf-ray")

        if _is_cloudflare_challenge(r):
            logger.error(
                "pixabay search was blocked by a Cloudflare challenge: "
                f"status={status_code}, cf_ray={cf_ray or 'unknown'}. "
                "Check the server network or proxy, or use Pexels/Coverr instead."
            )
            return []

        if status_code == 429:
            logger.error(
                "pixabay API rate limit exceeded: "
                f"status=429, retry_after={retry_after or 'unknown'}"
            )
            return []

        if status_code >= 400:
            logger.error(
                "pixabay search request failed: "
                f"status={status_code}, content_type={content_type or 'unknown'}"
            )
            return []

        try:
            response = r.json()
        except ValueError:
            logger.error(
                "pixabay returned an unexpected non-JSON response: "
                f"status={status_code}, content_type={content_type or 'unknown'}"
            )
            return []

        video_items = []
        if not isinstance(response, dict) or not isinstance(
            response.get("hits"), list
        ):
            logger.error("pixabay video search returned an unsupported response")
            return video_items
        videos = response["hits"]
        # loop through each video in the result
        for v in videos:
            if not isinstance(v, dict):
                continue
            duration = v.get("duration")
            # check if video has desired minimum duration
            if (
                isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or not math.isfinite(duration)
                or duration < minimum_duration
            ):
                continue
            video_files = v.get("videos")
            if not isinstance(video_files, dict):
                continue
            # Pixabay lists large (usually 3840x2160) before medium (usually
            # 1920x1080). As for Pexels, try the files from the smallest up and
            # keep the first that fills the output: a larger file only takes
            # longer to download and decode before it is scaled down.
            for video_type, video in sorted(
                video_files.items(), key=_pixabay_rendition_area
            ):
                if not isinstance(video, dict):
                    continue
                try:
                    w = int(video["width"])
                    h = int(video["height"])
                except (KeyError, OverflowError, TypeError, ValueError):
                    continue
                video_url = video.get("url")
                if not isinstance(video_url, str) or not video_url:
                    continue
                # Pixabay rarely returns native square videos; 1:1 output still accepts candidates that meet the resolution
                # and the composition stage crops them. Landscape and portrait must strictly match the target orientation.
                orientation_matches = aspect == VideoAspect.square or (
                    _matches_video_aspect(w, h, aspect)
                )
                if orientation_matches and w >= video_width and h >= video_height:
                    item = MaterialInfo()
                    item.provider = "pixabay"
                    item.url = video_url
                    item.duration = duration
                    item.source_info = {
                        "provider": "pixabay",
                        "search_term": search_term,
                        "asset_id": (
                            str(v.get("id")) if v.get("id") is not None else None
                        ),
                        "source_page": _safe_public_url(v.get("pageURL")),
                        "creator": _creator_info(
                            {
                                "id": v.get("user_id"),
                                "name": v.get("user"),
                            }
                        ),
                        "rendition": {
                            "id": video_type,
                            "width": w,
                            "height": video.get("height"),
                        },
                    }
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        error_message = _redact_request_error(e, api_key)
        logger.error(
            "pixabay search request failed: "
            f"error={type(e).__name__}, detail={error_message}"
        )

    return []


def search_videos_coverr(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    """
    Coverr (https://coverr.co) - free HD/4K stock videos,
    subject to Coverr license terms (https://coverr.co/license).

    Coverr API notes (based on official docs at api.coverr.co/docs/):
      - Auth: Authorization: Bearer <api_key>
      - Search endpoint: GET /videos?query=..., response structure {"hits": [...], ...}
      - Add ?urls=true to return direct mp4 links in the search response
      - URLs are signed JWTs (bound to the API key, no expiry)
      - Coverr supports filtering landscape/portrait materials via filter=is_vertical:true/false;
        responses are still validated locally using max_width/max_height or is_vertical
      - The duration field comes as both number and string; this function accepts both

    This function uses the urls.mp4_download field as the download URL — according to Coverr's official docs
    (https://api.coverr.co/docs/videos/#download-a-video),
    a GET of this URL is itself counted by Coverr as a legitimate download event,
    so there's no need to call PATCH /videos/:id/stats/downloads.
    """
    aspect = VideoAspect(video_aspect)
    api_key = get_api_key("coverr_api_keys")
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {
        "query": search_term,
        "page_size": 20,
        "urls": "true",
        "sort": "popular",
    }
    # Server-side orientation filtering returns target materials directly from the full search results, instead of fetching popular results first and
    # filtering locally, which left portrait candidates empty. Square materials have no matching boolean, so they still rely on local width/height checks.
    if aspect == VideoAspect.portrait:
        params["filter"] = "is_vertical:true"
    elif aspect == VideoAspect.landscape:
        params["filter"] = "is_vertical:false"
    query_url = f"https://api.coverr.co/videos?{urlencode(params)}"
    logger.info(f"searching videos on coverr: term={search_term!r}")

    try:
        r = trace_http_call(
            "GET", requests.get,
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        hits = _stock_search_results("coverr", r, "hits")
        if hits is None:
            return []
        video_items: List[MaterialInfo] = []

        for v in hits:
            if not isinstance(v, dict):
                continue
            # duration may be a number (11.625) or a string ("10.500000") in different responses
            try:
                duration = int(float(v.get("duration") or 0))
            except (OverflowError, TypeError, ValueError):
                continue
            if duration < minimum_duration:
                continue

            video_id = v.get("id")
            urls = v.get("urls")
            if not isinstance(urls, dict):
                continue
            mp4_download_url = urls.get("mp4_download")
            if (
                not video_id
                or not isinstance(mp4_download_url, str)
                or not mp4_download_url
            ):
                continue
            if aspect != VideoAspect.square and not _matches_video_aspect(
                v.get("max_width"),
                v.get("max_height"),
                aspect,
                is_vertical=v.get("is_vertical"),
            ):
                continue

            item = MaterialInfo()
            item.provider = "coverr"
            item.url = mp4_download_url
            item.duration = duration
            item.source_info = {
                "provider": "coverr",
                "search_term": search_term,
                "asset_id": str(video_id),
                "source_page": _safe_public_url(v.get("canonical_url") or v.get("url")),
                "creator": _creator_info(v.get("creator") or v.get("author")),
                "rendition": {
                    "id": "mp4_download",
                    "width": v.get("max_width"),
                    "height": v.get("max_height"),
                },
            }
            video_items.append(item)
        return video_items
    except Exception as e:
        logger.error(
            "coverr video search failed: "
            f"error={type(e).__name__}, detail={_redact_request_error(e, api_key)}"
        )

    return []


# WaveSpeed AI (https://wavespeed.ai) generates materials directly from script keywords using text-to-video models,
# sharing the MaterialInfo result structure and the later download and editing flow with the three stock material sources.
WAVESPEED_API_BASE_URL = "https://api.wavespeed.ai/api/v3"
WAVESPEED_DEFAULT_T2V_MODEL = "bytedance/seedance-2.0-fast/text-to-video"
WAVESPEED_POLL_INTERVAL_SECONDS = 2.0
WAVESPEED_RUN_TIMEOUT_SECONDS = 600.0
# The default model bytedance/seedance-2.0-fast/text-to-video only accepts 4-15 seconds; requests outside
# that range are rejected by the API. The WebUI default clip duration is 3 seconds, so it must be clamped to the model's
# supported range before submitting; any extra duration is trimmed to the clip duration by the existing editing flow.
WAVESPEED_MIN_DURATION_SECONDS = 4
WAVESPEED_MAX_DURATION_SECONDS = 15
# The three failure states mean different things (model error / user cancelled / platform timeout), but for the material flow they all mean
# this keyword produced nothing, so they're all treated as an empty result and the upper layer skips the clip and keeps generating.
WAVESPEED_FAILURE_STATUSES = frozenset({"failed", "cancelled", "timeout"})
# Same policy as WaveSpeed's official Python SDK / n8n node: 429 and 5xx are transient
# failures worth a limited number of backoff retries; 4xx are clear client errors and fail fast.
WAVESPEED_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
# Number of consecutive transient failures allowed per poll. One unlucky GET must not lose track of a task that's already billed.
WAVESPEED_MAX_POLL_RETRIES = 5
# Linear backoff base; the n-th retry waits base * n seconds.
WAVESPEED_RETRY_BASE_SECONDS = 1.0
# Number of retries against the same signed URL when downloading the output fails. The material is already paid for, so retry the original
# URL first; a single download hiccup must not resubmit another paid generation task.
WAVESPEED_MAX_DOWNLOAD_RETRIES = 2


class WaveSpeedUnconfirmedTaskError(RuntimeError):
    """
    A paid generation task was submitted, but its final state can't be confirmed locally.

    This exception never means "the task failed and can be retried": the remote task may still be running or may already have
    completed and been billed. The material flow must stop here and not submit new paid tasks for later keywords,
    and pass the submitted prediction id to the task state so it can be recovered manually.
    """

    def __init__(self, message: str, prediction_id: str = ""):
        super().__init__(message)
        self.prediction_id = prediction_id


class WaveSpeedDownloadError(RuntimeError):
    """A paid prediction completed, but its video could not be saved locally."""

    def __init__(self, message: str, prediction_id: str = ""):
        super().__init__(message)
        self.prediction_id = prediction_id


def _wavespeed_status_code(response: Any) -> int:
    """Read the response status code; treat it as 200 when a test double or exception object lacks the field."""
    try:
        return int(getattr(response, "status_code", 200))
    except (TypeError, ValueError):
        return 200


def _is_wavespeed_retryable_error(error: Exception) -> bool:
    """
    Decide whether a polling exception is worth retrying.

    Network exceptions such as connection errors and timeouts have no status code and are treated as transient; responses with a status code are only
    retried on 429 and 5xx, matching the retry set of the official SDK.
    """
    if isinstance(
        error,
        (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ),
    ):
        return True
    response = getattr(error, "response", None)
    if response is not None:
        return _wavespeed_status_code(response) in WAVESPEED_RETRYABLE_STATUS_CODES
    return False


def _wavespeed_duration_bounds() -> tuple[int, int]:
    """
    Return the generation duration range (seconds) supported by the current model.

    The default range matches the default Seedance model; when users switch to another text-to-video model they can
    adjust the range in config accordingly. Any invalid config falls back to the default and guarantees min <= max,
    so user input isn't turned into a remote request that's bound to fail.
    """

    def read_bound(key: str, fallback: int) -> int:
        try:
            value = int(config.app.get(key, fallback))
        except (TypeError, ValueError):
            return fallback
        return value if value >= 1 else fallback

    min_duration = read_bound("wavespeed_min_duration", WAVESPEED_MIN_DURATION_SECONDS)
    max_duration = read_bound("wavespeed_max_duration", WAVESPEED_MAX_DURATION_SECONDS)
    return min_duration, max(max_duration, min_duration)


def generate_videos_wavespeed(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    """
    Generate one material clip for a script keyword with a WaveSpeed text-to-video model.

    Keeps the same signature and empty-list-on-failure convention as the stock sources' search_videos_*,
    so it plugs directly into the generic download and duration accounting flow of ``download_videos``.
    In the generation context, ``minimum_duration`` is the target clip duration (seconds).
    """
    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()
    api_key = get_api_key("wavespeed_api_keys")
    model_id = (
        str(
            config.app.get("wavespeed_text_to_video_model", "")
            or WAVESPEED_DEFAULT_T2V_MODEL
        )
        .strip()
        .strip("/")
    )
    headers = {"Authorization": f"Bearer {api_key}"}
    requested_duration = max(int(minimum_duration), 1)
    min_duration, max_duration = _wavespeed_duration_bounds()
    duration = min(max(requested_duration, min_duration), max_duration)
    if duration != requested_duration:
        # Generating longer than requested doesn't affect the final video: editing still trims to the clip duration; generating shorter
        # than requested only happens when the request exceeds the model's maximum, in which case it can only be clamped to the maximum.
        logger.info(
            f"wavespeed clip duration clamped to model-supported range: "
            f"requested={requested_duration}s, using={duration}s "
            f"(supported {min_duration}-{max_duration}s)"
        )
    payload = {
        "prompt": search_term,
        "aspect_ratio": aspect.value,
        "duration": duration,
    }
    logger.info(
        f"generating video on wavespeed: model={model_id}, "
        f"term={search_term!r}, duration={duration}s"
    )

    # The POST submission is never retried automatically: the request may already have created a paid task remotely, and resending would cause
    # duplicate generation and duplicate charges (consistent with the official SDK's submission policy).
    generation_progress.submitting("wavespeed")
    try:
        submit_response = trace_http_call(
            "POST", requests.post,
            f"{WAVESPEED_API_BASE_URL}/{model_id}",
            json=payload,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
    except Exception as e:
        # Not receiving a response doesn't mean no task was created. The state is unknown, so the whole generation
        # flow must stop, rather than submitting a new paid task for the next keyword.
        raise WaveSpeedUnconfirmedTaskError(
            "wavespeed submission did not return a response, the task may "
            "already exist remotely: "
            f"error={type(e).__name__}, detail={_redact_request_error(e, api_key)}"
        ) from e

    submit_status = _wavespeed_status_code(submit_response)
    if submit_status >= 500:
        # A 5xx may happen after the task was created, so we can't tell whether it was billed.
        raise WaveSpeedUnconfirmedTaskError(
            f"wavespeed submission failed with HTTP {submit_status}, "
            "the task may already exist remotely"
        )
    try:
        submit_body = submit_response.json()
    except Exception as e:
        if 400 <= submit_status < 500:
            # A 4xx from a gateway or auth layer may be plain text/HTML. A 4xx is still a clear rejection;
            # no remote task was created, so it must not be misreported as "possibly billed" and abort the whole task.
            logger.error(
                "wavespeed video generation request rejected: "
                f"http_status={submit_status}, unreadable body: {type(e).__name__}"
            )
            return []
        raise WaveSpeedUnconfirmedTaskError(
            "wavespeed submission returned an unreadable response, the task "
            f"may already exist remotely: error={type(e).__name__}"
        ) from e

    submit_data = submit_body.get("data") if isinstance(submit_body, dict) else None
    if not isinstance(submit_body, dict) or submit_body.get("code") != 200:
        # 4xx and business error codes are clear rejections; no remote task was created, so there's no risk of duplicate
        # billing. Following the existing material source convention, return an empty result and continue.
        logger.error(
            "wavespeed video generation request rejected: "
            f"http_status={submit_status}, "
            f"code={submit_body.get('code') if isinstance(submit_body, dict) else None}, "
            f"detail={_redact_secret(str((submit_body or {}).get('message') or ''), api_key)}"
        )
        return []
    prediction_id = (
        str(submit_data.get("id") or "") if isinstance(submit_data, dict) else ""
    )
    if not prediction_id:
        # Submission was accepted but no ID was returned: the task may exist but can't be tracked, so no more orders can be placed.
        raise WaveSpeedUnconfirmedTaskError(
            "wavespeed accepted the submission without returning a prediction id"
        )
    # A successful submission has a remote billing side effect, so log the task ID first;
    # even if later polling fails, users can still recover the output in the WaveSpeed console by ID.
    logger.info(f"wavespeed prediction created: id={prediction_id}")

    result_data = _wait_for_wavespeed_prediction(
        prediction_id=prediction_id,
        headers=headers,
        api_key=api_key,
    )
    if result_data is None:
        return []

    try:
        video_items = []
        outputs = result_data.get("outputs")
        for output in outputs if isinstance(outputs, list) else []:
            # The output URL is a signed temporary download address and must be kept intact (query parameters
            # can't be stripped), so it isn't written into source_info and is only used for the immediate download.
            if not isinstance(output, str) or not output.startswith(
                ("http://", "https://")
            ):
                continue
            item = MaterialInfo()
            item.provider = "wavespeed"
            item.url = output
            item.duration = duration
            item.source_info = {
                "provider": "wavespeed",
                "search_term": search_term,
                "asset_id": prediction_id,
                "rendition": {
                    "id": None,
                    "width": video_width,
                    "height": video_height,
                },
            }
            video_items.append(item)
        if not video_items:
            logger.error(
                "wavespeed prediction completed without downloadable outputs: "
                f"id={prediction_id}"
            )
        return video_items
    except Exception as e:
        # The output was already generated and billed, so this exception can only come from local parsing. Log it and return an empty result,
        # letting the upper layer skip this clip; the task state itself is definite, so later clips can continue.
        logger.error(
            "wavespeed output parsing failed: "
            f"id={prediction_id}, error={type(e).__name__}, "
            f"detail={_redact_request_error(e, api_key)}"
        )

    return []


def _wait_for_wavespeed_prediction(
    *,
    prediction_id: str,
    headers: dict,
    api_key: str,
) -> dict | None:
    """
    Poll the same prediction id until there is a definite result.

    Returns the ``completed`` data; when the remote side clearly failed (failed / cancelled / timeout)
    returns None, meaning the task has ended and later clips can safely continue. Transient failures are retried on the same ID
    with linear backoff, never resubmitting the task; when the state can never be confirmed it raises
    :class:`WaveSpeedUnconfirmedTaskError`, and the caller aborts the whole generation flow.
    """
    deadline = time.monotonic() + WAVESPEED_RUN_TIMEOUT_SECONDS
    generation_progress.remote("wavespeed", prediction_id)
    consecutive_failures = 0
    while True:
        try:
            response = trace_http_call(
                "GET", requests.get,
                f"{WAVESPEED_API_BASE_URL}/predictions/{prediction_id}/result",
                headers=headers,
                proxies=config.proxy,
                verify=_get_tls_verify(),
                timeout=(30, 60),
            )
            status_code = _wavespeed_status_code(response)
            if status_code in WAVESPEED_RETRYABLE_STATUS_CODES:
                raise requests.exceptions.HTTPError(
                    f"HTTP {status_code}", response=response
                )
            result_body = response.json()
            result_data = (
                result_body.get("data") if isinstance(result_body, dict) else None
            )
            if not isinstance(result_body, dict) or result_body.get("code") != 200:
                # When polling is clearly rejected (e.g. 4xx) the task state is still unknown: the task was submitted,
                # we just can't find the result locally, so no new paid tasks may be submitted either.
                raise WaveSpeedUnconfirmedTaskError(
                    "wavespeed prediction status is unknown: "
                    f"http_status={status_code}, "
                    f"code={result_body.get('code') if isinstance(result_body, dict) else None}, "
                    f"detail={_redact_secret(str((result_body or {}).get('message') or ''), api_key)}",
                    prediction_id=prediction_id,
                )
            if not isinstance(result_data, dict):
                raise WaveSpeedUnconfirmedTaskError(
                    "wavespeed prediction result payload is malformed",
                    prediction_id=prediction_id,
                )
        except WaveSpeedUnconfirmedTaskError:
            raise
        except Exception as e:
            if not _is_wavespeed_retryable_error(e):
                raise WaveSpeedUnconfirmedTaskError(
                    "wavespeed prediction polling failed and the task state is "
                    f"unknown: error={type(e).__name__}, "
                    f"detail={_redact_request_error(e, api_key)}",
                    prediction_id=prediction_id,
                ) from e
            consecutive_failures += 1
            generation_progress.remote("wavespeed", prediction_id, retrying=True)
            if consecutive_failures > WAVESPEED_MAX_POLL_RETRIES:
                raise WaveSpeedUnconfirmedTaskError(
                    "wavespeed prediction polling failed after "
                    f"{WAVESPEED_MAX_POLL_RETRIES + 1} attempts, the task may "
                    "still be running remotely: "
                    f"error={type(e).__name__}, "
                    f"detail={_redact_request_error(e, api_key)}",
                    prediction_id=prediction_id,
                ) from e
            delay = WAVESPEED_RETRY_BASE_SECONDS * consecutive_failures
            logger.warning(
                "wavespeed prediction polling hit a transient error, retry the "
                f"same task: id={prediction_id}, "
                f"attempt={consecutive_failures}/{WAVESPEED_MAX_POLL_RETRIES}, "
                f"error={type(e).__name__}, retry_in={delay:.1f}s"
            )
            time.sleep(delay)
            continue

        # Reset the counter after one valid response; only consecutive failures consume the retry budget.
        consecutive_failures = 0
        status = str(result_data.get("status") or "")
        generation_progress.remote("wavespeed", prediction_id, status)
        if status == "completed":
            return result_data
        if status in WAVESPEED_FAILURE_STATUSES:
            logger.error(
                "wavespeed prediction did not produce a video: "
                f"id={prediction_id}, status={status}, "
                f"detail={_redact_secret(str(result_data.get('error') or ''), api_key)}"
            )
            return None
        if time.monotonic() > deadline:
            # The remote task is still running and its final state can't be confirmed locally, so stop placing orders.
            raise WaveSpeedUnconfirmedTaskError(
                f"wavespeed prediction is still {status or 'pending'} after "
                f"{WAVESPEED_RUN_TIMEOUT_SECONDS:.0f}s of local waiting",
                prediction_id=prediction_id,
            )
        time.sleep(WAVESPEED_POLL_INTERVAL_SECONDS)


def _save_generated_video_with_retry(
    video_url: str,
    save_dir: str,
    provider: str,
    request_headers: dict[str, str] | None = None,
) -> str:
    """
    Download an output that has already been paid for, retrying the same URL first on failure.

    Regenerating a remote task means paying again, so download hiccups must first be retried a limited number of times
    with backoff on the original URL; once retries are exhausted, the caller reports a recoverable paid-task failure.
    """
    for attempt in range(WAVESPEED_MAX_DOWNLOAD_RETRIES + 1):
        try:
            # request_headers is only set for links that need credentials,
            # such as a Google Vids file served through useapi.net.
            extra = {"request_headers": request_headers} if request_headers else {}
            saved_video_path = save_video(video_url=video_url, save_dir=save_dir, **extra)
            if saved_video_path:
                return saved_video_path
            failure_detail = "empty result"
        except Exception as e:
            if request_headers or str(video_url).startswith(useapi.DEFAULT_BASE_URL):
                # A useapi.net media link carries the account email in its
                # path, and the exception text can repeat that path; log only
                # the error type.
                failure_detail = f"error={type(e).__name__}"
            else:
                failure_detail = (
                    f"error={type(e).__name__}, "
                    f"detail={_redact_request_error(e, video_url)}"
                )
            failure_detail = useapi.mask_emails(failure_detail)
        if attempt >= WAVESPEED_MAX_DOWNLOAD_RETRIES:
            break
        delay = WAVESPEED_RETRY_BASE_SECONDS * (attempt + 1)
        logger.warning(
            "failed to download generated video, retry the same url: "
            f"provider={provider}, "
            f"attempt={attempt + 1}/{WAVESPEED_MAX_DOWNLOAD_RETRIES}, "
            f"{failure_detail}, retry_in={delay:.1f}s"
        )
        time.sleep(delay)
    logger.error(
        "failed to download generated video after "
        f"{WAVESPEED_MAX_DOWNLOAD_RETRIES + 1} attempts: "
        f"provider={provider}, {failure_detail}"
    )
    return ""


def _get_downloaded_video_duration(video_path: str) -> float:
    """Read the usable duration from the downloaded media file."""
    clip = None
    try:
        clip = VideoFileClip(video_path)
        duration = float(clip.duration or 0)
    except Exception as exc:
        raise ValueError(
            f"downloaded video duration could not be measured: {video_path}"
        ) from exc
    finally:
        if clip is not None:
            try:
                clip.close()
            except Exception as close_error:
                logger.warning(
                    "failed to close downloaded video after duration probe: "
                    f"path={video_path}, error={type(close_error).__name__}, "
                    f"detail={close_error}"
                )
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(
            f"downloaded video duration is not positive and finite: {video_path}"
        )
    return duration


# requests produces no logs while streaming a download. On slow networks a single 4K material can take minutes to download,
# and the task looks stuck. If it still hasn't finished after this interval, log the downloaded size and speed; small files that
# finish within the interval produce no extra logs, to avoid flooding.
_DOWNLOAD_HEARTBEAT_SECONDS = 15.0
_BYTES_PER_MEGABYTE = 1024 * 1024


def _describe_download_progress(
    downloaded_bytes: int, declared_size: int, elapsed_seconds: float
) -> str:
    """Format download progress as a log message; no percentage when the server didn't declare a size."""
    downloaded_mb = downloaded_bytes / _BYTES_PER_MEGABYTE
    speed = downloaded_mb / elapsed_seconds if elapsed_seconds > 0 else 0.0
    if declared_size > 0:
        percent = min(100, round(downloaded_bytes * 100 / declared_size))
        return (
            f"{downloaded_mb:.1f} of {declared_size / _BYTES_PER_MEGABYTE:.1f} MB "
            f"({percent}%), {speed:.2f} MB/s"
        )
    return f"{downloaded_mb:.1f} MB, {speed:.2f} MB/s"


def _is_valid_video_file(video_path: str) -> bool:
    """Return whether a video satisfies the cache publication contract."""
    clip = None
    try:
        # Decode the complete stream first. Unlike MoviePy's metadata probe,
        # this validator distinguishes confirmed bad media from an FFmpeg
        # execution failure through MaterialUploadError/MaterialServiceError.
        material_upload._validate_video(video_path)
    except material_upload.MaterialServiceError:
        raise
    except material_upload.MaterialUploadError as exc:
        logger.warning(f"invalid video file: {video_path} => {str(exc)}")
        return False
    except Exception as exc:
        raise material_upload.MaterialServiceError(
            "unexpected failure while validating video content"
        ) from exc

    try:
        clip = VideoFileClip(video_path)
        duration = clip.duration
        fps = clip.fps
        return bool(duration > 0 and fps > 0)
    except Exception as exc:
        # Complete decoding already succeeded. A MoviePy failure at this point
        # is an unavailable metadata probe (for example, its configured FFmpeg
        # executable is missing), not proof that the cached bytes are corrupt.
        raise material_upload.MaterialServiceError(
            "failed to probe video metadata"
        ) from exc
    finally:
        if clip is not None:
            try:
                clip.close()
            except Exception as close_error:
                logger.warning(
                    f"failed to close video clip: {video_path}, "
                    f"error: {str(close_error)}"
                )


def save_video(
    video_url: str,
    save_dir: str = "",
    request_headers: dict[str, str] | None = None,
) -> str:
    generation_progress.downloading()
    if not save_dir:
        save_dir = utils.storage_dir("cache_videos")

    os.makedirs(save_dir, exist_ok=True)

    # Query parameters can identify the asset itself (for example,
    # /download?file_id=123). Dropping the query makes unrelated paid videos
    # share one cache entry and silently reuse the first scene. Fragments are
    # not sent in HTTP requests, so they do not affect the downloaded bytes.
    url_hash = utils.md5(video_url.split("#", 1)[0])
    video_id = f"vid-{url_hash}"
    video_path = f"{save_dir}/{video_id}.mp4"

    # A nonempty path can still be a truncated file left by an older release,
    # a manual copy, or storage corruption. Validate it before declaring a hit
    # so the cache can repair itself instead of failing on every later render.
    try:
        cached_stat = os.stat(video_path)
    except FileNotFoundError:
        cached_stat = None
    if cached_stat is not None and cached_stat.st_size > 0:
        generation_progress.verifying()
        try:
            cached_video_is_valid = _is_valid_video_file(video_path)
        except material_upload.MaterialServiceError as exc:
            # Do not destroy the only local copy because the validation service
            # is temporarily unavailable. Reusing the existing nonempty cache
            # preserves the pre-validation behavior and avoids an unrecoverable
            # download attempt when a signed source URL has expired.
            logger.warning(
                f"video cache validation unavailable; preserving existing file: "
                f"{video_path} => {str(exc)}"
            )
            return video_path
        if cached_video_is_valid:
            logger.info(f"video already exists: {video_path}")
            return video_path

        logger.warning(f"discarding invalid cached video: {video_path}")
        try:
            current_stat = os.stat(video_path)
            cached_identity = (
                cached_stat.st_dev,
                cached_stat.st_ino,
                cached_stat.st_size,
                cached_stat.st_mtime_ns,
            )
            current_identity = (
                current_stat.st_dev,
                current_stat.st_ino,
                current_stat.st_size,
                current_stat.st_mtime_ns,
            )
            # Do not delete a valid replacement published by another worker
            # while this process was validating the stale entry.
            if current_identity == cached_identity:
                os.remove(video_path)
        except FileNotFoundError:
            pass

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    if request_headers:
        headers.update(request_headers)

    # A nonempty file is treated as a cache hit above. Keep the final path
    # unpublished until the complete download has passed media validation, so a
    # failed download cannot poison this or another concurrent task's cache.
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{video_id}-",
            suffix=".mp4",
            dir=save_dir,
            delete=False,
        ) as temp_file:
            temp_path = temp_file.name
            with trace_http_call(
                "GET", requests.get,
                video_url,
                headers=headers,
                proxies=config.proxy,
                verify=_get_tls_verify(),
                timeout=(60, 240),
                stream=True,
            ) as response:
                response.raise_for_status()
                headers = getattr(response, "headers", {}) or {}
                try:
                    declared_size = int(headers.get("Content-Length", ""))
                except (TypeError, ValueError):
                    declared_size = 0
                if declared_size > MAX_VIDEO_DOWNLOAD_BYTES:
                    raise ValueError("video download exceeds 512 MB limit")

                downloaded_bytes = 0
                started_at = time.monotonic()
                last_report_at = started_at
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        downloaded_bytes += len(chunk)
                        if downloaded_bytes > MAX_VIDEO_DOWNLOAD_BYTES:
                            raise ValueError("video download exceeds 512 MB limit")
                        temp_file.write(chunk)
                        now = time.monotonic()
                        if now - last_report_at >= _DOWNLOAD_HEARTBEAT_SECONDS:
                            last_report_at = now
                            generation_progress.downloading(downloaded_bytes, declared_size)
                            # Only log the cache filename: the download URL may carry signatures or keys.
                            logger.info(
                                f"downloading video {video_id}.mp4: "
                                + _describe_download_progress(
                                    downloaded_bytes,
                                    declared_size,
                                    now - started_at,
                                )
                            )

        if os.path.getsize(temp_path) == 0:
            return ""

        generation_progress.verifying()
        if not _is_valid_video_file(temp_path):
            return ""

        os.replace(temp_path, video_path)
        temp_path = ""
        return video_path
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass
            except OSError as remove_error:
                logger.warning(
                    f"failed to remove temporary video file: {temp_path}, "
                    f"error: {str(remove_error)}"
                )


# OpenAI-compatible text-to-image (Issue #1274) generates image materials for script keywords via the /images/generations protocol,
# and can point either at a local ComfyUI/SD gateway or at various OpenAI-protocol relay
# services. Generated images are immediately rendered into the same "slow zoom" mp4 clips as local materials, which is completely
# transparent to the downstream editing flow.
OPENAI_IMAGE_ENDPOINT_PATH = "images/generations"
# The official OpenAI image API only accepts sizes defined by the model and can't take a video resolution (e.g. 1080x1920) directly.
# When openai_image_size is empty, the following compatible defaults are used per aspect ratio; local gateways can override explicitly.
OPENAI_IMAGE_DEFAULT_SIZES = {
    VideoAspect.portrait: "1024x1536",
    VideoAspect.landscape: "1536x1024",
    VideoAspect.square: "1024x1024",
}
# Same retry policy as WaveSpeed: 429 and 5xx are transient failures, retried a limited number of times with backoff.
OPENAI_IMAGE_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
# 401/403 means the current key was explicitly rejected. get_api_key rotates keys on each call, so with multiple
# keys configured a retry switches keys automatically; with only one key it fails fast without pointless retries.
OPENAI_IMAGE_KEY_ERROR_STATUS_CODES = frozenset({401, 403})
OPENAI_IMAGE_MAX_ATTEMPTS = 3
OPENAI_IMAGE_MAX_BYTES = 25 * 1024 * 1024
OPENAI_IMAGE_MAX_PIXELS = 50_000_000
# Serial image generation + linear backoff, compatible with the rate-limit recovery windows common in relay services.
OPENAI_IMAGE_RETRY_BACKOFF_SECONDS = (5, 15, 30)
# Synchronous generation APIs may take tens of seconds to return an image, so the read timeout has plenty of headroom.
OPENAI_IMAGE_REQUEST_TIMEOUT = (30, 300)
# Download retries after an image is billed per piece: retry the original URL first rather than regenerating the same image.
OPENAI_IMAGE_MAX_DOWNLOAD_ATTEMPTS = 3
OPENAI_IMAGE_DOWNLOAD_BACKOFF_SECONDS = 2


def is_openai_image_enabled(app_config: dict | None = None) -> bool:
    """
    Decide whether the OpenAI-compatible text-to-image material source has the minimum required configuration.

    The API Key may be empty: a fully local ComfyUI/SD gateway usually needs no auth, and when empty
    requests carry no Authorization header. Used by task preflight and the WebUI to block tasks with missing config
    before consuming LLM and TTS quota.
    """
    app_config = config.app if app_config is None else app_config
    return bool(
        str(app_config.get("openai_image_base_url", "") or "").strip()
        and str(app_config.get("openai_image_model", "") or "").strip()
    )


def _openai_image_endpoint() -> tuple[str, str]:
    """
    Read the text-to-image endpoint and model name, raising an error with config guidance when missing.
    """
    base_url = (
        str(config.app.get("openai_image_base_url", "") or "").strip().rstrip("/")
    )
    model = str(config.app.get("openai_image_model", "") or "").strip()
    if not base_url:
        raise ValueError(
            "\n\n##### openai_image_base_url is not set #####\n\n"
            f"Please set it in the config.toml file: {config.config_file}\n"
        )
    if not model:
        raise ValueError(
            "\n\n##### openai_image_model is not set #####\n\n"
            f"Please set it in the config.toml file: {config.config_file}\n"
        )
    return f"{base_url}/{OPENAI_IMAGE_ENDPOINT_PATH}", model


def _openai_image_size(video_aspect: VideoAspect) -> str:
    """
    Resolve the requested image size.

    The official OpenAI API only accepts sizes defined by the model (e.g. 1024x1536); passing a video resolution directly
    (e.g. 1080x1920) returns 400. By default a compatible size is chosen per aspect ratio; ``openai_image_size``
    can be set explicitly to override it, for local gateways that support arbitrary resolutions (such as SD WebUI).
    """
    configured = str(config.app.get("openai_image_size", "") or "").strip()
    if configured:
        return configured
    return OPENAI_IMAGE_DEFAULT_SIZES.get(VideoAspect(video_aspect), "1024x1024")


def _openai_image_prompt(search_term: str) -> str:
    """
    Wrap a script keyword into the final prompt.

    The optional ``openai_image_prompt_template`` config supports a ``{term}`` placeholder,
    used to append consistent style modifiers (e.g. quality, composition, camera language) to improve image-text relevance:

    .. code-block:: toml

        openai_image_prompt_template = "cinematic photo of {term}, photorealistic"

    When empty or without the placeholder, the raw keyword is used, exactly like older versions. If placeholder
    substitution fails (e.g. the template contains formatting syntax by mistake), the raw text is used too, so a config error doesn't interrupt
    the whole generation task.
    """
    template = str(config.app.get("openai_image_prompt_template", "") or "").strip()
    if not template or "{term}" not in template:
        return search_term
    try:
        return template.replace("{term}", search_term)
    except Exception:
        return search_term


def _response_json_safely(response: Any) -> Any:
    """Read the response JSON; returns None when parsing fails for a test double or abnormal response."""
    try:
        return response.json()
    except Exception:
        return None


def _openai_image_response_message(body: Any) -> str:
    """
    Extract a readable error description from an OpenAI-compatible response.

    The standard format is ``{"error": {"message": ...}}``, and relay services often degrade to
    ``{"message": ...}`` or just a string. When none can be found, return an empty string and let the caller
    decide whether to fall back to the response body.
    """
    if not isinstance(body, dict):
        return str(body or "")[:300]
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or "")[:300]
    if error is not None:
        return str(error)[:300]
    return str(body.get("message") or "")[:300]


def _openai_image_http_failure(response: Any, status: int, api_key: str) -> str:
    """Turn an HTTP error response into a redacted, readable log description."""
    message = _openai_image_response_message(_response_json_safely(response))
    if not message:
        message = str(getattr(response, "text", "") or "")[:300]
    return f"HTTP {status}: {_redact_secret(message, api_key)}"


def _openai_image_download_bytes(
    image_url: str,
    api_key: str,
) -> tuple[bytes | None, str]:
    """
    Download the temporary URL of a generated image.

    The image is already billed per piece, so on download failure retry the original URL first instead of regenerating,
    avoiding paying twice for the same image. Raises when all retries fail, preventing the outer loop from buying the next image.
    """
    failure_detail = "no download attempt was made"
    for attempt in range(1, OPENAI_IMAGE_MAX_DOWNLOAD_ATTEMPTS + 1):
        response = None
        try:
            response = trace_http_call(
                "GET", requests.get,
                image_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/115.0.0.0 Safari/537.36"
                },
                proxies=config.proxy,
                verify=_get_tls_verify(),
                timeout=(30, 120),
                stream=True,
            )
            if response.status_code == 200:
                try:
                    declared_size = int(response.headers.get("Content-Length", 0))
                except (TypeError, ValueError):
                    declared_size = 0
                if declared_size > OPENAI_IMAGE_MAX_BYTES:
                    return None, "generated image exceeds the 25 MB download limit"
                image_bytes = bytearray()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    if len(image_bytes) + len(chunk) > OPENAI_IMAGE_MAX_BYTES:
                        return None, "generated image exceeds the 25 MB download limit"
                    image_bytes.extend(chunk)
                if image_bytes:
                    return bytes(image_bytes), ""
                failure_detail = "generated image download was empty"
            else:
                failure_detail = f"HTTP {response.status_code} while downloading image"
        except Exception as e:
            failure_detail = (
                f"error={type(e).__name__}, "
                f"detail={_redact_request_error(e, api_key, image_url)}"
            )
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception as exc:
                    logger.warning(
                        "failed to close generated image download response: "
                        f"error={type(exc).__name__}"
                    )
        if attempt < OPENAI_IMAGE_MAX_DOWNLOAD_ATTEMPTS:
            logger.warning(
                "generated image download failed, retrying the same url: "
                f"attempt={attempt}/{OPENAI_IMAGE_MAX_DOWNLOAD_ATTEMPTS}, "
                f"{failure_detail}"
            )
            time.sleep(OPENAI_IMAGE_DOWNLOAD_BACKOFF_SECONDS)
    raise OpenAIImagePaidResultError(
        "generated image could not be downloaded after retries"
    )


def _parse_openai_image_response(
    response: Any,
    api_key: str,
) -> tuple[bytes | None, str]:
    """
    Parse the /images/generations response and fetch the url or b64_json image data.

    A parse failure is either a clear business rejection (e.g. content policy) or an abnormal response format, so the
    error description is returned directly without backoff retries — resending the same request would only get the same result.
    """
    body = _response_json_safely(response)
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list) or not data:
        return None, _redact_secret(_openai_image_response_message(body), api_key)

    entry = data[0]
    if not isinstance(entry, dict):
        return None, "invalid image data entry"

    b64_payload = entry.get("b64_json")
    if b64_payload:
        if (
            not isinstance(b64_payload, str)
            or len(b64_payload) > 4 * ((OPENAI_IMAGE_MAX_BYTES + 2) // 3)
        ):
            return None, "generated image exceeds the 25 MB response limit"
        try:
            image_bytes = base64.b64decode(b64_payload)
        except Exception as e:
            return None, f"invalid b64_json payload: {type(e).__name__}"
        if len(image_bytes) > OPENAI_IMAGE_MAX_BYTES:
            return None, "generated image exceeds the 25 MB response limit"
        return image_bytes, ""

    image_url = entry.get("url")
    if isinstance(image_url, str) and image_url.startswith(("http://", "https://")):
        return _openai_image_download_bytes(image_url, api_key)

    return None, "image response has neither url nor b64_json"


def _request_openai_image(endpoint: str, payload: dict) -> tuple[bytes | None, str]:
    """
    Call the OpenAI-compatible /images/generations API with backoff retries and key rotation.

    429/5xx are retried with backoff as transient failures; 401/403 are retried only when multiple keys are configured
    (switching keys via get_api_key's rotation); other 4xx are clear rejections, fail fast,
    and are left to the upper layer to skip the keyword.

    Billing safety: a POST read timeout or dropped connection is treated as "unconfirmed" — the server may already have
    generated and charged, and only the response didn't come back; automatic resubmission could cause duplicate generation and duplicate
    charges, so a dedicated exception is raised to stop the local task. Only a connect-phase timeout (ConnectTimeout,
    the request definitely never reached the server) confirms that no generation task was created and is safe to retry.

    The API Key may be empty: a fully local ComfyUI/SD gateway usually needs no auth, and when empty
    no Authorization header is sent.
    """
    api_keys = config.app.get("openai_image_api_keys")
    if isinstance(api_keys, (list, tuple)):
        configured_keys = [k for k in api_keys if str(k or "").strip()]
    elif str(api_keys or "").strip():
        configured_keys = [api_keys]
    else:
        configured_keys = []

    failure_detail = "no request attempt was made"
    for attempt in range(1, OPENAI_IMAGE_MAX_ATTEMPTS + 1):
        api_key = get_api_key("openai_image_api_keys") if configured_keys else ""
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        retryable = False
        try:
            response = trace_http_call(
                "POST", requests.post,
                endpoint,
                json=payload,
                headers=headers,
                proxies=config.proxy,
                verify=_get_tls_verify(),
                timeout=OPENAI_IMAGE_REQUEST_TIMEOUT,
                allow_redirects=False,
            )
        except requests.exceptions.ConnectTimeout as e:
            # Connect-phase timeout: the request definitely didn't reach the server and no generation task was created,
            # so it is safe to retry.
            failure_detail = (
                f"connect timeout: detail={_redact_request_error(e, api_key)}"
            )
            retryable = True
        except Exception as e:
            # Read timeouts / dropped connections are "unconfirmed": the server may already have accepted and charged,
            # and resubmitting automatically or processing later keywords could double-bill, so the local task must stop.
            raise OpenAIImageUnconfirmedError(
                "unconfirmed image request (no retry to avoid double billing): "
                f"{type(e).__name__}, detail={_redact_request_error(e, api_key)}"
            ) from e
        else:
            status = int(getattr(response, "status_code", 200) or 200)
            if 300 <= status < 400:
                response.close()
                raise OpenAIImageUnconfirmedError(
                    "image submission returned a redirect; no redirected request "
                    "or retry was sent because the paid outcome is unconfirmed"
                )
            if status in OPENAI_IMAGE_KEY_ERROR_STATUS_CODES:
                failure_detail = _openai_image_http_failure(response, status, api_key)
                # Only with multiple keys configured can a retry rotate to a usable key.
                retryable = len(configured_keys) > 1
            elif status in OPENAI_IMAGE_RETRYABLE_STATUS_CODES:
                failure_detail = _openai_image_http_failure(response, status, api_key)
                retryable = True
            elif status >= 400:
                return None, _openai_image_http_failure(response, status, api_key)
            else:
                image_bytes, parse_error = _parse_openai_image_response(
                    response, api_key
                )
                if image_bytes is not None:
                    return image_bytes, ""
                failure_detail = parse_error

        if retryable and attempt < OPENAI_IMAGE_MAX_ATTEMPTS:
            backoff_seconds = OPENAI_IMAGE_RETRY_BACKOFF_SECONDS[
                min(attempt - 1, len(OPENAI_IMAGE_RETRY_BACKOFF_SECONDS) - 1)
            ]
            logger.warning(
                "openai image request failed, retrying: "
                f"attempt={attempt}/{OPENAI_IMAGE_MAX_ATTEMPTS}, "
                f"next_retry_in={backoff_seconds}s, detail={failure_detail}"
            )
            time.sleep(backoff_seconds)
            continue
        return None, failure_detail

    return None, failure_detail


def _save_openai_image_file(
    image_bytes: bytes,
    save_dir: str,
) -> tuple[str, int, int]:
    """
    Normalize the generated result to PNG on disk and return (path, width, height).

    Converting to PNG avoids two kinds of problems: relay services returning WebP/JPEG without a reliable
    extension, and images with abnormal metadata that make MoviePy fail to parse them (mirroring the sanitization of local
    materials, normalization here is done at the save stage).
    """
    if not save_dir:
        save_dir = utils.storage_dir("cache_images", create=True)
    elif not os.path.isdir(save_dir):
        os.makedirs(save_dir, exist_ok=True)

    image_path = os.path.join(save_dir, f"openai-image-{uuid.uuid4().hex[:12]}.png")
    if len(image_bytes) > OPENAI_IMAGE_MAX_BYTES:
        raise _OpenAIImageDecodeError("generated image exceeds the 25 MB limit")

    # An image decode failure can degrade to "skip the current keyword", but directory permission, disk space and file
    # write failures must keep propagating, otherwise the on-demand generation loop would keep creating
    # later paid tasks while files can't be saved locally. Image.open only reads in-memory bytes, so an OSError here is a format
    # detection failure; an OSError from image.load corresponds to truncated or corrupted image data.
    image = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(image_bytes))
            if image.width * image.height > OPENAI_IMAGE_MAX_PIXELS:
                raise ValueError("generated image exceeds the 50 million pixel limit")
            image.load()
    except (
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        if image is not None:
            image.close()
        raise _OpenAIImageDecodeError(f"{type(exc).__name__}: {exc}") from exc

    with image:
        if image.mode not in ("RGB", "RGBA", "L", "LA", "P"):
            image = image.convert("RGB")
        # save is kept out of the decode exception guard: a write error means the runtime environment is persistently unusable and the whole
        # task should stop immediately, so later keywords don't keep producing paid images that can't be saved.
        image.save(image_path, format="PNG")
        width, height = image.size
    return image_path, width, height


def generate_images_openai(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
    save_dir: str = "",
) -> List[MaterialInfo]:
    """
    Generate one image for a script keyword with an OpenAI-compatible text-to-image API and save it locally.

    Keeps the same signature and empty-list-on-failure convention as generate_videos_wavespeed. Images have no
    native duration, so ``duration`` records the target clip duration (seconds) for the on-demand download flow to check
    whether enough voice-over duration has been covered. The actual size returned by the API may differ from the request, so the
    image's real size is written into the rendition, not relying on request parameters.
    """
    aspect = VideoAspect(video_aspect)
    clip_duration = max(int(minimum_duration), 1)
    endpoint, model = _openai_image_endpoint()
    image_size = _openai_image_size(aspect)
    payload = {
        "model": model,
        "prompt": _openai_image_prompt(search_term),
        "n": 1,
        "size": image_size,
    }
    logger.info(
        f"generating image via openai-compatible endpoint: model={model}, "
        f"term={search_term!r}, size={image_size}"
    )
    generation_progress.submitting("openai_image")
    image_bytes, failure_detail = _request_openai_image(endpoint, payload)
    if image_bytes is None:
        logger.error(
            f"openai image generation failed: term={search_term!r}, "
            f"detail={failure_detail}"
        )
        return []

    try:
        image_path, width, height = _save_openai_image_file(image_bytes, save_dir)
    except _OpenAIImageDecodeError as e:
        # The compatibility layer may return 200 with a body that isn't an image (e.g. an HTML error page disguised as JSON,
        # a gateway's degraded notice page). An undecodable image means "this generation failed", so following the material source
        # convention an empty list is returned to let the upper layer skip the keyword and continue, rather than letting the exception abort the whole task.
        logger.error(
            "openai image response is not a decodable image, skipping term: "
            f"term={search_term!r}, error={type(e).__name__}, detail={e}"
        )
        return []
    item = MaterialInfo()
    item.provider = "openai_image"
    item.url = image_path
    item.duration = clip_duration
    item.source_info = {
        "provider": "openai_image",
        "search_term": search_term,
        "rendition": {
            "id": None,
            "width": width,
            "height": height,
        },
    }
    return [item]


def generate_images_codex(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
    save_dir: str = "",
    *,
    context=None,
) -> List[MaterialInfo]:
    """Obtain one Codex image using the existing PNG material representation."""
    aspect = VideoAspect(video_aspect)
    if minimum_duration <= 0:
        return []
    try:
        context = context if context is not None else codex_image.capture_context()
        codex_image.assert_current(context)
        # Independent of the OpenAI-compatible provider's template and settings.
        prompt = (
            f"Create one image depicting: {search_term}. "
            f"Compose the image for a {aspect.value} video frame."
        )
        generation_progress.submitting("codex_image")
        image_bytes = codex_image.generate_image(prompt, context)
        codex_image.assert_current(context)
        try:
            image_path, width, height = _save_openai_image_file(image_bytes, save_dir)
        except _OpenAIImageDecodeError:
            raise codex_image.CodexImageError("codex.image.invalid_result") from None
        except OSError:
            raise codex_image.CodexImageError("codex.image.save_failed") from None
        codex_image.assert_current(context)
    except codex_image.CodexImageError as error:
        raise CodexImageMaterialError(error) from None
    item = MaterialInfo()
    item.provider = "codex_image"
    item.url = image_path
    item.duration = max(int(minimum_duration), 1)
    item.source_info = {
        "provider": "codex_image",
        "search_term": search_term,
        "rendition": {"id": None, "width": width, "height": height},
    }
    return [item]


def generate_images_useapi(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
    save_dir: str = "",
) -> List[MaterialInfo]:
    """Generate one Nano Banana image through useapi.net for a script segment.

    A refused prompt returns an empty list so the next segment is tried, as
    for the OpenAI-compatible source. Errors that would repeat for every
    segment, or leave the request state unknown, stop the loop.
    """
    aspect = VideoAspect(video_aspect)
    try:
        image_bytes, job_id = useapi.generate_image(search_term, aspect)
    except useapi.UseAPIError as exc:
        raise UseAPIImageMaterialError(str(exc), task_id=exc.task_id) from exc
    if image_bytes is None:
        return []
    try:
        image_path, width, height = _save_openai_image_file(image_bytes, save_dir)
    except _OpenAIImageDecodeError as e:
        logger.error(
            "useapi.net image is not a decodable image, skipping term: "
            f"term={search_term!r}, error={type(e).__name__}, detail={e}"
        )
        return []
    item = MaterialInfo()
    item.provider = "useapi_image"
    item.url = image_path
    item.duration = max(int(minimum_duration), 1)
    item.source_info = {
        "provider": "useapi_image",
        "search_term": search_term,
        "asset_id": job_id,
        "rendition": {"id": job_id or None, "width": width, "height": height},
    }
    return [item]


def _render_openai_image_video(
    image_path: str, clip_duration: int, image_motion: ImageMotion = ImageMotion.zoom
) -> str:
    """
    Render the generated image into an mp4 clip, reusing the "image → animated clip" pipeline of local materials.

    Returns an empty string on render failure, and the caller stops further paid requests.
    """
    try:
        return video.render_image_zoom_video(
            image_path, clip_duration, image_motion=image_motion
        )
    except Exception as e:
        logger.error(
            "failed to render generated image as a video clip: "
            f"image={image_path}, error={type(e).__name__}, detail={e}"
        )
        return ""


def _download_videos_openai_image_on_demand(
    *,
    task_id: str,
    search_terms: List[str],
    video_aspect: VideoAspect,
    audio_duration: float,
    max_clip_duration: int,
    material_directory: str,
    image_motion: ImageMotion = ImageMotion.zoom,
    image_generator: Callable[..., List[MaterialInfo]] | None = None,
    provider: str = "openai_image",
    codex_image_context=None,
) -> List[str]:
    """
    Generate OpenAI-compatible text-to-image materials one by one in script segment order, stopping as soon as the required total duration is reached.

    Same paid-safety semantics as WaveSpeed's on-demand generation: text-to-image is billed per image, so generating everything first and then
    choosing would pay for unused frames. Each image is rendered into an mp4 clip immediately after generation and its
    effective duration accumulated (as in the stock flow, capped at the clip duration); once the required voice-over duration is reached,
    no new paid requests are made. A clearly rejected single image can be skipped; when a request result is unknown, a paid
    result fails to download or local rendering fails, the task must stop so later keywords aren't billed again.
    """
    # Calling the material service directly must also validate before paid requests, rather than finding invalid effect parameters after generation.
    image_motion = ImageMotion(image_motion)
    if not material_directory:
        # Generated images are billed per task and not reusable, so by default they're stored in the task directory for traceability.
        material_directory = utils.task_dir(task_id)

    video_paths: List[str] = []
    material_sources: list[dict[str, Any]] = []
    total_duration = 0.0

    # A non-positive voice-over duration makes the "accumulated required duration reached" check meaningless, so return empty-handed,
    # avoiding paying per image for a task that can never be satisfied (consistent with the Seedance preflight semantics).
    try:
        required_duration = float(audio_duration)
    except (TypeError, ValueError):
        required_duration = 0.0
    if required_duration <= 0:
        logger.warning(
            "skip openai image generation because required audio duration is "
            f"not positive: duration={audio_duration}"
        )
        _persist_material_sources(task_id, material_sources)
        return video_paths

    if image_generator is None:
        image_generator = generate_images_openai
    generation_options = {}
    if provider == "codex_image":
        try:
            codex_image_context = (
                codex_image_context
                if codex_image_context is not None
                else codex_image.capture_context()
            )
            codex_image.assert_current(codex_image_context)
        except codex_image.CodexImageError as error:
            raise CodexImageMaterialError(error) from None
        generation_options["context"] = codex_image_context

    for search_term in search_terms:
        try:
            items = image_generator(
                search_term=search_term,
                minimum_duration=max_clip_duration,
                video_aspect=video_aspect,
                save_dir=material_directory,
                **generation_options,
            )
        except OpenAIImagePaidResultError:
            _persist_material_sources(task_id, material_sources)
            raise
        for item in items:
            video_file = _render_openai_image_video(
                item.url, max_clip_duration, image_motion=image_motion
            )
            if not video_file:
                _persist_material_sources(task_id, material_sources)
                if provider == "codex_image":
                    raise CodexImageMaterialError(
                        codex_image.CodexImageError("codex.image.render_failed")
                    )
                raise OpenAIImagePaidResultError(
                    "generated image could not be rendered locally"
                )
            if provider == "codex_image":
                try:
                    codex_image.assert_current(codex_image_context)
                except codex_image.CodexImageError as error:
                    _persist_material_sources(task_id, material_sources)
                    raise CodexImageMaterialError(error) from None
            logger.info(f"image material rendered: {video_file}")
            video_paths.append(video_file)
            try:
                material_sources.append(_material_source_record(item, video_file))
            except Exception as source_error:
                # Consistent with stock sources: a source record exception must not treat a material that was already paid for and rendered
                # successfully as failed, let alone block video generation.
                logger.warning(
                    "failed to prepare generated material source record: "
                    f"provider={provider}, "
                    f"error={type(source_error).__name__}, detail={source_error}"
                )
            total_duration += min(max_clip_duration, item.duration)
            # Same >= check as WaveSpeed: when the duration is exactly covered, generating one more image would pay once more.
            # The inner and outer checks must keep the same semantics.
            if total_duration >= required_duration:
                break
        if total_duration >= required_duration:
            logger.info(
                "generated image materials cover the required duration, stop "
                f"generating more images: generated={total_duration:.1f}s, "
                f"required={required_duration:.1f}s"
            )
            break

    logger.success(f"generated and rendered {len(video_paths)} image materials")
    _persist_material_sources(task_id, material_sources)
    return video_paths


def _search_videos_with_cache(
    provider: str,
    search_videos: Callable[..., List[MaterialInfo]],
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect,
) -> List[MaterialInfo]:
    """
    Handle the 24-hour search cache for the three online material sources in one place.

    The cache only wraps the search API and doesn't change the later video download and dedup logic. Nothing is cached when the remote returns an empty list,
    because the existing provider interface uses an empty list for both "no results" and "request failed";
    until the two are split into explicit result types, it's better to retry next time than to cache a transient failure for a day.
    """
    cache_args = {
        "provider": provider,
        "search_term": search_term,
        "minimum_duration": minimum_duration,
        "video_aspect": video_aspect,
    }

    def load_cache_safely() -> List[MaterialInfo] | None:
        try:
            return material_cache.load_material_search_cache(**cache_args)
        except Exception as exc:
            # The cache is an optional optimization; any cache implementation exception must be treated as a miss and must not block
            # the normal remote search of Pexels, Pixabay or Coverr.
            logger.warning(
                "material search cache read failed, continue with remote search: "
                f"provider={provider}, error={type(exc).__name__}, detail={exc}"
            )
            return None

    def load_matching_cache() -> tuple[List[MaterialInfo] | None, int]:
        cached_items = load_cache_safely()
        if cached_items is None:
            return None, 0

        filtered_cached_items = _filter_materials_by_aspect(
            cached_items,
            video_aspect,
        )
        ignored_count = len(cached_items) - len(filtered_cached_items)
        if ignored_count:
            # Caches from older versions may contain materials of other orientations. Even if a few usable entries remain, refresh
            # the full candidate set, otherwise the same small batch of videos would be reused for the whole cache lifetime.
            return None, ignored_count
        return filtered_cached_items, 0

    cached_items, ignored_count = load_matching_cache()
    if cached_items is not None:
        return cached_items
    if ignored_count:
        logger.info(
            "material search cache contains mismatched orientations, "
            f"refresh from provider: provider={provider}, term={search_term!r}, "
            f"ignored={ignored_count}"
        )

    cache_lock = material_cache.get_material_search_cache_lock(**cache_args)
    with cache_lock:
        # Wait for the thread with the same search criteria to finish and read again, so multiple API tasks don't all hit the remote
        # on the first cache miss, reducing the chance of triggering third-party rate limits and risk controls.
        cached_items, _ = load_matching_cache()
        if cached_items is not None:
            return cached_items

        items = search_videos(
            search_term=search_term,
            minimum_duration=minimum_duration,
            video_aspect=video_aspect,
        )
        # Providers normally write the current keyword, but test doubles, third-party extensions or old implementations may
        # omit it or carry a wrong value. Cache reads restore this field from the cache key, so remote results are also
        # corrected at the same entry point, keeping task source records consistent between first search and cache hits.
        for item in items:
            if isinstance(item.source_info, dict):
                item.source_info = dict(item.source_info)
                item.source_info["search_term"] = search_term
        if items:
            try:
                material_cache.save_material_search_cache(
                    **cache_args,
                    items=items,
                )
            except Exception as exc:
                logger.warning(
                    "material search cache write failed, use remote results: "
                    f"provider={provider}, error={type(exc).__name__}, detail={exc}"
                )
        return items


def _search_terms_in_parallel(
    search_terms: List[str],
    search_videos: Callable[[str, int, VideoAspect], List[MaterialInfo]],
    minimum_duration: int,
    video_aspect: VideoAspect,
) -> list[tuple[str, List[MaterialInfo]]]:
    """Search keywords in parallel; failed keywords return empty results without blocking other materials."""
    if not search_terms:
        return []

    workers = min(_get_material_concurrency(), len(search_terms))
    if workers == 1:
        results = []
        for search_term in search_terms:
            try:
                items = search_videos(
                    search_term=search_term,
                    minimum_duration=minimum_duration,
                    video_aspect=video_aspect,
                )
            except Exception as exc:
                logger.error(
                    "failed to search material videos: "
                    f"search_term={search_term!r}, "
                    f"error={type(exc).__name__}, detail={exc}"
                )
                items = []
            logger.info(f"found {len(items)} videos for '{search_term}'")
            results.append((search_term, items))
        return results

    futures = {}
    with ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="material-search",
    ) as executor:
        for search_term in search_terms:
            futures[executor.submit(
                copy_context().run,
                logging_utils.bind_log_scope(search_videos),
                search_term,
                minimum_duration,
                video_aspect,
            )] = search_term

        results = []
        for future in futures:
            search_term = futures[future]
            try:
                items = future.result()
            except Exception as exc:
                logger.error(
                    "failed to search material videos: "
                    f"search_term={search_term!r}, "
                    f"error={type(exc).__name__}, detail={exc}"
                )
                items = []
            logger.info(f"found {len(items)} videos for '{search_term}'")
            results.append((search_term, items))
        return results


def _report_material_downloaded(
    position: int,
    total: int,
    item: MaterialInfo,
    saved_video_path: str,
    on_downloaded: Callable[[MaterialInfo], None] | None,
) -> None:
    """
    Record that a material finished downloading and notify the caller to update progress.

    Always called in the thread that started the download, so per-file logs and progress updates don't depend on download concurrency.
    """
    description = os.path.basename(saved_video_path)
    try:
        size_mb = os.path.getsize(saved_video_path) / _BYTES_PER_MEGABYTE
        description += f" ({size_mb:.1f} MB)"
    except OSError:
        # File size is only auxiliary info; failing to read it doesn't affect the download result.
        pass
    logger.info(f"downloaded material {position}/{total}: {description}")
    if on_downloaded is None:
        return
    try:
        on_downloaded(item)
    except Exception as exc:
        # Progress is only display info. A callback failure (e.g. the state backend is temporarily unavailable) must not invalidate
        # successfully downloaded materials, let alone abort the whole task.
        logger.warning(
            "failed to report material download progress: "
            f"error={type(exc).__name__}, detail={exc}"
        )


def _first_clip_duration(
    item: MaterialInfo, max_clip_duration: int, clip_speed: float
) -> float:
    """
    Return the seconds of the final video that the first clip of a stock video fills.

    combine_videos() cuts each clip from ``max_clip_duration * clip_speed`` seconds
    of the source and plays it at ``clip_speed``. A video shorter than that is a
    single clip of ``item.duration / clip_speed`` seconds: at 2x, a 6 s video fills
    3 s, not a whole 5 s clip. Both concat modes play one clip of every video
    before they play a second clip of any video.
    """
    return min(max_clip_duration, item.duration / clip_speed)


def _covered_duration_reporter(
    progress_callback: Callable[[float], None] | None,
    required_duration: float,
    max_clip_duration: int,
    clip_speed: float = 1.0,
) -> Callable[[MaterialInfo], None] | None:
    """
    Build a per-material callback: convert "voice-over duration covered" into a 0~1 download progress.

    The measure matches the download loop's stop condition — each material contributes at most one clip duration, and reaching
    the required duration means done, so any excess is capped at 1.0. Returns None when there's no progress callback.
    """
    if progress_callback is None:
        return None
    covered_duration = 0.0

    def report(item: MaterialInfo) -> None:
        nonlocal covered_duration
        covered_duration += _first_clip_duration(item, max_clip_duration, clip_speed)
        fraction = 1.0
        if required_duration > 0:
            fraction = min(1.0, covered_duration / required_duration)
        progress_callback(fraction)

    return report


def _download_materials_in_parallel(
    materials: List[tuple[str, MaterialInfo]],
    material_directory: str,
    on_downloaded: Callable[[MaterialInfo], None] | None = None,
) -> list[tuple[str, MaterialInfo, str]]:
    """
    Download one round of materials in parallel, keeping the candidate order passed in by the caller.

    After each material downloads successfully, a log line is written and ``on_downloaded`` is called so the caller can update
    task progress. Both the callback and logging happen in the thread that called this function.
    """
    if not materials:
        return []

    total = len(materials)
    workers = min(_get_material_concurrency(), total)
    if workers == 1:
        downloaded = []
        for position, (search_term, item) in enumerate(materials, start=1):
            try:
                saved_video_path = save_video(
                    video_url=item.url,
                    save_dir=material_directory,
                )
            except Exception as exc:
                logger.error(
                    "failed to download material video: "
                    f"provider={item.provider}, "
                    f"error={type(exc).__name__}, "
                    f"detail={_redact_request_error(exc, item.url)}"
                )
                continue
            if saved_video_path:
                downloaded.append((search_term, item, saved_video_path))
                _report_material_downloaded(
                    position, total, item, saved_video_path, on_downloaded
                )
        return downloaded

    futures = {}
    with ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="material-download",
    ) as executor:
        for search_term, item in materials:
            futures[executor.submit(
                copy_context().run,
                logging_utils.bind_log_scope(save_video),
                item.url,
                material_directory,
            )] = (search_term, item)

        downloaded = []
        for position, future in enumerate(futures, start=1):
            search_term, item = futures[future]
            try:
                saved_video_path = future.result()
            except Exception as exc:
                logger.error(
                    "failed to download material video: "
                    f"provider={item.provider}, "
                    f"error={type(exc).__name__}, "
                    f"detail={_redact_request_error(exc, item.url)}"
                )
                continue
            if saved_video_path:
                downloaded.append((search_term, item, saved_video_path))
                _report_material_downloaded(
                    position, total, item, saved_video_path, on_downloaded
                )
        return downloaded


def _select_materials_until_duration(
    materials: List[tuple[str, MaterialInfo]],
    max_clip_duration: int,
    audio_duration: float,
    current_duration: float = 0.0,
    clip_speed: float = 1.0,
) -> List[tuple[str, MaterialInfo]]:
    """
    Select one round of materials in candidate order, so concurrent downloads don't fetch candidates beyond the voice-over duration.

    Returns a prefix subset of ``materials``: accumulate from the first candidate and stop when the accumulated duration first
    exceeds the voice-over duration (including the one that exceeds it). Callers rely on this prefix property to know which
    candidates were actually attempted in this round.
    """
    selected = []
    total_duration = current_duration
    for material in materials:
        selected.append(material)
        total_duration += _first_clip_duration(
            material[1], max_clip_duration, clip_speed
        )
        if total_duration > audio_duration:
            break
    return selected


def download_videos(
    task_id: str,
    search_terms: List[str],
    source: str = "pexels",
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    audio_duration: float = 0.0,
    max_clip_duration: int = 5,
    clip_speed: float = 1.0,
    match_script_order: bool = False,
    progress_callback: Callable[[float], None] | None = None,
    image_motion: ImageMotion = ImageMotion.zoom,
    jalapeno_video_endpoint: volcengine_seedance.SeedanceEndpoint | None = None,
    codex_image_context=None,
) -> List[str]:
    """
    Search and download the materials needed to cover the voice-over duration, returning local file paths.

    ``progress_callback`` is optional: for stock materials (Pexels, Pixabay, Coverr) it is called with a 0~1 completion ratio
    after each file downloads, so the task layer can advance the progress bar. On-demand paid generation
    sources don't report download progress.

    ``clip_speed`` is the speed at which combine_videos() plays the clips. The
    stock sources count each video by the seconds its first clip fills at that
    speed.
    """
    provider = "pexels"
    remote_search_videos = search_videos_pexels
    if source == "pixabay":
        provider = "pixabay"
        remote_search_videos = search_videos_pixabay
    elif source == "coverr":
        provider = "coverr"
        remote_search_videos = search_videos_coverr

    def search_videos(
        search_term: str,
        minimum_duration: int,
        video_aspect: VideoAspect,
    ) -> List[MaterialInfo]:
        return _search_videos_with_cache(
            provider=provider,
            search_videos=remote_search_videos,
            search_term=search_term,
            minimum_duration=minimum_duration,
            video_aspect=video_aspect,
        )

    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    if source == "infistar":
        return _download_videos_infistar_on_demand(
            task_id=task_id, search_terms=search_terms, video_aspect=video_aspect,
            audio_duration=audio_duration, max_clip_duration=max_clip_duration,
        )
    if source == "wavespeed":
        # AI generation is billed per clip, so it can't use the stock sources' "fetch candidates for all keywords, then choose"
        # flow, or it would pay for unused clips. Generation sources instead generate segment by segment on demand, stopping as soon as
        # the required duration is covered; they also skip the 24-hour search cache — output URLs are signed addresses
        # that expire, and reusing the cache would give different tasks the same generated video repeatedly.
        return _download_videos_wavespeed_on_demand(
            task_id=task_id,
            search_terms=search_terms,
            video_aspect=video_aspect,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            material_directory=material_directory,
        )
    if source in {"volcengine_seedance", "jalapeno"}:
        # As with WaveSpeed, the official Ark API creates asynchronous paid tasks. It must generate segment by segment
        # on demand, buying only the materials the current voice-over duration really needs.
        return _download_videos_seedance_on_demand(
            task_id=task_id,
            search_terms=search_terms,
            video_aspect=video_aspect,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            material_directory=material_directory,
            source=source,
            endpoint_snapshot=jalapeno_video_endpoint,
        )
    if source == "ofox":
        # Same on-demand paid semantics as WaveSpeed/Ark: the OFox gateway's /v1/videos creates
        # asynchronous paid tasks, so it must generate segment by segment and stop once the required duration is covered; output URLs are
        # expiring temporary direct links, so it also skips the 24-hour search cache.
        return _download_videos_ofox_on_demand(
            task_id=task_id,
            search_terms=search_terms,
            video_aspect=video_aspect,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            material_directory=material_directory,
        )
    if source == "muapi":
        # MuAPI's model endpoints create asynchronous paid tasks. Submit segment by segment and stop once the voice-over duration
        # is covered, so unused script keywords aren't sent to the remote either.
        return _download_videos_muapi_on_demand(
            task_id=task_id,
            search_terms=search_terms,
            video_aspect=video_aspect,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            material_directory=material_directory,
        )
    if source == "useapi":
        # useapi.net generates on the user's own Google AI subscription, Kling AI or Dreamina account, and each segment
        # consumes that account's credits. As with MuAPI, submit segment by segment and stop once the voice-over duration is covered.
        return _download_videos_useapi_on_demand(
            task_id=task_id,
            search_terms=search_terms,
            video_aspect=video_aspect,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            material_directory=material_directory,
        )
    if source == "metaso_minimax":
        # Metaso MiniMax is also billed per remote asynchronous task. Its request body is similar to Volcengine Ark's,
        # but the task query path and response structure differ, so only the local on-demand generation semantics are shared, not
        # the provider client, keeping protocol differences out of the material orchestration layer.
        return _download_videos_metaso_minimax_on_demand(
            task_id=task_id,
            search_terms=search_terms,
            video_aspect=video_aspect,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            material_directory=material_directory,
        )
    if source in {"openai_image", "codex_image", "useapi_image"}:
        # Same on-demand paid semantics as WaveSpeed: text-to-image is billed per image, generated segment by segment, and stops
        # as soon as the required duration is covered. Results are one-off local image files and also skip the 24-hour
        # search cache — caching would give different tasks the same image repeatedly.
        image_options = {}
        if source == "codex_image":
            image_options = {
                "image_generator": generate_images_codex,
                "provider": source,
                "codex_image_context": codex_image_context,
            }
        elif source == "useapi_image":
            image_options = {
                "image_generator": generate_images_useapi,
                "provider": source,
            }
        return _download_videos_openai_image_on_demand(
            task_id=task_id,
            search_terms=search_terms,
            video_aspect=video_aspect,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            material_directory=material_directory,
            image_motion=image_motion,
            **image_options,
        )

    # Normalized as combine_videos() normalizes it.
    clip_speed = utils.normalize_clip_speed(clip_speed)
    if match_script_order:
        return _download_videos_by_script_order(
            task_id=task_id,
            search_terms=search_terms,
            search_videos=search_videos,
            video_aspect=video_aspect,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            clip_speed=clip_speed,
            material_directory=material_directory,
            progress_callback=progress_callback,
        )

    valid_video_items = []
    valid_video_urls = []
    found_duration = 0.0
    for search_term, video_items in _search_terms_in_parallel(
        search_terms=search_terms,
        search_videos=search_videos,
        minimum_duration=max_clip_duration,
        video_aspect=video_aspect,
    ):
        for item in video_items:
            if item.url not in valid_video_urls:
                valid_video_items.append(item)
                valid_video_urls.append(item.url)
                found_duration += item.duration

    logger.info(
        f"found total videos: {len(valid_video_items)}, required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )
    video_paths = []
    material_sources: list[dict[str, Any]] = []

    concat_mode_value = getattr(video_concat_mode, "value", video_concat_mode)
    if concat_mode_value == VideoConcatMode.random.value:
        random.shuffle(valid_video_items)

    total_duration = 0.0
    on_downloaded = _covered_duration_reporter(
        progress_callback, audio_duration, max_clip_duration, clip_speed
    )
    pending_items = list(valid_video_items)
    # The default/random path is also governed by the material concurrency config: each round's candidates are preselected by the serial logic's
    # stop condition (accumulate in order, stop when the voice-over duration is first exceeded). When all downloads succeed, each round's download set
    # is exactly the same as the serial logic; failed candidates are made up with later candidates in the next round.
    while pending_items and total_duration <= audio_duration:
        batch = []
        projected_duration = total_duration
        for item in pending_items:
            batch.append(item)
            projected_duration += _first_clip_duration(
                item, max_clip_duration, clip_speed
            )
            if projected_duration > audio_duration:
                break
        for item in batch:
            source_info = item.source_info if isinstance(item.source_info, dict) else {}
            logger.info(
                f"downloading {item.provider} video: "
                f"asset_id={source_info.get('asset_id') or 'unknown'}"
            )
        downloaded_materials = _download_materials_in_parallel(
            materials=[("", item) for item in batch],
            material_directory=material_directory,
            on_downloaded=on_downloaded,
        )
        pending_items = pending_items[len(batch):]
        for _, item, saved_video_path in downloaded_materials:
            try:
                if saved_video_path:
                    logger.info(f"video saved: {saved_video_path}")
                    video_paths.append(saved_video_path)
                    try:
                        material_sources.append(
                            _material_source_record(item, saved_video_path)
                        )
                    except Exception as source_error:
                        # A source record exception must not treat a successfully downloaded material as a download failure, let alone
                        # block video generation; the provider and exception type are kept for later diagnosis.
                        logger.warning(
                            "failed to prepare material source record: "
                            f"provider={item.provider}, "
                            f"error={type(source_error).__name__}, detail={source_error}"
                        )
                    seconds = _first_clip_duration(item, max_clip_duration, clip_speed)
                    total_duration += seconds
                    if total_duration > audio_duration:
                        logger.info(
                            f"total duration of downloaded videos: {round(total_duration, 2)} seconds, skip downloading more"
                        )
                        break
            except Exception as e:
                logger.error(
                    "failed to download material video: "
                    f"provider={item.provider}, error={type(e).__name__}, "
                    f"detail={_redact_request_error(e, item.url)}"
                )
    logger.success(f"downloaded {len(video_paths)} videos")
    _persist_material_sources(task_id, material_sources)
    return video_paths


def _download_videos_wavespeed_on_demand(
    *,
    task_id: str,
    search_terms: List[str],
    video_aspect: VideoAspect,
    audio_duration: float,
    max_clip_duration: int,
    material_directory: str,
) -> List[str]:
    """
    Generate WaveSpeed materials segment by segment in script order, stopping as soon as the required total duration is covered.

    Each keyword naturally corresponds to one script segment, and generation costs money: generating everything first and then choosing would pay for
    unused segments. Here each segment is downloaded immediately after generation and its effective duration accumulated (as in the stock
    flow, capped at the clip duration); once the required voice-over duration is covered, no new generation
    requests are made. Segments that clearly failed remotely can be skipped; paid tasks with unknown state or failed downloads must
    keep their ID and stop the local task.
    """
    video_paths: List[str] = []
    material_sources: list[dict[str, Any]] = []

    try:
        required_duration = float(audio_duration)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("WaveSpeed audio duration must be finite") from exc
    if not math.isfinite(required_duration):
        raise ValueError("WaveSpeed audio duration must be finite")
    if required_duration <= 0:
        logger.warning(
            "skip WaveSpeed paid generation because required audio duration "
            f"is not positive: duration={required_duration}"
        )
        _persist_material_sources(task_id, material_sources)
        return video_paths

    try:
        clip_duration = int(max_clip_duration)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("WaveSpeed clip duration must be a positive integer") from exc
    if clip_duration <= 0:
        raise ValueError("WaveSpeed clip duration must be a positive integer")

    total_duration = 0.0
    for search_term in search_terms:
        try:
            video_items = generate_videos_wavespeed(
                search_term=search_term,
                minimum_duration=clip_duration,
                video_aspect=video_aspect,
            )
        except WaveSpeedUnconfirmedTaskError as e:
            # A submitted paid task is in an unknown state: the remote may still be running or may already have completed and billed.
            # Placing orders for later keywords would cause duplicate generation and duplicate charges, so stop right here
            # and hand the prediction id to the task layer to write into the failure state, so the user can recover the output.
            logger.error(
                "stop submitting new wavespeed tasks, the last submitted task "
                f"is unconfirmed: prediction_id={e.prediction_id or 'unknown'}, "
                f"detail={e}"
            )
            _persist_material_sources(task_id, material_sources)
            raise
        for item in video_items:
            saved_video_path = _save_generated_video_with_retry(
                item.url, material_directory, "wavespeed"
            )
            if not saved_video_path:
                source_info = (
                    item.source_info if isinstance(item.source_info, dict) else {}
                )
                prediction_id = str(source_info.get("asset_id") or "").strip()
                _persist_material_sources(task_id, material_sources)
                raise WaveSpeedDownloadError(
                    "WaveSpeed generated a paid video but the result could not be "
                    f"downloaded: id={prediction_id or 'unknown'}",
                    prediction_id=prediction_id,
                )
            logger.info(f"video saved: {saved_video_path}")
            video_paths.append(saved_video_path)
            try:
                material_sources.append(_material_source_record(item, saved_video_path))
            except Exception as source_error:
                # Consistent with stock sources: a source record exception must not treat a material that was already paid for and downloaded
                # successfully as failed, let alone block video generation.
                logger.warning(
                    "failed to prepare material source record: "
                    f"provider={item.provider}, "
                    f"error={type(source_error).__name__}, detail={source_error}"
                )
            total_duration += min(clip_duration, item.duration)
            # Use >=: when the accumulated duration exactly equals the required duration it's already enough, and generating more would
            # pay once more. The inner and outer checks must keep the same semantics.
            if total_duration >= required_duration:
                break
        if total_duration >= required_duration:
            logger.info(
                "generated materials cover the required duration, stop "
                f"generating more clips: generated={total_duration:.1f}s, "
                f"required={required_duration:.1f}s"
            )
            break
    logger.success(f"generated and downloaded {len(video_paths)} videos")
    _persist_material_sources(task_id, material_sources)
    return video_paths


def _download_videos_seedance_on_demand(
    *,
    task_id: str,
    search_terms: List[str],
    video_aspect: VideoAspect,
    audio_duration: float,
    max_clip_duration: int,
    material_directory: str,
    source: str = "volcengine_seedance",
    endpoint_snapshot: volcengine_seedance.SeedanceEndpoint | None = None,
) -> List[str]:
    """Generate Seedance materials sequentially, stopping paid orders as soon as the voice-over duration is covered."""
    service = jalapeno_video if source == "jalapeno" else volcengine_seedance
    generation_options = (
        {"endpoint_snapshot": endpoint_snapshot}
        if source == "jalapeno" and endpoint_snapshot is not None else {}
    )
    video_paths: List[str] = []
    material_sources: list[dict[str, Any]] = []

    # The paid generation loop must first validate the two durations that control the loop count. NaN/Infinity would make
    # ``total_duration >= audio_duration`` never hold, and a non-positive clip duration would keep the
    # accumulated value from growing; either could create useless paid tasks for every keyword.
    try:
        required_duration = float(audio_duration)
    except (TypeError, ValueError) as exc:
        raise volcengine_seedance.VolcEngineSeedanceError(
            "Seedance audio duration must be a finite number"
        ) from exc
    if not math.isfinite(required_duration):
        raise volcengine_seedance.VolcEngineSeedanceError(
            "Seedance audio duration must be a finite number"
        )
    if required_duration <= 0:
        logger.warning(
            "skip Seedance paid generation because required audio duration is "
            f"not positive: duration={required_duration}"
        )
        _persist_material_sources(task_id, material_sources)
        return video_paths

    try:
        clip_duration = int(max_clip_duration)
    except (TypeError, ValueError, OverflowError) as exc:
        raise volcengine_seedance.VolcEngineSeedanceError(
            "Seedance clip duration must be a positive integer"
        ) from exc
    if clip_duration <= 0:
        raise volcengine_seedance.VolcEngineSeedanceError(
            "Seedance clip duration must be a positive integer"
        )

    total_duration = 0.0
    for search_term in search_terms:
        try:
            video_items = service.generate_videos(
                search_term=search_term,
                minimum_duration=clip_duration,
                video_aspect=video_aspect,
                **generation_options,
            )
        except volcengine_seedance.VolcEngineSeedanceUnconfirmedTaskError as exc:
            # The remote paid task may still succeed. Stop placing orders immediately and keep the task ID, so
            # the user can later confirm or recover the result in the Ark console.
            logger.error(
                "stop submitting new Seedance tasks because the last paid task "
                f"is unconfirmed: task_id={exc.task_id or 'unknown'}, detail={exc}"
            )
            _persist_material_sources(task_id, material_sources)
            raise
        except volcengine_seedance.VolcEngineSeedanceError as exc:
            logger.error(f"Seedance generation failed before completion: {exc}")
            _persist_material_sources(task_id, material_sources)
            raise

        for item in video_items:
            saved_video_path = _save_generated_video_with_retry(
                item.url, material_directory, source
            )
            if not saved_video_path:
                # The remote task completed and incurred a charge, so when the local download fails the remote task ID must
                # be carried back into the task state, so the user can recover the result in the Ark console. Raise a
                # dedicated error here directly, which also stops later keywords from creating new paid tasks.
                source_info = (
                    item.source_info if isinstance(item.source_info, dict) else {}
                )
                remote_task_id = str(source_info.get("asset_id") or "").strip()
                _persist_material_sources(task_id, material_sources)
                raise volcengine_seedance.VolcEngineSeedanceDownloadError(
                    "Seedance generated a paid video but the result could not be "
                    f"downloaded: id={remote_task_id or 'unknown'}",
                    task_id=remote_task_id,
                )
            logger.info(f"video saved: {saved_video_path}")
            if source == "jalapeno":
                # For the same 480p, different gateways may actually return a width of 854 or 864. Measure the size and duration from the downloaded
                # clip, so source records are accurate and material coverage isn't overestimated.
                try:
                    with VideoFileClip(saved_video_path) as downloaded:
                        actual_duration = float(downloaded.duration)
                        width, height = downloaded.size
                    if not math.isfinite(actual_duration) or actual_duration <= 0:
                        raise ValueError("invalid generated video duration")
                except Exception as exc:
                    remote_task_id = str((item.source_info or {}).get("asset_id") or "")
                    _persist_material_sources(task_id, material_sources)
                    raise volcengine_seedance.VolcEngineSeedanceDownloadError(
                        "Jalapeno Cloud generated a paid video but its local media could not be read",
                        task_id=remote_task_id,
                    ) from exc
                item.duration = actual_duration
                item.source_info = dict(item.source_info or {})
                item.source_info["rendition"] = {
                    **item.source_info.get("rendition", {}),
                    "width": width, "height": height,
                }
            video_paths.append(saved_video_path)
            try:
                material_sources.append(_material_source_record(item, saved_video_path))
            except Exception as source_error:
                logger.warning(
                    "failed to prepare generated material source record: "
                    f"provider={source}, "
                    f"error={type(source_error).__name__}, detail={source_error}"
                )
            total_duration += min(clip_duration, item.duration)
            if total_duration >= required_duration:
                break
        if total_duration >= required_duration:
            logger.info(
                "generated Seedance materials cover the required duration; stop "
                f"submitting paid tasks: generated={total_duration:.1f}s, "
                f"required={required_duration:.1f}s"
            )
            break

    logger.success(
        f"generated and downloaded {len(video_paths)} {source} videos"
    )
    _persist_material_sources(task_id, material_sources)
    return video_paths


def _download_videos_ofox_on_demand(
    *,
    task_id: str,
    search_terms: List[str],
    video_aspect: VideoAspect,
    audio_duration: float,
    max_clip_duration: int,
    material_directory: str,
) -> List[str]:
    """Generate OFox materials sequentially, stopping paid orders as soon as the voice-over duration is covered."""
    video_paths: List[str] = []
    material_sources: list[dict[str, Any]] = []

    # The paid generation loop must first validate the two durations that control the loop count. NaN/Infinity would make
    # ``total_duration >= audio_duration`` never hold, and a non-positive clip duration would keep the
    # accumulated value from growing; either could create useless paid tasks for every keyword.
    try:
        required_duration = float(audio_duration)
    except (TypeError, ValueError) as exc:
        raise ofox.OFoxError("OFox audio duration must be a finite number") from exc
    if not math.isfinite(required_duration):
        raise ofox.OFoxError("OFox audio duration must be a finite number")
    if required_duration <= 0:
        logger.warning(
            "skip OFox paid generation because required audio duration is "
            f"not positive: duration={required_duration}"
        )
        _persist_material_sources(task_id, material_sources)
        return video_paths

    try:
        clip_duration = int(max_clip_duration)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ofox.OFoxError("OFox clip duration must be a positive integer") from exc
    if clip_duration <= 0:
        raise ofox.OFoxError("OFox clip duration must be a positive integer")

    total_duration = 0.0
    for search_term in search_terms:
        try:
            video_items = ofox.generate_videos(
                search_term=search_term,
                minimum_duration=clip_duration,
                video_aspect=video_aspect,
            )
        except ofox.OFoxUnconfirmedTaskError as exc:
            # The remote paid task may still succeed. Stop placing orders immediately and keep the task ID, so
            # the user can later confirm or recover the result in the OFox console.
            logger.error(
                "stop submitting new OFox tasks because the last paid task "
                f"is unconfirmed: task_id={exc.task_id or 'unknown'}, detail={exc}"
            )
            _persist_material_sources(task_id, material_sources)
            raise
        except ofox.OFoxError as exc:
            logger.error(f"OFox generation failed before completion: {exc}")
            _persist_material_sources(task_id, material_sources)
            raise

        # When a single keyword is clearly failed by the remote (e.g. content moderation triggered), an empty list is returned: the task has
        # ended with no billing uncertainty, so skip this clip and keep generating later keywords.
        for item in video_items:
            saved_video_path = _save_generated_video_with_retry(
                item.url, material_directory, "ofox"
            )
            if not saved_video_path:
                # The remote task completed and incurred a charge, so when the local download fails the remote task ID must
                # be carried back into the task state, so the user can recover the result in the OFox console. Raise a
                # dedicated error here directly, which also stops later keywords from creating new paid tasks.
                source_info = (
                    item.source_info if isinstance(item.source_info, dict) else {}
                )
                remote_task_id = str(source_info.get("asset_id") or "").strip()
                _persist_material_sources(task_id, material_sources)
                raise ofox.OFoxDownloadError(
                    "OFox generated a paid video but the result could not be "
                    f"downloaded: id={remote_task_id or 'unknown'}",
                    task_id=remote_task_id,
                )
            logger.info(f"video saved: {saved_video_path}")
            video_paths.append(saved_video_path)
            try:
                material_sources.append(_material_source_record(item, saved_video_path))
            except Exception as source_error:
                logger.warning(
                    "failed to prepare generated material source record: "
                    f"provider=ofox, "
                    f"error={type(source_error).__name__}, detail={source_error}"
                )
            total_duration += min(clip_duration, item.duration)
            if total_duration >= required_duration:
                break
        if total_duration >= required_duration:
            logger.info(
                "generated OFox materials cover the required duration; stop "
                f"submitting paid tasks: generated={total_duration:.1f}s, "
                f"required={required_duration:.1f}s"
            )
            break

    logger.success(f"generated and downloaded {len(video_paths)} OFox videos")
    _persist_material_sources(task_id, material_sources)
    return video_paths


def _download_videos_muapi_on_demand(
    *,
    task_id: str,
    search_terms: List[str],
    video_aspect: VideoAspect,
    audio_duration: float,
    max_clip_duration: int,
    material_directory: str,
) -> List[str]:
    """Generate MuAPI materials until the narration duration is covered."""
    video_paths: List[str] = []
    material_sources: list[dict[str, Any]] = []

    try:
        required_duration = float(audio_duration)
    except (TypeError, ValueError) as exc:
        raise muapi.MuAPIError(
            "MuAPI audio duration must be a finite number"
        ) from exc
    if not math.isfinite(required_duration):
        raise muapi.MuAPIError("MuAPI audio duration must be a finite number")
    if required_duration <= 0:
        logger.warning(
            "skip MuAPI paid generation because required audio duration is "
            f"not positive: duration={required_duration}"
        )
        _persist_material_sources(task_id, material_sources)
        return video_paths

    try:
        clip_duration = int(max_clip_duration)
    except (TypeError, ValueError, OverflowError) as exc:
        raise muapi.MuAPIError(
            "MuAPI clip duration must be a positive integer"
        ) from exc
    if clip_duration <= 0:
        raise muapi.MuAPIError("MuAPI clip duration must be a positive integer")

    total_duration = 0.0
    for search_term in search_terms:
        try:
            video_items = muapi.generate_videos(
                search_term=search_term,
                minimum_duration=clip_duration,
                video_aspect=video_aspect,
            )
        except muapi.MuAPIUnconfirmedTaskError as exc:
            # An ambiguous paid submission must stop the loop: retrying with the
            # next keyword could create a duplicate charge.  The task ID is kept
            # for task-service recovery when the provider returned one.
            logger.error(
                "stop submitting new MuAPI tasks because the last paid task "
                f"is unconfirmed: task_id={exc.task_id or 'unknown'}, "
                f"detail={exc}"
            )
            _persist_material_sources(task_id, material_sources)
            raise
        except muapi.MuAPIError as exc:
            logger.error(f"MuAPI generation failed before completion: {exc}")
            _persist_material_sources(task_id, material_sources)
            raise

        for item in video_items:
            saved_video_path = _save_generated_video_with_retry(
                item.url, material_directory, "muapi"
            )
            if not saved_video_path:
                # The remote job completed and may already have incurred a
                # charge.  Do not submit a replacement task after download
                # failure; return the remote ID for manual recovery instead.
                source_info = (
                    item.source_info if isinstance(item.source_info, dict) else {}
                )
                remote_task_id = str(source_info.get("asset_id") or "").strip()
                _persist_material_sources(task_id, material_sources)
                raise muapi.MuAPIDownloadError(
                    "MuAPI generated a paid video but the result could not be "
                    f"downloaded: id={remote_task_id or 'unknown'}",
                    task_id=remote_task_id,
                )
            logger.info(f"video saved: {saved_video_path}")
            video_paths.append(saved_video_path)
            try:
                material_sources.append(_material_source_record(item, saved_video_path))
            except Exception as source_error:
                logger.warning(
                    "failed to prepare generated material source record: "
                    f"provider=muapi, error={type(source_error).__name__}, "
                    f"detail={source_error}"
                )
            try:
                downloaded_duration = _get_downloaded_video_duration(saved_video_path)
            except Exception as duration_error:
                source_info = (
                    item.source_info if isinstance(item.source_info, dict) else {}
                )
                remote_task_id = str(source_info.get("asset_id") or "").strip()
                _persist_material_sources(task_id, material_sources)
                raise muapi.MuAPIDownloadError(
                    "MuAPI generated a paid video but its downloaded duration "
                    "could not be measured: "
                    f"id={remote_task_id or 'unknown'}",
                    task_id=remote_task_id,
                ) from duration_error
            total_duration += min(clip_duration, downloaded_duration)
            if total_duration >= required_duration:
                break
        if total_duration >= required_duration:
            logger.info(
                "generated MuAPI materials cover the required duration; stop "
                f"submitting paid tasks: generated={total_duration:.1f}s, "
                f"required={required_duration:.1f}s"
            )
            break

    logger.success(f"generated and downloaded {len(video_paths)} MuAPI videos")
    _persist_material_sources(task_id, material_sources)
    return video_paths


def _download_videos_useapi_on_demand(
    *,
    task_id: str,
    search_terms: List[str],
    video_aspect: VideoAspect,
    audio_duration: float,
    max_clip_duration: int,
    material_directory: str,
) -> List[str]:
    """Generate useapi.net materials until the narration duration is covered."""
    video_paths: List[str] = []
    material_sources: list[dict[str, Any]] = []

    try:
        required_duration = float(audio_duration)
    except (TypeError, ValueError) as exc:
        raise useapi.UseAPIError(
            "useapi.net audio duration must be a finite number"
        ) from exc
    if not math.isfinite(required_duration):
        raise useapi.UseAPIError("useapi.net audio duration must be a finite number")
    if required_duration <= 0:
        logger.warning(
            "skip useapi.net generation because required audio duration is "
            f"not positive: duration={required_duration}"
        )
        _persist_material_sources(task_id, material_sources)
        return video_paths

    try:
        clip_duration = int(max_clip_duration)
    except (TypeError, ValueError, OverflowError) as exc:
        raise useapi.UseAPIError(
            "useapi.net clip duration must be a positive integer"
        ) from exc
    if clip_duration <= 0:
        raise useapi.UseAPIError("useapi.net clip duration must be a positive integer")

    total_duration = 0.0
    for search_term in search_terms:
        try:
            video_items = useapi.generate_videos(
                search_term=search_term,
                minimum_duration=clip_duration,
                video_aspect=video_aspect,
            )
        except useapi.UseAPIUnconfirmedTaskError as exc:
            # The generation may already be running on the user's account.
            # Submitting the next keyword could spend credits twice, so stop and
            # keep the job ID for recovery when useapi.net returned one.
            logger.error(
                "stop submitting new useapi.net jobs because the last job is "
                f"unconfirmed: job_id={exc.task_id or 'unknown'}, detail={exc}"
            )
            _persist_material_sources(task_id, material_sources)
            raise
        except useapi.UseAPIError as exc:
            logger.error(f"useapi.net generation failed before completion: {exc}")
            _persist_material_sources(task_id, material_sources)
            raise

        for item in video_items:
            source_info = item.source_info if isinstance(item.source_info, dict) else {}
            remote_task_id = str(source_info.get("asset_id") or "").strip()
            fallback_urls = source_info.get("fallback_urls")
            saved_video_path = ""
            # Dreamina serves the same file from more than one CDN host; try the
            # alternates before giving up on a generation that already ran.
            for video_url in [item.url, *(
                fallback_urls if isinstance(fallback_urls, list) else []
            )]:
                headers = useapi.download_headers(video_url)
                extra = {"request_headers": headers} if headers else {}
                saved_video_path = _save_generated_video_with_retry(
                    video_url, material_directory, "useapi", **extra
                )
                if saved_video_path:
                    break
            if not saved_video_path:
                # The job completed on the user's account. Do not submit a
                # replacement after a download failure; report the job ID.
                _persist_material_sources(task_id, material_sources)
                raise useapi.UseAPIDownloadError(
                    "useapi.net generated a video but the result could not be "
                    f"downloaded: id={remote_task_id or 'unknown'}",
                    task_id=remote_task_id,
                )
            logger.info(f"video saved: {saved_video_path}")
            video_paths.append(saved_video_path)
            try:
                material_sources.append(_material_source_record(item, saved_video_path))
            except Exception as source_error:
                logger.warning(
                    "failed to prepare generated material source record: "
                    f"provider=useapi, error={type(source_error).__name__}, "
                    f"detail={source_error}"
                )
            try:
                downloaded_duration = _get_downloaded_video_duration(saved_video_path)
            except Exception as duration_error:
                _persist_material_sources(task_id, material_sources)
                raise useapi.UseAPIDownloadError(
                    "useapi.net generated a video but its downloaded duration "
                    f"could not be measured: id={remote_task_id or 'unknown'}",
                    task_id=remote_task_id,
                ) from duration_error
            total_duration += min(clip_duration, downloaded_duration)
            if total_duration >= required_duration:
                break
        if total_duration >= required_duration:
            logger.info(
                "generated useapi.net materials cover the required duration; stop "
                f"submitting jobs: generated={total_duration:.1f}s, "
                f"required={required_duration:.1f}s"
            )
            break

    logger.success(f"generated and downloaded {len(video_paths)} useapi.net videos")
    _persist_material_sources(task_id, material_sources)
    return video_paths


def _download_videos_metaso_minimax_on_demand(
    *,
    task_id: str,
    search_terms: List[str],
    video_aspect: VideoAspect,
    audio_duration: float,
    max_clip_duration: int,
    material_directory: str,
) -> List[str]:
    """Generate Metaso MiniMax materials sequentially, stopping paid orders as soon as the voice-over duration is covered."""
    video_paths: List[str] = []
    material_sources: list[dict[str, Any]] = []

    # The remote generates at least 4 seconds, but locally it is still trimmed and accumulated by the user's clip duration. Validate the loop
    # control parameters up front, so NaN, Infinity or non-positive values can't make the stop condition unreachable and
    # submit every keyword as a paid task.
    try:
        required_duration = float(audio_duration)
    except (TypeError, ValueError) as exc:
        raise metaso_minimax.MetasoMiniMaxError(
            "Metaso MiniMax audio duration must be a finite number"
        ) from exc
    if not math.isfinite(required_duration):
        raise metaso_minimax.MetasoMiniMaxError(
            "Metaso MiniMax audio duration must be a finite number"
        )
    if required_duration <= 0:
        logger.warning(
            "skip Metaso MiniMax paid generation because required audio duration "
            f"is not positive: duration={required_duration}"
        )
        _persist_material_sources(task_id, material_sources)
        return video_paths

    try:
        clip_duration = int(max_clip_duration)
    except (TypeError, ValueError, OverflowError) as exc:
        raise metaso_minimax.MetasoMiniMaxError(
            "Metaso MiniMax clip duration must be a positive integer"
        ) from exc
    if clip_duration <= 0:
        raise metaso_minimax.MetasoMiniMaxError(
            "Metaso MiniMax clip duration must be a positive integer"
        )

    total_duration = 0.0
    for search_term in search_terms:
        try:
            video_items = metaso_minimax.generate_videos(
                search_term=search_term,
                minimum_duration=clip_duration,
                video_aspect=video_aspect,
            )
        except metaso_minimax.MetasoMiniMaxUnconfirmedTaskError as exc:
            # When the request or polling state is unknown, the remote task may still succeed and be billed. Stop the whole
            # generation loop immediately so later keywords don't place orders, and hand the task ID to the task service to save.
            logger.error(
                "stop submitting new Metaso MiniMax tasks because the last paid "
                f"task is unconfirmed: task_id={exc.task_id or 'unknown'}, "
                f"detail={exc}"
            )
            _persist_material_sources(task_id, material_sources)
            raise
        except metaso_minimax.MetasoMiniMaxError as exc:
            logger.error(f"Metaso MiniMax generation failed before completion: {exc}")
            _persist_material_sources(task_id, material_sources)
            raise

        for item in video_items:
            saved_video_path = _save_generated_video_with_retry(
                item.url, material_directory, "metaso_minimax"
            )
            if not saved_video_path:
                # A successful generation has already incurred a charge, so a download failure must not be replaced by creating a new task.
                # Raise a dedicated error carrying the remote ID, for the task state and manual recovery.
                source_info = (
                    item.source_info if isinstance(item.source_info, dict) else {}
                )
                remote_task_id = str(source_info.get("asset_id") or "").strip()
                _persist_material_sources(task_id, material_sources)
                raise metaso_minimax.MetasoMiniMaxDownloadError(
                    "Metaso MiniMax generated a paid video but the result could "
                    f"not be downloaded: id={remote_task_id or 'unknown'}",
                    task_id=remote_task_id,
                )
            logger.info(f"video saved: {saved_video_path}")
            video_paths.append(saved_video_path)
            try:
                material_sources.append(_material_source_record(item, saved_video_path))
            except Exception as source_error:
                logger.warning(
                    "failed to prepare generated material source record: "
                    f"provider=metaso_minimax, error={type(source_error).__name__}, "
                    f"detail={source_error}"
                )

            # The local video only uses the clip length the user chose; even if H3 generated a longer material because of its minimum duration
            # constraint, the unused part must not count toward coverage and cause necessary frames to be skipped.
            total_duration += min(clip_duration, item.duration)
            if total_duration >= required_duration:
                break
        if total_duration >= required_duration:
            logger.info(
                "generated Metaso MiniMax materials cover the required duration; "
                f"stop submitting paid tasks: generated={total_duration:.1f}s, "
                f"required={required_duration:.1f}s"
            )
            break

    logger.success(f"generated and downloaded {len(video_paths)} Metaso MiniMax videos")
    _persist_material_sources(task_id, material_sources)
    return video_paths


def _download_videos_by_script_order(
    task_id: str,
    search_terms: List[str],
    search_videos,
    video_aspect: VideoAspect,
    audio_duration: float,
    max_clip_duration: int,
    material_directory: str,
    progress_callback: Callable[[float], None] | None = None,
    clip_speed: float = 1.0,
) -> List[str]:
    """
    Download materials in script order.

    The default download logic merges all keywords' candidates into one big list; if the first
    keyword returns many results, the download may keep consuming that keyword's materials, and later
    script topics never make it onto the timeline. Here candidates are grouped by keyword and downloaded round-robin:
    round 1 takes each keyword's 1st candidate, round 2 takes each keyword's 2nd candidate.
    This keeps material order as close to the script order as possible without rewriting the video composition engine.
    """
    logger.info("downloading videos with script-order material matching")
    candidate_groups = []
    valid_video_urls = set()
    found_duration = 0.0

    for search_term, video_items in _search_terms_in_parallel(
        search_terms=search_terms,
        search_videos=search_videos,
        minimum_duration=max_clip_duration,
        video_aspect=video_aspect,
    ):
        # A topic the script returns to gets the same search results again. Dedupe
        # only within one term, so the repeated term keeps its slot on the timeline;
        # candidates another term already took are skipped when a round is built.
        term_items = []
        term_urls = set()
        for item in video_items:
            if item.url in term_urls:
                continue
            term_items.append(item)
            term_urls.add(item.url)
            if item.url not in valid_video_urls:
                valid_video_urls.add(item.url)
                found_duration += item.duration

        if term_items:
            candidate_groups.append((search_term, term_items))

    logger.info(
        f"found total ordered video candidates: {sum(len(items) for _, items in candidate_groups)}, "
        f"required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )

    video_paths = []
    material_sources: list[dict[str, Any]] = []
    total_duration = 0.0
    on_downloaded = _covered_duration_reporter(
        progress_callback, audio_duration, max_clip_duration, clip_speed
    )
    # Each keyword advances its candidate index independently: only candidates actually selected for download in this round advance it,
    # and unselected candidates are kept for the next round, so they aren't skipped by a round-wide shared index.
    next_candidate_indices = [0] * len(candidate_groups)
    picked_urls = set()
    while candidate_groups and total_duration <= audio_duration:
        round_materials = []
        round_urls = set()
        for group_position, (search_term, term_items) in enumerate(candidate_groups):
            # Skip candidates an earlier round or an earlier group of this round took.
            index = next_candidate_indices[group_position]
            while index < len(term_items) and (
                term_items[index].url in picked_urls
                or term_items[index].url in round_urls
            ):
                index += 1
            next_candidate_indices[group_position] = index
            if index < len(term_items):
                round_materials.append((group_position, search_term, term_items[index]))
                round_urls.add(term_items[index].url)
        if not round_materials:
            break

        selected_materials = _select_materials_until_duration(
            materials=[
                (search_term, item) for _, search_term, item in round_materials
            ],
            max_clip_duration=max_clip_duration,
            audio_duration=audio_duration,
            current_duration=total_duration,
            clip_speed=clip_speed,
        )
        # _select_materials_until_duration returns a prefix subset of the candidate list,
        # so the first len(selected_materials) are the candidates actually attempted this round,
        # and only the indices of the groups those candidates belong to are advanced.
        for group_position, _, item in round_materials[: len(selected_materials)]:
            next_candidate_indices[group_position] += 1
            picked_urls.add(item.url)

        downloaded_materials = _download_materials_in_parallel(
            materials=selected_materials,
            material_directory=material_directory,
            on_downloaded=on_downloaded,
        )
        for search_term, item, saved_video_path in downloaded_materials:
            try:
                source_info = (
                    item.source_info if isinstance(item.source_info, dict) else {}
                )
                logger.info(
                    f"downloading ordered {item.provider} video for {search_term!r}: "
                    f"asset_id={source_info.get('asset_id') or 'unknown'}"
                )
                if saved_video_path:
                    logger.info(f"video saved: {saved_video_path}")
                    video_paths.append(saved_video_path)
                    try:
                        material_sources.append(
                            _material_source_record(item, saved_video_path)
                        )
                    except Exception as source_error:
                        logger.warning(
                            "failed to prepare ordered material source record: "
                            f"provider={item.provider}, "
                            f"error={type(source_error).__name__}, "
                            f"detail={source_error}"
                        )
                    total_duration += _first_clip_duration(
                        item, max_clip_duration, clip_speed
                    )
                    if total_duration > audio_duration:
                        logger.info(
                            f"total duration of downloaded videos: {round(total_duration, 2)} seconds, skip downloading more"
                        )
                        break
            except Exception as e:
                logger.error(
                    "failed to download ordered material video: "
                    f"provider={item.provider}, error={type(e).__name__}, "
                    f"detail={_redact_request_error(e, item.url)}"
                )

    logger.success(f"downloaded {len(video_paths)} ordered videos")
    _persist_material_sources(task_id, material_sources)
    return video_paths


if __name__ == "__main__":
    download_videos(
        "test123", ["Money Exchange Medium"], audio_duration=100, source="pixabay"
    )


def _download_videos_infistar_on_demand(
    *, task_id, search_terms, video_aspect, audio_duration, max_clip_duration,
):
    """Order segment by segment; stop once materials are sufficient, and don't buy the next segment after an unknown state or download failure."""
    try:
        required = float(audio_duration)
        clip_duration = int(max_clip_duration)
    except (ValueError, TypeError, OverflowError) as exc:
        raise infistar_video.InfistarVideoError("Infistar duration must be finite and positive") from exc
    if not math.isfinite(required) or clip_duration <= 0:
        raise infistar_video.InfistarVideoError("Infistar duration must be finite and positive")
    paths = []
    sources = []
    covered = 0.0
    try:
        for term in search_terms:
            if covered >= required:
                break
            item = infistar_video.generate_video(
                search_term=term, video_aspect=video_aspect,
                output_dir=utils.task_dir(task_id),
            )
            paths.append(item.url)
            sources.append(_material_source_record(item, item.url))
            covered += min(clip_duration, item.duration)
    finally:
        _persist_material_sources(task_id, sources)
    return paths
