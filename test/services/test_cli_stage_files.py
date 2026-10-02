from unittest.mock import patch
import pytest
import cli
from app.models.schema import VideoParams


@pytest.mark.parametrize("stage", ["script", "terms"])
def test_text_only_stage_ignores_unused_custom_audio_and_bgm_paths(stage):
    params = VideoParams(
        video_subject="Coffee",
        custom_audio_file="missing.wav",
        bgm_type="custom",
        bgm_file="missing.mp3",
    )
    with (
        patch.object(
            cli,
            "_resolve_cli_file",
            side_effect=AssertionError("unused audio was opened"),
        ),
        patch(
            "app.services.bgm.resolve_bgm_file",
            side_effect=AssertionError("unused music was opened"),
        ),
    ):
        assert cli._validate_cli_files(params, stage) == ("", [])


@pytest.mark.parametrize("stage", ["audio", "subtitle", "materials"])
def test_non_video_stage_does_not_require_unused_background_music(stage):
    params = VideoParams(
        video_subject="Coffee", bgm_type="custom", bgm_file="missing.mp3"
    )
    with patch(
        "app.services.bgm.resolve_bgm_file",
        side_effect=AssertionError("unused music was opened"),
    ):
        assert cli._validate_cli_files(params, stage) == ("", [])


def test_video_stage_still_validates_background_music():
    params = VideoParams(
        video_subject="Coffee",
        bgm_type="custom",
        bgm_file="missing.mp3",
        subtitle_enabled=False,
    )
    with patch(
        "app.services.bgm.resolve_bgm_file", side_effect=ValueError("missing music")
    ):
        with pytest.raises(ValueError, match="background music"):
            cli._validate_cli_files(params, "video")
