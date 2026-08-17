from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Sequence
from typing import TYPE_CHECKING

from loguru import logger

from app.services.asset_library.db import connect, library_root
from app.services.asset_library.models import ORIGIN_MANUAL, AssetTag, IngestResult
from app.services.asset_library.store import add_tags, load_asset, normalize_tags
from app.services.photo_library import PHOTO_EXTENSIONS, list_photo_files

if TYPE_CHECKING:
    from psycopg import Connection

_HASH_CHUNK = 1 << 20


def file_digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_size(path: str) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as image:
        return int(image.width), int(image.height)


def _normalize_group(group: str) -> str:
    cleaned = str(group).strip().strip("/").replace(os.sep, "/").lower()
    return cleaned or "misc"


def _manual_tags(group: str, tags: Sequence[str | AssetTag]) -> list[AssetTag]:
    entries = [AssetTag(tag=group, weight=1.0, manual=True)]
    entries.extend(
        AssetTag(tag=tag.tag, weight=tag.weight, manual=True)
        for tag in normalize_tags(tags)
    )
    return normalize_tags(entries)


def _target_rel_path(group: str, source: str, digest: str) -> str:
    stem, ext = os.path.splitext(os.path.basename(source))
    rel = f"{group}/{stem}{ext.lower()}"
    if os.path.exists(os.path.join(library_root(), *rel.split("/"))):
        rel = f"{group}/{stem}-{digest[:8]}{ext.lower()}"
    return rel


def _apply_manual(
    conn: Connection,
    asset_id: int,
    *,
    group: str,
    tags: Sequence[str | AssetTag],
    caption: str | None,
    min_display: float | None,
) -> None:
    with conn.cursor() as cur:
        if caption is not None:
            cur.execute(
                "UPDATE asset SET caption = %s, caption_manual = TRUE WHERE id = %s",
                (caption, asset_id),
            )
        if min_display is not None:
            cur.execute(
                "UPDATE asset SET min_display = %s, min_display_manual = TRUE "
                "WHERE id = %s",
                (float(min_display), asset_id),
            )
        add_tags(cur, asset_id, _manual_tags(group, tags), manual=True)


def _ingest(
    conn: Connection,
    source: str,
    *,
    group: str,
    tags: Sequence[str | AssetTag] = (),
    caption: str | None = None,
    min_display: float | None = None,
    origin: str = ORIGIN_MANUAL,
    source_query: str | None = None,
    source_url: str | None = None,
) -> IngestResult:
    group = _normalize_group(group)
    digest = file_digest(source)

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM asset WHERE sha256 = %s", (digest,))
        existing = cur.fetchone()

    if existing is not None:
        asset_id = existing["id"]
        _apply_manual(
            conn,
            asset_id,
            group=group,
            tags=tags,
            caption=caption,
            min_display=min_display,
        )
        with conn.cursor() as cur:
            stored = load_asset(cur, asset_id)
        conn.commit()
        return IngestResult(asset=stored, created=False)

    width, height = _image_size(source)
    rel_path = _target_rel_path(group, source, digest)
    target = os.path.join(library_root(), *rel_path.split("/"))

    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO asset (sha256, rel_path, width, height, caption, "
                "caption_manual, min_display, min_display_manual, origin, "
                "source_query, source_url) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    digest,
                    rel_path,
                    width,
                    height,
                    caption or "",
                    caption is not None,
                    None if min_display is None else float(min_display),
                    min_display is not None,
                    origin,
                    source_query,
                    source_url,
                ),
            )
            asset_id = cur.fetchone()["id"]
            add_tags(cur, asset_id, _manual_tags(group, tags), manual=True)
        # Copying inside the transaction keeps a failed copy from leaving a row
        # that points at a file which was never written.
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)
        with conn.cursor() as cur:
            stored = load_asset(cur, asset_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return IngestResult(asset=stored, created=True)


def ingest_file(
    source: str,
    *,
    group: str,
    tags: Sequence[str | AssetTag] = (),
    caption: str | None = None,
    min_display: float | None = None,
    origin: str = ORIGIN_MANUAL,
    source_query: str | None = None,
    source_url: str | None = None,
) -> IngestResult:
    """Copy one image into the library; the source file is left untouched."""
    if not source.lower().endswith(PHOTO_EXTENSIONS):
        raise ValueError(f"unsupported asset extension: {source}")
    if not os.path.isfile(source):
        raise ValueError(f"asset file not found: {source}")
    with connect() as conn:
        return _ingest(
            conn,
            source,
            group=group,
            tags=tags,
            caption=caption,
            min_display=min_display,
            origin=origin,
            source_query=source_query,
            source_url=source_url,
        )


def ingest_directory(
    source_dir: str,
    *,
    tags: Sequence[str | AssetTag] = (),
    caption: str | None = None,
    min_display: float | None = None,
    origin: str = ORIGIN_MANUAL,
    source_query: str | None = None,
) -> list[IngestResult]:
    """Ingest a tree of images; each subdirectory name becomes a tag of weight 1.0."""
    if not os.path.isdir(source_dir):
        raise ValueError(f"asset directory not found: {source_dir}")
    base = os.path.normpath(source_dir)
    results: list[IngestResult] = []
    with connect() as conn:
        for photo in list_photo_files(base):
            parent = os.path.dirname(os.path.relpath(photo, base))
            group = parent if parent and parent != "." else os.path.basename(base)
            try:
                results.append(
                    _ingest(
                        conn,
                        photo,
                        group=group,
                        tags=tags,
                        caption=caption,
                        min_display=min_display,
                        origin=origin,
                        source_query=source_query,
                    )
                )
            except Exception as error:
                logger.warning(f"failed to ingest {photo}: {str(error)}")
    return results
