import sqlite3
from datetime import datetime, timedelta

import pytest

from app.services import schedule_store

BASE_PARAMS = {"video_subject": "placeholder", "video_aspect": "portrait"}


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "schedule.db")


def _occurrence(when: datetime, subject: str = "Café todo dia"):
    return {"generate_at": when, "video_subject": subject}


def test_create_schedule_persists_one_row_per_occurrence(db_path):
    now = datetime(2026, 3, 5, 9, 0)
    group_id = schedule_store.create_schedule(
        occurrences=[_occurrence(now), _occurrence(now + timedelta(days=1))],
        params=BASE_PARAMS,
        db_path=db_path,
    )

    rows = schedule_store.list_occurrences(db_path=db_path)
    assert len(rows) == 2
    assert all(row["group_id"] == group_id for row in rows)
    assert {row["status"] for row in rows} == {"pending"}


def test_create_schedule_stores_per_occurrence_subject(db_path):
    now = datetime(2026, 3, 5, 9, 0)
    schedule_store.create_schedule(
        occurrences=[
            _occurrence(now, "Assunto A"),
            _occurrence(now + timedelta(days=1), "Assunto B"),
        ],
        params=BASE_PARAMS,
        db_path=db_path,
    )

    rows = sorted(
        schedule_store.list_occurrences(db_path=db_path),
        key=lambda r: r["generate_at"],
    )
    assert [row["video_subject"] for row in rows] == ["Assunto A", "Assunto B"]


def test_create_schedule_stores_youtube_overrides(db_path):
    schedule_store.create_schedule(
        occurrences=[_occurrence(datetime(2026, 3, 5, 9, 0))],
        params=BASE_PARAMS,
        youtube_title="Título fixo",
        youtube_description="Descrição fixa",
        youtube_tags=["tag1", "tag2"],
        youtube_publish_offset_hours=2.5,
        youtube_review_required=True,
        db_path=db_path,
    )

    row = schedule_store.list_occurrences(db_path=db_path)[0]
    assert row["youtube_title"] == "Título fixo"
    assert row["youtube_description"] == "Descrição fixa"
    assert row["youtube_tags"] == ["tag1", "tag2"]
    assert row["youtube_publish_offset_hours"] == 2.5
    assert row["youtube_review_required"] is True


def test_get_due_occurrences_only_returns_past_pending_rows(db_path):
    past = datetime(2026, 3, 5, 9, 0)
    future = datetime(2026, 3, 20, 9, 0)
    schedule_store.create_schedule(
        occurrences=[_occurrence(past), _occurrence(future)],
        params=BASE_PARAMS,
        db_path=db_path,
    )

    due = schedule_store.get_due_occurrences(now=datetime(2026, 3, 6), db_path=db_path)
    assert len(due) == 1
    assert due[0]["video_subject"] == "Café todo dia"


def test_get_due_occurrences_skips_already_dispatched(db_path):
    past = datetime(2026, 3, 5, 9, 0)
    group_id = schedule_store.create_schedule(
        occurrences=[_occurrence(past)], params=BASE_PARAMS, db_path=db_path
    )
    occurrence_id = schedule_store.list_occurrences(db_path=db_path)[0]["id"]
    schedule_store.mark_dispatched(occurrence_id, task_id="task-1", db_path=db_path)

    due = schedule_store.get_due_occurrences(now=datetime(2026, 3, 6), db_path=db_path)
    assert due == []

    row = schedule_store.list_occurrences(group_id=group_id, db_path=db_path)[0]
    assert row["status"] == "dispatched"
    assert row["task_id"] == "task-1"


def test_mark_failed_records_error_and_status(db_path):
    schedule_store.create_schedule(
        occurrences=[_occurrence(datetime(2026, 3, 5, 9, 0))],
        params=BASE_PARAMS,
        db_path=db_path,
    )
    occurrence_id = schedule_store.list_occurrences(db_path=db_path)[0]["id"]

    schedule_store.mark_failed(occurrence_id, error="ffmpeg missing", db_path=db_path)

    row = schedule_store.list_occurrences(db_path=db_path)[0]
    assert row["status"] == "failed"
    assert row["error"] == "ffmpeg missing"


def test_cancel_occurrence_marks_single_row_cancelled(db_path):
    group_id = schedule_store.create_schedule(
        occurrences=[
            _occurrence(datetime(2026, 3, 5, 9, 0)),
            _occurrence(datetime(2026, 3, 6, 9, 0)),
        ],
        params=BASE_PARAMS,
        db_path=db_path,
    )
    rows = schedule_store.list_occurrences(group_id=group_id, db_path=db_path)

    schedule_store.cancel_occurrence(rows[0]["id"], db_path=db_path)

    updated = schedule_store.list_occurrences(group_id=group_id, db_path=db_path)
    statuses = {row["id"]: row["status"] for row in updated}
    assert statuses[rows[0]["id"]] == "cancelled"
    assert statuses[rows[1]["id"]] == "pending"


def test_cancel_group_marks_all_pending_rows_cancelled(db_path):
    group_id = schedule_store.create_schedule(
        occurrences=[
            _occurrence(datetime(2026, 3, 5, 9, 0)),
            _occurrence(datetime(2026, 3, 6, 9, 0)),
        ],
        params=BASE_PARAMS,
        db_path=db_path,
    )

    cancelled_count = schedule_store.cancel_group(group_id, db_path=db_path)

    assert cancelled_count == 2
    rows = schedule_store.list_occurrences(group_id=group_id, db_path=db_path)
    assert all(row["status"] == "cancelled" for row in rows)


def test_cancel_group_does_not_touch_dispatched_rows(db_path):
    group_id = schedule_store.create_schedule(
        occurrences=[_occurrence(datetime(2026, 3, 5, 9, 0))],
        params=BASE_PARAMS,
        db_path=db_path,
    )
    occurrence_id = schedule_store.list_occurrences(group_id=group_id, db_path=db_path)[
        0
    ]["id"]
    schedule_store.mark_dispatched(occurrence_id, task_id="task-1", db_path=db_path)

    cancelled_count = schedule_store.cancel_group(group_id, db_path=db_path)

    assert cancelled_count == 0
    row = schedule_store.list_occurrences(group_id=group_id, db_path=db_path)[0]
    assert row["status"] == "dispatched"


def test_list_occurrences_filters_by_status(db_path):
    group_id = schedule_store.create_schedule(
        occurrences=[
            _occurrence(datetime(2026, 3, 5, 9, 0)),
            _occurrence(datetime(2026, 3, 6, 9, 0)),
        ],
        params=BASE_PARAMS,
        db_path=db_path,
    )
    occurrence_id = schedule_store.list_occurrences(group_id=group_id, db_path=db_path)[
        0
    ]["id"]
    schedule_store.mark_dispatched(occurrence_id, task_id="task-1", db_path=db_path)

    pending = schedule_store.list_occurrences(status="pending", db_path=db_path)
    assert len(pending) == 1


def test_params_round_trips_through_json(db_path):
    params = {"video_subject": "x", "voice_name": "pt-BR-AntonioNeural", "video_count": 2}
    schedule_store.create_schedule(
        occurrences=[_occurrence(datetime(2026, 3, 5, 9, 0))],
        params=params,
        db_path=db_path,
    )
    row = schedule_store.list_occurrences(db_path=db_path)[0]
    assert row["params"]["voice_name"] == "pt-BR-AntonioNeural"
    assert row["params"]["video_count"] == 2


def test_creates_table_on_first_connect(db_path):
    schedule_store.create_schedule(
        occurrences=[_occurrence(datetime(2026, 3, 5, 9, 0))],
        params=BASE_PARAMS,
        db_path=db_path,
    )
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "schedule_occurrences" in tables
