import base64
import io
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from PIL import Image

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoParams
from app.services import material, useapi, state as sm, video
from app.services import task as task_service


TOKEN = "user:1234-useapi-test-token"
IMAGE_URL = "https://flow-content.google/image/abc?Expires=1&Signature=s"


def _png_bytes(width=72, height=128):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (40, 120, 200)).save(buffer, format="PNG")
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


def _image_body(**generated):
    return {
        "jobId": "j-image-1",
        "media": [{"image": {"generatedImage": {"seed": 1, **generated}}}],
    }


@pytest.fixture(autouse=True)
def restore_config():
    original_app = dict(config.app)
    original_proxy = dict(config.proxy)
    config.app.update(
        {
            "useapi_api_token": TOKEN,
            "useapi_image_model": useapi.DEFAULT_IMAGE_MODEL,
            "useapi_run_timeout": 1800,
        }
    )
    config.proxy.clear()
    yield
    config.app.clear()
    config.app.update(original_app)
    config.proxy.clear()
    config.proxy.update(original_proxy)


def test_all_documented_nano_banana_models_are_offered_with_free_default():
    assert list(useapi.IMAGE_MODELS) == [
        "nano-banana-2-lite",
        "nano-banana-2",
        "nano-banana-pro",
        "kling-kolors-v3-0",
        "kling-kolors-v2-1",
        "kling-omni-image-v3",
        "kling-omni-image-o1",
    ]
    assert useapi.DEFAULT_IMAGE_MODEL == "nano-banana-2-lite"
    for model in useapi.IMAGE_MODELS:
        assert set(useapi.IMAGE_MODELS[model]["aspects"]) == set(VideoAspect)


def test_unknown_image_model_is_rejected_before_submission():
    config.app["useapi_image_model"] = "imagen-4"
    with patch.object(useapi.requests, "post") as post:
        with pytest.raises(useapi.UseAPIError, match="Unsupported useapi.net image model"):
            useapi.generate_image("lake", VideoAspect.portrait)
    post.assert_not_called()


@pytest.mark.parametrize(
    "aspect, expected", [
        (VideoAspect.portrait, "9:16"),
        (VideoAspect.landscape, "16:9"),
        (VideoAspect.square, "1:1"),
    ],
)
def test_image_request_downloads_signed_link_without_token(aspect, expected):
    config.app["useapi_image_model"] = "nano-banana-pro"
    png = _png_bytes()
    with (
        patch.object(
            useapi.requests, "post", return_value=_response(_image_body(fifeUrl=IMAGE_URL))
        ) as post,
        patch.object(useapi.requests, "get", return_value=_download(png)) as get,
    ):
        image_bytes, job_id = useapi.generate_image("  mountain lake  ", aspect)

    assert image_bytes == png
    assert job_id == "j-image-1"
    assert post.call_args.args[0] == "https://api.useapi.net/v1/google-flow/images"
    assert post.call_args.kwargs["json"] == {
        "prompt": "Create one image depicting: mountain lake.",
        "model": "nano-banana-pro",
        "aspectRatio": expected,
        "count": 1,
    }
    assert post.call_args.kwargs["headers"]["User-Agent"] == "MoneyPrinterTurbo-useapi/1.0"
    assert post.call_args.kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert post.call_args.kwargs["allow_redirects"] is False
    assert get.call_args.args[0] == IMAGE_URL
    assert get.call_args.kwargs["headers"] == {"User-Agent": "MoneyPrinterTurbo-useapi/1.0"}


def test_inline_image_is_decoded_when_link_is_missing():
    png = _png_bytes()
    body = _image_body(encodedImage=base64.b64encode(png).decode())
    with (
        patch.object(useapi.requests, "post", return_value=_response(body)),
        patch.object(useapi.requests, "get") as get,
    ):
        image_bytes, job_id = useapi.generate_image("lake", VideoAspect.landscape)
    assert image_bytes == png
    assert job_id == "j-image-1"
    get.assert_not_called()


@pytest.mark.parametrize("status_code", [400, 500])
def test_refused_prompt_skips_the_segment(status_code):
    refused = _response(
        {"error": {"code": status_code, "message": "PUBLIC_ERROR_UNSAFE_GENERATION"}},
        status_code=status_code,
    )
    with patch.object(useapi.requests, "post", return_value=refused) as post:
        image_bytes, _ = useapi.generate_image("lake", VideoAspect.portrait)
    assert image_bytes is None
    assert post.call_count == 1


def test_busy_image_request_waits_and_retries():
    busy = _response({"error": "no_eligible_account"}, 429, headers={"Retry-After": "9"})
    png = _png_bytes()
    with (
        patch.object(
            useapi.requests,
            "post",
            side_effect=[busy, _response(_image_body(fifeUrl=IMAGE_URL))],
        ) as post,
        patch.object(useapi.requests, "get", return_value=_download(png)),
        patch.object(useapi.time, "sleep") as sleep,
    ):
        image_bytes, _ = useapi.generate_image("lake", VideoAspect.portrait)
    assert image_bytes == png
    assert post.call_count == 2
    sleep.assert_called_once_with(9.0)


@pytest.mark.parametrize(
    "side_effect, response",
    [
        (requests.exceptions.ReadTimeout("slow"), None),
        (None, _response({"error": "unavailable"}, status_code=503)),
        (None, _response({}, status_code=307, headers={"Location": "https://x.example"})),
    ],
)
def test_ambiguous_image_request_is_unconfirmed(side_effect, response):
    with patch.object(
        useapi.requests, "post", side_effect=side_effect, return_value=response
    ) as post:
        with pytest.raises(useapi.UseAPIUnconfirmedTaskError):
            useapi.generate_image("lake", VideoAspect.portrait)
    assert post.call_count == 1


def test_download_retries_same_link_then_fails_with_job_id():
    with (
        patch.object(
            useapi.requests, "post", return_value=_response(_image_body(fifeUrl=IMAGE_URL))
        ) as post,
        patch.object(useapi.requests, "get", return_value=_download(b"", 503)) as get,
        patch.object(useapi.time, "sleep"),
    ):
        with pytest.raises(useapi.UseAPIError) as raised:
            useapi.generate_image("lake", VideoAspect.portrait)
    assert raised.value.task_id == "j-image-1"
    assert post.call_count == 1
    assert get.call_count == useapi.IMAGE_DOWNLOAD_ATTEMPTS
    assert {call.args[0] for call in get.call_args_list} == {IMAGE_URL}


def test_material_generator_saves_png_with_job_id(tmp_path):
    with patch.object(useapi, "generate_image", return_value=(_png_bytes(), "j-image-1")):
        items = material.generate_images_useapi(
            "lake", 4, VideoAspect.portrait, save_dir=str(tmp_path)
        )
    assert len(items) == 1
    item = items[0]
    assert item.provider == "useapi_image"
    assert item.duration == 4
    assert item.url.endswith(".png")
    assert item.source_info["asset_id"] == "j-image-1"
    assert item.source_info["rendition"] == {"id": "j-image-1", "width": 72, "height": 128}


def test_material_generator_skips_refused_and_undecodable_images(tmp_path):
    with patch.object(useapi, "generate_image", return_value=(None, "")):
        assert material.generate_images_useapi("a", 3, save_dir=str(tmp_path)) == []
    with patch.object(useapi, "generate_image", return_value=(b"not an image", "j-bad")):
        assert material.generate_images_useapi("a", 3, save_dir=str(tmp_path)) == []


def test_on_demand_images_skip_refused_segment_and_stop_when_covered(tmp_path):
    item = MaterialInfo(
        provider="useapi_image", url=str(tmp_path / "scene.png"), duration=3
    )
    with (
        patch.object(
            material, "generate_images_useapi", side_effect=[[], [item], [item]]
        ) as generate,
        patch.object(video, "render_image_zoom_video", return_value="clip.mp4") as render,
        patch.object(material, "_persist_material_sources"),
    ):
        paths = material.download_videos(
            "useapi-images",
            ["refused", "second", "third", "unused"],
            source="useapi_image",
            audio_duration=6,
            max_clip_duration=3,
            image_motion="static",
        )
    assert paths == ["clip.mp4", "clip.mp4"]
    assert generate.call_count == 3
    assert render.call_args.kwargs["image_motion"] == "static"


def test_on_demand_images_stop_on_unconfirmed_request():
    failure = useapi.UseAPIUnconfirmedTaskError("unknown")
    with (
        patch.object(useapi, "generate_image", side_effect=failure) as generate,
        patch.object(material, "_persist_material_sources") as persist,
    ):
        with pytest.raises(material.UseAPIImageMaterialError):
            material.download_videos(
                "useapi-images",
                ["one", "two"],
                source="useapi_image",
                audio_duration=6,
                max_clip_duration=3,
            )
    assert generate.call_count == 1
    persist.assert_called_once()


def test_task_preflight_rejects_missing_token_before_script_generation():
    params = VideoParams(video_subject="useapi images", video_source="useapi_image")
    with (
        patch.object(useapi, "is_enabled", return_value=False),
        patch.object(task_service.sm, "state", sm.MemoryState()),
        patch.object(task_service, "generate_script") as generate_script,
    ):
        result = task_service.start("useapi-image-preflight", params, stop_at="materials")
    assert result["failed_stage"] == "preflight"
    assert "useapi.net API token" in result["error"]
    generate_script.assert_not_called()


def test_task_preflight_rejects_unknown_image_model():
    config.app["useapi_image_model"] = "nano-banana-9"
    params = VideoParams(video_subject="useapi images", video_source="useapi_image")
    with (
        patch.object(task_service.sm, "state", sm.MemoryState()),
        patch.object(task_service, "generate_script") as generate_script,
    ):
        result = task_service.start("useapi-image-model", params, stop_at="materials")
    assert result["failed_stage"] == "preflight"
    assert "nano-banana-9" in result["error"]
    generate_script.assert_not_called()
