from unittest.mock import patch
import pytest
from app.models.schema import TaskVideoRequest
from app.services import task as tm
from app.services.state import MemoryState


@pytest.mark.parametrize("source", ["pexel", "unknown-provider", None, ""])
def test_unknown_material_source_fails_before_llm_or_narration(source):
    params = TaskVideoRequest(
        video_subject="Coffee", video_source=source, subtitle_enabled=False
    )
    state = MemoryState()
    with (
        patch.object(tm.sm, "state", state),
        patch.object(tm.utils, "check_ffmpeg_ready", return_value=True),
        patch.object(tm, "generate_script", return_value="Narration") as script,
        patch.object(tm, "generate_terms", return_value=["coffee"]) as terms,
        patch.object(tm, "save_script_data"),
        patch.object(tm, "generate_audio", return_value=(None, None, None)) as audio,
    ):
        result = tm.start("invalid-source", params)
    assert result["failed_stage"] == "preflight"
    assert "video source" in result["error"].lower()
    script.assert_not_called()
    terms.assert_not_called()
    audio.assert_not_called()


def test_script_only_stage_does_not_require_a_material_provider():
    params = TaskVideoRequest(
        video_subject="Coffee",
        video_source="unknown-provider",
        video_script="Narration",
    )
    with patch.object(tm.sm, "state", MemoryState()):
        assert tm.start("script-only", params, stop_at="script") == {
            "script": "Narration"
        }
