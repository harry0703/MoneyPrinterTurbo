from datetime import UTC, datetime

from app.services.trends.models import SourceStatus, TrendSignal, TrendSnapshot
from app.services.trends.service import TrendDiscoveryService


NOW = datetime(2026, 9, 2, tzinfo=UTC)


class FakeSource:
    def __init__(self, source, signals=(), status=SourceStatus.AVAILABLE):
        self.source = source
        self.signals = list(signals)
        self.status = status

    def fetch(self, markets, collected_at):
        return self.signals, self.status


class FakeStore:
    def __init__(self, latest=None, previous=None):
        self.latest = latest
        self.previous = previous
        self.saved = []

    def load_latest(self):
        return self.latest

    def load_previous(self):
        return self.previous

    def save_snapshot(self, snapshot):
        self.saved.append(snapshot)


def signal(topic, market, source, confidence):
    return TrendSignal(
        topic=topic,
        market=market,
        rank=1,
        collected_at=NOW,
        source=source,
        source_reference=f"https://example.com/{source}",
        source_confidence=confidence,
    )


def test_refresh_keeps_platforms_separate():
    google = FakeSource(
        "google_trends",
        [signal("Ocean mystery", "US", "google_trends", 0.8)],
    )
    youtube = FakeSource(
        "youtube_most_popular",
        [signal("Ocean mystery", "US", "youtube_most_popular", 0.9)],
    )
    service = TrendDiscoveryService(FakeStore(), google, youtube, clock=lambda: NOW)

    snapshot = service.refresh()

    assert set(snapshot.platforms) == {
        "youtube_shorts",
        "tiktok",
        "instagram_reels",
    }
    assert snapshot.platforms["youtube_shorts"][0].confidence_label == "verified"
    assert snapshot.platforms["tiktok"][0].confidence_label == "inferred"
    assert snapshot.platforms["instagram_reels"][0].confidence_label == "inferred"


def test_all_sources_failed_returns_stale_cache():
    cached = TrendSnapshot(collected_at=NOW, topics=(), source_status={})
    failures = FakeSource("source", status=SourceStatus.UNAVAILABLE)
    service = TrendDiscoveryService(
        FakeStore(latest=cached), failures, failures, clock=lambda: NOW
    )

    result = service.refresh()

    assert result.stale
    assert result.collected_at == cached.collected_at
    assert result.source_status["google_trends"] is SourceStatus.UNAVAILABLE
