"""覆盖付费提交幂等边界、模型参数、下载凭据隔离及素材按需生成。"""

import subprocess
import imageio_ffmpeg
from types import SimpleNamespace
from unittest.mock import patch, Mock

import pytest
import requests

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoParams
from app.services import infistar_video as provider, material, task, state
import cli


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    monkeypatch.setattr(config, "app", {"infistar_video_api_key": "test-infistar-key"})
    monkeypatch.setattr(config, "proxy", {})
    monkeypatch.setenv("INFISTAR_VIDEO_API_KEY", "")


def response(body=None, status=200, headers=None, content=b"video"):
    return SimpleNamespace(
        status_code=status,
        json=lambda: body,
        headers=headers or {},
        close=Mock(),
        iter_content=lambda _: iter([content]),
    )


def test_video_key_is_independent_from_llm(monkeypatch):
    assert provider.get_api_key() == "test-infistar-key"
    config.app.clear()
    config.app.update({"openai_api_key": "other-key", "infistar_api_key": "llm-key"})
    assert not provider.is_enabled()
    monkeypatch.setenv("INFISTAR_VIDEO_API_KEY", "env-key")
    assert provider.get_api_key() == "env-key"


@pytest.mark.parametrize(
    "model,seconds,size",
    [
        (provider.DEFAULT_MODEL, "5", "720x1280"),
        ("MiniMax-H3", "6", "768p"),
        ("kling-v2-6", "5", "720x1280"),
    ],
)
def test_model_specific_request_and_success(model, seconds, size, tmp_path):
    config.app["infistar_video_model"] = model
    with (
        patch.object(
            provider, "_request", return_value=response({"id": "task-1"})
        ) as send,
        patch.object(provider, "_wait", return_value={"status": "completed"}),
        patch.object(
            provider, "_download", return_value=(tmp_path / "video.mp4", 6.1, 720, 1280)
        ),
    ):
        item = provider.generate_video(
            search_term="  sunrise  ",
            video_aspect=VideoAspect.portrait,
            output_dir=tmp_path,
        )
    body = send.call_args.kwargs["json"]
    assert (
        body["model"] == model and body["seconds"] == seconds and body["size"] == size
    )
    assert body["prompt"] == "sunrise"
    if model == "MiniMax-H3":
        assert "aspect_ratio" not in body
    assert item.source_info["asset_id"] == "task-1"
    assert "test-infistar-key" not in repr(item)


@pytest.mark.parametrize("status", [301, 302, 307, 308, 500, 502, 503])
def test_ambiguous_submission_is_never_retried(status, tmp_path):
    with patch.object(
        provider, "_request", return_value=response(status=status)
    ) as send:
        with pytest.raises(provider.InfistarVideoUnconfirmedError):
            provider.generate_video(
                search_term="sunrise", video_aspect="16:9", output_dir=tmp_path
            )
    assert send.call_count == 1


def test_submission_timeout_is_never_retried(tmp_path):
    with patch.object(provider, "_request", side_effect=requests.Timeout()) as send:
        with pytest.raises(provider.InfistarVideoUnconfirmedError):
            provider.generate_video(
                search_term="sunrise", video_aspect="16:9", output_dir=tmp_path
            )
    assert send.call_count == 1


@pytest.mark.parametrize("status", [400, 401, 403, 422, 429])
def test_clear_rejection_does_not_poll_or_download(status, tmp_path):
    with (
        patch.object(
            provider,
            "_request",
            return_value=response(
                {"message": "test-infistar-key insufficient_user_quota"}, status
            ),
        ) as send,
        patch.object(provider, "_wait") as wait,
    ):
        with pytest.raises(provider.InfistarVideoError) as caught:
            provider.generate_video(
                search_term="sunrise", video_aspect="16:9", output_dir=tmp_path
            )
    assert "test-infistar-key" not in str(caught.value)
    assert send.call_count == 1
    wait.assert_not_called()


@pytest.mark.parametrize("body", [[], {}, {"status": "queued"}])
def test_malformed_accepted_response_does_not_resubmit(body, tmp_path):
    with patch.object(provider, "_request", return_value=response(body)) as send:
        with pytest.raises(provider.InfistarVideoUnconfirmedError):
            provider.generate_video(
                search_term="sunrise", video_aspect="16:9", output_dir=tmp_path
            )
    assert send.call_count == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("infistar_video_model", "unknown"),
        ("infistar_video_api_key", ""),
        ("infistar_video_base_url", "https://user:pass@example.com/v1"),
    ],
)
def test_invalid_config_rejected_before_payment(field, value, tmp_path):
    config.app[field] = value
    with patch.object(provider, "_request") as send:
        with pytest.raises(provider.InfistarVideoError):
            provider.generate_video(
                search_term="sunrise", video_aspect="16:9", output_dir=tmp_path
            )
    send.assert_not_called()


@pytest.mark.parametrize(
    "term,aspect", [("", "16:9"), ("x" * 2001, "16:9"), ("sunrise", "1:1")]
)
def test_invalid_input_rejected_before_payment(term, aspect, tmp_path):
    with patch.object(provider, "_request") as send:
        with pytest.raises(provider.InfistarVideoError):
            provider.generate_video(
                search_term=term, video_aspect=aspect, output_dir=tmp_path
            )
    send.assert_not_called()


def test_pending_and_in_progress_are_not_terminal():
    with (
        patch.object(
            provider,
            "_request",
            side_effect=[
                response({"status": s})
                for s in ["pending", "queued", "in_progress", "completed"]
            ],
        ),
        patch.object(provider.time, "sleep"),
    ):
        assert (
            provider._wait("paid-task", provider.DEFAULT_BASE_URL, {}, "key")["status"]
            == "completed"
        )


@pytest.mark.parametrize(
    "body", [{"status": "unknown"}, {"status": "failed", "error": "bad prompt"}, []]
)
def test_failed_or_unknown_poll_keeps_task_id(body):
    with patch.object(provider, "_request", return_value=response(body)):
        with pytest.raises(provider.InfistarVideoError) as caught:
            provider._wait("paid-task", provider.DEFAULT_BASE_URL, {}, "key")
    assert caught.value.task_id == "paid-task"


def test_poll_transient_errors_retry_only_same_task():
    with (
        patch.object(
            provider,
            "_request",
            side_effect=[
                response(status=429),
                requests.Timeout(),
                response({"status": "completed"}),
            ],
        ) as send,
        patch.object(provider.time, "sleep"),
    ):
        provider._wait("paid-task", provider.DEFAULT_BASE_URL, {}, "key")
    assert all(
        call.args[:2] == ("GET", provider.DEFAULT_BASE_URL + "/videos/paid-task")
        for call in send.call_args_list
    )


def test_poll_network_failure_keeps_task_id():
    with (
        patch.object(provider, "_request", side_effect=requests.Timeout()),
        patch.object(provider.time, "sleep"),
    ):
        with pytest.raises(provider.InfistarVideoUnconfirmedError) as caught:
            provider._wait("paid-task", provider.DEFAULT_BASE_URL, {}, "key")
    assert caught.value.task_id == "paid-task"


def test_download_redirect_drops_authorization_and_validates_real_video(tmp_path):
    fixture = tmp_path / "input.mp4"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:d=1:r=4",
            "-c:v",
            "libx264",
            str(fixture),
        ],
        check=True,
        capture_output=True,
    )
    redirect = response(
        status=302, headers={"Location": "https://cdn.example/video.mp4?sig=signed"}
    )
    content = response(content=fixture.read_bytes())
    with patch.object(provider, "_request", side_effect=[redirect, content]) as send:
        path, duration, width, height = provider._download(
            "../paid-task",
            provider.DEFAULT_BASE_URL,
            {"Authorization": "Bearer secret"},
            tmp_path,
        )
    assert path.parent == tmp_path and path.is_file() and duration > 0
    assert send.call_args_list[0].kwargs["headers"] == {
        "Authorization": "Bearer secret"
    }
    assert send.call_args_list[1].kwargs["headers"] == {}
    assert redirect.close.called and content.close.called
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("content", [b"", b'{"error":"not a video"}'])
def test_bad_download_keeps_task_id_and_removes_partial_file(content, tmp_path):
    with patch.object(provider, "_request", return_value=response(content=content)):
        with pytest.raises(provider.InfistarVideoError) as caught:
            provider._download("paid-task", provider.DEFAULT_BASE_URL, {}, tmp_path)
    assert caught.value.task_id == "paid-task"
    assert not list(tmp_path.iterdir())


def test_material_generation_stops_when_audio_is_covered(tmp_path):
    item = MaterialInfo(
        provider="infistar", url=str(tmp_path / "video.mp4"), duration=5
    )
    with (
        patch.object(provider, "generate_video", return_value=item) as generate,
        patch.object(material, "_persist_material_sources"),
        patch.object(material.utils, "task_dir", return_value=str(tmp_path)),
    ):
        paths = material.download_videos(
            task_id="test",
            search_terms=["one", "two", "unused"],
            source="infistar",
            video_aspect=VideoAspect.landscape,
            audio_duration=8,
            max_clip_duration=5,
        )
    assert generate.call_count == 2 and len(paths) == 2


def test_unknown_paid_task_stops_next_material_and_surfaces_recovery_id(tmp_path):
    params = VideoParams(
        video_subject="test", video_source="infistar", video_terms="one,two"
    )
    with (
        patch.object(
            provider,
            "generate_video",
            side_effect=provider.InfistarVideoUnconfirmedError(
                "wait timeout", "paid-task"
            ),
        ) as generate,
        patch.object(material, "_persist_material_sources"),
        patch.object(material.utils, "task_dir", return_value=str(tmp_path)),
        patch.object(task.sm, "state", state.MemoryState()),
    ):
        task.sm.state.update_task("test")
        assert task.get_video_materials("test", params, ["one", "two"], 8) is None
        result = task.sm.state.get_task("test")
    assert generate.call_count == 1
    assert result["infistar_task_id"] == "paid-task"


def test_cli_requires_charge_confirmation():
    with pytest.raises(SystemExit):
        cli.parse_args(["--video-subject", "test", "--video-source", "infistar"])
    args = cli.parse_args(
        [
            "--video-subject",
            "test",
            "--video-source",
            "infistar",
            "--confirm-infistar-charge",
        ]
    )
    assert args.video_source == "infistar" and args.confirm_infistar_charge


@pytest.mark.parametrize("required", [float("nan"), float("inf"), "invalid"])
def test_invalid_audio_duration_never_submits(required):
    with patch.object(provider, "generate_video") as generate:
        with pytest.raises(provider.InfistarVideoError):
            material.download_videos(
                task_id="test",
                search_terms=["one"],
                source="infistar",
                video_aspect=VideoAspect.landscape,
                audio_duration=required,
                max_clip_duration=5,
            )
    generate.assert_not_called()


def test_infistar_preflight_handles_default_aspect_before_tts():
    params = VideoParams(
        video_subject="test",
        video_script="test",
        video_terms="sunrise",
        video_source="infistar",
    )
    with (
        patch.object(task, "generate_script", return_value="test"),
        patch.object(task, "generate_terms", return_value=["sunrise"]),
        patch.object(task, "generate_audio", return_value=(None, None, None)) as audio,
        patch.object(task.sm, "state", state.MemoryState()),
    ):
        task.start("infistar-preflight", params)
    audio.assert_called_once()


def test_video_request_does_not_use_llm_key_or_base_url(tmp_path):
    config.app.update(
        {
            "llm_provider": "openai",
            "infistar_api_key": "llm-key",
            "infistar_base_url": "https://llm.example/v1",
            "infistar_video_base_url": "https://video.example/v1",
        }
    )
    with (
        patch.object(
            provider, "_request", return_value=response({"id": "task-1"})
        ) as send,
        patch.object(provider, "_wait", return_value={"status": "completed"}),
        patch.object(
            provider, "_download", return_value=(tmp_path / "video.mp4", 5, 1280, 720)
        ),
    ):
        provider.generate_video(
            search_term="sunrise", video_aspect="16:9", output_dir=tmp_path
        )
    assert send.call_args.args[:2] == ("POST", "https://video.example/v1/videos")
    assert (
        send.call_args.kwargs["headers"]["Authorization"] == "Bearer test-infistar-key"
    )
