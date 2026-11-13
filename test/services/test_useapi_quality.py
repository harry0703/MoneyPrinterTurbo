"""Resolution / quality-mode choice and Google Flow upscaling for useapi.net."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from loguru import logger

from app.config import config
from app.models.schema import VideoAspect
from app.services import useapi


TOKEN = "user:1234-useapi-test-token"
EMAIL = "someone.private@gmail.com"
FLOW_JOB = f"j1108v-u700-email:{EMAIL}-bot:google-flow"
UPSCALE_JOB = f"j1109v-u700-email:{EMAIL}-bot:google-flow"
MEDIA_ID = f"user:700-email:{EMAIL}-video:CAMaJDMx"
ORIGINAL_URL = "https://flow-content.google/video/original?Expires=1"
UPSCALED_URL = "https://flow-content.google/video/original_upsampled?Expires=1"

EXPECTED_RESOLUTIONS = {
    "veo-3.1-lite": (),
    "veo-3.1-lite-low-priority": (),
    "veo-3.1-fast": (),
    "veo-3.1-quality": (),
    "omni-flash": ("720p", "360p"),
    "omni-flash-1.2": ("720p", "360p"),
    "vids-omni-flash-1.2": ("1080p", "720p"),
    "kling-v4-0": ("720p", "1080p"),
    "kling-v4-0-flash": ("720p",),
    "kling-v3-0": ("720p", "1080p", "4K"),
    "kling-v3-0-turbo": ("720p", "1080p"),
    "kling-v2-6": ("720p", "1080p"),
    "kling-v2-5": ("1080p",),
    "kling-v2-1-master": ("1080p",),
    "kling-v1-6": ("720p", "1080p"),
    "kling-v1-5": ("720p", "1080p"),
    "seedance-2.5": ("480p", "720p", "1080p"),
    "seedance-2.0": ("720p", "1080p", "4k"),
    "seedance-2.0-fast": ("720p", "1080p", "2k", "4k"),
    "seedance-2.0-mini": ("720p", "1080p", "2k", "4k"),
    "seedance-1.5-pro": ("720p", "1080p"),
    "seedance-1.0-pro": ("1080p",),
    "seedance-1.0-mini": ("720p",),
    "seedance-1.0-fast": ("720p", "1080p"),
}
FLOW_MODELS = [
    "veo-3.1-lite", "veo-3.1-lite-low-priority", "veo-3.1-fast",
    "veo-3.1-quality", "omni-flash", "omni-flash-1.2",
]


def _response(payload, status_code=200, headers=None):
    return SimpleNamespace(status_code=status_code, headers=headers or {}, json=lambda: payload)


def _flow_completed(job_id, url, media_id=MEDIA_ID):
    return {
        "jobid": job_id,
        "status": "completed",
        "response": {
            "media": [
                {
                    "mediaGenerationId": media_id,
                    "mediaMetadata": {
                        "mediaStatus": {"mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SUCCESSFUL"}
                    },
                    "videoUrl": url,
                }
            ]
        },
    }


@pytest.fixture(autouse=True)
def restore_config():
    original_app = dict(config.app)
    original_proxy = dict(config.proxy)
    config.app.update(
        {
            "useapi_api_token": TOKEN,
            "useapi_video_model": "veo-3.1-lite",
            "useapi_resolution": "",
            "useapi_upscale": "",
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


def test_resolution_table_covers_every_model():
    assert set(EXPECTED_RESOLUTIONS) == set(useapi.MODELS)


@pytest.mark.parametrize("model, expected", EXPECTED_RESOLUTIONS.items())
def test_each_model_offers_only_its_documented_resolutions(model, expected):
    assert useapi.resolution_options(model) == expected
    expected_default = expected[0] if expected else ""
    assert useapi.resolution_for(model, {}) == expected_default


def test_google_vids_defaults_to_1080p_and_sends_it():
    _, payload = useapi._submission(
        "vids-omni-flash-1.2", "lake", VideoAspect.portrait, 5
    )
    assert payload["resolution"] == "1080p"


@pytest.mark.parametrize(
    "model, configured, sent",
    [
        ("veo-3.1-lite", "360p", None),  # Veo has one quality; 360p is never sent
        ("seedance-2.0", "360p", "720p"),  # stale Omni value -> model default
        ("vids-omni-flash-1.2", "360p", "1080p"),
        ("omni-flash-1.2", "1080p", "720p"),
        ("omni-flash-1.2", "360p", "360p"),
        ("seedance-2.5", "", "480p"),
        ("seedance-1.0-pro", "720p", "1080p"),
        ("seedance-2.0", "4K", "4k"),
    ],
)
def test_stale_resolution_never_reaches_a_model_that_rejects_it(model, configured, sent):
    config.app["useapi_resolution"] = configured
    _, payload = useapi._submission(model, "lake", VideoAspect.portrait, 5)
    assert payload.get("resolution") == sent


@pytest.mark.parametrize(
    "model, configured, mode",
    [
        ("kling-v4-0", "", "std"),
        ("kling-v4-0", "1080p", "pro"),
        ("kling-v4-0", "4K", "std"),
        ("kling-v4-0-flash", "1080p", "std"),
        ("kling-v3-0", "4K", "4k"),
        ("kling-v3-0-turbo", "4K", "std"),
        ("kling-v2-6", "1080p", "pro"),
        ("kling-v2-5", "720p", "pro"),
        ("kling-v2-1-master", "", "pro"),
        ("kling-v1-5", "1080p", "pro"),
    ],
)
def test_kling_quality_modes_per_model(model, configured, mode):
    config.app["useapi_resolution"] = configured
    url, payload = useapi._submission(model, "lake", VideoAspect.portrait, 5)
    assert url.endswith("/kling/videos/text2video")
    assert payload["mode"] == mode
    assert "resolution" not in payload


def test_kling_mode_labels():
    assert useapi.resolution_label("kling-v3-0", "720p") == "720p (std)"
    assert useapi.resolution_label("kling-v3-0", "1080p") == "1080p (pro)"
    assert useapi.resolution_label("kling-v3-0", "4K") == "4K"
    assert useapi.resolution_label("seedance-2.0", "1080p") == "1080p"


@pytest.mark.parametrize("model", FLOW_MODELS)
def test_upscale_is_offered_for_every_google_flow_model(model):
    assert useapi.upscale_options(model, {}) == ("", "1080p", "4K")


@pytest.mark.parametrize("model", ["omni-flash", "omni-flash-1.2"])
def test_720p_upscale_is_offered_only_for_360p_clips(model):
    assert useapi.upscale_options(model, {"useapi_resolution": "360p"}) == (
        "", "720p", "1080p", "4K"
    )
    assert useapi.upscale_for(model, {"useapi_resolution": "720p", "useapi_upscale": "720p"}) == ""
    assert useapi.upscale_for(model, {"useapi_resolution": "360p", "useapi_upscale": "720p"}) == "720p"


@pytest.mark.parametrize(
    "model", [m for m in useapi.MODELS if useapi.MODELS[m]["service"] != useapi.GOOGLE_FLOW]
)
def test_no_upscale_outside_google_flow(model):
    assert useapi.upscale_options(model, {}) == ()
    assert useapi.upscale_for(model, {"useapi_upscale": "1080p"}) == ""


def _run_flow_clip(post_side_effect, get_side_effect):
    with (
        captured_logs() as lines,
        patch.object(useapi.requests, "post", side_effect=post_side_effect) as post,
        patch.object(useapi.requests, "get", side_effect=get_side_effect) as get,
        patch.object(useapi.time, "sleep"),
    ):
        result = useapi.generate_videos("lake", 5, VideoAspect.portrait)
    return result, post, get, lines


def test_upscale_submits_polls_and_downloads_the_upscaled_clip():
    config.app.update({"useapi_video_model": "omni-flash-1.2", "useapi_resolution": "360p",
                       "useapi_upscale": "1080p"})
    result, post, get, lines = _run_flow_clip(
        [_response({"jobid": FLOW_JOB}, 201), _response({"jobid": UPSCALE_JOB}, 201)],
        [
            _response(_flow_completed(FLOW_JOB, ORIGINAL_URL)),
            _response({"jobid": UPSCALE_JOB, "status": "started"}),
            _response(_flow_completed(UPSCALE_JOB, UPSCALED_URL, MEDIA_ID + "_upsampled")),
        ],
    )
    first, second = post.call_args_list
    assert first.kwargs["json"]["resolution"] == "360p"
    assert second.args[0] == "https://api.useapi.net/v1/google-flow/videos/upscale"
    assert second.kwargs["json"] == {
        "mediaGenerationId": MEDIA_ID,
        "resolution": "1080p",
        "async": True,
    }
    assert second.kwargs["headers"]["User-Agent"] == "MoneyPrinterTurbo-useapi/1.0"
    assert get.call_args_list[-1].args[0] == (
        f"https://api.useapi.net/v1/google-flow/jobs/{UPSCALE_JOB}"
    )
    item = result[0]
    assert item.url == UPSCALED_URL
    # The original clip stays as the download fallback.
    assert item.source_info["fallback_urls"] == [ORIGINAL_URL]
    assert all(EMAIL not in line for line in lines)


def _refused(resolution="4K"):
    return _response(
        {"error": f"{resolution} upscaling is not available for this account", "code": 400},
        status_code=400,
    )


def test_refused_upscale_keeps_the_original_and_the_next_clip_asks_again():
    config.app.update({"useapi_video_model": "veo-3.1-lite", "useapi_upscale": "4K"})
    result, post, _, lines = _run_flow_clip(
        [_response({"jobid": FLOW_JOB}, 201), _refused()],
        [_response(_flow_completed(FLOW_JOB, ORIGINAL_URL))],
    )
    assert result[0].url == ORIGINAL_URL
    assert post.call_count == 2
    assert len([line for line in lines if "not included in this Google account's plan" in line]) == 1
    assert all(EMAIL not in line for line in lines)

    # Nothing is remembered: the refusal is free, and the plan may have changed.
    result, post, _, _ = _run_flow_clip(
        [_response({"jobid": FLOW_JOB}, 201), _response({"jobid": UPSCALE_JOB}, 201)],
        [
            _response(_flow_completed(FLOW_JOB, ORIGINAL_URL)),
            _response(_flow_completed(UPSCALE_JOB, UPSCALED_URL)),
        ],
    )
    assert post.call_count == 2
    assert result[0].url == UPSCALED_URL


def test_refusal_for_one_account_does_not_block_another_token_or_account():
    config.app.update({"useapi_video_model": "veo-3.1-lite", "useapi_upscale": "1080p"})
    result, post, _, _ = _run_flow_clip(
        [_response({"jobid": FLOW_JOB}, 201), _refused("1080p")],
        [_response(_flow_completed(FLOW_JOB, ORIGINAL_URL))],
    )
    assert result[0].url == ORIGINAL_URL
    assert post.call_count == 2

    # Same process, another useapi.net token whose clip came from another
    # connected Google account on a paid plan.
    other_token = "user:5678-other-token"
    other_email = "another.account@gmail.com"
    other_job = f"j1110v-u701-email:{other_email}-bot:google-flow"
    other_media = f"user:701-email:{other_email}-video:CAMbXYZ"
    config.app["useapi_api_token"] = other_token
    result, post, _, lines = _run_flow_clip(
        [_response({"jobid": other_job}, 201), _response({"jobid": UPSCALE_JOB}, 201)],
        [
            _response(_flow_completed(other_job, ORIGINAL_URL, other_media)),
            _response(_flow_completed(UPSCALE_JOB, UPSCALED_URL)),
        ],
    )
    assert post.call_count == 2
    upscale = post.call_args_list[1]
    assert upscale.args[0] == "https://api.useapi.net/v1/google-flow/videos/upscale"
    assert upscale.kwargs["json"]["mediaGenerationId"] == other_media
    assert upscale.kwargs["headers"]["Authorization"] == f"Bearer {other_token}"
    assert result[0].url == UPSCALED_URL
    assert all(other_email not in line for line in lines)


def test_other_400_is_not_treated_as_a_plan_refusal():
    config.app.update({"useapi_video_model": "veo-3.1-lite", "useapi_upscale": "1080p"})
    invalid = _response({"error": "mediaGenerationId is invalid", "code": 400}, status_code=400)
    result, post, _, lines = _run_flow_clip(
        [_response({"jobid": FLOW_JOB}, 201), invalid],
        [_response(_flow_completed(FLOW_JOB, ORIGINAL_URL))],
    )
    assert result[0].url == ORIGINAL_URL
    assert post.call_count == 2
    assert any("rejected the upscale to 1080p" in line for line in lines)
    assert not any("not included in this Google account's plan" in line for line in lines)

    # A later valid clip at the same resolution is still upscaled.
    result, post, _, _ = _run_flow_clip(
        [_response({"jobid": FLOW_JOB}, 201), _response({"jobid": UPSCALE_JOB}, 201)],
        [
            _response(_flow_completed(FLOW_JOB, ORIGINAL_URL)),
            _response(_flow_completed(UPSCALE_JOB, UPSCALED_URL)),
        ],
    )
    assert post.call_count == 2
    assert result[0].url == UPSCALED_URL


@pytest.mark.parametrize(
    "upscale_answer",
    [
        _response({"error": "bad gateway"}, status_code=502),
        _response({"status": "created"}, status_code=201),
    ],
)
def test_ambiguous_upscale_keeps_the_original_and_is_never_resubmitted(upscale_answer):
    config.app.update({"useapi_video_model": "veo-3.1-fast", "useapi_upscale": "1080p"})
    result, post, get, lines = _run_flow_clip(
        [_response({"jobid": FLOW_JOB}, 201), upscale_answer],
        [_response(_flow_completed(FLOW_JOB, ORIGINAL_URL))],
    )
    assert result[0].url == ORIGINAL_URL
    assert post.call_count == 2
    assert get.call_count == 1
    assert all(EMAIL not in line for line in lines)


def test_failed_upscale_job_keeps_the_original():
    config.app.update({"useapi_video_model": "veo-3.1-quality", "useapi_upscale": "1080p"})
    result, post, _, _ = _run_flow_clip(
        [_response({"jobid": FLOW_JOB}, 201), _response({"jobid": UPSCALE_JOB}, 201)],
        [
            _response(_flow_completed(FLOW_JOB, ORIGINAL_URL)),
            _response({"jobid": UPSCALE_JOB, "status": "failed", "error": "upscale failed"}),
        ],
    )
    assert result[0].url == ORIGINAL_URL
    assert post.call_count == 2


def test_busy_upscale_waits_then_upscales():
    config.app.update({"useapi_video_model": "omni-flash", "useapi_upscale": "1080p"})
    busy = _response({"error": "no_eligible_account"}, 429, headers={"Retry-After": "5"})
    result, post, _, _ = _run_flow_clip(
        [_response({"jobid": FLOW_JOB}, 201), busy, _response({"jobid": UPSCALE_JOB}, 201)],
        [
            _response(_flow_completed(FLOW_JOB, ORIGINAL_URL)),
            _response(_flow_completed(UPSCALE_JOB, UPSCALED_URL)),
        ],
    )
    assert result[0].url == UPSCALED_URL
    assert post.call_count == 3


@pytest.mark.parametrize("model", ["kling-v2-6", "seedance-2.0", "vids-omni-flash-1.2"])
def test_no_upscale_request_outside_google_flow(model):
    config.app.update({"useapi_video_model": model, "useapi_upscale": "1080p"})
    if model.startswith("kling"):
        submitted = _response({"task": {"id": 5}})
        done = _response({
            "status_name": "succeed",
            "works": [{"contentType": "video", "resource": {"resource": "https://k.example/v.mp4"}}],
        })
    elif model.startswith("seedance"):
        submitted = _response({"jobid": "j-d"})
        done = _response({"status": "completed", "response": {"videoUrl": "https://d.example/v.mp4"}})
    else:
        submitted = _response({"jobid": "j-v"}, 202)
        done = _response({"status": "completed", "result": {"mediaId": "m1"}})
    with (
        patch.object(useapi.requests, "post", return_value=submitted) as post,
        patch.object(useapi.requests, "get", return_value=done),
    ):
        useapi.generate_videos("lake", 5, VideoAspect.portrait)
    assert post.call_count == 1
    assert "upscale" not in post.call_args.args[0]
