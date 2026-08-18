from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from app.services.asset_library.db import asset_path, connect
from app.services.asset_library.models import (
    EMBEDDING_DIM,
    Asset,
    AssetTag,
    LibrarySummary,
)

if TYPE_CHECKING:
    from psycopg import Cursor

_ASSET_COLUMNS = (
    "a.id, a.sha256, a.rel_path, a.width, a.height, a.caption, a.caption_manual, "
    "a.has_text, a.min_display, a.min_display_manual, a.origin, a.source_query, "
    "a.source_url, a.embed_model, a.annotate_model, a.created_at, a.last_used_at, "
    "a.use_count"
)

# An asset counts as unannotated while no annotator ran and no human wrote a caption.
_UNANNOTATED = "a.annotate_model IS NULL AND NOT a.caption_manual"


def normalize_tags(tags: Iterable[str | AssetTag]) -> list[AssetTag]:
    normalized: dict[str, AssetTag] = {}
    for entry in tags:
        if isinstance(entry, AssetTag):
            name, weight, manual = entry.tag, entry.weight, entry.manual
        else:
            name, weight, manual = entry, 1.0, False
        name = str(name).strip().lower()
        if not name:
            continue
        normalized[name] = AssetTag(tag=name, weight=float(weight), manual=manual)
    return list(normalized.values())


def format_vector(embedding: Sequence[float]) -> str:
    values = [float(value) for value in embedding]
    if len(values) != EMBEDDING_DIM:
        raise ValueError(
            f"embedding must have {EMBEDDING_DIM} dimensions, got {len(values)}"
        )
    return "[" + ",".join(repr(value) for value in values) + "]"


def _asset_from_row(row: dict[str, Any]) -> Asset:
    return Asset(
        id=row["id"],
        sha256=row["sha256"],
        rel_path=row["rel_path"],
        width=row["width"],
        height=row["height"],
        caption=row["caption"],
        caption_manual=row["caption_manual"],
        has_text=row["has_text"],
        min_display=row["min_display"],
        min_display_manual=row["min_display_manual"],
        origin=row["origin"],
        source_query=row["source_query"],
        source_url=row["source_url"],
        embed_model=row["embed_model"],
        annotate_model=row["annotate_model"],
        created_at=row["created_at"],
        last_used_at=row["last_used_at"],
        use_count=row["use_count"],
        distance=row.get("distance"),
    )


def _attach_tags(cur: Cursor, assets: list[Asset]) -> list[Asset]:
    if not assets:
        return assets
    by_id = {asset.id: asset for asset in assets}
    cur.execute(
        "SELECT asset_id, tag, weight, manual FROM asset_tag "
        "WHERE asset_id = ANY(%s) ORDER BY weight DESC, tag",
        (list(by_id),),
    )
    for row in cur.fetchall():
        by_id[row["asset_id"]].tags.append(
            AssetTag(tag=row["tag"], weight=row["weight"], manual=row["manual"])
        )
    return assets


def _fetch_assets(cur: Cursor, sql: str, params: Sequence[Any]) -> list[Asset]:
    cur.execute(sql, params)
    return _attach_tags(cur, [_asset_from_row(row) for row in cur.fetchall()])


def add_tags(
    cur: Cursor, asset_id: int, tags: Iterable[str | AssetTag], *, manual: bool
) -> None:
    for tag in normalize_tags(tags):
        cur.execute(
            "INSERT INTO asset_tag (asset_id, tag, weight, manual) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (asset_id, tag) "
            "DO UPDATE SET weight = EXCLUDED.weight, manual = EXCLUDED.manual",
            (asset_id, tag.tag, tag.weight, manual),
        )


def replace_tags(
    cur: Cursor, asset_id: int, tags: Iterable[str | AssetTag], *, manual: bool
) -> None:
    """Replace the tags of one origin, leaving the other origin's tags alone."""
    cur.execute(
        "DELETE FROM asset_tag WHERE asset_id = %s AND manual = %s",
        (asset_id, manual),
    )
    add_tags(cur, asset_id, tags, manual=manual)


def load_asset(cur: Cursor, asset_id: int) -> Asset | None:
    found = _fetch_assets(
        cur, f"SELECT {_ASSET_COLUMNS} FROM asset a WHERE a.id = %s", (asset_id,)
    )
    return found[0] if found else None


def get_asset(asset_id: int) -> Asset | None:
    with connect() as conn, conn.cursor() as cur:
        return load_asset(cur, asset_id)


def list_assets(
    *,
    any_tags: Sequence[str] = (),
    limit: int = 100,
    offset: int = 0,
) -> list[Asset]:
    clauses = []
    params: list[Any] = []
    if any_tags:
        clauses.append(
            "EXISTS (SELECT 1 FROM asset_tag t "
            "WHERE t.asset_id = a.id AND t.tag = ANY(%s))"
        )
        params.append([tag.tag for tag in normalize_tags(any_tags)])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend((limit, offset))
    with connect() as conn, conn.cursor() as cur:
        return _fetch_assets(
            cur,
            f"SELECT {_ASSET_COLUMNS} FROM asset a {where} "
            "ORDER BY a.id LIMIT %s OFFSET %s",
            params,
        )


def search_assets(
    embedding: Sequence[float],
    *,
    limit: int = 20,
    any_tags: Sequence[str] = (),
    exclude_tags: Sequence[str] = (),
    exclude_ids: Sequence[int] = (),
    max_distance: float | None = None,
) -> list[Asset]:
    """Nearest assets by cosine distance, filtered by tags and skipping stale rows."""
    vector = format_vector(embedding)
    clauses = ["a.embedding IS NOT NULL"]
    params: list[Any] = []
    if any_tags:
        clauses.append(
            "EXISTS (SELECT 1 FROM asset_tag t "
            "WHERE t.asset_id = a.id AND t.tag = ANY(%s))"
        )
        params.append([tag.tag for tag in normalize_tags(any_tags)])
    if exclude_tags:
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM asset_tag t "
            "WHERE t.asset_id = a.id AND t.tag = ANY(%s))"
        )
        params.append([tag.tag for tag in normalize_tags(exclude_tags)])
    if exclude_ids:
        clauses.append("a.id <> ALL(%s)")
        params.append(list(exclude_ids))
    if max_distance is not None:
        clauses.append("(a.embedding <=> %s::vector) <= %s")
        params.extend((vector, float(max_distance)))

    sql = (
        f"SELECT {_ASSET_COLUMNS}, a.embedding <=> %s::vector AS distance "
        f"FROM asset a WHERE {' AND '.join(clauses)} "
        "ORDER BY a.embedding <=> %s::vector LIMIT %s"
    )
    with connect() as conn, conn.cursor() as cur:
        found = _fetch_assets(cur, sql, [vector, *params, vector, limit])
    return [asset for asset in found if os.path.isfile(asset_path(asset.rel_path))]


def tagged_assets_without_embedding(
    *,
    any_tags: Sequence[str],
    exclude_tags: Sequence[str] = (),
    exclude_ids: Sequence[int] = (),
    limit: int = 20,
) -> list[Asset]:
    wanted = [tag.tag for tag in normalize_tags(any_tags)]
    if not wanted:
        return []

    clauses = [
        "a.embedding IS NULL",
        "EXISTS (SELECT 1 FROM asset_tag t "
        "WHERE t.asset_id = a.id AND t.tag = ANY(%s))",
    ]
    params: list[Any] = [wanted]
    if exclude_tags:
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM asset_tag t "
            "WHERE t.asset_id = a.id AND t.tag = ANY(%s))"
        )
        params.append([tag.tag for tag in normalize_tags(exclude_tags)])
    if exclude_ids:
        clauses.append("a.id <> ALL(%s)")
        params.append(list(exclude_ids))
    params.append(limit)

    with connect() as conn, conn.cursor() as cur:
        found = _fetch_assets(
            cur,
            f"SELECT {_ASSET_COLUMNS} FROM asset a "
            f"WHERE {' AND '.join(clauses)} ORDER BY a.id LIMIT %s",
            params,
        )
    return [asset for asset in found if os.path.isfile(asset_path(asset.rel_path))]


def assets_missing_annotation(limit: int = 100) -> list[Asset]:
    with connect() as conn, conn.cursor() as cur:
        return _fetch_assets(
            cur,
            f"SELECT {_ASSET_COLUMNS} FROM asset a WHERE {_UNANNOTATED} "
            "ORDER BY a.id LIMIT %s",
            (limit,),
        )


def assets_missing_embedding(limit: int = 100, *, embed_model: str = "") -> list[Asset]:
    clause = "a.embedding IS NULL"
    params: list[Any] = []
    if embed_model:
        clause = "(a.embedding IS NULL OR a.embed_model IS DISTINCT FROM %s)"
        params.append(embed_model)
    params.append(limit)
    with connect() as conn, conn.cursor() as cur:
        return _fetch_assets(
            cur,
            f"SELECT {_ASSET_COLUMNS} FROM asset a WHERE {clause} ORDER BY a.id LIMIT %s",
            params,
        )


def save_annotation(
    asset_id: int,
    *,
    model: str,
    caption: str | None = None,
    tags: Sequence[str | AssetTag] | None = None,
    has_text: bool | None = None,
    min_display: float | None = None,
) -> None:
    """Store automatic annotation without touching values a human set by hand."""
    with connect() as conn, conn.cursor() as cur:
        if caption is not None:
            cur.execute(
                "UPDATE asset SET caption = %s WHERE id = %s AND NOT caption_manual",
                (caption, asset_id),
            )
        if min_display is not None:
            cur.execute(
                "UPDATE asset SET min_display = %s "
                "WHERE id = %s AND NOT min_display_manual",
                (float(min_display), asset_id),
            )
        if has_text is not None:
            cur.execute(
                "UPDATE asset SET has_text = %s WHERE id = %s", (has_text, asset_id)
            )
        cur.execute(
            "UPDATE asset SET annotate_model = %s WHERE id = %s", (model, asset_id)
        )
        if tags is not None:
            replace_tags(cur, asset_id, tags, manual=False)


def save_embedding(asset_id: int, embedding: Sequence[float], *, model: str) -> None:
    vector = format_vector(embedding)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE asset SET embedding = %s::vector, embed_model = %s WHERE id = %s",
            (vector, model, asset_id),
        )


def set_tags(
    asset_id: int, tags: Sequence[str | AssetTag], *, manual: bool = True
) -> None:
    with connect() as conn, conn.cursor() as cur:
        replace_tags(cur, asset_id, tags, manual=manual)


def record_usage(asset_id: int, task_id: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO asset_usage (asset_id, task_id) VALUES (%s, %s)",
            (asset_id, task_id),
        )
        cur.execute(
            "UPDATE asset SET use_count = use_count + 1, last_used_at = now() "
            "WHERE id = %s",
            (asset_id,),
        )


def usage_counts(recent_tasks: int) -> dict[int, int]:
    """How often each asset was used across the last `recent_tasks` distinct tasks."""
    if recent_tasks <= 0:
        return {}
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "WITH recent AS ("
            "  SELECT task_id FROM asset_usage GROUP BY task_id "
            # now() is the transaction timestamp, so usages recorded together
            # share a used_at; the identity column breaks those ties.
            "  ORDER BY max(used_at) DESC, max(id) DESC LIMIT %s"
            ") "
            "SELECT asset_id, count(*) AS total FROM asset_usage "
            "WHERE task_id IN (SELECT task_id FROM recent) GROUP BY asset_id",
            (recent_tasks,),
        )
        return {row["asset_id"]: row["total"] for row in cur.fetchall()}


def delete_asset(asset_id: int) -> bool:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM asset WHERE id = %s RETURNING rel_path", (asset_id,))
        row = cur.fetchone()
    if row is None:
        return False
    stored = asset_path(row["rel_path"])
    if os.path.isfile(stored):
        os.remove(stored)
    return True


def summary() -> LibrarySummary:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS total, "
            f"count(*) FILTER (WHERE {_UNANNOTATED}) AS without_annotation, "
            "count(*) FILTER (WHERE a.embedding IS NULL) AS without_embedding "
            "FROM asset a"
        )
        totals = cur.fetchone() or {}
        cur.execute(
            "SELECT tag, count(*) AS total FROM asset_tag "
            "GROUP BY tag ORDER BY total DESC, tag"
        )
        tags = {row["tag"]: row["total"] for row in cur.fetchall()}
    return LibrarySummary(
        total=totals.get("total", 0),
        without_annotation=totals.get("without_annotation", 0),
        without_embedding=totals.get("without_embedding", 0),
        tags=tags,
    )
