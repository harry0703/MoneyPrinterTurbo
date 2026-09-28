import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoParams
from app.services import material, muapi, state as sm
from app.services import task as task_service


def _response(payload, status_code=200, headers=None):
    return SimpleNamespace(
        status_code=status_code,
        headers=headers or {},
        json=lambda: payload,
    )


@pytest.fixture(autouse=True)
def restore_config():
    original_app = dict(config.app)
    original_proxy = dict(config.proxy)
    config.app.update(
        {
            "muapi_api_key": "muapi-test-key",
            "muapi_base_url": muapi.DEFAULT_BASE_URL,
            "muapi_video_endpoint": muapi.DEFAULT_ENDPOINT,
            "muapi_resolution": muapi.DEFAULT_RESOLUTION,
            "muapi_poll_interval": 5,
            "muapi_run_timeout": 1800,
        }
    )
    config.proxy.clear()
    yield
    config.app.clear()
    config.app.update(original_app)
    config.proxy.clear()
    config.proxy.update(original_proxy)


def test_api_key_prefers_config_then_muapi_environment():
    with patch.dict(os.environ, {"MUAPI_API_KEY": "environment-key"}, clear=False):
        assert muapi.get_api_key() == "muapi-test-key"
        config.app["muapi_api_key"] = ""
        assert muapi.get_api_key() == "environment-key"
        os.environ["MUAPI_API_KEY"] = ""
        assert muapi.get_api_key() == ""


@pytest.mark.parametrize("term", ["", "   ", None])
def test_invalid_input_fails_before_paid_submission(term):
    with patch.object(muapi.requests, "post") as post:
        with pytest.raises(muapi.MuAPIError):
            muapi.generate_videos(term, 5)
    post.assert_not_called()


def test_submit_poll_and_parse_successful_video():
    submit = _response({"request_id": "muapi-task-1", "status": "queued"}, 202)
    polls = [
        _response({"request_id": "muapi-task-1", "status": "processing"}),
        _response(
            {
                "request_id": "muapi-task-1",
                "status": "completed",
                "outputs": ["https://cdn.example.com/video.mp4"],
            }
        ),
    ]
    with (
        patch.object(muapi.requests, "post", return_value=submit) as post,
        patch.object(muapi.requests, "get", side_effect=polls) as get,
        patch.object(muapi.time, "sleep") as sleep,
    ):
        result = muapi.generate_videos(
            "  sunrise over mountains  ",
            minimum_duration=5,
            video_aspect=VideoAspect.portrait,
        )

    assert len(result) == 1
    item = result[0]
    assert item.provider == "muapi"
    assert item.url == "https://cdn.example.com/video.mp4"
    assert item.duration == 5
    assert item.source_info == {
        "provider": "muapi",
        "search_term": "sunrise over mountains",
        "asset_id": "muapi-task-1",
        "rendition": {
            "id": "muapi-task-1",
            "width": 1080,
            "height": 1920,
        },
    }
    assert post.call_args.args[0] == (
        f"{muapi.DEFAULT_BASE_URL}/{muapi.DEFAULT_ENDPOINT}"
    )
    assert post.call_args.kwargs["headers"] == {
        "x-api-key": "muapi-test-key",
        "Content-Type": "application/json",
    }
    assert post.call_args.kwargs["allow_redirects"] is False
    assert post.call_args.kwargs["json"] == {
        "prompt": "sunrise over mountains",
        "aspect_ratio": "9:16",
        "resolution": "480p",
        "duration": 5,
    }
    assert get.call_count == 2
    assert all(
        call.args[0].endswith("/predictions/muapi-task-1/result")
        for call in get.call_args_list
    )
    assert all(call.kwargs["allow_redirects"] is False for call in get.call_args_list)
    sleep.assert_called_once_with(muapi.DEFAULT_POLL_INTERVAL_SECONDS)


def test_configured_endpoint_resolution_and_duration_bounds_are_applied():
    config.app.update(
        {
            "muapi_base_url": "https://muapi.example.test/api/v1/",
            "muapi_video_endpoint": "seedance-2-text-to-video",
            "muapi_resolution": "1080p",
            "muapi_min_duration": 4,
            "muapi_max_duration": 8,
        }
    )
    submit = _response({"id": "muapi-bounds"}, 202)
    completed = _response(
        {
            "id": "muapi-bounds",
            "status": "completed",
            "outputs": ["https://cdn.example.com/bounds.mp4"],
        }
    )
    with (
        patch.object(muapi.requests, "post", return_value=submit) as post,
        patch.object(muapi.requests, "get", return_value=completed),
    ):
        result = muapi.generate_videos("city", 99, VideoAspect.landscape)

    assert result[0].duration == 8
    assert post.call_args.args[0] == (
        "https://muapi.example.test/api/v1/seedance-2-text-to-video"
    )
    assert post.call_args.kwargs["json"] == {
        "prompt": "city",
        "aspect_ratio": "16:9",
        "resolution": "1080p",
        "duration": 8,
    }


def test_submission_errors_are_not_retried_and_secret_is_redacted():
    rejected = _response({"detail": "rejected muapi-test-key"}, status_code=400)
    with patch.object(muapi.requests, "post", return_value=rejected) as post:
        with pytest.raises(muapi.MuAPIError) as raised:
            muapi.generate_videos("unsafe", 5)
    assert "muapi-test-key" not in str(raised.value)
    assert post.call_count == 1

    for side_effect, response in (
        (requests.exceptions.ConnectionError("offline"), None),
        (None, _response({"message": "bad gateway"}, status_code=502)),
    ):
        with patch.object(
            muapi.requests,
            "post",
            side_effect=side_effect,
            return_value=response,
        ) as post:
            with pytest.raises(muapi.MuAPIUnconfirmedTaskError):
                muapi.generate_videos("sunrise", 5)
        assert post.call_count == 1


def test_submission_redirect_is_unconfirmed_and_never_followed():
    redirect = _response(
        {},
        status_code=307,
        headers={"Location": "https://attacker.example/submit?key=muapi-test-key"},
    )
    with (
        patch.object(muapi.requests, "post", return_value=redirect) as post,
        patch.object(muapi.requests, "get") as get,
    ):
        with pytest.raises(muapi.MuAPIUnconfirmedTaskError) as raised:
            muapi.generate_videos("sunrise", 5)

    assert "muapi-test-key" not in str(raised.value)
    assert post.call_count == 1
    assert post.call_args.kwargs["allow_redirects"] is False
    get.assert_not_called()


def test_poll_redirect_is_unconfirmed_and_never_retried():
    submit = _response({"request_id": "muapi-redirect"}, 202)
    redirect = _response(
        {},
        status_code=307,
        headers={"Location": "https://attacker.example/result"},
    )
    with (
        patch.object(muapi.requests, "post", return_value=submit) as post,
        patch.object(muapi.requests, "get", return_value=redirect) as get,
    ):
        with pytest.raises(muapi.MuAPIUnconfirmedTaskError) as raised:
            muapi.generate_videos("sunrise", 5)

    assert raised.value.task_id == "muapi-redirect"
    assert post.call_count == 1
    assert get.call_count == 1
    assert get.call_args.kwargs["allow_redirects"] is False


def test_poll_retries_transient_errors_on_same_task():
    submit = _response({"request_id": "muapi-retry"}, 202)
    completed = _response(
        {
            "request_id": "muapi-retry",
            "status": "completed",
            "outputs": ["https://cdn.example.com/retry.mp4"],
        }
    )
    with (
        patch.object(muapi.requests, "post", return_value=submit) as post,
        patch.object(
            muapi.requests,
            "get",
            side_effect=[
                _response({}, status_code=429),
                requests.exceptions.ConnectionError("offline"),
                completed,
            ],
        ) as get,
        patch.object(muapi.time, "sleep") as sleep,
    ):
        result = muapi.generate_videos("sunrise", 5)

    assert len(result) == 1
    assert post.call_count == 1
    assert get.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [1.0, 2.0]


@pytest.mark.parametrize("payload", [{}, {"request_id": "   "}, [], None])
def test_missing_task_id_is_unconfirmed_and_never_polled(payload):
    with (
        patch.object(muapi.requests, "post", return_value=_response(payload, 202)),
        patch.object(muapi.requests, "get") as get,
    ):
        with pytest.raises(muapi.MuAPIUnconfirmedTaskError):
            muapi.generate_videos("sunrise", 5)
    get.assert_not_called()


def test_completed_task_without_video_url_preserves_task_id():
    with (
        patch.object(
            muapi.requests,
            "post",
            return_value=_response({"request_id": "muapi-no-url"}, 202),
        ),
        patch.object(
            muapi.requests,
            "get",
            return_value=_response(
                {
                    "request_id": "muapi-no-url",
                    "status": "completed",
                    "outputs": [],
                }
            ),
        ),
    ):
        with pytest.raises(muapi.MuAPIError) as raised:
            muapi.generate_videos("sunrise", 5)
    assert raised.value.task_id == "muapi-no-url"


@pytest.mark.parametrize("status", sorted(muapi.TERMINAL_FAILURE_STATUSES))
def test_terminal_failure_returns_empty_result(status):
    with patch.object(
        muapi.requests,
        "get",
        return_value=_response(
            {
                "request_id": "muapi-failed",
                "status": status,
                "error": {"message": "generation failed"},
            }
        ),
    ):
        result = muapi._wait_for_task(
            task_id="muapi-failed",
            base_url=muapi.DEFAULT_BASE_URL,
            headers={},
            api_key="muapi-test-key",
        )
    assert result is None


def test_on_demand_generation_stops_after_required_duration():
    generated_item = MaterialInfo(
        provider="muapi",
        url="https://cdn.example.com/video.mp4",
        duration=5,
        source_info={"asset_id": "muapi-paid-1"},
    )
    with (
        patch.object(muapi, "generate_videos", return_value=[generated_item]) as generate,
        patch.object(material, "_save_generated_video_with_retry", return_value="/tmp/video.mp4"),
        patch.object(material, "_get_downloaded_video_duration", return_value=5.0),
        patch.object(material, "_persist_material_sources"),
    ):
        paths = material._download_videos_muapi_on_demand(
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


def test_on_demand_counts_actual_downloaded_duration_before_next_paid_submission():
    generated_items = [
        MaterialInfo(
            provider="muapi",
            url="https://cdn.example.com/short.mp4",
            duration=5,
            source_info={"asset_id": "muapi-paid-short"},
        ),
        MaterialInfo(
            provider="muapi",
            url="https://cdn.example.com/full.mp4",
            duration=5,
            source_info={"asset_id": "muapi-paid-full"},
        ),
    ]
    with (
        patch.object(
            muapi,
            "generate_videos",
            side_effect=[[generated_items[0]], [generated_items[1]]],
        ) as generate,
        patch.object(
            material,
            "_save_generated_video_with_retry",
            side_effect=["/tmp/short.mp4", "/tmp/full.mp4"],
        ),
        patch.object(
            material,
            "_get_downloaded_video_duration",
            side_effect=[2.0, 5.0],
        ),
        patch.object(material, "_persist_material_sources"),
    ):
        paths = material._download_videos_muapi_on_demand(
            task_id="local-task",
            search_terms=["short scene", "full scene"],
            video_aspect=VideoAspect.landscape,
            audio_duration=5,
            max_clip_duration=5,
            material_directory="/tmp",
        )

    assert paths == ["/tmp/short.mp4", "/tmp/full.mp4"]
    assert generate.call_count == 2
    assert [call.kwargs["search_term"] for call in generate.call_args_list] == [
        "short scene",
        "full scene",
    ]


@pytest.mark.parametrize("audio_duration", [float("nan"), float("inf"), None, "bad"])
def test_on_demand_rejects_invalid_audio_duration_before_submission(audio_duration):
    with patch.object(muapi, "generate_videos") as generate:
        with pytest.raises(muapi.MuAPIError, match="audio duration"):
            material.download_videos(
                task_id="muapi-invalid-audio",
                search_terms=["one", "two"],
                source="muapi",
                audio_duration=audio_duration,
                max_clip_duration=5,
            )
    generate.assert_not_called()


def test_download_failure_stops_later_paid_submissions_and_keeps_task_id():
    generated_item = MaterialInfo(
        provider="muapi",
        url="https://cdn.example.com/video.mp4",
        duration=5,
        source_info={"asset_id": "muapi-paid-download"},
    )
    with (
        patch.object(muapi, "generate_videos", return_value=[generated_item]) as generate,
        patch.object(material, "_save_generated_video_with_retry", return_value=""),
    ):
        with pytest.raises(muapi.MuAPIDownloadError) as raised:
            material.download_videos(
                task_id="muapi-download-failed",
                search_terms=["one", "two"],
                source="muapi",
                audio_duration=10,
                max_clip_duration=5,
            )
    assert raised.value.task_id == "muapi-paid-download"
    assert generate.call_count == 1


def test_task_preflight_rejects_missing_key_before_script_generation():
    params = VideoParams(video_subject="MuAPI preflight", video_source="muapi")
    memory_state = sm.MemoryState()
    with (
        patch.object(muapi, "is_enabled", return_value=False),
        patch.object(task_service.sm, "state", memory_state),
        patch.object(task_service, "generate_script") as generate_script,
    ):
        result = task_service.start("muapi-preflight", params, stop_at="materials")

    assert result["failed_stage"] == "preflight"
    assert "MuAPI video generation requires a MuAPI API key" in result["error"]
    generate_script.assert_not_called()


def test_material_failure_keeps_muapi_remote_task_id():
    params = VideoParams(video_subject="space fleet", video_source="muapi")
    failure = muapi.MuAPIUnconfirmedTaskError(
        "remote state unknown", task_id="muapi-recover-1"
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
    assert failed_update["muapi_task_id"] == "muapi-recover-1"
