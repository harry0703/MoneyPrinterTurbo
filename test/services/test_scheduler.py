from datetime import datetime
from unittest.mock import patch

from app.services import scheduler


def _occurrence(**overrides) -> dict:
    base = {
        "id": 1,
        "group_id": "group-1",
        "generate_at": datetime(2026, 3, 5, 9, 0),
        "video_subject": "Café todo dia",
        "params": {"video_subject": "Café todo dia", "video_aspect": "9:16"},
        "youtube_title": "",
        "youtube_description": "",
        "youtube_tags": [],
        "youtube_publish_offset_hours": 0.0,
        "youtube_review_required": False,
        "status": "pending",
        "task_id": None,
        "error": None,
        "created_at": datetime(2026, 3, 1, 9, 0),
    }
    base.update(overrides)
    return base


def test_dispatch_occurrence_starts_task_with_params_from_row():
    occurrence = _occurrence()

    with (
        patch.object(scheduler.task_service, "start") as start,
        patch.object(scheduler.schedule_store, "mark_dispatched") as mark_dispatched,
    ):
        scheduler._dispatch_occurrence(occurrence)

    assert start.call_count == 1
    task_id, params = start.call_args.args[:2]
    assert isinstance(task_id, str) and task_id
    assert params.video_subject == "Café todo dia"
    mark_dispatched.assert_called_once_with(1, task_id=task_id)


def test_dispatch_occurrence_applies_youtube_overrides():
    occurrence = _occurrence(
        youtube_title="Título fixo",
        youtube_description="Descrição fixa",
        youtube_tags=["a", "b"],
        youtube_publish_offset_hours=3.0,
        youtube_review_required=True,
    )

    with (
        patch.object(scheduler.task_service, "start") as start,
        patch.object(scheduler.schedule_store, "mark_dispatched"),
    ):
        scheduler._dispatch_occurrence(occurrence)

    params = start.call_args.args[1]
    assert params.youtube_title_override == "Título fixo"
    assert params.youtube_description_override == "Descrição fixa"
    assert params.youtube_tags_override == ["a", "b"]
    assert params.youtube_publish_offset_hours == 3.0
    assert params.youtube_review_required is True


def test_dispatch_occurrence_marks_failed_on_invalid_params_without_starting_task():
    occurrence = _occurrence(params={})  # missing required video_subject

    with (
        patch.object(scheduler.task_service, "start") as start,
        patch.object(scheduler.schedule_store, "mark_dispatched") as mark_dispatched,
        patch.object(scheduler.schedule_store, "mark_failed") as mark_failed,
    ):
        scheduler._dispatch_occurrence(occurrence)

    start.assert_not_called()
    mark_dispatched.assert_not_called()
    mark_failed.assert_called_once()
    assert mark_failed.call_args.args[0] == 1


def test_dispatch_occurrence_marks_dispatched_before_starting_the_pipeline():
    """mark_dispatched deve acontecer antes de start(), pra um poll concorrente
    nao pegar a mesma ocorrencia de novo enquanto start() ainda esta rodando."""
    occurrence = _occurrence()
    call_order = []

    with (
        patch.object(
            scheduler.task_service,
            "start",
            side_effect=lambda *a, **k: call_order.append("start"),
        ),
        patch.object(
            scheduler.schedule_store,
            "mark_dispatched",
            side_effect=lambda *a, **k: call_order.append("mark_dispatched"),
        ),
    ):
        scheduler._dispatch_occurrence(occurrence)

    assert call_order == ["mark_dispatched", "start"]


def test_dispatch_occurrence_survives_unexpected_start_crash():
    """task.start() ja se blinda sozinho, mas um crash inesperado no dispatcher
    nao pode subir e matar a thread do poller."""
    occurrence = _occurrence()

    with (
        patch.object(scheduler.task_service, "start", side_effect=RuntimeError("boom")),
        patch.object(scheduler.schedule_store, "mark_dispatched"),
    ):
        scheduler._dispatch_occurrence(occurrence)  # nao deve levantar


def test_poll_once_submits_every_due_occurrence():
    due = [_occurrence(id=1), _occurrence(id=2)]

    with (
        patch.object(scheduler.schedule_store, "get_due_occurrences", return_value=due),
        patch.object(scheduler, "_dispatch_executor") as executor,
    ):
        scheduler._poll_once()

    assert executor.submit.call_count == 2
    dispatched_ids = {call.args[1]["id"] for call in executor.submit.call_args_list}
    assert dispatched_ids == {1, 2}


def test_poll_once_does_not_raise_when_store_fails():
    with patch.object(
        scheduler.schedule_store,
        "get_due_occurrences",
        side_effect=RuntimeError("db locked"),
    ):
        scheduler._poll_once()  # nao deve levantar, so logar
