from unittest.mock import patch
import pytest
from app.models.schema import VideoParams
from app.services import task as tm
from app.services.state import MemoryState

@pytest.mark.parametrize("stage", ["audio", "subtitle"])
def test_narration_stages_do_not_depend_on_visual_search_terms(stage):
    params = VideoParams(video_subject="Coffee", video_script="A supplied script", video_source="pexels")
    state = MemoryState()
    with (patch.object(tm.sm, "state", state),
          patch.object(tm.utils, "check_ffmpeg_ready", return_value=True),
          patch.object(tm, "generate_terms", side_effect=RuntimeError("search terms unavailable")) as terms,
          patch.object(tm, "save_script_data") as save,
          patch.object(tm, "generate_audio", return_value=("audio.mp3", 3.0, object())) as audio,
          patch.object(tm, "generate_subtitle", return_value="captions.srt")):
        result = tm.start("task-1", params, stop_at=stage)
    terms.assert_not_called()
    audio.assert_called_once()
    assert state.get_task("task-1")["state"] == tm.const.TASK_STATE_COMPLETE
    assert result == ({"audio_file": "audio.mp3", "audio_duration": 3.0} if stage == "audio" else {"subtitle_path": "captions.srt"})
    assert save.call_args.args[2] == ""

def test_terms_stage_still_generates_visual_search_terms():
    params = VideoParams(video_subject="Coffee", video_script="A supplied script")
    with (patch.object(tm.sm, "state", MemoryState()), patch.object(tm, "save_script_data"),
          patch.object(tm, "generate_terms", return_value=["coffee beans"]) as terms):
        result = tm.start("task-1", params, stop_at="terms")
    terms.assert_called_once()
    assert result["terms"] == ["coffee beans"]
