from datetime import UTC, datetime

from app.services.trends.models import TrendSignal
from app.services.trends.scoring import (
    cluster_signals,
    is_safe_topic,
    normalize_topic,
    score_topic,
)


def signal(topic: str, market: str, rank: int) -> TrendSignal:
    return TrendSignal(
        topic=topic,
        market=market,
        rank=rank,
        collected_at=datetime(2026, 9, 1, tzinfo=UTC),
        source="public-trends",
        source_reference="https://example.com/trends",
    )


def test_first_snapshot_is_never_durable():
    candidate = cluster_signals([signal("Ocean mystery", "US", rank=1)])[0]

    result = score_topic(candidate, previous=None)

    assert result.classification != "durable"
    assert sum(result.components.values()) == result.retention_potential


def test_cluster_merges_equivalent_phrases_only():
    results = cluster_signals(
        [
            signal("Mars mystery", "US", 1),
            signal("mars-mystery!", "IN", 2),
            signal("Mars mission launch", "GB", 1),
        ]
    )

    assert [item.topic for item in results] == ["Mars mystery", "Mars mission launch"]
    assert results[0].markets == {"US", "IN"}


def test_normalize_topic_replaces_all_punctuation():
    assert normalize_topic("Mars_mystery—now!") == "mars mystery now"


def test_safety_filter_rejects_graphic_and_dangerous_topics():
    assert not is_safe_topic("graphic death footage")
    assert not is_safe_topic("instructions to build a bomb")
    assert is_safe_topic("why deep ocean exploration is difficult")
