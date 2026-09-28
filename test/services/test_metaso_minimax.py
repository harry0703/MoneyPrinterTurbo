import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoParams
from app.services import material, metaso_minimax, state as sm
from app.services import task as task_service


def _response(payload, status_code=200):
    """构造只暴露服务层实际使用字段的轻量 HTTP 响应。"""
    return SimpleNamespace(status_code=status_code, json=lambda: payload)


@pytest.fixture(autouse=True)
def restore_config():
    """隔离全局配置，避免供应商测试影响其它 Provider 用例。"""
    original_app = dict(config.app)
    original_proxy = dict(config.proxy)
    config.app.update(
        {
            "metaso_minimax_api_key": "metaso-test-key",
            "metaso_minimax_base_url": metaso_minimax.DEFAULT_BASE_URL,
            "metaso_minimax_resolution": metaso_minimax.DEFAULT_RESOLUTION,
        }
    )
    config.proxy.clear()
    yield
    config.app.clear()
    config.app.update(original_app)
    config.proxy.clear()
    config.proxy.update(original_proxy)


def test_api_key_prefers_config_then_provider_environment():
    with patch.dict(
        os.environ,
        {
            "METASO_MINIMAX_API_KEY": "environment-key",
            "MINIMAX_API_KEY": "official-key-must-not-be-used",
        },
        clear=False,
    ):
        assert metaso_minimax.get_api_key() == "metaso-test-key"
        config.app["metaso_minimax_api_key"] = ""
        assert metaso_minimax.get_api_key() == "environment-key"
        os.environ["METASO_MINIMAX_API_KEY"] = ""
        config.app["minimax_api_key"] = "shared-key-must-not-be-used"
        assert metaso_minimax.get_api_key() == ""


def test_invalid_input_fails_before_paid_submission():
    invalid_terms = ("", "   ", None, "a" * (metaso_minimax.MAX_PROMPT_LENGTH + 1))
    for term in invalid_terms:
        with patch.object(metaso_minimax.requests, "post") as post:
            with pytest.raises(metaso_minimax.MetasoMiniMaxError):
                metaso_minimax.generate_videos(term, 5)
        post.assert_not_called()

    config.app["metaso_minimax_api_key"] = ""
    with (
        patch.dict(os.environ, {"METASO_MINIMAX_API_KEY": ""}, clear=False),
        patch.object(metaso_minimax.requests, "post") as post,
    ):
        with pytest.raises(metaso_minimax.MetasoMiniMaxError):
            metaso_minimax.generate_videos("sunrise", 5)
    post.assert_not_called()


def test_submit_poll_and_parse_successful_video():
    submit = _response({"task_id": "metaso-task-1"})
    polls = [
        _response(
            {
                "task": {
                    "id": "metaso-task-1",
                    "status": "running",
                }
            }
        ),
        _response(
            {
                "task": {
                    "id": "metaso-task-1",
                    "status": "succeeded",
                    "content": {
                        "url": "https://cdn.example.com/video.mp4?signature=abc"
                    },
                    "duration": 5,
                    "resolution": "2K",
                    "ratio": "16:9",
                }
            }
        ),
    ]
    with (
        patch.object(metaso_minimax.requests, "post", return_value=submit) as post,
        patch.object(metaso_minimax.requests, "get", side_effect=polls) as get,
        patch.object(metaso_minimax.time, "sleep") as sleep,
    ):
        result = metaso_minimax.generate_videos(
            "  cinematic sunrise  ",
            minimum_duration=5,
            video_aspect=VideoAspect.landscape,
        )

    assert len(result) == 1
    item = result[0]
    assert item.provider == "metaso_minimax"
    assert item.url.endswith("video.mp4?signature=abc")
    assert item.duration == 5
    assert item.source_info == {
        "provider": "metaso_minimax",
        "search_term": "cinematic sunrise",
        "asset_id": "metaso-task-1",
        "rendition": {"id": "metaso-task-1"},
    }
    assert post.call_args.args[0] == (
        f"{metaso_minimax.DEFAULT_BASE_URL}/v2/video_generation"
    )
    assert post.call_args.kwargs["headers"]["Authorization"] == (
        "Bearer metaso-test-key"
    )
    assert post.call_args.kwargs["json"] == {
        "model": "MiniMax-H3",
        "content": [{"type": "text", "text": "cinematic sunrise"}],
        "resolution": "2K",
        "duration": 5,
        "ratio": "16:9",
    }
    assert get.call_count == 2
    assert all(
        call.args[0].endswith("/v2/query/video_generation/metaso-task-1")
        for call in get.call_args_list
    )
    sleep.assert_called_once_with(metaso_minimax.DEFAULT_POLL_INTERVAL_SECONDS)


def test_duration_is_clamped_and_resolution_is_normalized():
    config.app["metaso_minimax_resolution"] = " 768p "
    submit = _response({"task_id": "metaso-task-bounds"})
    completed = _response(
        {
            "task": {
                "id": "metaso-task-bounds",
                "status": "succeeded",
                "content": {"url": "https://cdn.example.com/bounds.mp4"},
                "duration": 4,
            }
        }
    )
    with (
        patch.object(metaso_minimax.requests, "post", return_value=submit) as post,
        patch.object(metaso_minimax.requests, "get", return_value=completed),
    ):
        result = metaso_minimax.generate_videos("city", 2)

    assert post.call_args.kwargs["json"]["duration"] == 4
    assert post.call_args.kwargs["json"]["resolution"] == "768P"
    assert result[0].duration == 4


@pytest.mark.parametrize("invalid", ["1080P", "", None, False, "4K"])
def test_invalid_resolution_fails_before_paid_submission(invalid):
    config.app["metaso_minimax_resolution"] = invalid
    with patch.object(metaso_minimax.requests, "post") as post:
        with pytest.raises(
            metaso_minimax.MetasoMiniMaxError,
            match="Unsupported Metaso MiniMax resolution",
        ):
            metaso_minimax.generate_videos("city", 5)
    post.assert_not_called()


def test_submission_errors_are_not_retried_and_secret_is_redacted():
    rejected = _response(
        {
            "type": "error",
            "error": {
                "type": "bad_request_error",
                "message": "rejected metaso-test-key",
                "http_code": "400",
            },
        },
        status_code=400,
    )
    with patch.object(metaso_minimax.requests, "post", return_value=rejected) as post:
        with pytest.raises(metaso_minimax.MetasoMiniMaxError) as raised:
            metaso_minimax.generate_videos("unsafe", 5)
    assert "metaso-test-key" not in str(raised.value)
    assert post.call_count == 1

    for side_effect, response in (
        (requests.exceptions.ConnectionError("offline"), None),
        (None, _response({"message": "bad gateway"}, status_code=502)),
    ):
        with patch.object(
            metaso_minimax.requests,
            "post",
            side_effect=side_effect,
            return_value=response,
        ) as post:
            with pytest.raises(metaso_minimax.MetasoMiniMaxUnconfirmedTaskError):
                metaso_minimax.generate_videos("sunrise", 5)
        assert post.call_count == 1


def test_poll_retries_transient_errors_on_same_task():
    submit = _response({"task_id": "metaso-retry"})
    rate_limited = _response({}, status_code=429)
    completed = _response(
        {
            "task": {
                "id": "metaso-retry",
                "status": "succeeded",
                "content": {"url": "https://cdn.example.com/retry.mp4"},
            }
        }
    )
    with (
        patch.object(metaso_minimax.requests, "post", return_value=submit) as post,
        patch.object(
            metaso_minimax.requests,
            "get",
            side_effect=[
                rate_limited,
                requests.exceptions.ConnectionError("offline"),
                completed,
            ],
        ) as get,
        patch.object(metaso_minimax.time, "sleep") as sleep,
    ):
        result = metaso_minimax.generate_videos("sunrise", 5)

    assert len(result) == 1
    assert post.call_count == 1
    assert get.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [1.0, 2.0]


@pytest.mark.parametrize("payload", [{}, {"task_id": "   "}, [], None])
def test_missing_task_id_is_unconfirmed_and_never_polled(payload):
    with (
        patch.object(metaso_minimax.requests, "post", return_value=_response(payload)),
        patch.object(metaso_minimax.requests, "get") as get,
    ):
        with pytest.raises(metaso_minimax.MetasoMiniMaxUnconfirmedTaskError):
            metaso_minimax.generate_videos("sunrise", 5)
    get.assert_not_called()


def test_succeeded_task_without_video_url_preserves_task_id():
    with (
        patch.object(
            metaso_minimax.requests,
            "post",
            return_value=_response({"task_id": "metaso-no-url"}),
        ),
        patch.object(
            metaso_minimax.requests,
            "get",
            return_value=_response(
                {
                    "task": {
                        "id": "metaso-no-url",
                        "status": "succeeded",
                        "content": {},
                    }
                }
            ),
        ),
    ):
        with pytest.raises(metaso_minimax.MetasoMiniMaxError) as raised:
            metaso_minimax.generate_videos("sunrise", 5)
    assert raised.value.task_id == "metaso-no-url"


@pytest.mark.parametrize("status", sorted(metaso_minimax.TERMINAL_FAILURE_STATUSES))
def test_terminal_failure_preserves_task_id(status):
    with patch.object(
        metaso_minimax.requests,
        "get",
        return_value=_response(
            {
                "task": {
                    "id": "metaso-failed",
                    "status": status,
                    "error": {"message": "generation failed"},
                }
            }
        ),
    ):
        with pytest.raises(metaso_minimax.MetasoMiniMaxError) as raised:
            metaso_minimax._wait_for_task(
                task_id="metaso-failed",
                base_url=metaso_minimax.DEFAULT_BASE_URL,
                headers={},
                api_key="metaso-test-key",
            )
    assert raised.value.task_id == "metaso-failed"


def test_on_demand_generation_stops_after_required_duration():
    generated_item = MaterialInfo(
        provider="metaso_minimax",
        url="https://cdn.example.com/video.mp4",
        duration=5,
        source_info={
            "provider": "metaso_minimax",
            "asset_id": "metaso-paid-1",
        },
    )
    with (
        patch.object(
            metaso_minimax, "generate_videos", return_value=[generated_item]
        ) as generate,
        patch.object(
            material,
            "_save_generated_video_with_retry",
            return_value="/tmp/video.mp4",
        ),
        patch.object(material, "_persist_material_sources"),
    ):
        paths = material._download_videos_metaso_minimax_on_demand(
            task_id="local-task",
            search_terms=["first", "second"],
            video_aspect=VideoAspect.landscape,
            audio_duration=5,
            max_clip_duration=5,
            material_directory="/tmp",
        )

    assert paths == ["/tmp/video.mp4"]
    assert generate.call_count == 1
    assert generate.call_args.kwargs["search_term"] == "first"


@pytest.mark.parametrize("audio_duration", [float("nan"), float("inf"), None, "bad"])
def test_on_demand_rejects_invalid_audio_duration_before_submission(audio_duration):
    with patch.object(metaso_minimax, "generate_videos") as generate:
        with pytest.raises(metaso_minimax.MetasoMiniMaxError, match="audio duration"):
            material.download_videos(
                task_id="metaso-invalid-audio",
                search_terms=["one", "two"],
                source="metaso_minimax",
                audio_duration=audio_duration,
                max_clip_duration=5,
            )
    generate.assert_not_called()


@pytest.mark.parametrize("clip_duration", [0, -1, None, "bad", float("nan")])
def test_on_demand_rejects_invalid_clip_duration_before_submission(clip_duration):
    with patch.object(metaso_minimax, "generate_videos") as generate:
        with pytest.raises(metaso_minimax.MetasoMiniMaxError, match="clip duration"):
            material.download_videos(
                task_id="metaso-invalid-clip",
                search_terms=["one", "two"],
                source="metaso_minimax",
                audio_duration=5,
                max_clip_duration=clip_duration,
            )
    generate.assert_not_called()


def test_download_failure_stops_later_paid_submissions_and_keeps_task_id():
    generated_item = MaterialInfo(
        provider="metaso_minimax",
        url="https://cdn.example.com/video.mp4",
        duration=5,
        source_info={"asset_id": "metaso-paid-download"},
    )
    with (
        patch.object(
            metaso_minimax, "generate_videos", return_value=[generated_item]
        ) as generate,
        patch.object(material, "_save_generated_video_with_retry", return_value=""),
    ):
        with pytest.raises(metaso_minimax.MetasoMiniMaxDownloadError) as raised:
            material.download_videos(
                task_id="metaso-download-failed",
                search_terms=["one", "two"],
                source="metaso_minimax",
                audio_duration=10,
                max_clip_duration=5,
            )
    assert raised.value.task_id == "metaso-paid-download"
    assert generate.call_count == 1


def test_task_preflight_rejects_missing_key_before_script_generation():
    params = VideoParams(
        video_subject="Metaso preflight",
        video_source="metaso_minimax",
    )
    memory_state = sm.MemoryState()
    with (
        patch.object(metaso_minimax, "is_enabled", return_value=False),
        patch.object(task_service.sm, "state", memory_state),
        patch.object(task_service, "generate_script") as generate_script,
    ):
        result = task_service.start("metaso-preflight", params, stop_at="materials")

    assert result["failed_stage"] == "preflight"
    assert "Metaso MiniMax requires an API key" in result["error"]
    generate_script.assert_not_called()


def test_material_failure_keeps_metaso_remote_task_id():
    params = VideoParams(
        video_subject="space fleet",
        video_source="metaso_minimax",
    )
    failure = metaso_minimax.MetasoMiniMaxUnconfirmedTaskError(
        "remote state unknown",
        task_id="metaso-recover-1",
    )
    with (
        patch.object(task_service.material, "download_videos", side_effect=failure),
        patch.object(sm.state, "update_task") as update_task,
    ):
        result = task_service.get_video_materials(
            "local-task",
            params,
            ["space fleet"],
            audio_duration=5,
        )

    assert result is None
    failed_update = update_task.call_args.kwargs
    assert failed_update["metaso_minimax_task_id"] == "metaso-recover-1"
