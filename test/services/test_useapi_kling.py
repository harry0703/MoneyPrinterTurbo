from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoParams
from app.services import material, useapi, state as sm
from app.services import task as task_service


TOKEN = "user:1234-useapi-test-token"
VIDEO_URL = "https://s21-kling.klingai.com/video/clip.mp4"


def _response(payload, status_code=200, headers=None):
    return SimpleNamespace(
        status_code=status_code,
        headers=headers or {},
        json=lambda: payload,
    )


def _submitted(task_id=123456789, user_id=12345):
    return {
        "task": {"id": task_id, "userId": user_id, "status": 5, "status_name": "submitted"},
        "works": [],
        "status": 5,
        "status_name": "submitted",
        "status_final": False,
    }


def _task(status_name, status=10, final=False, works=None):
    return {
        "status": status,
        "status_name": status_name,
        "status_final": final,
        "task": {"id": 123456789, "status": status, "status_name": status_name},
        "works": works or [],
    }


def _succeeded(url=VIDEO_URL, width=720, height=1280):
    return _task(
        "succeed",
        status=99,
        final=True,
        works=[
            {
                "workId": 987,
                "contentType": "video",
                "status_name": "succeed",
                "resource": {
                    "resource": url,
                    "width": width,
                    "height": height,
                    "duration": 5041,
                },
            }
        ],
    )


@pytest.fixture(autouse=True)
def restore_config():
    original_app = dict(config.app)
    original_proxy = dict(config.proxy)
    config.app.update(
        {
            "useapi_api_token": TOKEN,
            "useapi_video_model": "kling-v4-0",
            "useapi_resolution": "720p",
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


def _get_router(accounts, polls):
    """Route GET calls: the accounts list, then the task polls in order."""
    poll_iter = iter(polls)

    def get(url, *args, **kwargs):
        if url.endswith("/kling/accounts"):
            return accounts
        return next(poll_iter)

    return get


def test_kling_submit_poll_and_parse_successful_video_single_account():
    accounts = _response({"a@example.com": {"email": "a@example.com", "session": {"userId": 12345}}})
    polls = [
        _response(_task("submitted", status=5)),
        _response(_task("processing", status=10)),
        _response(_succeeded()),
    ]
    with (
        patch.object(useapi.requests, "post", return_value=_response(_submitted())) as post,
        patch.object(useapi.requests, "get", side_effect=_get_router(accounts, polls)) as get,
        patch.object(useapi.time, "sleep") as sleep,
    ):
        result = useapi.generate_videos("  city at night  ", 5, VideoAspect.portrait)

    assert post.call_args.args[0] == "https://api.useapi.net/v1/kling/videos/text2video"
    # Kling's quality is "mode"; useapi_resolution is not sent to Kling.
    assert post.call_args.kwargs["json"] == {
        "prompt": "city at night",
        "model_name": "kling-v4-0",
        "aspect_ratio": "9:16",
        "duration": "5",
        "mode": "std",
    }
    assert post.call_args.kwargs["headers"]["User-Agent"] == "MoneyPrinterTurbo-useapi/1.0"
    assert post.call_args.kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert post.call_args.kwargs["allow_redirects"] is False
    task_calls = [call for call in get.call_args_list if "/kling/tasks/" in call.args[0]]
    assert len(task_calls) == 3
    assert all(
        call.args[0] == "https://api.useapi.net/v1/kling/tasks/123456789"
        and "params" not in call.kwargs
        and call.kwargs["headers"]["User-Agent"] == "MoneyPrinterTurbo-useapi/1.0"
        for call in task_calls
    )
    assert [call.args[0] for call in sleep.call_args_list] == [10.0, 10.0]

    item = result[0]
    assert isinstance(item, MaterialInfo)
    assert item.provider == "useapi"
    assert item.url == VIDEO_URL
    assert item.duration == 5
    assert item.source_info["asset_id"] == "123456789"
    assert item.source_info["rendition"] == {
        "id": "123456789",
        "width": 720,
        "height": 1280,
    }


def test_kling_task_is_read_from_the_account_that_ran_it():
    accounts = _response(
        {
            "a@example.com": {"email": "a@example.com", "session": {"userId": 111}},
            "b@example.com": {"email": "b@example.com", "session": {"userId": 12345}},
        }
    )
    with (
        patch.object(useapi.requests, "post", return_value=_response(_submitted())),
        patch.object(
            useapi.requests,
            "get",
            side_effect=_get_router(accounts, [_response(_succeeded())]),
        ) as get,
    ):
        useapi.generate_videos("city", 5, VideoAspect.landscape)
    task_call = next(c for c in get.call_args_list if "/kling/tasks/" in c.args[0])
    assert task_call.kwargs["params"] == {"email": "b@example.com"}


def test_kling_account_lookup_failure_still_polls_without_email():
    with (
        patch.object(useapi.requests, "post", return_value=_response(_submitted())) as post,
        patch.object(
            useapi.requests,
            "get",
            side_effect=_get_router(
                _response({"error": "down"}, status_code=503), [_response(_succeeded())]
            ),
        ) as get,
    ):
        result = useapi.generate_videos("city", 5, VideoAspect.landscape)
    assert result[0].url == VIDEO_URL
    assert post.call_count == 1
    task_call = next(c for c in get.call_args_list if "/kling/tasks/" in c.args[0])
    assert "params" not in task_call.kwargs


@pytest.mark.parametrize(
    "model, requested, expected",
    [
        ("kling-v4-0", 1, 3),
        ("kling-v4-0", 7, 7),
        ("kling-v4-0-flash", 40, 20),
        ("kling-v4-0", 40, 30),
        ("kling-v3-0-turbo", 12, 12),
        ("kling-v2-6", 3, 5),
        ("kling-v2-6", 6, 10),
        ("kling-v2-6", 10, 10),
        ("kling-v2-6", 20, 10),
    ],
)
def test_kling_durations_round_up_to_each_model(model, requested, expected):
    assert useapi.request_duration(model, requested) == expected


@pytest.mark.parametrize(
    "aspect, ratio",
    [
        (VideoAspect.portrait, "9:16"),
        (VideoAspect.landscape, "16:9"),
        (VideoAspect.square, "1:1"),
    ],
)
def test_kling_sends_every_mpt_ratio_and_duration_as_string(aspect, ratio):
    config.app["useapi_video_model"] = "kling-v2-6"
    with (
        patch.object(useapi.requests, "post", return_value=_response(_submitted(user_id=None))) as post,
        patch.object(useapi.requests, "get", return_value=_response(_succeeded())),
    ):
        result = useapi.generate_videos("city", 7, aspect)
    assert post.call_args.kwargs["json"]["aspect_ratio"] == ratio
    assert post.call_args.kwargs["json"]["duration"] == "10"
    assert result[0].duration == 10


@pytest.mark.parametrize(
    "polled",
    [
        _response(_task("failed", status=7, final=True)),
        _response({"error": "Sorry, the requested resource was not found"}, status_code=404),
    ],
)
def test_kling_failed_or_missing_task_returns_empty_result(polled):
    with (
        patch.object(useapi.requests, "post", return_value=_response(_submitted(user_id=None))) as post,
        patch.object(useapi.requests, "get", return_value=polled),
    ):
        result = useapi.generate_videos("city", 5, VideoAspect.portrait)
    assert result == []
    assert post.call_count == 1


def test_kling_busy_submission_waits_and_submits_again():
    busy = _response({"error": "All accounts are busy"}, status_code=429)
    with (
        patch.object(
            useapi.requests,
            "post",
            side_effect=[busy, _response(_submitted(user_id=None))],
        ) as post,
        patch.object(useapi.requests, "get", return_value=_response(_succeeded())),
        patch.object(useapi.time, "sleep") as sleep,
    ):
        result = useapi.generate_videos("city", 5, VideoAspect.portrait)
    assert result[0].url == VIDEO_URL
    assert post.call_count == 2
    sleep.assert_called_once_with(useapi.DEFAULT_BUSY_RETRY_SECONDS)


@pytest.mark.parametrize(
    "side_effect, response",
    [
        (requests.exceptions.ConnectionError("offline"), None),
        # Kling answers moderation with 500 too, but its docs say a real
        # server error cannot be told apart, so the submission is unconfirmed.
        (None, _response({"error": "Service busy (CM_EXT.POther)"}, status_code=500)),
        (None, _response({"task": {"userId": 1}}, status_code=200)),
        (None, _response({"task": {"id": "abc"}}, status_code=200)),
    ],
)
def test_kling_ambiguous_submission_is_unconfirmed_and_never_retried(side_effect, response):
    with (
        patch.object(
            useapi.requests, "post", side_effect=side_effect, return_value=response
        ) as post,
        patch.object(useapi.requests, "get") as get,
        patch.object(useapi.time, "sleep") as sleep,
    ):
        with pytest.raises(useapi.UseAPIUnconfirmedTaskError):
            useapi.generate_videos("city", 5, VideoAspect.portrait)
    assert post.call_count == 1
    get.assert_not_called()
    sleep.assert_not_called()


def test_kling_model_access_refusal_is_a_plain_rejection():
    refused = _response(
        {"error": "This Kling account does not have access to the requested model"},
        status_code=403,
    )
    with patch.object(useapi.requests, "post", return_value=refused) as post:
        with pytest.raises(useapi.UseAPIError) as raised:
            useapi.generate_videos("city", 5, VideoAspect.portrait)
    assert not isinstance(raised.value, useapi.UseAPIUnconfirmedTaskError)
    assert post.call_count == 1


# The exact answer useapi.net returned on 2026-11-12 for a Kling 2.6 video on an
# account without credits: HTTP 200, no task, Kling's error.
OUT_OF_CREDITS = {
    "task": None,
    "works": [],
    "status": 52,
    "message": "积分消费失败",
    "limitation": None,
    "userPoints": None,
    "userTickets": None,
    "editProject": None,
    "taskWorks": [],
    "failedCount": 0,
    "error": {
        "type": "TASK.PointNotEnough",
        "detail": "Credit are insufficient, you can upgrade your membership or purchase credit.",
        "subType": "",
        "extra": {"traceId": "trace"},
        "brief": "Credit are insufficient, you can upgrade your membership or purchase credit.",
    },
}


def test_kling_out_of_credits_is_a_plain_rejection_with_kling_reason():
    with (
        patch.object(useapi.requests, "post", return_value=_response(OUT_OF_CREDITS)) as post,
        patch.object(useapi.requests, "get") as get,
        patch.object(useapi.time, "sleep") as sleep,
    ):
        with pytest.raises(useapi.UseAPIError) as raised:
            useapi.generate_videos("city", 5, VideoAspect.portrait)
    assert not isinstance(raised.value, useapi.UseAPIUnconfirmedTaskError)
    assert "nothing was created" in str(raised.value)
    assert "Credit are insufficient" in str(raised.value)
    assert "TASK.PointNotEnough" in str(raised.value)
    assert post.call_count == 1
    get.assert_not_called()
    sleep.assert_not_called()


def test_kling_completed_task_without_video_keeps_job_id():
    with (
        patch.object(useapi.requests, "post", return_value=_response(_submitted(user_id=None))),
        patch.object(
            useapi.requests,
            "get",
            return_value=_response(_task("succeed", status=99, final=True)),
        ),
    ):
        with pytest.raises(useapi.UseAPIError) as raised:
            useapi.generate_videos("city", 5, VideoAspect.portrait)
    assert raised.value.task_id == "123456789"


def test_kling_poll_retries_busy_and_server_errors_on_same_task():
    with (
        patch.object(useapi.requests, "post", return_value=_response(_submitted(user_id=None))) as post,
        patch.object(
            useapi.requests,
            "get",
            side_effect=[
                _response({}, status_code=429, headers={"Retry-After": "4"}),
                _response({}, status_code=502),
                _response(_succeeded()),
            ],
        ) as get,
        patch.object(useapi.time, "sleep") as sleep,
    ):
        result = useapi.generate_videos("city", 5, VideoAspect.portrait)
    assert result[0].url == VIDEO_URL
    assert post.call_count == 1
    assert get.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [4.0, 2.0]


def test_kling_clip_is_downloaded_by_the_material_service():
    item = MaterialInfo(
        provider="useapi",
        url=VIDEO_URL,
        duration=5,
        source_info={"asset_id": "123456789", "fallback_urls": []},
    )
    with (
        patch.object(useapi, "generate_videos", return_value=[item]),
        patch.object(
            material, "_save_generated_video_with_retry", return_value="/tmp/kling.mp4"
        ) as save,
        patch.object(material, "_get_downloaded_video_duration", return_value=5.0),
        patch.object(material, "_persist_material_sources"),
    ):
        paths = material._download_videos_useapi_on_demand(
            task_id="local-task",
            search_terms=["city", "unused"],
            video_aspect=VideoAspect.portrait,
            audio_duration=5,
            max_clip_duration=5,
            material_directory="/tmp",
        )
    assert paths == ["/tmp/kling.mp4"]
    save.assert_called_once_with(VIDEO_URL, "/tmp", "useapi")


@pytest.mark.parametrize(
    "model", [name for name, spec in useapi.MODELS.items() if spec["service"] == useapi.KLING]
)
def test_every_kling_model_takes_all_three_mpt_ratios(model):
    for aspect in VideoAspect:
        assert useapi.check_aspect(model, aspect) == aspect


def test_task_preflight_rejects_missing_token_for_kling():
    params = VideoParams(video_subject="kling", video_source="useapi")
    with (
        patch.object(useapi, "is_enabled", return_value=False),
        patch.object(task_service.sm, "state", sm.MemoryState()),
        patch.object(task_service, "generate_script") as generate_script,
    ):
        result = task_service.start("kling-preflight", params, stop_at="materials")
    assert result["failed_stage"] == "preflight"
    generate_script.assert_not_called()
