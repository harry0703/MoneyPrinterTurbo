"""Opt-in request tracing must cover the LoomLoom video artifact download.

The shared tracer covers every other HTTP call of the paid video providers:
the LoomLoom API calls (quote/execute/poll) go through ``trace_http_call`` and
so do the Infistar and stock-video downloads. The LoomLoom artifact download
was added with a raw ``Session.get``, so enabling "Trace API Requests" while a
paid video generation was downloading its result showed nothing at all for
that phase, which is exactly the situation a user turns the switch on for.

These tests are behavioural: with the switch off no trace is emitted and the
download works as before, and with the switch on the download emits a
request/response pair whose signed artifact URL is redacted.
"""

import io
import json

import pytest
from loguru import logger

from app.services.loomloom import LoomLoomSettings, LoomLoomVideoBackend
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
    finally:
        logger.remove(handler)


def trace_events(sink):
    return [
        json.loads(line.removeprefix("request_trace "))
        for line in sink.getvalue().splitlines()
        if line.startswith("request_trace ")
    ]


class FakeResponse:
    def __init__(self, body, status=200):
        self.status_code = status
        self.headers = {"content-length": str(len(body))}
        self._body = body

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=1):
        yield self._body

    def close(self):
        pass


class FakeSession:
    def __init__(self, response):
        self._response = response
        self.get_urls = []

    def get(self, url, **kwargs):
        self.get_urls.append(url)
        return self._response


BODY = b"MP4-ARTIFACT-FIXTURE" * 64
ACCESS_URL = (
    "https://cdn.loomloom.example/artifacts/run-1/video.mp4"
    "?expires=1799999999&signature=SECRET-ARTIFACT-SIGNATURE"
)


def download(destination, session):
    backend = LoomLoomVideoBackend(
        LoomLoomSettings(
            base_url="https://loomloom.example/loom/v1",
            api_token="synthetic",
            market_listing_id="fixture",
        ),
        session=session,
    )
    backend._download_video_artifact(ACCESS_URL, str(destination))


def test_download_writes_the_artifact_and_stays_silent_without_tracing(
    tmp_path, trace_output
):
    session = FakeSession(FakeResponse(BODY))
    destination = tmp_path / "loomloom-video-01.mp4"

    logs.set_logging_options("DEBUG", False)
    download(destination, session)

    assert destination.read_bytes() == BODY
    assert trace_events(trace_output) == []


def test_download_is_traced_with_the_signed_url_redacted(tmp_path, trace_output):
    session = FakeSession(FakeResponse(BODY))
    destination = tmp_path / "loomloom-video-01.mp4"

    logs.set_logging_options("DEBUG", True)
    download(destination, session)

    assert destination.read_bytes() == BODY
    events = trace_events(trace_output)
    assert [event["event"] for event in events] == ["request", "response"]
    assert events[0]["method"] == "GET"
    assert events[0]["endpoint"].startswith(
        "https://cdn.loomloom.example/artifacts/run-1/video.mp4?"
    )
    # 查询串值整体遮盖（urlencode 后写作 %5BREDACTED%5D）：artifact 地址
    # 自带的签名不进入日志。
    assert "signature=%5BREDACTED%5D" in events[0]["endpoint"]
    assert "SECRET-ARTIFACT-SIGNATURE" not in trace_output.getvalue()
    assert events[1]["status"] == 200


def test_failed_download_emits_the_error_event(tmp_path, trace_output):
    import requests

    class BrokenSession:
        def get(self, url, **kwargs):
            raise requests.exceptions.ConnectionError("connection refused")

    destination = tmp_path / "loomloom-video-01.mp4"

    logs.set_logging_options("DEBUG", True)
    with pytest.raises(Exception, match="download failed"):
        download(destination, BrokenSession())

    events = trace_events(trace_output)
    assert [event["event"] for event in events] == ["request", "error"]
    assert events[1]["error_type"] == "ConnectionError"
    assert not list(tmp_path.glob("*.part"))
