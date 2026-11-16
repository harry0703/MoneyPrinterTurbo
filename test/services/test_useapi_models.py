"""Per-model durations, ratios and request fields for every useapi.net video model."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.config import config
from app.models.schema import VideoAspect
from app.services import useapi


TOKEN = "user:1234-useapi-test-token"
ALL_RATIOS = set(VideoAspect)
NO_SQUARE = {VideoAspect.portrait, VideoAspect.landscape}

# (model, allowed durations, ratios) as documented on useapi.net.
EXPECTED = [
    # Google Flow video takes landscape or portrait only, Veo included.
    ("veo-3.1-lite", (8,), NO_SQUARE),
    ("veo-3.1-lite-low-priority", (8,), NO_SQUARE),
    ("veo-3.1-fast", (8,), NO_SQUARE),
    ("veo-3.1-quality", (8,), NO_SQUARE),
    ("omni-flash", (4, 6, 8, 10), NO_SQUARE),
    ("omni-flash-1.2", tuple(range(3, 11)), NO_SQUARE),
    ("vids-omni-flash-1.2", tuple(range(3, 16)), NO_SQUARE),
    ("kling-v4-0", tuple(range(3, 31)), ALL_RATIOS),
    ("kling-v4-0-flash", tuple(range(3, 21)), ALL_RATIOS),
    ("kling-v3-0", tuple(range(3, 16)), ALL_RATIOS),
    ("kling-v3-0-turbo", tuple(range(3, 16)), ALL_RATIOS),
    ("kling-v2-6", (5, 10), ALL_RATIOS),
    ("kling-v2-5", (5, 10), ALL_RATIOS),
    ("kling-v2-1-master", (5, 10), ALL_RATIOS),
    ("kling-v1-6", (5, 10), ALL_RATIOS),
    ("kling-v1-5", (5, 10), ALL_RATIOS),
    ("seedance-2.5", tuple(range(4, 31)), ALL_RATIOS),
    ("seedance-2.0", tuple(range(4, 16)), ALL_RATIOS),
    ("seedance-2.0-fast", tuple(range(4, 16)), ALL_RATIOS),
    ("seedance-2.0-mini", tuple(range(4, 16)), ALL_RATIOS),
    ("seedance-1.5-pro", (5, 10, 12), ALL_RATIOS),
    ("seedance-1.0-pro", (5, 10), ALL_RATIOS),
    ("seedance-1.0-mini", (5, 10), ALL_RATIOS),
    ("seedance-1.0-fast", (5, 10), ALL_RATIOS),
]


def _response(payload, status_code=200):
    return SimpleNamespace(status_code=status_code, headers={}, json=lambda: payload)


@pytest.fixture(autouse=True)
def restore_config():
    original_app = dict(config.app)
    config.app.update({"useapi_api_token": TOKEN, "useapi_resolution": ""})
    yield
    config.app.clear()
    config.app.update(original_app)


def test_expected_table_covers_every_offered_model():
    assert [model for model, _, _ in EXPECTED] == list(useapi.MODELS)


@pytest.mark.parametrize("model, durations, ratios", EXPECTED)
def test_model_durations_and_ratios_match_the_docs(model, durations, ratios):
    assert useapi.MODELS[model]["durations"] == durations
    assert set(useapi.MODELS[model]["aspects"]) == ratios
    # Every requested length becomes an allowed one that covers it when it can.
    for requested in range(1, 35):
        sent = useapi.request_duration(model, requested)
        assert sent in durations
        assert sent >= requested or sent == max(durations)


@pytest.mark.parametrize("model", [m for m, _, r in EXPECTED if r == NO_SQUARE])
def test_models_without_square_reject_1_1_before_submission(model):
    config.app["useapi_video_model"] = model
    with patch.object(useapi.requests, "post") as post:
        with pytest.raises(useapi.UseAPIError, match="9:16, 16:9"):
            useapi.generate_videos("lake", 5, VideoAspect.square)
    post.assert_not_called()


@pytest.mark.parametrize(
    "model, requested, expected_json",
    [
        (
            "veo-3.1-quality",
            5,
            {"prompt": "lake", "model": "veo-3.1-quality", "aspectRatio": "landscape",
             "duration": 8, "async": True},
        ),
        (
            "veo-3.1-lite-low-priority",
            5,
            {"prompt": "lake", "model": "veo-3.1-lite-low-priority", "aspectRatio": "landscape",
             "duration": 8, "async": True},
        ),
        (
            "kling-v2-1-master",
            7,
            {"prompt": "lake", "model_name": "kling-v2-1-master", "aspect_ratio": "1:1",
             "duration": "10", "mode": "pro"},
        ),
        (
            "kling-v2-5",
            5,
            {"prompt": "lake", "model_name": "kling-v2-5", "aspect_ratio": "1:1",
             "duration": "5", "mode": "pro"},
        ),
        (
            "kling-v1-5",
            5,
            {"prompt": "lake", "model_name": "kling-v1-5", "aspect_ratio": "1:1",
             "duration": "5", "mode": "std"},
        ),
        (
            "seedance-1.0-pro",
            6,
            {"prompt": "lake", "model": "seedance-1.0-pro", "ratio": "1:1",
             "duration": 10, "resolution": "1080p"},
        ),
        (
            "seedance-1.5-pro",
            11,
            {"prompt": "lake", "model": "seedance-1.5-pro", "ratio": "1:1",
             "duration": 12, "resolution": "720p"},
        ),
    ],
)
def test_request_fields_per_model(model, requested, expected_json):
    # Google Flow models take no 1:1, so they are checked in landscape.
    aspect = (
        VideoAspect.landscape
        if useapi.MODELS[model]["service"] == useapi.GOOGLE_FLOW
        else VideoAspect.square
    )
    _, payload = useapi._submission(model, "lake", aspect,
                                    useapi.request_duration(model, requested))
    assert payload == expected_json


def test_omni_1_1_sends_configured_360p():
    config.app["useapi_resolution"] = "360p"
    url, payload = useapi._submission("omni-flash", "lake", VideoAspect.portrait, 6)
    assert url == "https://api.useapi.net/v1/google-flow/videos"
    assert payload == {
        "prompt": "lake", "model": "omni-flash", "aspectRatio": "portrait",
        "duration": 6, "async": True, "resolution": "360p",
    }


def test_configured_resolution_overrides_a_model_default():
    config.app["useapi_resolution"] = "1080p"
    _, payload = useapi._submission("seedance-2.0", "lake", VideoAspect.portrait, 5)
    assert payload["resolution"] == "1080p"


RETIRING = {
    "veo-3.1-fast": "Veo 3.1 Fast (Google Flow, retires December 5)",
    "veo-3.1-quality": "Veo 3.1 Quality (Google Flow, retires December 5)",
    "omni-flash": "Gemini Omni 1.1 Flash (Google Flow, retires December 5)",
}


def test_only_the_retiring_models_name_their_retirement_date():
    for model, spec in useapi.MODELS.items():
        if model in RETIRING:
            assert spec["label"] == RETIRING[model]
        else:
            assert "retire" not in spec["label"].lower()
    assert (
        useapi.MODELS["veo-3.1-lite-low-priority"]["label"]
        == "Veo 3.1 Lite low priority (0 credits on Ultra $199)"
    )


def test_translated_labels_in_en_and_zh():
    root = Path(__file__).resolve().parents[2] / "webui" / "i18n"
    en = json.loads((root / "en.json").read_text(encoding="utf-8"))["Translation"]
    zh = json.loads((root / "zh.json").read_text(encoding="utf-8"))["Translation"]
    for model, label in RETIRING.items():
        assert en[f"useapi_model_label.{model}"] == label
    assert zh["useapi_model_label.veo-3.1-fast"] == "Veo 3.1 Fast（Google Flow，12 月 5 日停用）"
    assert zh["useapi_model_label.veo-3.1-quality"] == "Veo 3.1 Quality（Google Flow，12 月 5 日停用）"
    assert zh["useapi_model_label.omni-flash"] == "Gemini Omni 1.1 Flash（Google Flow，12 月 5 日停用）"
    assert en["useapi_model_label.veo-3.1-lite-low-priority"] == (
        "Veo 3.1 Lite low priority (0 credits on Ultra $199)"
    )
    assert zh["useapi_model_label.veo-3.1-lite-low-priority"] == (
        "Veo 3.1 Lite 低优先级（Ultra $199 套餐 0 积分）"
    )
