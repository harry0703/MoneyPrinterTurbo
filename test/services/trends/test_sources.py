from datetime import UTC, datetime
from pathlib import Path

import pytest
import requests

from app.services.trends.models import SourceStatus
from app.services.trends.sources import GoogleTrendsRssSource, YouTubeMostPopularSource


class FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code

    def __bool__(self):
        return self.status_code < 400

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error


class FakeSession:
    def __init__(self):
        self.calls = []
        self.responses = []

    def reply_file(self, path: str, status_code: int = 200):
        self.responses.append(FakeResponse(Path(path).read_bytes(), status_code))

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


@pytest.fixture
def fixed_time():
    return datetime(2026, 9, 1, tzinfo=UTC)


@pytest.fixture
def fake_session():
    return FakeSession()


def test_google_source_maps_market_rank_and_reference(fake_session, fixed_time):
    fake_session.reply_file("test/resources/trends/google_trends_us.xml")

    signals, status = GoogleTrendsRssSource(fake_session).fetch(("US",), fixed_time)

    assert [(signal.market, signal.rank) for signal in signals] == [("US", 1), ("US", 2)]
    assert [signal.topic for signal in signals] == ["Ocean mystery", "Space exploration"]
    assert {signal.source_reference for signal in signals} == {
        "https://trends.google.com/trending/rss?geo=US"
    }
    assert status is SourceStatus.AVAILABLE


def test_google_source_retries_a_transient_failure(fake_session, fixed_time):
    fake_session.reply_file("test/resources/trends/google_trends_us.xml", status_code=500)
    fake_session.reply_file("test/resources/trends/google_trends_us.xml")

    signals, status = GoogleTrendsRssSource(fake_session).fetch(("US",), fixed_time)

    assert [signal.topic for signal in signals] == ["Ocean mystery", "Space exploration"]
    assert status is SourceStatus.AVAILABLE
    assert len(fake_session.calls) == 2


def test_google_source_limits_transient_failures_to_one_retry(fake_session, fixed_time):
    fake_session.reply_file("test/resources/trends/google_trends_us.xml", status_code=500)
    fake_session.reply_file("test/resources/trends/google_trends_us.xml", status_code=500)
    fake_session.reply_file("test/resources/trends/google_trends_us.xml", status_code=500)

    signals, status = GoogleTrendsRssSource(fake_session).fetch(("US",), fixed_time)

    assert signals == []
    assert status is SourceStatus.UNAVAILABLE
    assert len(fake_session.calls) == 2


def test_youtube_without_key_skips_network(fake_session, fixed_time):
    signals, status = YouTubeMostPopularSource(fake_session, "").fetch(("US",), fixed_time)

    assert signals == []
    assert status is SourceStatus.UNAVAILABLE
    assert fake_session.calls == []


def test_youtube_source_maps_public_video_evidence(fake_session, fixed_time):
    fake_session.reply_file("test/resources/trends/youtube_most_popular.json")

    signals, status = YouTubeMostPopularSource(fake_session, "test-key").fetch(
        ("US",), fixed_time
    )

    assert [(signal.topic, signal.market, signal.rank) for signal in signals] == [
        ("Ocean mystery", "US", 1),
        ("Space exploration", "US", 2),
    ]
    assert [signal.source_reference for signal in signals] == [
        "https://www.youtube.com/watch?v=ocean123",
        "https://www.youtube.com/watch?v=space456",
    ]
    assert status is SourceStatus.AVAILABLE


def test_youtube_source_rejects_non_object_json(fake_session, fixed_time):
    fake_session.responses.append(FakeResponse(b"[]"))

    signals, status = YouTubeMostPopularSource(fake_session, "test-key").fetch(
        ("US",), fixed_time
    )

    assert signals == []
    assert status is SourceStatus.UNAVAILABLE
