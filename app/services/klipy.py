"""KLIPY GIF provider for animated overlays."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests
from loguru import logger

from app.config import config
from app.services.material import _get_tls_verify, _redact_request_error
from app.utils import utils

_BASE_URL = "https://api.klipy.com/api/v1"
_DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    )
}
# Ordered from the largest variant down. The API always exposes at least one of
# these buckets, but never guarantees all of them for a given item.
_SIZE_BUCKETS = ("hd", "md", "sm", "xs")
_MIN_PER_PAGE = 8

_api_key_counter = 0
_api_key_lock = threading.Lock()
_rate_limit_lock = threading.Lock()
_rate_limit_remaining: int | None = None


@dataclass
class GifInfo:
    slug: str
    title: str
    url: str
    width: int
    height: int
    duration: float = 0.0
    provider: str = "klipy"


def get_api_key() -> str:
    api_keys = config.app.get("klipy_api_keys")
    if not api_keys:
        raise ValueError(
            "\n\n##### klipy_api_keys is not set #####\n\n"
            f"Please set it in the config.toml file: {config.config_file}\n"
        )

    if isinstance(api_keys, str):
        return api_keys

    global _api_key_counter
    with _api_key_lock:
        _api_key_counter += 1
        return api_keys[_api_key_counter % len(api_keys)]


def _track_rate_limit(response: requests.Response) -> None:
    """Remember the hourly budget KLIPY reports so callers can back off early."""
    raw = (getattr(response, "headers", {}) or {}).get("x-ratelimit-remaining")
    if raw is None:
        return
    try:
        remaining = int(raw)
    except (TypeError, ValueError):
        return

    global _rate_limit_remaining
    with _rate_limit_lock:
        _rate_limit_remaining = remaining

    if remaining <= 5:
        logger.warning(f"klipy hourly rate limit is nearly exhausted: {remaining} left")


def get_rate_limit_remaining() -> int | None:
    with _rate_limit_lock:
        return _rate_limit_remaining


def _pick_media_file(item: dict[str, Any], min_width: int) -> tuple[str, int, int]:
    """
    Pick the smallest mp4 variant that still covers ``min_width``.

    mp4 is the only variant MoviePy decodes reliably; animated GIF frames are
    read through a much slower path and webm from KLIPY has no alpha anyway.
    """
    files = item.get("file")
    if not isinstance(files, dict):
        return "", 0, 0

    candidates: list[tuple[int, str, int, int]] = []
    for bucket in _SIZE_BUCKETS:
        variant = files.get(bucket)
        if not isinstance(variant, dict):
            continue
        mp4 = variant.get("mp4")
        if not isinstance(mp4, dict):
            continue
        url = str(mp4.get("url") or "")
        width = int(mp4.get("width") or 0)
        height = int(mp4.get("height") or 0)
        if not url.startswith("https://") or width <= 0 or height <= 0:
            continue
        candidates.append((width, url, width, height))

    if not candidates:
        return "", 0, 0

    candidates.sort(key=lambda entry: entry[0])
    for width, url, w, h in candidates:
        if width >= min_width:
            return url, w, h

    _, url, w, h = candidates[-1]
    return url, w, h


def search_gifs(
    search_term: str,
    min_width: int = 320,
    rating: str = "pg",
    limit: int = 8,
) -> list[GifInfo]:
    api_key = get_api_key()
    params = {
        "q": search_term,
        "per_page": max(_MIN_PER_PAGE, min(limit, 50)),
        "rating": rating,
    }
    query_url = f"{_BASE_URL}/{api_key}/gifs/search?{urlencode(params)}"
    logger.info(f"searching gifs on klipy: term={search_term!r}")

    try:
        response = requests.get(
            query_url,
            headers=_DOWNLOAD_HEADERS,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        _track_rate_limit(response)
        if response.status_code == 429:
            logger.warning("klipy hourly rate limit reached, skipping gif overlays")
            return []
        response.raise_for_status()
        payload = response.json()
    except Exception as error:
        logger.error(
            f"klipy gif search failed: {_redact_request_error(error, api_key)}"
        )
        return []

    if not isinstance(payload, dict) or not payload.get("result"):
        logger.error("klipy gif search returned an unsupported response")
        return []

    data = payload.get("data")
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        logger.error("klipy gif search returned an unsupported response")
        return []

    gifs: list[GifInfo] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url, width, height = _pick_media_file(item, min_width)
        if not url:
            continue
        gifs.append(
            GifInfo(
                slug=str(item.get("slug") or ""),
                title=str(item.get("title") or ""),
                url=url,
                width=width,
                height=height,
            )
        )

    logger.info(f"found {len(gifs)} gifs for term={search_term!r}")
    return gifs


def save_gif(gif_url: str, save_dir: str = "") -> str:
    if not save_dir:
        save_dir = utils.storage_dir("cache_gifs", create=True)
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    url_hash = utils.md5(gif_url.split("?")[0])
    gif_path = os.path.join(save_dir, f"gif-{url_hash}.mp4")
    if os.path.exists(gif_path) and os.path.getsize(gif_path) > 0:
        logger.info(f"gif already exists: {gif_path}")
        return gif_path

    try:
        response = requests.get(
            gif_url,
            headers=_DOWNLOAD_HEADERS,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(60, 240),
        )
        response.raise_for_status()
        with open(gif_path, "wb") as f:
            f.write(response.content)
    except Exception as error:
        logger.error(f"failed to download gif: {_redact_request_error(error)}")
        _remove_file(gif_path)
        return ""

    if not os.path.exists(gif_path) or os.path.getsize(gif_path) == 0:
        _remove_file(gif_path)
        return ""

    return gif_path


def _remove_file(file_path: str) -> None:
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except OSError as error:
        logger.warning(f"failed to remove file: {file_path}, error: {str(error)}")


def fetch_gif(
    search_term: str,
    min_width: int = 320,
    rating: str = "pg",
    exclude_slugs: set[str] | None = None,
) -> GifInfo | None:
    """Return the first downloadable gif for ``search_term``."""
    exclude_slugs = exclude_slugs or set()
    for gif in search_gifs(search_term, min_width=min_width, rating=rating):
        if gif.slug and gif.slug in exclude_slugs:
            continue
        local_path = save_gif(gif.url)
        if not local_path:
            continue
        gif.url = local_path
        return gif

    logger.warning(f"no usable gif found for term={search_term!r}")
    return None
