import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoParams
from app.services import material, useapi, state as sm
from app.services import task as task_service


TOKEN = "user:1234-useapi-test-token"


def _response(payload, status_code=200, headers=None):
    return SimpleNamespace(
        status_code=status_code,
        headers=headers or {},
        json=lambda: payload,
    )


def _flow_job(job_id, status, media=None):
    body = {"jobid": job_id, "type": "video", "status": status}
    if media is not None:
        body["response"] = {"media": media}
    return body


def _flow_media(url, status="MEDIA_GENERATION_STATUS_SUCCESSFUL"):
    item = {"mediaMetadata": {"mediaStatus": {"mediaGenerationStatus": status}}}
    if url:
        item["videoUrl"] = url
    return item


@pytest.fixture(autouse=True)
def restore_config():
    original_app = dict(config.app)
    original_proxy = dict(config.proxy)
    config.app.update(
        {
            "useapi_api_token": TOKEN,
            "useapi_video_model": useapi.DEFAULT_MODEL,
            "useapi_resolution": "",
            "useapi_poll_interval": 10,
            "useapi_run_timeout": 1800,
        }
    )
    config.proxy.clear()
    yield
    config.app.clear()
    config.app.update(original_app)
    config.proxy.clear()
    config.proxy.update(original_proxy)


def test_token_prefers_config_then_useapi_environment():
    with patch.dict(os.environ, {"USEAPI_TOKEN": "environment-token"}, clear=False):
        assert useapi.get_api_key() == TOKEN
        config.app["useapi_api_token"] = "   "
        assert useapi.get_api_key() == "environment-token"
        os.environ["USEAPI_TOKEN"] = ""
        assert useapi.get_api_key() == ""
        assert useapi.is_enabled() is False


def test_unknown_model_is_rejected_before_submission():
    config.app["useapi_video_model"] = "veo-3.0-fast"
    with patch.object(useapi.requests, "post") as post:
        with pytest.raises(useapi.UseAPIError, match="Unsupported useapi.net video model"):
            useapi.generate_videos("sunrise", 5)
    post.assert_not_called()


def test_every_documented_video_model_is_offered_with_veo_lite_default():
    assert useapi.DEFAULT_MODEL == "veo-3.1-lite"
    assert list(useapi.MODELS) == [
        "veo-3.1-lite",
        "veo-3.1-lite-low-priority",
        "veo-3.1-fast",
        "veo-3.1-quality",
        "omni-flash",
        "omni-flash-1.2",
        "vids-omni-flash-1.2",
        "kling-v4-0",
        "kling-v4-0-flash",
        "kling-v3-0",
        "kling-v3-0-turbo",
        "kling-v2-6",
        "kling-v2-5",
        "kling-v2-1-master",
        "kling-v1-6",
        "kling-v1-5",
        "seedance-2.5",
        "seedance-2.0",
        "seedance-2.0-fast",
        "seedance-2.0-mini",
        "seedance-1.5-pro",
        "seedance-1.0-pro",
        "seedance-1.0-mini",
        "seedance-1.0-fast",
    ]


@pytest.mark.parametrize("term", ["", "   ", None])
def test_invalid_input_fails_before_submission(term):
    with patch.object(useapi.requests, "post") as post:
        with pytest.raises(useapi.UseAPIError):
            useapi.generate_videos(term, 5)
    post.assert_not_called()


def test_google_flow_submit_poll_and_parse_successful_video():
    submit = _response({"jobid": "j1-flow", "status": "created"}, 201)
    polls = [
        _response(_flow_job("j1-flow", "created")),
        _response(_flow_job("j1-flow", "started")),
        _response(
            _flow_job(
                "j1-flow",
                "completed",
                [_flow_media("https://flow-content.google/video/1?Expires=1")],
            )
        ),
    ]
    with (
        patch.object(useapi.requests, "post", return_value=submit) as post,
        patch.object(useapi.requests, "get", side_effect=polls) as get,
        patch.object(useapi.time, "sleep") as sleep,
    ):
        result = useapi.generate_videos(
            "  sunrise over mountains  ",
            minimum_duration=5,
            video_aspect=VideoAspect.portrait,
        )

    assert len(result) == 1
    item = result[0]
    assert item.provider == "useapi"
    assert item.url == "https://flow-content.google/video/1?Expires=1"
    # Veo is always requested at 8 s, the length every Google AI plan accepts.
    assert item.duration == 8
    assert item.source_info["asset_id"] == "j1-flow"
    assert item.source_info["search_term"] == "sunrise over mountains"
    assert item.source_info["rendition"] == {
        "id": "j1-flow",
        "width": 1080,
        "height": 1920,
    }
    assert post.call_args.args[0] == "https://api.useapi.net/v1/google-flow/videos"
    assert post.call_args.kwargs["headers"] == {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "MoneyPrinterTurbo-useapi/1.0",
    }
    assert post.call_args.kwargs["allow_redirects"] is False
    assert post.call_args.kwargs["json"] == {
        "prompt": "sunrise over mountains",
        "model": "veo-3.1-lite",
        "aspectRatio": "portrait",
        "duration": 8,
        "async": True,
    }
    assert get.call_count == 3
    assert all(
        call.args[0] == "https://api.useapi.net/v1/google-flow/jobs/j1-flow"
        for call in get.call_args_list
    )
    assert all(
        call.kwargs["headers"]["User-Agent"] == "MoneyPrinterTurbo-useapi/1.0"
        for call in get.call_args_list
    )
    assert all(call.kwargs["allow_redirects"] is False for call in get.call_args_list)
    assert [call.args[0] for call in sleep.call_args_list] == [10.0, 10.0]


def test_omni_duration_and_aspect_mapping():
    config.app["useapi_video_model"] = "omni-flash-1.2"
    config.app["useapi_resolution"] = "360p"
    submit = _response({"jobid": "j-omni"}, 201)
    completed = _response(
        _flow_job("j-omni", "completed", [_flow_media("https://flow-content.google/v")])
    )
    for requested, expected in ((1, 3), (5, 5), (10, 10), (99, 10)):
        with (
            patch.object(useapi.requests, "post", return_value=submit) as post,
            patch.object(useapi.requests, "get", return_value=completed),
        ):
            result = useapi.generate_videos("city", requested, VideoAspect.landscape)
        assert result[0].duration == expected
        assert post.call_args.kwargs["json"] == {
            "prompt": "city",
            "model": "omni-flash-1.2",
            "aspectRatio": "landscape",
            "duration": expected,
            "async": True,
            "resolution": "360p",
        }


def test_square_is_rejected_for_omni_but_sent_to_veo():
    config.app["useapi_video_model"] = "omni-flash-1.2"
    with patch.object(useapi.requests, "post") as post:
        with pytest.raises(useapi.UseAPIError, match="9:16, 16:9"):
            useapi.generate_videos("city", 5, VideoAspect.square)
    post.assert_not_called()

    config.app["useapi_video_model"] = "veo-3.1-lite"
    completed = _response(
        _flow_job("j-square", "completed", [_flow_media("https://flow-content.google/s")])
    )
    with (
        patch.object(useapi.requests, "post", return_value=_response({"jobid": "j-square"}, 201)) as post,
        patch.object(useapi.requests, "get", return_value=completed),
    ):
        useapi.generate_videos("city", 5, VideoAspect.square)
    assert post.call_args.kwargs["json"]["aspectRatio"] == "1:1"


@pytest.mark.parametrize(
    "model, requested, expected",
    [
        ("veo-3.1-lite", 2, 8),
        ("veo-3.1-lite", 12, 8),
        ("seedance-2.0", 2, 4),
        ("seedance-2.0", 7, 7),
        ("seedance-2.5", 40, 30),
        ("omni-flash-1.2", 11, 10),
    ],
)
def test_requested_durations_are_clamped_to_each_model(model, requested, expected):
    assert useapi.request_duration(model, requested) == expected
    minimum, maximum = useapi._duration_bounds(model)
    assert minimum <= expected <= maximum


def test_clip_duration_options_follow_the_model():
    assert useapi.clip_duration_options("veo-3.1-lite") == list(range(2, 9))
    assert useapi.clip_duration_options("omni-flash-1.2") == list(range(3, 11))
    assert useapi.clip_duration_options("seedance-2.0-fast") == list(range(4, 16))


def test_dreamina_submit_poll_and_parse_successful_video():
    config.app["useapi_video_model"] = "seedance-2.0-fast"
    submit = _response(
        {"jobid": "j-dreamina", "type": "video", "status": "created", "code": 200}
    )
    polls = [
        _response({"jobid": "j-dreamina", "status": "created"}),
        _response(
            {
                "jobid": "j-dreamina",
                "status": "completed",
                "response": {
                    "videoUrl": "https://v16m-default.tiktokcdn.com/clean.mp4",
                    "videoUrlBackup": "https://v16m.byteicdn.com/clean.mp4",
                    "width": 720,
                    "height": 1280,
                },
            }
        ),
    ]
    with (
        patch.object(useapi.requests, "post", return_value=submit) as post,
        patch.object(useapi.requests, "get", side_effect=polls) as get,
        patch.object(useapi.time, "sleep"),
    ):
        result = useapi.generate_videos("forest", 6, VideoAspect.portrait)

    assert post.call_args.args[0] == "https://api.useapi.net/v1/dreamina/videos"
    assert post.call_args.kwargs["json"] == {
        "prompt": "forest",
        "model": "seedance-2.0-fast",
        "ratio": "9:16",
        "duration": 6,
        "resolution": "720p",
    }
    assert post.call_args.kwargs["headers"]["User-Agent"] == useapi.USER_AGENT
    assert all(
        call.args[0] == "https://api.useapi.net/v1/dreamina/videos/j-dreamina"
        for call in get.call_args_list
    )
    item = result[0]
    assert item.url == "https://v16m-default.tiktokcdn.com/clean.mp4"
    assert item.duration == 6
    assert item.source_info["fallback_urls"] == ["https://v16m.byteicdn.com/clean.mp4"]
    assert item.source_info["rendition"]["width"] == 720
    assert item.source_info["rendition"]["height"] == 1280


def test_submission_rejections_are_not_retried_and_token_is_redacted():
    rejected = _response({"error": f"bad request {TOKEN}"}, status_code=400)
    with patch.object(useapi.requests, "post", return_value=rejected) as post:
        with pytest.raises(useapi.UseAPIError) as raised:
            useapi.generate_videos("unsafe", 5)
    assert not isinstance(raised.value, useapi.UseAPIUnconfirmedTaskError)
    assert TOKEN not in str(raised.value)
    assert post.call_count == 1

    session = _response({"error": "session expired"}, status_code=596)
    with patch.object(useapi.requests, "post", return_value=session) as post:
        with pytest.raises(useapi.UseAPIError) as raised:
            useapi.generate_videos("sunrise", 5)
    assert not isinstance(raised.value, useapi.UseAPIUnconfirmedTaskError)
    assert post.call_count == 1


@pytest.mark.parametrize(
    "side_effect, response",
    [
        (requests.exceptions.ConnectionError("offline"), None),
        (requests.exceptions.ReadTimeout("slow captcha"), None),
        (None, _response({"error": "bad gateway"}, status_code=502)),
        (None, _response({"error": "unavailable"}, status_code=503)),
        (None, _response({"jobid": ""}, status_code=201)),
    ],
)
def test_ambiguous_submission_is_unconfirmed_and_never_retried(side_effect, response):
    with (
        patch.object(
            useapi.requests, "post", side_effect=side_effect, return_value=response
        ) as post,
        patch.object(useapi.requests, "get") as get,
        patch.object(useapi.time, "sleep") as sleep,
    ):
        with pytest.raises(useapi.UseAPIUnconfirmedTaskError):
            useapi.generate_videos("sunrise", 5)
    assert post.call_count == 1
    get.assert_not_called()
    sleep.assert_not_called()


def test_busy_submission_waits_and_submits_again():
    busy = _response(
        {"error": "All accounts at capacity"},
        status_code=429,
        headers={"Retry-After": "12"},
    )
    accepted = _response({"jobid": "j-after-busy"}, 201)
    completed = _response(
        _flow_job("j-after-busy", "completed", [_flow_media("https://flow-content.google/b")])
    )
    with (
        patch.object(useapi.requests, "post", side_effect=[busy, busy, accepted]) as post,
        patch.object(useapi.requests, "get", return_value=completed),
        patch.object(useapi.time, "sleep") as sleep,
    ):
        result = useapi.generate_videos("sunrise", 5)

    assert result[0].source_info["asset_id"] == "j-after-busy"
    assert post.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [12.0, 12.0]


def test_busy_submission_reads_retry_after_from_body_and_gives_up():
    busy = _response(
        {"error": "All accounts at capacity", "retryAfterSec": 45}, status_code=429
    )
    with (
        patch.object(useapi.requests, "post", return_value=busy) as post,
        patch.object(useapi.time, "sleep") as sleep,
    ):
        with pytest.raises(useapi.UseAPIError, match="busy") as raised:
            useapi.generate_videos("sunrise", 5)
    assert not isinstance(raised.value, useapi.UseAPIUnconfirmedTaskError)
    assert post.call_count == useapi.MAX_SUBMIT_BUSY_RETRIES + 1
    assert {call.args[0] for call in sleep.call_args_list} == {45.0}


def test_submission_redirect_is_unconfirmed_and_never_followed():
    redirect = _response(
        {},
        status_code=307,
        headers={"Location": f"https://attacker.example/submit?token={TOKEN}"},
    )
    with (
        patch.object(useapi.requests, "post", return_value=redirect) as post,
        patch.object(useapi.requests, "get") as get,
    ):
        with pytest.raises(useapi.UseAPIUnconfirmedTaskError) as raised:
            useapi.generate_videos("sunrise", 5)
    assert TOKEN not in str(raised.value)
    assert post.call_count == 1
    get.assert_not_called()


def test_poll_retries_busy_and_transient_errors_on_same_job():
    submit = _response({"jobid": "j-retry"}, 201)
    completed = _response(
        _flow_job("j-retry", "completed", [_flow_media("https://flow-content.google/r")])
    )
    with (
        patch.object(useapi.requests, "post", return_value=submit) as post,
        patch.object(
            useapi.requests,
            "get",
            side_effect=[
                _response({}, status_code=429, headers={"Retry-After": "7"}),
                requests.exceptions.ConnectionError("offline"),
                _response({}, status_code=503),
                completed,
            ],
        ) as get,
        patch.object(useapi.time, "sleep") as sleep,
    ):
        result = useapi.generate_videos("sunrise", 5)

    assert len(result) == 1
    assert post.call_count == 1
    assert get.call_count == 4
    assert [call.args[0] for call in sleep.call_args_list] == [7.0, 2.0, 3.0]


def test_poll_gives_up_after_repeated_failures_with_job_id():
    with (
        patch.object(
            useapi.requests, "get", return_value=_response({}, status_code=502)
        ) as get,
        patch.object(useapi.time, "sleep"),
    ):
        with pytest.raises(useapi.UseAPIUnconfirmedTaskError) as raised:
            useapi._wait_for_task(
                task_id="j-down",
                jobs_url="https://api.useapi.net/v1/google-flow/jobs",
                headers={},
                api_key=TOKEN,
            )
    assert raised.value.task_id == "j-down"
    assert get.call_count == useapi.MAX_POLL_RETRIES + 1


def test_poll_redirect_and_not_found_are_unconfirmed():
    for response in (
        _response({}, status_code=307, headers={"Location": "https://attacker.example"}),
        _response({"error": "Job not found"}, status_code=404),
    ):
        with (
            patch.object(useapi.requests, "post", return_value=_response({"jobid": "j-x"}, 201)),
            patch.object(useapi.requests, "get", return_value=response) as get,
        ):
            with pytest.raises(useapi.UseAPIUnconfirmedTaskError) as raised:
                useapi.generate_videos("sunrise", 5)
        assert raised.value.task_id == "j-x"
        assert get.call_count == 1


@pytest.mark.parametrize("service", [useapi.GOOGLE_FLOW, useapi.DREAMINA])
def test_failed_job_returns_empty_result(service):
    failed = {
        "jobid": "j-failed",
        "status": "failed",
        "error": "All operations failed",
        "response": {"failureReasons": ["PUBLIC_ERROR_MINOR"]},
    }
    with patch.object(useapi.requests, "get", return_value=_response(failed)):
        result = useapi._wait_for_task(
            task_id="j-failed",
            jobs_url="https://api.useapi.net/v1/jobs",
            headers={},
            api_key=TOKEN,
            service=service,
        )
    assert result is None


def test_unknown_status_is_unconfirmed():
    with patch.object(
        useapi.requests, "get", return_value=_response({"status": "mystery"})
    ):
        with pytest.raises(useapi.UseAPIUnconfirmedTaskError):
            useapi._wait_for_task(
                task_id="j-odd",
                jobs_url="https://api.useapi.net/v1/google-flow/jobs",
                headers={},
                api_key=TOKEN,
            )


def test_completed_flow_job_waits_for_a_missing_video_url():
    submit = _response({"jobid": "j-late-url"}, 201)
    polls = [
        _response(_flow_job("j-late-url", "completed", [_flow_media("")])),
        _response(
            _flow_job("j-late-url", "completed", [_flow_media("https://flow-content.google/late")])
        ),
    ]
    with (
        patch.object(useapi.requests, "post", return_value=submit),
        patch.object(useapi.requests, "get", side_effect=polls),
        patch.object(useapi.time, "sleep") as sleep,
    ):
        result = useapi.generate_videos("sunrise", 5)
    assert result[0].url == "https://flow-content.google/late"
    assert sleep.call_args_list[0].args[0] == useapi.MISSING_URL_POLL_SECONDS


def test_completed_job_without_any_video_url_keeps_job_id():
    config.app["useapi_video_model"] = "seedance-2.0"
    with (
        patch.object(useapi.requests, "post", return_value=_response({"jobid": "j-no-url"})),
        patch.object(
            useapi.requests,
            "get",
            return_value=_response({"jobid": "j-no-url", "status": "completed", "response": {}}),
        ),
    ):
        with pytest.raises(useapi.UseAPIError) as raised:
            useapi.generate_videos("sunrise", 5)
    assert raised.value.task_id == "j-no-url"


def test_on_demand_generation_stops_after_required_duration():
    generated_item = MaterialInfo(
        provider="useapi",
        url="https://flow-content.google/video.mp4",
        duration=8,
        source_info={"asset_id": "j-paid-1"},
    )
    with (
        patch.object(useapi, "generate_videos", return_value=[generated_item]) as generate,
        patch.object(material, "_save_generated_video_with_retry", return_value="/tmp/video.mp4") as save,
        patch.object(material, "_get_downloaded_video_duration", return_value=8.0),
        patch.object(material, "_persist_material_sources"),
    ):
        paths = material._download_videos_useapi_on_demand(
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
    assert save.call_args.args == ("https://flow-content.google/video.mp4", "/tmp", "useapi")


def test_on_demand_download_tries_alternate_host_before_failing():
    generated_item = MaterialInfo(
        provider="useapi",
        url="https://v16m-default.tiktokcdn.com/a.mp4",
        duration=5,
        source_info={
            "asset_id": "j-backup",
            "fallback_urls": ["https://v16m.byteicdn.com/a.mp4"],
        },
    )
    with (
        patch.object(useapi, "generate_videos", return_value=[generated_item]),
        patch.object(
            material,
            "_save_generated_video_with_retry",
            side_effect=["", "/tmp/backup.mp4"],
        ) as save,
        patch.object(material, "_get_downloaded_video_duration", return_value=5.0),
        patch.object(material, "_persist_material_sources"),
    ):
        paths = material._download_videos_useapi_on_demand(
            task_id="local-task",
            search_terms=["one"],
            video_aspect=VideoAspect.portrait,
            audio_duration=5,
            max_clip_duration=5,
            material_directory="/tmp",
        )
    assert paths == ["/tmp/backup.mp4"]
    assert [call.args[0] for call in save.call_args_list] == [
        "https://v16m-default.tiktokcdn.com/a.mp4",
        "https://v16m.byteicdn.com/a.mp4",
    ]


def test_on_demand_failed_job_moves_to_next_term():
    generated_item = MaterialInfo(
        provider="useapi",
        url="https://flow-content.google/second.mp4",
        duration=5,
        source_info={"asset_id": "j-second"},
    )
    with (
        patch.object(useapi, "generate_videos", side_effect=[[], [generated_item]]) as generate,
        patch.object(material, "_save_generated_video_with_retry", return_value="/tmp/second.mp4"),
        patch.object(material, "_get_downloaded_video_duration", return_value=5.0),
        patch.object(material, "_persist_material_sources"),
    ):
        paths = material._download_videos_useapi_on_demand(
            task_id="local-task",
            search_terms=["moderated", "second"],
            video_aspect=VideoAspect.portrait,
            audio_duration=5,
            max_clip_duration=5,
            material_directory="/tmp",
        )
    assert paths == ["/tmp/second.mp4"]
    assert generate.call_count == 2


def test_unconfirmed_submission_stops_later_submissions():
    failure = useapi.UseAPIUnconfirmedTaskError("unknown", task_id="")
    with (
        patch.object(useapi, "generate_videos", side_effect=failure) as generate,
        patch.object(material, "_persist_material_sources"),
    ):
        with pytest.raises(useapi.UseAPIUnconfirmedTaskError):
            material.download_videos(
                task_id="useapi-unconfirmed",
                search_terms=["one", "two", "three"],
                source="useapi",
                audio_duration=20,
                max_clip_duration=5,
            )
    assert generate.call_count == 1


@pytest.mark.parametrize("audio_duration", [float("nan"), float("inf"), None, "bad"])
def test_on_demand_rejects_invalid_audio_duration_before_submission(audio_duration):
    with patch.object(useapi, "generate_videos") as generate:
        with pytest.raises(useapi.UseAPIError, match="audio duration"):
            material.download_videos(
                task_id="useapi-invalid-audio",
                search_terms=["one", "two"],
                source="useapi",
                audio_duration=audio_duration,
                max_clip_duration=5,
            )
    generate.assert_not_called()


def test_download_failure_stops_later_submissions_and_keeps_job_id():
    generated_item = MaterialInfo(
        provider="useapi",
        url="https://flow-content.google/video.mp4",
        duration=8,
        source_info={"asset_id": "j-paid-download"},
    )
    with (
        patch.object(useapi, "generate_videos", return_value=[generated_item]) as generate,
        patch.object(material, "_save_generated_video_with_retry", return_value=""),
        patch.object(material, "_persist_material_sources"),
    ):
        with pytest.raises(useapi.UseAPIDownloadError) as raised:
            material.download_videos(
                task_id="useapi-download-failed",
                search_terms=["one", "two"],
                source="useapi",
                audio_duration=10,
                max_clip_duration=5,
            )
    assert raised.value.task_id == "j-paid-download"
    assert generate.call_count == 1


def test_task_preflight_rejects_missing_token_before_script_generation():
    params = VideoParams(video_subject="useapi preflight", video_source="useapi")
    memory_state = sm.MemoryState()
    with (
        patch.object(useapi, "is_enabled", return_value=False),
        patch.object(task_service.sm, "state", memory_state),
        patch.object(task_service, "generate_script") as generate_script,
    ):
        result = task_service.start("useapi-preflight", params, stop_at="materials")

    assert result["failed_stage"] == "preflight"
    assert "useapi.net API token" in result["error"]
    generate_script.assert_not_called()


def test_task_preflight_rejects_unsupported_ratio_before_script_generation():
    config.app["useapi_video_model"] = "omni-flash-1.2"
    params = VideoParams(
        video_subject="useapi square",
        video_source="useapi",
        video_aspect=VideoAspect.square,
    )
    memory_state = sm.MemoryState()
    with (
        patch.object(task_service.sm, "state", memory_state),
        patch.object(task_service, "generate_script") as generate_script,
    ):
        result = task_service.start("useapi-square", params, stop_at="materials")

    assert result["failed_stage"] == "preflight"
    assert "omni-flash-1.2" in result["error"]
    generate_script.assert_not_called()


def test_material_failure_keeps_useapi_job_id():
    params = VideoParams(video_subject="space fleet", video_source="useapi")
    failure = useapi.UseAPIUnconfirmedTaskError(
        "remote state unknown", task_id="j-recover-1"
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
    assert failed_update["useapi_job_id"] == "j-recover-1"
