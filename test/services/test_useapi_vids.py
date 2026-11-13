from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect
from app.services import material, useapi


TOKEN = "user:1234-useapi-test-token"
JOB_ID = "j1007154417508260291v-u12345-email:user@example.com-bot:google-vids"
MEDIA_ID = "user:12345-user@example.com-video:eyJ1IjoiaHR0"
MEDIA_URL = (
    "https://api.useapi.net/v1/google-vids/media/"
    "user%3A12345-user%40example.com-video%3AeyJ1IjoiaHR0"
)


def _response(payload, status_code=200, headers=None):
    return SimpleNamespace(
        status_code=status_code,
        headers=headers or {},
        json=lambda: payload,
    )


def _completed(width=720, height=1280):
    return {
        "jobid": JOB_ID,
        "type": "video",
        "status": "completed",
        "result": {
            "mediaId": MEDIA_ID,
            "width": width,
            "height": height,
            "duration": 6,
            "resolution": "720p",
        },
    }


@pytest.fixture(autouse=True)
def restore_config():
    original_app = dict(config.app)
    original_proxy = dict(config.proxy)
    config.app.update(
        {
            "useapi_api_token": TOKEN,
            "useapi_video_model": "vids-omni-flash-1.2",
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


def test_vids_submit_poll_and_media_link():
    submit = _response({"jobid": JOB_ID, "status": "processing"}, status_code=202)
    polls = [
        _response({"jobid": JOB_ID, "status": "processing"}),
        _response(_completed()),
    ]
    with (
        patch.object(useapi.requests, "post", return_value=submit) as post,
        patch.object(useapi.requests, "get", side_effect=polls) as get,
        patch.object(useapi.time, "sleep") as sleep,
    ):
        result = useapi.generate_videos("  harbor at dawn ", 6, VideoAspect.portrait)

    assert post.call_args.args[0] == "https://api.useapi.net/v1/google-vids/videos"
    assert post.call_args.kwargs["json"] == {
        "prompt": "harbor at dawn",
        "aspectRatio": "portrait",
        "duration": 6,
        "async": True,
        "resolution": "1080p",
    }
    assert post.call_args.kwargs["headers"]["User-Agent"] == "MoneyPrinterTurbo-useapi/1.0"
    assert post.call_args.kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert all(
        call.args[0] == f"https://api.useapi.net/v1/google-vids/jobs/{JOB_ID}"
        and call.kwargs["headers"]["User-Agent"] == "MoneyPrinterTurbo-useapi/1.0"
        for call in get.call_args_list
    )
    sleep.assert_called_once_with(10.0)
    item = result[0]
    assert item.url == MEDIA_URL
    assert item.duration == 6
    assert item.source_info["asset_id"] == useapi.safe_job_id(JOB_ID)
    assert "user@example.com" not in str(item.source_info)
    assert item.source_info["rendition"]["width"] == 720
    assert item.source_info["rendition"]["height"] == 1280


@pytest.mark.parametrize("requested, expected", [(1, 3), (7, 7), (15, 15), (20, 15)])
def test_vids_durations_round_up_within_3_to_15(requested, expected):
    with (
        patch.object(useapi.requests, "post", return_value=_response({"jobid": JOB_ID}, 202)) as post,
        patch.object(useapi.requests, "get", return_value=_response(_completed())),
    ):
        result = useapi.generate_videos("harbor", requested, VideoAspect.landscape)
    assert post.call_args.kwargs["json"]["duration"] == expected
    assert post.call_args.kwargs["json"]["aspectRatio"] == "landscape"
    assert result[0].duration == expected


def test_vids_sends_configured_resolution():
    config.app["useapi_resolution"] = "1080p"
    with (
        patch.object(useapi.requests, "post", return_value=_response({"jobid": JOB_ID}, 202)) as post,
        patch.object(useapi.requests, "get", return_value=_response(_completed())),
    ):
        useapi.generate_videos("harbor", 5, VideoAspect.landscape)
    assert post.call_args.kwargs["json"]["resolution"] == "1080p"


def test_vids_has_no_square_and_fails_before_submission():
    with patch.object(useapi.requests, "post") as post:
        with pytest.raises(useapi.UseAPIError, match="9:16, 16:9"):
            useapi.generate_videos("harbor", 5, VideoAspect.square)
    post.assert_not_called()


def test_failed_vids_job_skips_the_segment():
    failed = {
        "jobid": JOB_ID,
        "status": "failed",
        "error": {"code": 422, "message": "Google refused this request"},
    }
    with (
        patch.object(useapi.requests, "post", return_value=_response({"jobid": JOB_ID}, 202)) as post,
        patch.object(useapi.requests, "get", return_value=_response(failed)),
    ):
        assert useapi.generate_videos("harbor", 5, VideoAspect.portrait) == []
    assert post.call_count == 1


def test_busy_vids_account_waits_and_submits_again():
    busy = _response(
        {"error": "Account user@example.com is running 3 of 3 jobs (maxJobs)", "code": 429},
        status_code=429,
        headers={"Retry-After": "15"},
    )
    with (
        patch.object(
            useapi.requests,
            "post",
            side_effect=[busy, _response({"jobid": JOB_ID}, 202)],
        ) as post,
        patch.object(useapi.requests, "get", return_value=_response(_completed())),
        patch.object(useapi.time, "sleep") as sleep,
    ):
        result = useapi.generate_videos("harbor", 5, VideoAspect.portrait)
    assert result[0].url == MEDIA_URL
    assert post.call_count == 2
    sleep.assert_called_once_with(15.0)


def test_used_up_monthly_allowance_is_reported_without_waiting():
    reset = (datetime.now(timezone.utc) + timedelta(days=12)).isoformat()
    used_up = _response(
        {
            "error": "All 3 healthy Google Vids accounts have used up this month's video allowance",
            "code": 429,
            "retryAt": reset,
        },
        status_code=429,
    )
    with (
        patch.object(useapi.requests, "post", return_value=used_up) as post,
        patch.object(useapi.time, "sleep") as sleep,
    ):
        with pytest.raises(useapi.UseAPIError, match="busy") as raised:
            useapi.generate_videos("harbor", 5, VideoAspect.portrait)
    assert not isinstance(raised.value, useapi.UseAPIUnconfirmedTaskError)
    assert post.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize(
    "side_effect, response",
    [
        (requests.exceptions.ReadTimeout("slow"), None),
        (None, _response({"error": "bad gateway"}, status_code=502)),
        (None, _response({"status": "processing"}, status_code=202)),
    ],
)
def test_ambiguous_vids_submission_is_unconfirmed_and_never_retried(side_effect, response):
    with (
        patch.object(
            useapi.requests, "post", side_effect=side_effect, return_value=response
        ) as post,
        patch.object(useapi.requests, "get") as get,
        patch.object(useapi.time, "sleep") as sleep,
    ):
        with pytest.raises(useapi.UseAPIUnconfirmedTaskError):
            useapi.generate_videos("harbor", 5, VideoAspect.portrait)
    assert post.call_count == 1
    get.assert_not_called()
    sleep.assert_not_called()


def test_refused_vids_prompt_is_a_plain_rejection():
    refused = _response(
        {"jobid": JOB_ID, "status": "failed", "error": {"code": 422, "message": "refused"}},
        status_code=422,
    )
    with patch.object(useapi.requests, "post", return_value=refused) as post:
        with pytest.raises(useapi.UseAPIError) as raised:
            useapi.generate_videos("harbor", 5, VideoAspect.portrait)
    assert not isinstance(raised.value, useapi.UseAPIUnconfirmedTaskError)
    assert post.call_count == 1


def test_completed_vids_job_without_media_keeps_job_id():
    with (
        patch.object(useapi.requests, "post", return_value=_response({"jobid": JOB_ID}, 202)),
        patch.object(
            useapi.requests,
            "get",
            return_value=_response({"jobid": JOB_ID, "status": "completed", "result": {}}),
        ),
    ):
        with pytest.raises(useapi.UseAPIError) as raised:
            useapi.generate_videos("harbor", 5, VideoAspect.portrait)
    assert raised.value.task_id == useapi.safe_job_id(JOB_ID)


def test_download_headers_only_for_useapi_media_links():
    assert useapi.download_headers(MEDIA_URL) == {
        "Authorization": f"Bearer {TOKEN}",
        "User-Agent": "MoneyPrinterTurbo-useapi/1.0",
    }
    for public in (
        "https://flow-content.google/video/1",
        "https://s21-kling.klingai.com/video/clip.mp4",
        "https://api.useapi.net.attacker.example/v1/x",
    ):
        assert useapi.download_headers(public) is None


def test_vids_clip_is_downloaded_with_the_token_and_others_without():
    items = [
        MaterialInfo(provider="useapi", url=MEDIA_URL, duration=5,
                     source_info={"asset_id": JOB_ID}),
        MaterialInfo(provider="useapi", url="https://flow-content.google/v.mp4", duration=5,
                     source_info={"asset_id": "j-flow"}),
    ]
    with (
        patch.object(useapi, "generate_videos", side_effect=[[items[0]], [items[1]]]),
        patch.object(
            material, "_save_generated_video_with_retry", side_effect=["/tmp/a.mp4", "/tmp/b.mp4"]
        ) as save,
        patch.object(material, "_get_downloaded_video_duration", return_value=5.0),
        patch.object(material, "_persist_material_sources"),
    ):
        paths = material._download_videos_useapi_on_demand(
            task_id="local-task",
            search_terms=["one", "two"],
            video_aspect=VideoAspect.portrait,
            audio_duration=10,
            max_clip_duration=5,
            material_directory="/tmp",
        )
    assert paths == ["/tmp/a.mp4", "/tmp/b.mp4"]
    first, second = save.call_args_list
    assert first.args == (MEDIA_URL, "/tmp", "useapi")
    assert first.kwargs["request_headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert second.args == ("https://flow-content.google/v.mp4", "/tmp", "useapi")
    assert "request_headers" not in second.kwargs


def test_save_video_sends_request_headers(tmp_path):
    class _Stream:
        status_code = 200
        headers = {"Content-Length": "4"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            return iter((b"mp4!",))

    with (
        patch.object(material.requests, "get", return_value=_Stream()) as get,
        patch.object(material, "_is_valid_video_file", return_value=True),
    ):
        path = material.save_video(
            MEDIA_URL, str(tmp_path), request_headers={"Authorization": "Bearer x"}
        )
    assert path.endswith(".mp4")
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer x"
    assert "Mozilla" in get.call_args.kwargs["headers"]["User-Agent"]
