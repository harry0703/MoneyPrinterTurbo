from types import SimpleNamespace
from unittest.mock import patch
import pytest
from app.models.schema import VideoParams, VideoConcatMode
from app.services import video


class SourceClip:
    size = (1080, 1920)
    w, h = size
    duration = 3.0

    def subclipped(self, start, end):
        child = SourceClip()
        child.duration = end - start
        return child

    def close(self):
        pass


@pytest.mark.parametrize(
    "mode",
    [
        VideoParams(video_subject="Coffee").video_concat_mode,
        "sequential",
        None,
        VideoConcatMode.random,
    ],
)
def test_combine_accepts_request_model_default_and_supported_modes(tmp_path, mode):
    audio = SimpleNamespace(duration=2.0, close=lambda: None)
    with (
        patch.object(video, "AudioFileClip", return_value=audio),
        patch.object(
            video,
            "_open_video_clip_quietly",
            side_effect=lambda *args, **kwargs: SourceClip(),
        ),
        patch.object(video, "_write_videofile_with_codec_fallback") as writer,
        patch.object(video, "concat_video_clips_with_ffmpeg") as concat,
        patch.object(video, "delete_files"),
    ):
        output = str(tmp_path / "combined.mp4")
        assert (
            video.combine_videos(
                output, ["source.mp4"], "audio.mp3", video_concat_mode=mode
            )
            == output
        )
    writer.assert_called_once()
    concat.assert_called_once()


def test_nullable_api_mode_reaches_native_renderer_and_completes(tmp_path):
    from app.models.schema import TaskVideoRequest
    from app.services import task as tm
    from app.services.state import MemoryState

    params = TaskVideoRequest(
        video_subject="Coffee",
        video_script="Supplied narration",
        video_concat_mode=None,
        subtitle_enabled=False,
        bgm_type="",
    )
    state = MemoryState()
    audio = SimpleNamespace(duration=2.0, close=lambda: None)
    with (
        patch.object(tm.sm, "state", state),
        patch.object(tm.utils, "check_ffmpeg_ready", return_value=True),
        patch.object(tm.utils, "task_dir", return_value=str(tmp_path)),
        patch.object(tm, "generate_terms", return_value=["coffee"]),
        patch.object(tm, "save_script_data"),
        patch.object(tm, "generate_audio", return_value=("audio.mp3", 2.0, None)),
        patch.object(tm, "generate_subtitle", return_value=""),
        patch.object(tm, "get_video_materials", return_value=["source.mp4"]),
        patch.object(
            tm.upload_post.upload_post_service, "is_configured", return_value=False
        ),
        patch.object(video, "AudioFileClip", return_value=audio),
        patch.object(
            video,
            "_open_video_clip_quietly",
            side_effect=lambda *args, **kwargs: SourceClip(),
        ),
        patch.object(video, "_write_videofile_with_codec_fallback"),
        patch.object(video, "concat_video_clips_with_ffmpeg"),
        patch.object(video, "delete_files"),
        patch.object(video, "generate_video"),
    ):
        result = tm.start("task-null-mode", params)
    assert result["videos"] == [str(tmp_path / "final-1.mp4")]
    assert state.get_task("task-null-mode")["state"] == tm.const.TASK_STATE_COMPLETE
