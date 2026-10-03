import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoParams
from app.services import material, tensorscale
from app.services import state as sm
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
            "tensorscale_api_key": "tensorscale-test-key",
            "tensorscale_base_url": tensorscale.DEFAULT_BASE_URL,
            "tensorscale_resolution": tensorscale.DEFAULT_RESOLUTION,
            "tensorscale_poll_interval": 5,
            "tensorscale_run_timeout": 1800,
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
            "TENSORSCALE_API_KEY": "environment-key",
            "MINIMAX_API_KEY": "unrelated-key",
        },
        clear=False,
    ):
        assert tensorscale.get_api_key() == "tensorscale-test-key"
        config.app["tensorscale_api_key"] = ""
        assert tensorscale.get_api_key() == "environment-key"
        os.environ["TENSORSCALE_API_KEY"] = ""
        assert tensorscale.get_api_key() == ""


def test_invalid_inputs_fail_before_paid_submission():
    config.app["tensorscale_resolution"] = "1080p"
    with (
        patch.object(tensorscale.requests, "post") as post,
        pytest.raises(tensorscale.TensorScaleError, match="resolution"),
    ):
        tensorscale.generate_videos("city", 5)
    post.assert_not_called()

    config.app["tensorscale_resolution"] = "360p"
    with (
        patch.object(tensorscale.requests, "post") as post,
        pytest.raises(tensorscale.TensorScaleError, match="square"),
    ):
        tensorscale.generate_videos("city", 5, VideoAspect.square)
    post.assert_not_called()

    config.app["tensorscale_api_key"] = ""
    with (
        patch.dict(os.environ, {"TENSORSCALE_API_KEY": ""}, clear=False),
        patch.object(tensorscale.requests, "post") as post,
        pytest.raises(tensorscale.TensorScaleError, match="API key"),
    ):
        tensorscale.generate_videos("city", 5)
    post.assert_not_called()


def test_submit_poll_and_parse_successful_video():
    submit = _response({"id": "job-ts-1", "status": "pending"})
    polls = [
        _response({"id": "job-ts-1", "status": "in_progress"}),
        _response(
            {
                "id": "job-ts-1",
                "status": "completed",
                "download_url": "https://storage.example/video.mp4?signature=abc",
            }
        ),
    ]
    with (
        patch.object(tensorscale.requests, "post", return_value=submit) as post,
        patch.object(tensorscale.requests, "get", side_effect=polls) as get,
        patch.object(tensorscale.time, "sleep") as sleep,
    ):
        result = tensorscale.generate_videos(
            "  cinematic sunrise  ", 5, VideoAspect.landscape
        )

    assert len(result) == 1
    item = result[0]
    assert item.provider == "tensorscale"
    assert item.url.endswith("video.mp4?signature=abc")
    assert item.source_info == {
        "provider": "tensorscale",
        "search_term": "cinematic sunrise",
        "asset_id": "job-ts-1",
        "rendition": {
            "id": "job-ts-1",
            "resolution": "768p",
            "aspect_ratio": "16:9",
        },
    }
    assert post.call_args.args[0] == f"{tensorscale.DEFAULT_BASE_URL}/videos"
    assert post.call_args.kwargs["json"] == {
        "model": "MiniMax-H3-Fast",
        "prompt": "cinematic sunrise",
        "duration": 5,
        "resolution": "768p",
        "aspect_ratio": "16:9",
        "generate_audio": True,
    }
    assert post.call_args.kwargs["headers"]["Authorization"] == (
        "Bearer tensorscale-test-key"
    )
    assert post.call_args.kwargs["headers"]["Idempotency-Key"].startswith("mpt-")
    assert get.call_count == 2
    assert all(call.args[0].endswith("/videos/job-ts-1") for call in get.call_args_list)
    sleep.assert_called_once_with(5.0)


@pytest.mark.parametrize(("requested", "expected"), [(2, 4), (99, 15)])
def test_duration_is_clamped_to_h3_limits(requested, expected):
    with (
        patch.object(
            tensorscale.requests,
            "post",
            return_value=_response({"id": "job-bounds"}),
        ) as post,
        patch.object(
            tensorscale.requests,
            "get",
            return_value=_response(
                {
                    "status": "completed",
                    "download_url": "https://storage.example/bounds.mp4",
                }
            ),
        ),
    ):
        result = tensorscale.generate_videos("city", requested)

    assert post.call_args.kwargs["json"]["duration"] == expected
    assert result[0].duration == expected


def test_submission_retries_three_times_with_one_idempotency_key():
    responses = [
        _response({}, 503),
        _response({}, 429, {"Retry-After": "2"}),
        _response({"id": "job-retried"}),
    ]
    with (
        patch.object(tensorscale.requests, "post", side_effect=responses) as post,
        patch.object(
            tensorscale.requests,
            "get",
            return_value=_response(
                {
                    "status": "completed",
                    "download_url": "https://storage.example/retried.mp4",
                }
            ),
        ),
        patch.object(tensorscale.time, "sleep") as sleep,
    ):
        result = tensorscale.generate_videos("sunrise", 5)

    assert len(result) == 1
    keys = [call.kwargs["headers"]["Idempotency-Key"] for call in post.call_args_list]
    assert len(set(keys)) == 1
    assert keys[0].startswith("mpt-")
    assert [call.args[0] for call in sleep.call_args_list] == [1.0, 2.0]


def test_deterministic_4xx_is_not_retried_and_redacts_secret():
    rejected = _response(
        {"error": {"code": "bad_request", "message": "tensorscale-test-key"}},
        400,
    )
    with (
        patch.object(tensorscale.requests, "post", return_value=rejected) as post,
        pytest.raises(tensorscale.TensorScaleError) as raised,
    ):
        tensorscale.generate_videos("sunrise", 5)
    assert post.call_count == 1
    assert "tensorscale-test-key" not in str(raised.value)


def test_poll_retries_transient_errors_on_the_same_job():
    with (
        patch.object(
            tensorscale.requests,
            "get",
            side_effect=[
                requests.exceptions.ConnectionError("offline"),
                _response({}, 502),
                _response(
                    {
                        "status": "completed",
                        "download_url": "https://storage.example/retry.mp4",
                    }
                ),
            ],
        ) as get,
        patch.object(tensorscale.time, "sleep") as sleep,
    ):
        task = tensorscale._wait_for_task(
            task_id="job-retry",
            videos_url=f"{tensorscale.DEFAULT_BASE_URL}/videos",
            headers={},
            api_key="tensorscale-test-key",
        )

    assert task["status"] == "completed"
    assert get.call_count == 3
    assert all(
        call.args[0].endswith("/videos/job-retry") for call in get.call_args_list
    )
    assert [call.args[0] for call in sleep.call_args_list] == [1.0, 2.0]


@pytest.mark.parametrize("status", sorted(tensorscale.TERMINAL_FAILURE_STATUSES))
def test_terminal_failure_stops_polling(status):
    with patch.object(
        tensorscale.requests,
        "get",
        return_value=_response({"id": "job-failed", "status": status}),
    ):
        result = tensorscale._wait_for_task(
            task_id="job-failed",
            videos_url=f"{tensorscale.DEFAULT_BASE_URL}/videos",
            headers={},
            api_key="tensorscale-test-key",
        )
    assert result is None


def test_unknown_status_and_poll_retry_exhaustion_preserve_job_id():
    with (
        patch.object(
            tensorscale.requests,
            "get",
            return_value=_response({"status": "mystery"}),
        ),
        pytest.raises(tensorscale.TensorScaleUnconfirmedTaskError) as unknown,
    ):
        tensorscale._wait_for_task(
            task_id="job-unknown",
            videos_url=f"{tensorscale.DEFAULT_BASE_URL}/videos",
            headers={},
            api_key="key",
        )
    assert unknown.value.task_id == "job-unknown"

    with (
        patch.object(
            tensorscale.requests,
            "get",
            side_effect=requests.exceptions.ConnectionError("offline"),
        ) as get,
        patch.object(tensorscale.time, "sleep"),
        pytest.raises(tensorscale.TensorScaleUnconfirmedTaskError) as exhausted,
    ):
        tensorscale._wait_for_task(
            task_id="job-unconfirmed",
            videos_url=f"{tensorscale.DEFAULT_BASE_URL}/videos",
            headers={},
            api_key="key",
        )
    assert exhausted.value.task_id == "job-unconfirmed"
    assert get.call_count == tensorscale.MAX_POLL_RETRIES + 1


def test_poll_timeout_preserves_job_id_without_submitting_another_job():
    config.app["tensorscale_run_timeout"] = 60
    with (
        patch.object(tensorscale.time, "monotonic", side_effect=[100.0, 161.0]),
        patch.object(tensorscale.requests, "get") as get,
        pytest.raises(tensorscale.TensorScaleUnconfirmedTaskError) as raised,
    ):
        tensorscale._wait_for_task(
            task_id="job-timeout",
            videos_url=f"{tensorscale.DEFAULT_BASE_URL}/videos",
            headers={},
            api_key="key",
        )
    assert raised.value.task_id == "job-timeout"
    get.assert_not_called()


@pytest.mark.parametrize("download_url", [None, "", "file:///tmp/video.mp4"])
def test_completed_without_http_download_url_requires_server_upgrade(download_url):
    with (
        patch.object(
            tensorscale.requests,
            "post",
            return_value=_response({"id": "job-no-url"}),
        ),
        patch.object(
            tensorscale.requests,
            "get",
            return_value=_response(
                {"status": "completed", "download_url": download_url}
            ),
        ),
        pytest.raises(tensorscale.TensorScaleError, match="upgrade") as raised,
    ):
        tensorscale.generate_videos("sunrise", 5)
    assert raised.value.task_id == "job-no-url"


def test_on_demand_stops_after_audio_is_covered_and_persists_safe_metadata():
    item = MaterialInfo(
        provider="tensorscale",
        url="https://storage.example/video.mp4?signature=secret",
        duration=5,
        source_info={
            "provider": "tensorscale",
            "search_term": "first",
            "asset_id": "job-paid-1",
            "rendition": {
                "id": "job-paid-1",
                "resolution": "768p",
                "aspect_ratio": "16:9",
            },
        },
    )
    with (
        patch.object(tensorscale, "generate_videos", return_value=[item]) as generate,
        patch.object(
            material, "_save_generated_video_with_retry", return_value="/tmp/video.mp4"
        ),
        patch.object(material, "_persist_material_sources") as persist,
    ):
        paths = material._download_videos_tensorscale_on_demand(
            task_id="local-task",
            search_terms=["first", "second"],
            video_aspect=VideoAspect.landscape,
            audio_duration=5,
            max_clip_duration=5,
            material_directory="/tmp",
        )

    assert paths == ["/tmp/video.mp4"]
    assert generate.call_count == 1
    saved = persist.call_args.args[1][0]
    assert saved["asset_id"] == "job-paid-1"
    assert saved["rendition"] == {
        "id": "job-paid-1",
        "resolution": "768p",
        "aspect_ratio": "16:9",
    }
    assert "url" not in saved
    assert "signature" not in str(saved)


def test_download_failure_stops_later_submissions_and_preserves_job_id():
    item = MaterialInfo(
        provider="tensorscale",
        url="https://storage.example/video.mp4",
        duration=5,
        source_info={"asset_id": "job-paid-download"},
    )
    with (
        patch.object(tensorscale, "generate_videos", return_value=[item]) as generate,
        patch.object(material, "_save_generated_video_with_retry", return_value=""),
        pytest.raises(tensorscale.TensorScaleDownloadError) as raised,
    ):
        material.download_videos(
            task_id="local-task",
            search_terms=["one", "two"],
            source="tensorscale",
            audio_duration=10,
            max_clip_duration=5,
        )
    assert raised.value.task_id == "job-paid-download"
    assert generate.call_count == 1


def test_task_preflight_and_failure_recovery_keep_tensor_scale_job_id():
    params = VideoParams(video_subject="TensorScale", video_source="tensorscale")
    memory_state = sm.MemoryState()
    with (
        patch.object(tensorscale, "is_enabled", return_value=False),
        patch.object(task_service.sm, "state", memory_state),
        patch.object(task_service, "generate_script") as generate_script,
    ):
        result = task_service.start("ts-preflight", params, stop_at="materials")
    assert result["failed_stage"] == "preflight"
    generate_script.assert_not_called()

    failure = tensorscale.TensorScaleUnconfirmedTaskError(
        "remote state unknown", task_id="job-recover-1"
    )
    with (
        patch.object(task_service.material, "download_videos", side_effect=failure),
        patch.object(sm.state, "update_task") as update_task,
    ):
        result = task_service.get_video_materials(
            "local-task", params, ["space fleet"], audio_duration=5
        )
    assert result is None
    assert update_task.call_args.kwargs["tensorscale_job_id"] == "job-recover-1"
