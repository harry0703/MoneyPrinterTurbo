"""useapi.net job and media ids carry the account email; it must never leak."""

import re
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from loguru import logger

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoParams
from app.services import material, state as sm, useapi
from app.services import task as task_service
from app.utils import request_logging


TOKEN = "user:1234-useapi-test-token"
EMAIL = "someone.private@gmail.com"
FLOW_JOB = f"j1108123456789v-u700-email:{EMAIL}-bot:google-flow"
DREAMINA_JOB = f"j0223140530123456789v-u700-CA:{EMAIL}-bot:dreamina"
VIDS_MEDIA_URL = (
    "https://api.useapi.net/v1/google-vids/media/"
    "user%3A700-someone.private%40gmail.com-video%3AeyJ1IjoiaHR0"
)
EMAIL_PATTERN = re.compile(r"[\w.+-]+(?:@|%40)[\w-]+\.[\w.-]+", re.IGNORECASE)


def _response(payload, status_code=200, headers=None):
    return SimpleNamespace(status_code=status_code, headers=headers or {}, json=lambda: payload)


@pytest.fixture(autouse=True)
def restore_config():
    original_app = dict(config.app)
    original_proxy = dict(config.proxy)
    config.app.update(
        {
            "useapi_api_token": TOKEN,
            "useapi_video_model": "veo-3.1-lite",
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


@contextmanager
def captured_logs():
    lines = []
    sink = logger.add(lambda message: lines.append(str(message)), level="DEBUG")
    try:
        yield lines
    finally:
        logger.remove(sink)


def _assert_no_email(*texts):
    for text in texts:
        assert EMAIL not in str(text)
        assert "someone.private%40gmail.com" not in str(text)


@pytest.mark.parametrize(
    "job_id, expected",
    [
        (FLOW_JOB, "j1108123456789v-u700-email:***-bot:google-flow"),
        (DREAMINA_JOB, "j0223140530123456789v-u700-CA:***-bot:dreamina"),
        ("j1-flow", "j1-flow"),
        ("123456789", "123456789"),
        ("", ""),
        (None, ""),
    ],
)
def test_safe_job_id_masks_only_the_email(job_id, expected):
    assert useapi.safe_job_id(job_id) == expected


def test_url_encoded_email_is_masked():
    masked = useapi.safe_job_id(VIDS_MEDIA_URL)
    _assert_no_email(masked)
    assert masked.startswith("https://api.useapi.net/v1/google-vids/media/")


def test_successful_flow_run_logs_and_returns_no_email():
    completed = {
        "jobid": FLOW_JOB,
        "status": "completed",
        "response": {"media": [{"videoUrl": "https://flow-content.google/v.mp4"}]},
    }
    with (
        captured_logs() as lines,
        patch.object(useapi.requests, "post", return_value=_response({"jobid": FLOW_JOB}, 201)),
        patch.object(
            useapi.requests,
            "get",
            side_effect=[_response({"jobid": FLOW_JOB, "status": "started"}), _response(completed)],
        ) as get,
        patch.object(useapi.time, "sleep"),
    ):
        result = useapi.generate_videos("lake", 5, VideoAspect.portrait)
    # The raw id is still what the API is asked about.
    assert get.call_args.args[0].endswith(FLOW_JOB)
    _assert_no_email(*lines, result[0].source_info)
    assert any("email:***" in line for line in lines)


def test_poll_errors_and_task_state_carry_no_email():
    with (
        captured_logs() as lines,
        patch.object(useapi.requests, "post", return_value=_response({"jobid": DREAMINA_JOB})),
        patch.object(
            useapi.requests,
            "get",
            return_value=_response(
                {"error": f"Account CA:{EMAIL} session expired"}, status_code=404
            ),
        ),
    ):
        config.app["useapi_video_model"] = "seedance-2.0"
        with pytest.raises(useapi.UseAPIUnconfirmedTaskError) as raised:
            useapi.generate_videos("lake", 5, VideoAspect.portrait)
    _assert_no_email(raised.value, raised.value.task_id, *lines)
    assert raised.value.task_id == useapi.safe_job_id(DREAMINA_JOB)

    params = VideoParams(video_subject="lake", video_source="useapi")
    with (
        patch.object(task_service.material, "download_videos", side_effect=raised.value),
        patch.object(sm.state, "update_task") as update_task,
    ):
        task_service.get_video_materials("local-task", params, ["lake"], audio_duration=5)
    _assert_no_email(update_task.call_args.kwargs)
    assert update_task.call_args.kwargs["useapi_job_id"] == useapi.safe_job_id(DREAMINA_JOB)


def test_api_error_text_naming_the_account_is_masked():
    rejected = _response(
        {"error": f"Account {EMAIL} is running 3 of 3 jobs (maxJobs)", "code": 400},
        status_code=400,
    )
    with captured_logs() as lines, patch.object(useapi.requests, "post", return_value=rejected):
        with pytest.raises(useapi.UseAPIError) as raised:
            useapi.generate_videos("lake", 5, VideoAspect.portrait)
    _assert_no_email(raised.value, *lines)


def test_every_error_built_with_an_email_is_masked():
    error = useapi.UseAPIError(f"failed for {EMAIL}", task_id=FLOW_JOB)
    _assert_no_email(error, error.task_id)


def test_material_download_failure_messages_carry_no_email():
    item = MaterialInfo(
        provider="useapi",
        url=VIDS_MEDIA_URL,
        duration=5,
        source_info={"asset_id": useapi.safe_job_id(FLOW_JOB)},
    )
    with (
        captured_logs() as lines,
        patch.object(useapi, "generate_videos", return_value=[item]),
        patch.object(material, "_save_generated_video_with_retry", return_value=""),
        patch.object(material, "_persist_material_sources"),
    ):
        with pytest.raises(useapi.UseAPIDownloadError) as raised:
            material._download_videos_useapi_on_demand(
                task_id="local-task",
                search_terms=["lake"],
                video_aspect=VideoAspect.portrait,
                audio_duration=5,
                max_clip_duration=5,
                material_directory="/tmp",
            )
    _assert_no_email(raised.value, raised.value.task_id, *lines)


def test_kling_image_and_flow_image_ids_returned_masked():
    body = {
        "jobId": FLOW_JOB,
        "media": [{"image": {"generatedImage": {"encodedImage": "aGVsbG8="}}}],
    }
    config.app["useapi_image_model"] = "nano-banana-2-lite"
    with captured_logs() as lines, patch.object(useapi.requests, "post", return_value=_response(body)):
        _, job_id = useapi.generate_image("lake", VideoAspect.portrait)
    _assert_no_email(job_id, *lines)


def test_logged_request_urls_mask_emails_in_the_path():
    for url in (
        f"https://api.useapi.net/v1/google-flow/jobs/{FLOW_JOB}",
        VIDS_MEDIA_URL,
        f"https://api.useapi.net/v1/kling/tasks/1?email={EMAIL}",
    ):
        safe = request_logging._safe_url(url)
        _assert_no_email(safe)
        assert not EMAIL_PATTERN.search(safe)
    # Ordinary URLs are untouched apart from the existing query masking.
    assert (
        request_logging._safe_url("https://api.useapi.net/v1/google-flow/jobs/j1-flow")
        == "https://api.useapi.net/v1/google-flow/jobs/j1-flow"
    )


def test_traced_poll_request_logs_no_email():
    completed = {
        "jobid": FLOW_JOB,
        "status": "completed",
        "response": {"media": [{"videoUrl": "https://flow-content.google/v.mp4"}]},
    }
    with (
        patch.object(request_logging, "get_logging_options", return_value=("DEBUG", True)),
        captured_logs() as lines,
        patch.object(useapi.requests, "post", return_value=_response({"jobid": FLOW_JOB}, 201)),
        patch.object(useapi.requests, "get", return_value=_response(completed)),
    ):
        useapi.generate_videos("lake", 5, VideoAspect.portrait)
    assert any("request_trace" in line for line in lines)
    _assert_no_email(*lines)


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.ConnectionError(
            "HTTPSConnectionPool(host='api.useapi.net', port=443): Max retries "
            "exceeded with url: /v1/google-vids/media/"
            "user%3A700-someone.private%40gmail.com-video%3AeyJ1 (Caused by timeout)"
        ),
        requests.exceptions.HTTPError(
            f"404 Client Error: Not Found for url: /v1/google-vids/media/user:700-{EMAIL}-video:x"
        ),
    ],
)
def test_failed_useapi_media_download_never_logs_an_email(tmp_path, error):
    with (
        captured_logs() as lines,
        patch.object(material, "save_video", side_effect=error) as save,
        patch.object(material.time, "sleep"),
    ):
        path = material._save_generated_video_with_retry(
            VIDS_MEDIA_URL,
            str(tmp_path),
            "useapi",
            request_headers=useapi.download_headers(VIDS_MEDIA_URL),
        )
    assert path == ""
    assert save.call_count == material.WAVESPEED_MAX_DOWNLOAD_RETRIES + 1
    assert any("failed to download generated video" in line for line in lines)
    _assert_no_email(*lines)
    assert not any(EMAIL_PATTERN.search(line) for line in lines)


def test_failed_public_download_masks_an_email_in_the_error_text(tmp_path):
    error = requests.exceptions.ConnectionError(f"proxy rejected {EMAIL}")
    with (
        captured_logs() as lines,
        patch.object(material, "save_video", side_effect=error),
        patch.object(material.time, "sleep"),
    ):
        material._save_generated_video_with_retry(
            "https://flow-content.google/video/1", str(tmp_path), "useapi"
        )
    _assert_no_email(*lines)
    assert any("ConnectionError" in line for line in lines)


def test_traced_upscale_request_logs_no_email():
    media_id = f"user:700-email:{EMAIL}-video:CAMaJDMx"
    upscale_job = f"j1109v-u700-email:{EMAIL}-bot:google-flow"

    def completed(job_id, url, media=media_id):
        return {
            "jobid": job_id,
            "status": "completed",
            "response": {"media": [{"mediaGenerationId": media, "videoUrl": url}]},
        }

    config.app.update({"useapi_video_model": "veo-3.1-lite", "useapi_upscale": "1080p"})
    with (
        patch.object(request_logging, "get_logging_options", return_value=("DEBUG", True)),
        captured_logs() as lines,
        patch.object(
            useapi.requests,
            "post",
            side_effect=[
                _response({"jobid": FLOW_JOB}, 201),
                _response({"jobid": upscale_job}, 201),
            ],
        ) as post,
        patch.object(
            useapi.requests,
            "get",
            side_effect=[
                _response(completed(FLOW_JOB, "https://flow-content.google/v.mp4")),
                _response(completed(upscale_job, "https://flow-content.google/v_up.mp4")),
            ],
        ),
    ):
        result = useapi.generate_videos("lake", 5, VideoAspect.portrait)
    # The upscale request still carries the raw media id to the API.
    assert post.call_args_list[1].kwargs["json"]["mediaGenerationId"] == media_id
    assert result[0].url == "https://flow-content.google/v_up.mp4"
    traces = [line for line in lines if "request_trace" in line]
    assert any("videos/upscale" in line for line in traces)
    assert any("mediaGenerationId" in line for line in traces)
    _assert_no_email(*lines)
    assert not any(EMAIL_PATTERN.search(line) for line in lines)


def test_traced_strings_mask_emails_anywhere():
    sanitized = request_logging.sanitize_payload(
        {"mediaGenerationId": f"user:1-email:{EMAIL}-video:x", "note": f"for {EMAIL}"}
    )
    _assert_no_email(sanitized)
