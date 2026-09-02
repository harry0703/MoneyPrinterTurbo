"""Persistence for scheduled video-generation occurrences.

Mirrors the sqlite pattern already used by ``auth_store.py``: one small local
database, no external service required, survives process restarts. Each row
is one concrete occurrence (a specific generate-at datetime, already expanded
by ``schedule_rules.expand_occurrences``); a ``group_id`` links every
occurrence created from the same recurrence rule so the WebUI can show and
cancel them together.
"""

import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from uuid import uuid4

from app.utils import utils

STATUS_PENDING = "pending"
STATUS_DISPATCHED = "dispatched"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"


def _default_db_path() -> str:
    override = os.environ.get("MPT_SCHEDULE_DB_PATH")
    if override:
        return override
    return os.path.join(utils.storage_dir(create=True), "schedule.db")


def _connect(db_path: str | None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or _default_db_path())
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule_occurrences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id TEXT NOT NULL,
            generate_at REAL NOT NULL,
            video_subject TEXT NOT NULL,
            params_json TEXT NOT NULL,
            youtube_title TEXT NOT NULL DEFAULT '',
            youtube_description TEXT NOT NULL DEFAULT '',
            youtube_tags_json TEXT NOT NULL DEFAULT '[]',
            youtube_publish_offset_hours REAL NOT NULL DEFAULT 0,
            youtube_review_required INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            task_id TEXT,
            error TEXT,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_schedule_status_generate_at "
        "ON schedule_occurrences (status, generate_at)"
    )
    conn.commit()
    return conn


def _row_to_dict(row: tuple) -> dict:
    (
        occurrence_id,
        group_id,
        generate_at,
        video_subject,
        params_json,
        youtube_title,
        youtube_description,
        youtube_tags_json,
        youtube_publish_offset_hours,
        youtube_review_required,
        status,
        task_id,
        error,
        created_at,
    ) = row
    return {
        "id": occurrence_id,
        "group_id": group_id,
        "generate_at": datetime.fromtimestamp(generate_at),
        "video_subject": video_subject,
        "params": json.loads(params_json),
        "youtube_title": youtube_title,
        "youtube_description": youtube_description,
        "youtube_tags": json.loads(youtube_tags_json),
        "youtube_publish_offset_hours": youtube_publish_offset_hours,
        "youtube_review_required": bool(youtube_review_required),
        "status": status,
        "task_id": task_id,
        "error": error,
        "created_at": datetime.fromtimestamp(created_at),
    }


_SELECT_COLUMNS = (
    "id, group_id, generate_at, video_subject, params_json, youtube_title, "
    "youtube_description, youtube_tags_json, youtube_publish_offset_hours, "
    "youtube_review_required, status, task_id, error, created_at"
)


def create_schedule(
    occurrences: list[dict],
    params: dict,
    youtube_title: str = "",
    youtube_description: str = "",
    youtube_tags: list[str] | None = None,
    youtube_publish_offset_hours: float = 0.0,
    youtube_review_required: bool = False,
    db_path: str | None = None,
) -> str:
    """Persist a batch of occurrences sharing one recurrence rule.

    ``occurrences`` is the already-expanded, already-reviewed list of
    ``{"generate_at": datetime, "video_subject": str}`` dicts (see
    ``schedule_rules.expand_occurrences``); each becomes its own row so a
    partial failure or a per-occurrence cancel never touches the others.
    ``params`` is the base ``VideoParams`` payload used for generation; its
    ``video_subject`` is overridden per row from the occurrence.
    Returns the new ``group_id``.
    """
    if not occurrences:
        raise ValueError("occurrences must not be empty")

    group_id = uuid4().hex
    created_at = time.time()
    tags_json = json.dumps(list(youtube_tags or []), ensure_ascii=False)

    with closing(_connect(db_path)) as conn:
        for occurrence in occurrences:
            occurrence_params = dict(params)
            occurrence_params["video_subject"] = occurrence["video_subject"]
            conn.execute(
                """
                INSERT INTO schedule_occurrences (
                    group_id, generate_at, video_subject, params_json,
                    youtube_title, youtube_description, youtube_tags_json,
                    youtube_publish_offset_hours, youtube_review_required,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    group_id,
                    occurrence["generate_at"].timestamp(),
                    occurrence["video_subject"],
                    json.dumps(occurrence_params, ensure_ascii=False),
                    youtube_title,
                    youtube_description,
                    tags_json,
                    youtube_publish_offset_hours,
                    int(youtube_review_required),
                    STATUS_PENDING,
                    created_at,
                ),
            )
        conn.commit()

    return group_id


def list_occurrences(
    group_id: str | None = None,
    status: str | None = None,
    db_path: str | None = None,
) -> list[dict]:
    query = f"SELECT {_SELECT_COLUMNS} FROM schedule_occurrences WHERE 1=1"
    args: list = []
    if group_id is not None:
        query += " AND group_id = ?"
        args.append(group_id)
    if status is not None:
        query += " AND status = ?"
        args.append(status)
    query += " ORDER BY generate_at ASC"

    with closing(_connect(db_path)) as conn:
        rows = conn.execute(query, args).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_due_occurrences(now: datetime, db_path: str | None = None) -> list[dict]:
    """Pending occurrences whose generate_at has already passed."""
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            f"SELECT {_SELECT_COLUMNS} FROM schedule_occurrences "
            "WHERE status = ? AND generate_at <= ? ORDER BY generate_at ASC",
            (STATUS_PENDING, now.timestamp()),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def mark_dispatched(occurrence_id: int, task_id: str, db_path: str | None = None) -> None:
    with closing(_connect(db_path)) as conn:
        conn.execute(
            "UPDATE schedule_occurrences SET status = ?, task_id = ? WHERE id = ?",
            (STATUS_DISPATCHED, task_id, occurrence_id),
        )
        conn.commit()


def mark_failed(occurrence_id: int, error: str, db_path: str | None = None) -> None:
    with closing(_connect(db_path)) as conn:
        conn.execute(
            "UPDATE schedule_occurrences SET status = ?, error = ? WHERE id = ?",
            (STATUS_FAILED, error, occurrence_id),
        )
        conn.commit()


def cancel_occurrence(occurrence_id: int, db_path: str | None = None) -> bool:
    """Cancel one pending occurrence. No-op (returns False) once dispatched."""
    with closing(_connect(db_path)) as conn:
        cursor = conn.execute(
            "UPDATE schedule_occurrences SET status = ? WHERE id = ? AND status = ?",
            (STATUS_CANCELLED, occurrence_id, STATUS_PENDING),
        )
        conn.commit()
        return cursor.rowcount > 0


def cancel_group(group_id: str, db_path: str | None = None) -> int:
    """Cancel every still-pending occurrence in a group. Returns how many."""
    with closing(_connect(db_path)) as conn:
        cursor = conn.execute(
            "UPDATE schedule_occurrences SET status = ? WHERE group_id = ? AND status = ?",
            (STATUS_CANCELLED, group_id, STATUS_PENDING),
        )
        conn.commit()
        return cursor.rowcount
