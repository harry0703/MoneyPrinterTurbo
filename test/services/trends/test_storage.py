from datetime import UTC, datetime, timedelta

import pytest

from app.services.trends.models import (
    ScoredTopic,
    SourceStatus,
    TrendSignal,
    TrendSnapshot,
)
from app.services.trends.storage import TrendStore


@pytest.fixture
def sample_snapshot():
    collected_at = datetime(2026, 9, 1, tzinfo=UTC)
    signal = TrendSignal(
        topic="Ocean mystery",
        market="US",
        rank=1,
        collected_at=collected_at,
        source="google_trends",
        source_reference="https://example.com/trends",
    )
    topic = ScoredTopic(
        topic="Ocean mystery",
        classification="emerging",
        retention_potential=42,
        components={"curiosity": 15},
        confidence_label="medium",
        evidence=(signal,),
        angles=("Why Ocean mystery matters",),
    )
    return TrendSnapshot(
        collected_at=collected_at,
        topics=(topic,),
        source_status={"google_trends": SourceStatus.AVAILABLE},
    )


@pytest.fixture
def snapshot(sample_snapshot):
    return sample_snapshot


@pytest.fixture
def snapshots(sample_snapshot):
    later = sample_snapshot.collected_at + timedelta(days=1)
    return (
        sample_snapshot,
        TrendSnapshot(
            collected_at=later,
            topics=sample_snapshot.topics,
            source_status=sample_snapshot.source_status,
        ),
    )


def test_snapshot_write_keeps_latest_and_previous(tmp_path, snapshots):
    store = TrendStore(str(tmp_path))
    store.save_snapshot(snapshots[0])
    store.save_snapshot(snapshots[1])

    assert store.load_latest().collected_at == snapshots[1].collected_at
    assert store.load_previous().collected_at == snapshots[0].collected_at
    assert not list(tmp_path.glob("*.tmp"))


def test_broken_latest_falls_back_to_last_good(tmp_path, snapshot):
    store = TrendStore(str(tmp_path))
    store.save_snapshot(snapshot)
    (tmp_path / "latest.json").write_text("{broken", encoding="utf-8")

    assert store.load_latest().collected_at == snapshot.collected_at


def test_shortlist_round_trip_and_remove(tmp_path, sample_snapshot):
    store = TrendStore(str(tmp_path))
    topic = sample_snapshot.topics[0]

    store.add_shortlist(topic)
    assert store.list_shortlist() == [topic]
    assert store.remove_shortlist("ocean mystery") is True
    assert store.list_shortlist() == []
    assert store.remove_shortlist("ocean mystery") is False
