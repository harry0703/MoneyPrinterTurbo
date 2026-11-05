"""验证 Jalapeno 的 LLM 请求、Seedance 接入配置与付费任务边界。"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from openai import OpenAI
import pytest
import requests

import cli
from app.config import config
from app.models.llm_provider import get_llm_provider
from app.models.schema import MaterialInfo, VideoParams
from app.services import jalapeno_video as provider, llm, material, state, task
from app.services import volcengine_seedance as seedance


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    monkeypatch.setattr(config, "app", {"jalapeno_api_key": "shared-test-key"})
    monkeypatch.setattr(config, "proxy", {})
    monkeypatch.setenv("JALAPENO_VIDEO_API_KEY", "")
    monkeypatch.setattr(state, "state", state.MemoryState())


@pytest.mark.parametrize(
    "base,model,expected_url,expected_model",
    [
        (
            "",
            "",
            "https://api.jalapeno-cloud.ai/v1/chat/completions",
            "DeepSeek-V4.1-Flash",
        ),
        (
            "https://custom.example/v1",
            "custom-model",
            "https://custom.example/v1/chat/completions",
            "custom-model",
        ),
    ],
)
def test_llm_uses_real_sdk_and_provider_defaults(
    base, model, expected_url, expected_model
):
    received = []

    def respond(request):
        received.append(request)
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": expected_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "测试成功"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    def client(**kwargs):
        return OpenAI(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond))
        )

    settings = dict(
        config.app,
        llm_provider="jalapeno",
        jalapeno_base_url=base,
        jalapeno_model_name=model,
    )
    with patch.object(llm, "OpenAI", client):
        assert llm._generate_response("测试", app_config=settings) == "测试成功"
    assert len(received) == 1
    assert str(received[0].url) == expected_url
    assert received[0].headers["Authorization"] == "Bearer shared-test-key"
    assert json.loads(received[0].content)["model"] == expected_model
    spec = get_llm_provider("jalapeno")
    assert spec.api_key_url == provider.CAMPAIGN_URL
    assert spec.model_docs_url == provider.MODELS_URL


@pytest.mark.parametrize(
    "dedicated,environment,shared,expected",
    [
        ("video", "environment", "shared", "video"),
        ("", "environment", "shared", "environment"),
        ("", "", "shared", "shared"),
        (" ", "", " ", ""),
    ],
)
def test_video_key_precedence_and_independent_llm_selection(
    monkeypatch, dedicated, environment, shared, expected
):
    monkeypatch.setenv("JALAPENO_VIDEO_API_KEY", environment)
    values = {
        "llm_provider": "openai",
        "openai_api_key": "unrelated",
        "infistar_api_key": "unrelated",
        "jalapeno_video_api_key": dedicated,
        "jalapeno_api_key": shared,
    }
    assert provider.get_api_key(values) == expected
    assert provider.is_enabled(values) == bool(expected)


@pytest.mark.parametrize(
    "base",
    [
        provider.DEFAULT_BASE_URL,
        provider.DEFAULT_BASE_URL + "/",
        provider.DEFAULT_BASE_URL + provider.TASKS_PATH + "/",
    ],
)
def test_base_url_accepts_prefix_and_full_task_endpoint(base):
    endpoint = provider.endpoint(dict(config.app, jalapeno_video_base_url=base))
    assert endpoint.tasks_url == provider.DEFAULT_BASE_URL + provider.TASKS_PATH
    assert endpoint.model == "Doubao-Seedance-2-5-260628"
    assert endpoint.resolution == "480p"
    assert "shared-test-key" not in repr(endpoint)


@pytest.mark.parametrize(
    "base",
    [
        "ftp://example.com",
        "https://[bad/api/v3",
        "https://example.com:bad/api/v3",
        "https://user:password@example.com/api/v3",
        "https://example.com/api/v3?token=secret",
        "https://example.com/api/v3#fragment",
    ],
)
def test_invalid_endpoint_fails_before_audio_or_paid_submission(base):
    config.app["jalapeno_video_base_url"] = base
    params = VideoParams(
        video_subject="test",
        video_script="Ready.",
        video_source="jalapeno",
        subtitle_enabled=False,
    )
    with (
        patch.object(task, "generate_audio") as audio,
        patch.object(seedance.requests, "post") as submit,
    ):
        task.start("jalapeno-invalid-endpoint", params)
    audio.assert_not_called()
    submit.assert_not_called()
    assert (
        state.state.get_task("jalapeno-invalid-endpoint")["failed_stage"] == "preflight"
    )


def response(body, status=200):
    return SimpleNamespace(status_code=status, json=lambda: body)


def test_video_request_uses_explicit_endpoint_without_mutating_ark_config():
    config.app.update(
        {
            "jalapeno_video_api_key": "video-only",
            "volcengine_seedance_api_key": "ark-only",
            "volcengine_seedance_model": "original-ark-model",
            "jalapeno_video_poll_interval": 1,
        }
    )
    before = dict(config.app)
    with (
        patch.object(
            seedance.requests, "post", return_value=response({"id": "jala-1"})
        ) as submit,
        patch.object(
            seedance.requests,
            "get",
            return_value=response(
                {
                    "status": "succeeded",
                    "content": {"video_url": "https://cdn.example/1.mp4"},
                }
            ),
        ) as poll,
    ):
        items = provider.generate_videos("sunrise", 5, "16:9")
    assert config.app == before
    assert submit.call_count == 1
    assert submit.call_args.args[0] == provider.DEFAULT_BASE_URL + provider.TASKS_PATH
    assert submit.call_args.kwargs["headers"]["Authorization"] == "Bearer video-only"
    assert submit.call_args.kwargs["json"] == {
        "model": provider.DEFAULT_MODEL,
        "content": [{"type": "text", "text": "sunrise"}],
        "duration": 5,
        "resolution": "480p",
        "ratio": "16:9",
        "watermark": False,
        "generate_audio": False,
    }
    assert poll.call_args.args[0].endswith("/tasks/jala-1")
    assert items[0].provider == "jalapeno"
    assert items[0].source_info["provider"] == "jalapeno"


@pytest.mark.parametrize("status", [301, 500, 503])
def test_uncertain_submission_does_not_retry_or_poll(status):
    with (
        patch.object(
            seedance.requests, "post", return_value=response({}, status)
        ) as submit,
        patch.object(seedance.requests, "get") as poll,
    ):
        with pytest.raises(seedance.VolcEngineSeedanceUnconfirmedTaskError):
            provider.generate_videos("river", 5)
    assert submit.call_count == 1
    poll.assert_not_called()


def test_submit_timeout_does_not_retry():
    with patch.object(
        seedance.requests, "post", side_effect=requests.Timeout()
    ) as submit:
        with pytest.raises(seedance.VolcEngineSeedanceUnconfirmedTaskError):
            provider.generate_videos("river", 5)
    assert submit.call_count == 1


def test_transient_poll_failure_reuses_the_same_paid_task():
    with (
        patch.object(
            seedance.requests, "post", return_value=response({"id": "jala-retry"})
        ) as submit,
        patch.object(
            seedance.requests,
            "get",
            side_effect=[
                response({}, 429),
                response(
                    {
                        "status": "succeeded",
                        "content": {"video_url": "https://cdn.example/result.mp4"},
                    }
                ),
            ],
        ) as poll,
        patch.object(seedance.time, "sleep"),
    ):
        provider.generate_videos("river", 5)
    assert submit.call_count == 1
    assert poll.call_count == 2
    assert all(call.args[0].endswith("/jala-retry") for call in poll.call_args_list)


def test_materials_stop_after_covering_audio_and_keep_provider_identity(tmp_path):
    item = MaterialInfo(
        provider="jalapeno",
        url="https://cdn.example/clip.mp4",
        duration=5,
        source_info={"provider": "jalapeno", "asset_id": "jala-paid"},
    )
    with (
        patch.object(provider, "generate_videos", return_value=[item]) as generate,
        patch.object(
            material,
            "_save_generated_video_with_retry",
            return_value=str(tmp_path / "clip.mp4"),
        ) as download,
        patch.object(material, "VideoFileClip") as media,
    ):
        media.return_value.__enter__.return_value = SimpleNamespace(
            duration=5.04, size=(854, 480)
        )
        paths = material.download_videos(
            "jala-demand",
            ["first", "unused"],
            source="jalapeno",
            audio_duration=4,
            max_clip_duration=5,
        )
    assert len(paths) == 1
    assert generate.call_count == 1
    assert download.call_args.args[-1] == "jalapeno"
    assert item.duration == 5.04
    assert item.source_info["rendition"] == {"width": 854, "height": 480}


def test_failure_state_preserves_jalapeno_task_id():
    params = VideoParams(
        video_subject="test", video_script="Ready.", video_source="jalapeno"
    )
    error = seedance.VolcEngineSeedanceUnconfirmedTaskError(
        "still running", task_id="jala-known"
    )
    with patch.object(material, "download_videos", side_effect=error):
        assert task.get_video_materials("jala-failed", params, ["river"], 4) is None
    assert state.state.get_task("jala-failed")["jalapeno_task_id"] == "jala-known"


def test_cli_requires_explicit_charge_confirmation():
    with pytest.raises(SystemExit):
        cli.parse_args(["--video-subject", "test", "--video-source", "jalapeno"])
    args = cli.parse_args(
        [
            "--video-subject",
            "test",
            "--video-source",
            "jalapeno",
            "--confirm-jalapeno-charge",
        ]
    )
    assert cli.build_video_params(args).video_source == "jalapeno"
    assert args.confirm_jalapeno_charge


def test_unreadable_paid_video_stops_without_submitting_the_next_clip(tmp_path):
    item = MaterialInfo(
        provider="jalapeno",
        url="https://cdn.example/clip.mp4",
        duration=5,
        source_info={"provider": "jalapeno", "asset_id": "jala-paid"},
    )
    with (
        patch.object(provider, "generate_videos", return_value=[item]) as generate,
        patch.object(
            material,
            "_save_generated_video_with_retry",
            return_value=str(tmp_path / "clip.mp4"),
        ),
        patch.object(
            material, "VideoFileClip", side_effect=OSError("cannot read media")
        ),
    ):
        with pytest.raises(seedance.VolcEngineSeedanceDownloadError) as error:
            material.download_videos(
                "jala-unreadable",
                ["first", "unused"],
                source="jalapeno",
                audio_duration=10,
                max_clip_duration=5,
            )
    assert error.value.task_id == "jala-paid"
    assert generate.call_count == 1


def test_batch_jalapeno_requires_global_charge_confirmation(tmp_path):
    manifest = tmp_path / "tasks.json"
    manifest.write_text(
        json.dumps([{"video_subject": "river", "video_source": "jalapeno"}])
    )
    args = cli.parse_args(["--batch-file", str(manifest)])
    with pytest.raises(ValueError, match="confirm-jalapeno-charge"):
        cli._build_batch_tasks(args)
    args = cli.parse_args(["--batch-file", str(manifest), "--confirm-jalapeno-charge"])
    assert cli._build_batch_tasks(args)[0].video_source == "jalapeno"


def test_queued_webui_video_keeps_the_confirmed_endpoint():
    """真实队列延后执行：后续表单变化不能替换已确认的计费配置。"""
    from app.controllers.manager.memory_manager import InMemoryTaskManager
    from app.services import webui_task

    manager = InMemoryTaskManager(max_concurrent_tasks=0)
    config.app.update(
        jalapeno_video_api_key="confirmed-key",
        jalapeno_video_model=provider.DEFAULT_MODEL,
        jalapeno_video_resolution="480p",
    )
    expected = provider.endpoint()
    observed = []

    def execute(**kwargs):
        observed.append(kwargs.get("jalapeno_video_endpoint") or provider.endpoint())
        return {"videos": []}

    with (
        patch.object(webui_task, "_task_manager", manager),
        patch.object(webui_task.tm, "start", side_effect=execute),
    ):
        webui_task.submit_generation(
            "jalapeno-queued",
            VideoParams(video_subject="river", video_source="jalapeno"),
            capture_logs=False,
        )
        assert manager.queue_size() == 1
        config.app.update(
            jalapeno_video_api_key="later-key",
            jalapeno_video_model="later-model",
            jalapeno_video_resolution="1080p",
        )
        queued = manager.dequeue()
        queued["func"](**queued["kwargs"])
    assert observed == [expected]


@pytest.mark.parametrize("confirmed_before_queue", [False, True])
def test_pipeline_uses_one_endpoint_after_configuration_changes(
    tmp_path, confirmed_before_queue
):
    """覆盖预检、配音、素材下载到实际 HTTP 参数，防止中途重新读取全局配置。"""
    config.app.update(jalapeno_video_api_key="confirmed-key")
    confirmed = provider.endpoint() if confirmed_before_queue else None
    params = VideoParams(
        video_subject="river",
        video_script="A peaceful river.",
        video_terms=["river"],
        video_source="jalapeno",
        subtitle_enabled=False,
        bgm_type="",
    )

    def change_configuration(*_args, **_kwargs):
        config.app.update(
            jalapeno_video_api_key="later-key",
            jalapeno_video_model="later-model",
            jalapeno_video_base_url="https://later.example/api/v3",
            jalapeno_video_resolution="1080p",
        )
        return str(tmp_path / "audio.mp3"), 4, None

    if confirmed_before_queue:
        change_configuration()
    with (
        patch.object(task, "generate_audio", side_effect=change_configuration),
        patch.object(task.utils, "check_ffmpeg_ready", return_value=True),
        patch.object(
            seedance.requests, "post", return_value=response({"id": "paid-confirmed"})
        ) as submit,
        patch.object(
            seedance.requests,
            "get",
            return_value=response(
                {
                    "status": "succeeded",
                    "content": {"video_url": "https://cdn.example/clip.mp4"},
                }
            ),
        ),
        patch.object(
            material,
            "_save_generated_video_with_retry",
            return_value=str(tmp_path / "clip.mp4"),
        ),
        patch.object(material, "VideoFileClip") as media,
    ):
        media.return_value.__enter__.return_value = SimpleNamespace(
            duration=5.04, size=(854, 480)
        )
        result = task.start(
            "jalapeno-frozen-pipeline",
            params,
            stop_at="materials",
            jalapeno_video_endpoint=confirmed,
        )
    assert result == {"materials": [str(tmp_path / "clip.mp4")]}
    assert submit.call_count == 1
    assert submit.call_args.args[0] == provider.DEFAULT_TASKS_URL
    assert submit.call_args.kwargs["headers"]["Authorization"] == "Bearer confirmed-key"
    assert submit.call_args.kwargs["json"]["model"] == provider.DEFAULT_MODEL
    assert submit.call_args.kwargs["json"]["resolution"] == "480p"
    assert config.app["jalapeno_video_api_key"] == "later-key"
    assert "confirmed-key" not in json.dumps(
        state.state.get_task("jalapeno-frozen-pipeline")
    )
