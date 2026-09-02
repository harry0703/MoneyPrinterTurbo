from dataclasses import replace
from datetime import UTC, datetime

from app.services.trends.models import ScoredTopic, TrendSnapshot
from app.services.trends.service import TrendDiscoveryService


def test_add_angles_updates_only_selected_cached_topic(monkeypatch):
    first = ScoredTopic("Ocean mystery", "emerging", 50, {}, "inferred", (), ())
    second = ScoredTopic("Space news", "emerging", 40, {}, "inferred", (), ())
    cached = TrendSnapshot(
        datetime(2026, 9, 2, tzinfo=UTC),
        (first, second),
        {},
        {"youtube_shorts": (first, second)},
    )

    class Store:
        latest = cached

        def load_latest(self):
            return self.latest

        def save_snapshot(self, snapshot):
            self.latest = snapshot

    store = Store()
    service = TrendDiscoveryService(store, None, None)
    monkeypatch.setattr(
        "app.services.llm.generate_trend_angles",
        lambda topic, evidence, app_config=None: ["One", "Two", "Three"],
    )

    updated = service.add_angles("Ocean mystery")

    assert updated.angles == ("One", "Two", "Three")
    assert store.latest.platforms["youtube_shorts"][1] == second
    assert store.latest.topics[0] == replace(first, angles=("One", "Two", "Three"))
