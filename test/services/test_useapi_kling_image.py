import io
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from PIL import Image

from app.config import config
from app.models.schema import VideoAspect
from app.services import material, useapi


TOKEN = "user:1234-useapi-test-token"
IMAGE_URL = "https://s21-kling.klingai.com/image/result.png"


def _png_bytes(width=64, height=112):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 80, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def _response(payload, status_code=200, headers=None):
    return SimpleNamespace(
        status_code=status_code,
        headers=headers or {},
        json=lambda: payload,
    )


def _download(content, status_code=200):
    return SimpleNamespace(
        status_code=status_code,
        headers={"Content-Length": str(len(content))},
        iter_content=lambda chunk_size: iter((content,)),
        close=lambda: None,
    )


def _submitted(user_id=None):
    return {"task": {"id": 555, "userId": user_id, "status_name": "submitted"}}


def _task(status_name, works=None):
    return {"status_name": status_name, "task": {"id": 555}, "works": works or []}


def _succeeded(url=IMAGE_URL):
    return _task(
        "succeed",
        [{"contentType": "image", "status_name": "succeed", "resource": {"resource": url}}],
    )


@pytest.fixture(autouse=True)
def restore_config():
    original_app = dict(config.app)
    original_proxy = dict(config.proxy)
    config.app.update(
        {
            "useapi_api_token": TOKEN,
            "useapi_image_model": "kling-kolors-v2-1",
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


def _get_router(polls, download):
    poll_iter = iter(polls)

    def get(url, *args, **kwargs):
        if url == IMAGE_URL:
            return download
        return next(poll_iter)

    return get


@pytest.mark.parametrize(
    "model, path, version",
    [
        ("kling-kolors-v3-0", "kolors", {"version": "kling-v3-0"}),
        ("kling-kolors-v2-1", "kolors", {"version": "kling-v2-1"}),
        ("kling-omni-image-v3", "omni", {"omni_version": "v3"}),
        ("kling-omni-image-o1", "omni", {"omni_version": "o1"}),
    ],
)
def test_kling_image_submit_poll_and_download(model, path, version):
    config.app["useapi_image_model"] = model
    png = _png_bytes()
    polls = [_response(_task("submitted")), _response(_task("processing")), _response(_succeeded())]
    with (
        patch.object(useapi.requests, "post", return_value=_response(_submitted())) as post,
        patch.object(useapi.requests, "get", side_effect=_get_router(polls, _download(png))) as get,
        patch.object(useapi.time, "sleep") as sleep,
    ):
        image_bytes, job_id = useapi.generate_image("  harbor at dawn ", VideoAspect.portrait)

    assert image_bytes == png
    assert job_id == "555"
    assert post.call_args.args[0] == f"https://api.useapi.net/v1/kling/images/{path}"
    assert post.call_args.kwargs["json"] == {
        "prompt": "Create one image depicting: harbor at dawn.",
        **version,
        "aspect_ratio": "9:16",
        "imageCount": 1,
    }
    assert post.call_args.kwargs["headers"]["User-Agent"] == "MoneyPrinterTurbo-useapi/1.0"
    assert post.call_args.kwargs["allow_redirects"] is False
    task_calls = [c for c in get.call_args_list if "/kling/tasks/" in c.args[0]]
    assert [c.args[0] for c in task_calls] == ["https://api.useapi.net/v1/kling/tasks/555"] * 3
    download_call = next(c for c in get.call_args_list if c.args[0] == IMAGE_URL)
    # The token never goes to the image host.
    assert download_call.kwargs["headers"] == {"User-Agent": "MoneyPrinterTurbo-useapi/1.0"}
    assert [c.args[0] for c in sleep.call_args_list] == [10.0, 10.0]


@pytest.mark.parametrize(
    "aspect, ratio",
    [(VideoAspect.portrait, "9:16"), (VideoAspect.landscape, "16:9"), (VideoAspect.square, "1:1")],
)
def test_kling_image_aspect_mapping(aspect, ratio):
    with (
        patch.object(useapi.requests, "post", return_value=_response(_submitted())) as post,
        patch.object(
            useapi.requests,
            "get",
            side_effect=_get_router([_response(_succeeded())], _download(_png_bytes())),
        ),
    ):
        useapi.generate_image("harbor", aspect)
    assert post.call_args.kwargs["json"]["aspect_ratio"] == ratio


def test_failed_kling_image_task_skips_the_segment():
    with (
        patch.object(useapi.requests, "post", return_value=_response(_submitted())) as post,
        patch.object(useapi.requests, "get", return_value=_response(_task("failed"))),
    ):
        image_bytes, job_id = useapi.generate_image("harbor", VideoAspect.portrait)
    assert image_bytes is None
    assert job_id == "555"
    assert post.call_count == 1


def test_busy_kling_image_submission_waits_and_submits_again():
    busy = _response({"error": "All accounts are busy"}, 429, headers={"Retry-After": "6"})
    with (
        patch.object(useapi.requests, "post", side_effect=[busy, _response(_submitted())]) as post,
        patch.object(
            useapi.requests,
            "get",
            side_effect=_get_router([_response(_succeeded())], _download(_png_bytes())),
        ),
        patch.object(useapi.time, "sleep") as sleep,
    ):
        image_bytes, _ = useapi.generate_image("harbor", VideoAspect.portrait)
    assert image_bytes
    assert post.call_count == 2
    sleep.assert_called_once_with(6.0)


@pytest.mark.parametrize(
    "side_effect, response",
    [
        (requests.exceptions.ReadTimeout("slow"), None),
        (None, _response({"error": "Service busy (CM_EXT.POther)"}, status_code=500)),
        (None, _response({"task": {}}, status_code=200)),
    ],
)
def test_ambiguous_kling_image_submission_is_unconfirmed_and_never_retried(side_effect, response):
    with (
        patch.object(
            useapi.requests, "post", side_effect=side_effect, return_value=response
        ) as post,
        patch.object(useapi.requests, "get") as get,
        patch.object(useapi.time, "sleep") as sleep,
    ):
        with pytest.raises(useapi.UseAPIUnconfirmedTaskError):
            useapi.generate_image("harbor", VideoAspect.portrait)
    assert post.call_count == 1
    get.assert_not_called()
    sleep.assert_not_called()


def test_kling_image_without_result_keeps_job_id():
    with (
        patch.object(useapi.requests, "post", return_value=_response(_submitted())),
        patch.object(useapi.requests, "get", return_value=_response(_task("succeed"))),
    ):
        with pytest.raises(useapi.UseAPIError) as raised:
            useapi.generate_image("harbor", VideoAspect.portrait)
    assert raised.value.task_id == "555"


def test_kling_image_download_failure_stops_the_material_loop():
    with (
        patch.object(useapi.requests, "post", return_value=_response(_submitted())) as post,
        patch.object(
            useapi.requests,
            "get",
            side_effect=_get_router([_response(_succeeded())], _download(b"", 503)),
        ),
        patch.object(useapi.time, "sleep"),
        patch.object(material, "_persist_material_sources"),
    ):
        with pytest.raises(material.UseAPIImageMaterialError) as raised:
            material.download_videos(
                "kling-image-task",
                ["harbor", "second"],
                source="useapi_image",
                audio_duration=6,
                max_clip_duration=3,
            )
    assert raised.value.task_id == "555"
    assert post.call_count == 1


@pytest.mark.parametrize(
    "model, needs_confirmation",
    [
        ("nano-banana-2-lite", False),
        ("nano-banana-2", False),
        ("nano-banana-pro", False),
        ("kling-kolors-v3-0", True),
        ("kling-kolors-v2-1", True),
        ("kling-omni-image-v3", True),
        ("kling-omni-image-o1", True),
        ("unknown-model", False),
    ],
)
def test_only_kling_image_models_need_charge_confirmation(model, needs_confirmation):
    assert useapi.image_requires_confirmation({"useapi_image_model": model}) is needs_confirmation
