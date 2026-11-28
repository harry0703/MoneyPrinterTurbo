"""Opt-in request tracing must cover the Aigei preview and model downloads.

The Aigei provider routes its API calls (search, paid download link) through
``trace_http_call`` like every other provider. The two remaining raw
``requests.get`` calls were added with the Aigei feature itself: the free
preview-frame fetches used to verify sideways footage, and the 24 MB
orientation model download. With "Trace API Requests" enabled, a portrait
generation that stalls on the model download or silently loses its previews
showed nothing at all for exactly the phase the user turns the switch on for.

These tests are behavioural: with the switch off nothing is emitted and both
downloads keep working, and with the switch on each call emits a
request/response pair (or request/error on failure) whose query values never
reach the log.
"""

import hashlib
import io
import json

import pytest
from loguru import logger
from PIL import Image

from app.models.schema import MaterialInfo
from app.services import aigei, video_orientation
from app.utils import logging_utils as logs


@pytest.fixture(autouse=True)
def restore_logging_options():
    previous = logs.get_logging_options()
    yield
    logs.set_logging_options(*previous)


@pytest.fixture
def trace_output():
    sink = io.StringIO()
    handler = logger.add(
        sink, level=0, filter=logs.runtime_log_filter, format="{message}"
    )
    try:
        yield sink
    except Exception:
        pass
    finally:
        logger.remove(handler)


def trace_events(sink):
    return [
        json.loads(line.removeprefix("request_trace "))
        for line in sink.getvalue().splitlines()
        if line.startswith("request_trace ")
    ]


PREVIEW_URLS = [
    f"https://cdn.aigei.example/preview-{index}.jpg"
    f"?expires=1799999999&token=SECRET-PREVIEW-TOKEN-{index}"
    for index in range(1, 4)
]


def _preview_item():
    return MaterialInfo(
        provider="aigei",
        url="file-1",
        duration=8,
        source_info={"preview_urls": list(PREVIEW_URLS)},
    )


def _png_body(index):
    image = Image.new("RGB", (64, 48), (index * 60 % 255, 90, 130))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class _RawBody:
    def __init__(self, body):
        self._body = body

    def read(self, size=-1, decode_content=None):
        if size is None or size < 0:
            return self._body
        return self._body[:size]


class PreviewResponse:
    def __init__(self, body):
        self.status_code = 200
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @property
    def raw(self):
        return _RawBody(self._body)


def install_preview_backend(monkeypatch):
    requested = []

    def fake_get(url, **kwargs):
        requested.append(url)
        return PreviewResponse(_png_body(len(requested)))

    monkeypatch.setattr(aigei.requests, "get", fake_get)
    return requested


def test_preview_frames_stay_silent_without_tracing(monkeypatch, trace_output):
    requested = install_preview_backend(monkeypatch)

    logs.set_logging_options("DEBUG", False)
    frames = list(aigei.preview_frames(_preview_item()))

    assert requested == PREVIEW_URLS
    assert len(frames) == 3
    assert trace_events(trace_output) == []


def test_preview_frames_are_traced_with_query_values_redacted(
    monkeypatch, trace_output
):
    install_preview_backend(monkeypatch)

    logs.set_logging_options("DEBUG", True)
    frames = list(aigei.preview_frames(_preview_item()))

    assert len(frames) == 3
    events = trace_events(trace_output)
    assert [event["event"] for event in events] == ["request", "response"] * 3
    for index, url in enumerate(PREVIEW_URLS):
        request_event = events[index * 2]
        assert request_event["method"] == "GET"
        assert request_event["endpoint"].startswith(
            f"https://cdn.aigei.example/preview-{index + 1}.jpg?"
        )
        assert "token=%5BREDACTED%5D" in request_event["endpoint"]
        assert f"SECRET-PREVIEW-TOKEN-{index + 1}" not in trace_output.getvalue()
        assert events[index * 2 + 1]["status"] == 200


MODEL_URL = "https://cdn.example/rightwayup/69076d99/fast-s224-int8.onnx"
MODEL_BODY = b"onnx-orientation-model-fixture" * 32


class ModelResponse:
    def __init__(self, body):
        self.status_code = 200
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start:start + chunk_size]


def install_model_backend(monkeypatch, body=MODEL_BODY, url=MODEL_URL):
    monkeypatch.setattr(video_orientation, "_MODEL_URL", url)
    monkeypatch.setattr(video_orientation, "_MODEL_SIZE", len(body))
    monkeypatch.setattr(
        video_orientation,
        "_MODEL_SHA256",
        hashlib.sha256(body).hexdigest(),
    )
    monkeypatch.setattr(
        video_orientation.requests, "get", lambda url, **kwargs: ModelResponse(body)
    )


def test_orientation_model_download_stays_silent_without_tracing(
    monkeypatch, tmp_path, trace_output
):
    install_model_backend(monkeypatch)
    destination = tmp_path / "model.onnx"

    logs.set_logging_options("DEBUG", False)
    video_orientation._fetch_model(destination)

    assert destination.read_bytes() == MODEL_BODY
    assert trace_events(trace_output) == []


def test_orientation_model_download_is_traced(monkeypatch, tmp_path, trace_output):
    install_model_backend(monkeypatch)
    destination = tmp_path / "model.onnx"

    logs.set_logging_options("DEBUG", True)
    video_orientation._fetch_model(destination)

    assert destination.read_bytes() == MODEL_BODY
    events = trace_events(trace_output)
    assert [event["event"] for event in events] == ["request", "response"]
    assert events[0]["method"] == "GET"
    assert events[0]["endpoint"] == MODEL_URL
    assert events[1]["status"] == 200


def test_orientation_model_download_error_emits_the_error_event(
    monkeypatch, tmp_path, trace_output
):
    import requests

    def broken_get(url, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(video_orientation, "_MODEL_URL", MODEL_URL)
    monkeypatch.setattr(video_orientation.requests, "get", broken_get)
    destination = tmp_path / "model.onnx"

    logs.set_logging_options("DEBUG", True)
    with pytest.raises(requests.exceptions.ConnectionError):
        video_orientation._fetch_model(destination)

    events = trace_events(trace_output)
    assert [event["event"] for event in events] == ["request", "error"]
    assert events[1]["error_type"] == "ConnectionError"
    assert not destination.exists()
