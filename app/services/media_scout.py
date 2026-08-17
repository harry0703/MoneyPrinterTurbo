"""
Media scouting: fetch missing photo assets from a DuckDuckGo image search and
ingest them into the photo asset library (`app.services.asset_library`).

Opt-in and non-breaking:
  * `photo_scout_enabled` (config.toml, [app]) gates every public function;
    off by default, so pipeline behavior is unchanged without it.
  * `playwright` is an optional dependency (`uv sync --extra scout`), imported
    lazily inside `_fetch_full_size_urls` so its absence never breaks the
    import graph, other pipeline stages, or the test suite.

Recipe (docs/playbook/media-scouting.md, "Топ-N «как на странице»"):
  1. Open the DuckDuckGo image search page for the query.
  2. Full-size URLs never land in the DOM (tiles only carry Bing thumbnails);
     the page already fetched them as JSON, so recover that request's URL
     from the Performance API (it contains "i.js").
  3. Re-fetch that URL from the page's own JS context — it reuses the page's
     vqd token and cookies — and read `results[].image` in page order.
  4. Download each URL, numbered by position; expect 1-2 out of every ten to
     fail (dead SSL, slow host), so keep walking the list until enough are
     accepted instead of retrying a failed one.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from typing import TYPE_CHECKING
from urllib.parse import quote

import requests
from loguru import logger

from app.config import config
from app.services.material import _get_tls_verify

if TYPE_CHECKING:
    from app.services.asset_library import Asset

_DUCKDUCKGO_IMAGES_URL = "https://duckduckgo.com/?q={query}&iax=images&ia=images"
_DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    )
}
# Photo library only ingests these extensions (app/services/photo_library.py);
# content-types outside this map are dropped as "not a usable photo".
_CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/pjpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
_MIN_FILE_SIZE = 5 * 1024


def is_enabled() -> bool:
    return bool(config.app.get("photo_scout_enabled", False))


def search_limit() -> int:
    """Configured cap on search requests per pipeline run; enforced by the caller."""
    return int(config.app.get("photo_scout_search_limit", 3))


def _slugify(query: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "-" for c in query.strip())
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "scout"


def _fetch_full_size_urls(query: str) -> list[str]:
    """Return full-size image URLs in page order, or [] on any failure."""
    from playwright.sync_api import sync_playwright

    page_url = _DUCKDUCKGO_IMAGES_URL.format(query=quote(query))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(user_agent=_DOWNLOAD_HEADERS["User-Agent"])
            page.goto(page_url, wait_until="networkidle")
            resource_url = page.evaluate(
                "() => performance.getEntriesByType('resource')"
                ".map(e => e.name).find(n => n.includes('i.js'))"
            )
            if not resource_url:
                logger.warning(
                    f"media_scout: no i.js resource request found for query={query!r}"
                )
                return []
            payload = page.evaluate(
                "(url) => fetch(url).then((r) => r.json())", resource_url
            )
        finally:
            browser.close()

    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        logger.warning(f"media_scout: unexpected i.js payload for query={query!r}")
        return []

    return [
        str(item["image"])
        for item in results
        if isinstance(item, dict) and item.get("image")
    ]


def _download_image(url: str, dest_dir: str, position: int) -> str | None:
    try:
        response = requests.get(
            url,
            headers=_DOWNLOAD_HEADERS,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(15, 60),
        )
        response.raise_for_status()
    except Exception as error:
        logger.warning(f"media_scout: failed to download {url}: {error}")
        return None

    content_type = (
        response.headers.get("content-type", "").split(";")[0].strip().lower()
    )
    ext = _CONTENT_TYPE_EXTENSIONS.get(content_type)
    if ext is None:
        logger.warning(
            f"media_scout: skipping non-photo content-type {content_type!r} from {url}"
        )
        return None

    content = response.content
    if len(content) < _MIN_FILE_SIZE:
        logger.warning(
            f"media_scout: skipping undersized file ({len(content)}B) from {url}"
        )
        return None

    path = os.path.join(dest_dir, f"scout-{position:03d}{ext}")
    with open(path, "wb") as handle:
        handle.write(content)
    return path


def _file_hash(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        digest.update(handle.read())
    return digest.hexdigest()


def scout_images(query: str, limit: int = 10) -> list["Asset"]:
    """
    Search DuckDuckGo images for ``query``, download up to ``limit`` usable
    photos, and ingest them into the asset library with search provenance.

    Returns the accepted `asset_library.Asset` list, or [] on any failure
    (scouting disabled, no browser, no network, empty/changed results) —
    this never raises.
    """
    if not is_enabled():
        return []
    query = (query or "").strip()
    if not query:
        return []

    try:
        urls = _fetch_full_size_urls(query)
    except Exception as error:  # noqa: BLE001 - never break the pipeline on scout errors
        logger.warning(f"media_scout: search failed for query={query!r}: {error}")
        return []

    if not urls:
        logger.warning(f"media_scout: no image results for query={query!r}")
        return []

    from app.services import asset_library

    group = _slugify(query)
    dest_dir = tempfile.mkdtemp(prefix="media-scout-")
    seen_hashes: set[str] = set()
    accepted: list["Asset"] = []
    try:
        for position, url in enumerate(urls):
            if len(accepted) >= limit:
                break
            path = _download_image(url, dest_dir, position)
            if path is None:
                continue

            digest = _file_hash(path)
            if digest in seen_hashes:
                os.remove(path)
                continue
            seen_hashes.add(digest)

            try:
                result = asset_library.ingest_file(
                    path,
                    group=group,
                    origin=asset_library.ORIGIN_SEARCH,
                    source_query=query,
                    source_url=url,
                )
            except Exception as error:
                logger.warning(f"media_scout: failed to ingest {url}: {error}")
                continue
            accepted.append(result.asset)
    finally:
        shutil.rmtree(dest_dir, ignore_errors=True)

    logger.info(f"media_scout: accepted {len(accepted)} asset(s) for query={query!r}")
    return accepted
