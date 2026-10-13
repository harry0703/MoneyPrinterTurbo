"""vgenv integration tests never make a paid or unauthenticated network call."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

import cli
from app.config import config
from app.models.schema import MaterialInfo, VideoAspect
from app.services import material, vgenv
from app.utils import utils


def response(body, status=200):
    return SimpleNamespace(status_code=status, json=lambda: body)


@pytest.fixture(autouse=True)
def settings():
    previous = dict(config.app)
    config.app.update({"vgenv_api_key": "secret-test-key", "vgenv_resolution": "768p", "vgenv_tier": "fast"})
    yield
    config.app.clear()
    config.app.update(previous)


def test_v3_submit_poll_raw_and_isolated_idempotency_keys():
    output = {"id": "video-1", "status": "succeeded", "output": {"url": "https://cdn.example.com/one.mp4?sig=abc"}}
    with (
        patch.object(vgenv.requests, "post", return_value=response({"id": "video-1"}, 202)) as post,
        patch.object(vgenv.requests, "get", return_value=response(output)) as get,
    ):
        first = vgenv.generate_videos("A city at sunrise", 5, VideoAspect.landscape)
        vgenv.generate_videos("A city at sunrise", 5, VideoAspect.landscape)
    assert first[0].provider == "vgenv"
    assert first[0].source_info["asset_id"] == "video-1"
    assert get.call_args.kwargs["allow_redirects"] is False
    assert post.call_args_list[0].args[0] == "https://api.vgenv.com/v3/videos"
    assert post.call_args_list[0].kwargs["json"] == {
        "model": "base", "tier": "fast", "prompt": "A city at sunrise",
        "duration": 5, "resolution": "768p", "aspect_ratio": "16:9",
        "prompt_optimization": {"mode": "raw"},
    }
    assert post.call_args_list[0].kwargs["headers"]["Idempotency-Key"] != post.call_args_list[1].kwargs["headers"]["Idempotency-Key"]
    assert post.call_args.kwargs["allow_redirects"] is False


def test_create_retry_uses_same_key_and_stops_when_unconfirmed():
    with (
        patch.object(vgenv.requests, "post", side_effect=[requests.Timeout(), response({"id": "video-1"}, 202)]) as post,
        patch.object(vgenv.requests, "get", return_value=response({"status": "failed"})),
    ):
        with pytest.raises(vgenv.VgenvError):
            vgenv.generate_videos("A city at sunrise", 5)
    assert post.call_count == 2
    assert post.call_args_list[0].kwargs["headers"]["Idempotency-Key"] == post.call_args_list[1].kwargs["headers"]["Idempotency-Key"]

    with patch.object(vgenv.requests, "post", return_value=response({}, 503)) as post:
        with pytest.raises(vgenv.VgenvUnconfirmedTaskError):
            vgenv.generate_videos("A city at sunrise", 5)
    assert post.call_count == 2


def test_wrong_poll_id_and_missing_output_preserve_remote_id():
    for result in [
        {"id": "other-video", "status": "running"},
        {"id": "video-1", "status": "succeeded", "output": None},
    ]:
        with (
            patch.object(vgenv.requests, "post", return_value=response({"id": "video-1"}, 202)),
            patch.object(vgenv.requests, "get", return_value=response(result)),
        ):
            with pytest.raises(vgenv.VgenvError) as raised:
                vgenv.generate_videos("A city at sunrise", 5)
        assert raised.value.task_id == "video-1"


def test_timeout_cancels_same_task_and_preserves_id():
    with (
        patch.object(vgenv.requests, "post", return_value=response({"id": "video-1"}, 202)),
        patch.object(vgenv.requests, "get", return_value=response({"status": "running"})),
        patch.object(vgenv.requests, "delete") as delete,
        patch.object(vgenv.time, "monotonic", side_effect=[0, 1] + [1801] * 30),
        patch.object(vgenv.time, "sleep"),
    ):
        with pytest.raises(vgenv.VgenvUnconfirmedTaskError) as raised:
            vgenv.generate_videos("A city at sunrise", 5)
    assert raised.value.task_id == "video-1"
    assert delete.call_args.args[0].endswith("/v3/videos/video-1")
    assert delete.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("url", [
    "http://cdn.example.com/video.mp4", "https://localhost/video.mp4",
    "https://127.0.0.1/video.mp4", "https://user:pass@cdn.example.com/video.mp4",
])
def test_reject_unsafe_download_url(url):
    with pytest.raises(vgenv.VgenvError):
        vgenv._safe_output_url(url)


def test_safe_download_does_not_follow_redirect_or_replace_concurrent_file(tmp_path):
    url = "https://cdn.example.com/video.mp4?sig=abc"
    target = tmp_path / f"vid-{utils.md5(url)}.mp4"

    class Download:
        headers = {"Content-Length": "4"}

        def __enter__(self):
            target.write_bytes(b"winner")  # Published by another worker mid-download.
            return self

        def __exit__(self, *_):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"data"

    with (
        patch.object(material.requests, "get", return_value=Download()) as get,
        patch.object(material, "VideoFileClip", return_value=SimpleNamespace(duration=5, fps=24, close=lambda: None)),
        patch.object(material.material_upload, "_validate_video"),
    ):
        result = material.save_video(url, str(tmp_path), safe_download=True)
    assert result == str(target)
    assert target.read_bytes() == b"winner"
    assert get.call_args.kwargs["allow_redirects"] is False


def test_invalid_input_never_submits_paid_job():
    for prompt, duration in [("short", 0), ("a", 5), ("A city at sunrise", float("nan"))]:
        with patch.object(vgenv.requests, "post") as post:
            with pytest.raises(vgenv.VgenvError):
                vgenv.generate_videos(prompt, duration)
            post.assert_not_called()


def test_cli_exposes_independent_opt_in_source_and_confirmation():
    args = cli.parse_args([
        "--video-subject", "City scenes", "--video-source", "vgenv",
        "--confirm-vgenv-charge",
    ])
    assert args.video_source == "vgenv"
    assert args.confirm_vgenv_charge is True


def test_material_uses_downloaded_duration_and_stops_after_failure(tmp_path):
    items = [MaterialInfo(provider="vgenv", url="https://cdn.example.com/video.mp4", duration=15,
                          source_info={"asset_id": "video-1"})]
    with (
        patch.object(vgenv, "generate_videos", return_value=items) as generate,
        patch.object(material, "_save_generated_video_with_retry", return_value=str(tmp_path / "clip.mp4")),
        patch.object(material, "_get_downloaded_video_duration", return_value=2),
        patch.object(material, "_persist_material_sources"),
    ):
        material._download_videos_vgenv_on_demand(
            task_id="local-task", search_terms=["first", "second", "third"],
            video_aspect=VideoAspect.portrait, audio_duration=4,
            max_clip_duration=5, material_directory=str(tmp_path),
        )
    assert generate.call_count == 2  # 15-second claim cannot cover a 4-second voiceover.

    with (
        patch.object(vgenv, "generate_videos", side_effect=vgenv.VgenvUnconfirmedTaskError("unknown", "video-1")) as generate,
        patch.object(material, "_persist_material_sources"),
    ):
        with pytest.raises(vgenv.VgenvUnconfirmedTaskError):
            material._download_videos_vgenv_on_demand(
                task_id="local-task", search_terms=["first", "second"],
                video_aspect=VideoAspect.portrait, audio_duration=4,
                max_clip_duration=5, material_directory=str(tmp_path),
            )
    assert generate.call_count == 1


def test_download_failure_never_creates_replacement(tmp_path):
    item = MaterialInfo(provider="vgenv", url="https://cdn.example.com/video.mp4", duration=5,
                        source_info={"asset_id": "video-1"})
    with (
        patch.object(vgenv, "generate_videos", return_value=[item]) as generate,
        patch.object(material, "_save_generated_video_with_retry", return_value=""),
        patch.object(material, "_persist_material_sources"),
    ):
        with pytest.raises(vgenv.VgenvDownloadError) as raised:
            material._download_videos_vgenv_on_demand(
                task_id="local-task", search_terms=["first", "second"],
                video_aspect=VideoAspect.portrait, audio_duration=10,
                max_clip_duration=5, material_directory=str(tmp_path),
            )
    assert raised.value.task_id == "video-1"
    assert generate.call_count == 1
