"""验证图片动态效果的兼容默认值、参数传递和真实渲染像素。"""

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from moviepy import VideoFileClip
from PIL import Image, ImageDraw
from pydantic import ValidationError

import cli
from app.config import config
from app.models.schema import ImageMotion, MaterialInfo, TaskVideoRequest, VideoParams
from app.services import material, task, video


def test_old_requests_keep_zoom_and_invalid_motion_is_rejected():
    assert TaskVideoRequest(video_subject="old task").image_motion == ImageMotion.zoom
    assert TaskVideoRequest(video_subject="still", image_motion="static").image_motion == ImageMotion.static
    with pytest.raises(ValidationError, match="image_motion"):
        TaskVideoRequest(video_subject="bad", image_motion="unknown")


def test_api_motion_reaches_task_queue_and_rejects_invalid_input():
    from fastapi.testclient import TestClient
    from app import asgi
    from app.controllers.v1 import video as controller

    with (
        patch.dict(config.app, {"api_key": ""}),
        patch.object(controller.task_manager, "add_task") as enqueue,
        patch.object(controller.sm.state, "update_task"),
    ):
        client = TestClient(asgi.app)
        for value, expected in ((None, "zoom"), ("static", "static"), ("zoom", "zoom")):
            payload = {"video_subject": "test", "subtitle_enabled": False}
            if value is not None:
                payload["image_motion"] = value
            response = client.post("/api/v1/videos", json=payload)
            assert response.status_code == 200
            assert enqueue.call_args.kwargs["params"].image_motion == expected
        enqueue.reset_mock()
        response = client.post("/api/v1/videos", json={"video_subject": "test", "image_motion": "bad"})
        assert response.status_code == 400
        enqueue.assert_not_called()


def test_cli_motion_uses_saved_value_but_explicit_argument_wins():
    args = ["--video-subject", "test"]
    with patch.dict(config.ui, {}, clear=True):
        assert cli.build_video_params(cli.parse_args(args)).image_motion == ImageMotion.zoom
    with patch.dict(config.ui, {"image_motion": "static"}, clear=True):
        assert cli.build_video_params(cli.parse_args(args)).image_motion == ImageMotion.static
        explicit = cli.build_video_params(cli.parse_args(args + ["--image-motion", "zoom"]))
        assert explicit.image_motion == ImageMotion.zoom
    with patch.dict(config.ui, {"image_motion": "bad"}, clear=True):
        assert cli.build_video_params(cli.parse_args(args)).image_motion == ImageMotion.zoom
    with pytest.raises(SystemExit):
        cli.parse_args(args + ["--image-motion", "bad"])


@pytest.mark.parametrize("motion", [ImageMotion.static, ImageMotion.zoom])
def test_task_passes_motion_to_local_and_generated_images(motion):
    params = VideoParams(video_subject="test", video_source="local", image_motion=motion)
    with patch.object(video, "preprocess_video", return_value=[MaterialInfo(url="local.mp4")]) as preprocess:
        assert task.get_video_materials("motion-test", params, [], 2) == ["local.mp4"]
        assert preprocess.call_args.kwargs["image_motion"] == motion
    params.video_source = "openai_image"
    with patch.object(material, "download_videos", return_value=["generated.mp4"]) as download:
        assert task.get_video_materials("motion-test", params, ["scene"], 2) == ["generated.mp4"]
        assert download.call_args.kwargs["image_motion"] == motion


def test_generated_image_motion_reaches_renderer_without_extra_paid_requests(tmp_path):
    item = MaterialInfo(provider="openai_image", url=str(tmp_path / "scene.png"), duration=2)
    with (
        patch.object(material, "generate_images_openai", return_value=[item]) as generate,
        patch.object(video, "render_image_zoom_video", return_value="static.mp4") as render,
        patch.object(material, "_persist_material_sources"),
    ):
        paths = material.download_videos(
            "motion-test", ["first", "unused"], source="openai_image",
            audio_duration=2, max_clip_duration=2, image_motion="static",
        )
    assert paths == ["static.mp4"]
    generate.assert_called_once()
    assert render.call_args.kwargs["image_motion"] == "static"


def test_invalid_motion_is_rejected_before_paid_image_generation():
    with patch.object(material, "generate_images_openai") as generate:
        with pytest.raises(ValueError, match="ImageMotion"):
            material.download_videos(
                "motion-test", ["scene"], source="openai_image",
                audio_duration=2, image_motion="invalid",
            )
    generate.assert_not_called()


def _white_width(frame):
    _, x = np.where(frame.min(axis=2) > 220)
    return int(x.max() - x.min() + 1)


def test_native_static_pixels_zoom_default_and_output_identity(tmp_path):
    source = tmp_path / "scene.png"
    image = Image.new("RGB", (256, 256), (220, 0, 0))
    ImageDraw.Draw(image).rectangle((80, 80, 175, 175), fill="white")
    image.save(source)
    default = video.render_image_zoom_video(str(source), 3)
    zoom_bytes = Path(default).read_bytes()
    still = video.render_image_zoom_video(str(source), 3, image_motion="static")
    assert still != default
    assert Path(default).read_bytes() == zoom_bytes
    with VideoFileClip(still, audio=False) as clip:
        first, last = clip.get_frame(0), clip.get_frame(2.5)
        assert clip.size == [256, 256]
        assert clip.duration == pytest.approx(3, abs=0.04)
        assert abs(_white_width(first) - _white_width(last)) <= 1
        assert np.abs(first.astype(float) - last).mean() < 1
    with VideoFileClip(default, audio=False) as clip:
        assert _white_width(clip.get_frame(2.5)) > _white_width(clip.get_frame(0)) + 4
    assert video.render_image_zoom_video(str(source), 3, image_motion="zoom") == default


def test_static_image_preserves_alpha_composition(tmp_path):
    source = tmp_path / "alpha.png"
    Image.new("RGBA", (64, 64), (240, 0, 0, 128)).save(source)
    output = video.render_image_zoom_video(str(source), 0.2, image_motion="static")
    with VideoFileClip(output, audio=False) as clip:
        pixel = clip.get_frame(0)[32, 32]
        assert 110 <= pixel[0] <= 130
        assert max(pixel[1:]) < 5


@pytest.mark.parametrize("motion", ["static", "zoom"])
def test_failed_motion_render_keeps_previous_output_and_removes_partial_file(tmp_path, motion):
    source = tmp_path / "scene.png"
    Image.new("RGB", (64, 64), "red").save(source)
    output = video.render_image_zoom_video(str(source), 0.2, image_motion=motion)
    completed = Path(output).read_bytes()

    def interrupted_write(_clip, filename, **_kwargs):
        Path(filename).write_bytes(b"partial video")
        raise RuntimeError("encoder interrupted")

    with patch.object(video.CompositeVideoClip, "write_videofile", interrupted_write):
        with pytest.raises(RuntimeError, match="encoder interrupted"):
            video.render_image_zoom_video(str(source), 0.2, image_motion=motion)
    assert Path(output).read_bytes() == completed
    assert not list(tmp_path.glob(".image-zoom-*.mp4"))
