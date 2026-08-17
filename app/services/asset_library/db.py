from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from loguru import logger

from app.config import config

if TYPE_CHECKING:  # psycopg stays out of the import graph while the library is off
    from psycopg import Connection

_MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), "migrations"
)

_MIGRATION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migration (
    name TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def is_enabled() -> bool:
    return bool(config.app.get("photo_library_enabled", False))


def library_root() -> str:
    root = str(config.app.get("photo_library_root", "storage/library")).strip()
    if not root:
        root = "storage/library"
    if not os.path.isabs(root):
        root = os.path.join(config.root_dir, root)
    return os.path.normpath(root)


def asset_path(rel_path: str) -> str:
    """Absolute path of a stored asset; the database only keeps the relative one."""
    return os.path.join(library_root(), *rel_path.split("/"))


def connection_params() -> dict[str, Any]:
    return {
        "host": str(config.app.get("photo_library_db_host", "127.0.0.1")),
        "port": int(config.app.get("photo_library_db_port", 5433)),
        "dbname": str(config.app.get("photo_library_db_name", "asset_library")),
        "user": str(config.app.get("photo_library_db_user", "asset_library")),
        "password": str(config.app.get("photo_library_db_password", "")),
    }


def connect() -> Connection:
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(row_factory=dict_row, **connection_params())


def _migrations() -> list[tuple[str, str]]:
    found = []
    for name in sorted(os.listdir(_MIGRATIONS_DIR)):
        if not name.endswith(".sql"):
            continue
        with open(os.path.join(_MIGRATIONS_DIR, name), "r", encoding="utf-8") as handle:
            found.append((name, handle.read()))
    return found


def init_library() -> None:
    """Create or upgrade the schema. Safe to repeat on a populated database."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_MIGRATION_TABLE)
            cur.execute("SELECT name FROM schema_migration")
            applied = {row["name"] for row in cur.fetchall()}
        for name, sql in _migrations():
            if name in applied:
                continue
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute("INSERT INTO schema_migration (name) VALUES (%s)", (name,))
            logger.info(f"asset library migration applied: {name}")
    os.makedirs(library_root(), exist_ok=True)
