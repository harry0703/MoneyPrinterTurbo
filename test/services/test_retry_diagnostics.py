from unittest.mock import patch
import cli
from app.services import task as tm
from app.services.state import MemoryState


def test_cli_retry_of_failed_task_id_clears_previous_failure_diagnostics(capsys):
    state = MemoryState()
    state.update_task(
        "00000000-0000-4000-8000-000000000001",
        state=tm.const.TASK_STATE_FAILED,
        failed_stage="audio",
        error="old provider outage",
        video_subject="Coffee",
    )
    with patch.object(tm.sm, "state", state):
        code = cli.run_cli(
            [
                "--task-id",
                "00000000-0000-4000-8000-000000000001",
                "--video-subject",
                "Coffee",
                "--video-script",
                "New narration",
                "--stop-at",
                "script",
            ]
        )
    assert code == 0
    task = state.get_task("00000000-0000-4000-8000-000000000001")
    assert task["state"] == tm.const.TASK_STATE_COMPLETE
    assert task.get("error") is None
    assert task.get("failed_stage") is None
    assert task["video_subject"] == "Coffee"
    assert task["script"] == "New narration"


def test_new_attempt_clears_diagnostics_before_generating_any_output():
    state = MemoryState()
    state.update_task(
        "00000000-0000-4000-8000-000000000001",
        state=tm.const.TASK_STATE_FAILED,
        failed_stage="audio",
        error="old provider outage",
    )
    from app.models.schema import VideoParams

    def generate(task_id, params):
        task = state.get_task(task_id)
        assert task.get("error") is None
        assert task.get("failed_stage") is None
        return "New narration"

    with (
        patch.object(tm.sm, "state", state),
        patch.object(tm, "generate_script", side_effect=generate),
    ):
        result = tm.start(
            "00000000-0000-4000-8000-000000000001", VideoParams(video_subject="Coffee"), stop_at="script"
        )
    assert result == {"script": "New narration"}
