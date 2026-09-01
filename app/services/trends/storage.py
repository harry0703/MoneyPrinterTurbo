"""Atomic local persistence for trend snapshots and the shortlist."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.trends.models import ScoredTopic, SourceStatus, TrendSignal, TrendSnapshot
from app.services.trends.scoring import normalize_topic
from app.utils import utils


class TrendStore:
    def __init__(self, base_dir: str | os.PathLike[str] | None = None):
        self.base_dir = Path(base_dir or utils.storage_dir("trends", create=True))
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def load_latest(self) -> TrendSnapshot | None:
        return self._load_snapshot("latest.json") or self._load_snapshot("last_good.json")

    def load_previous(self) -> TrendSnapshot | None:
        return self._load_snapshot("previous.json")

    def save_snapshot(self, snapshot: TrendSnapshot) -> None:
        previous = self._load_snapshot("latest.json")
        if previous is not None:
            self._atomic_write("previous.json", _snapshot_payload(previous))
        payload = _snapshot_payload(snapshot)
        self._atomic_write("latest.json", payload)
        self._atomic_write("last_good.json", payload)

    def list_shortlist(self) -> list[ScoredTopic]:
        try:
            with (self.base_dir / "shortlist.json").open(encoding="utf-8") as handle:
                items = json.load(handle)
            if not isinstance(items, list):
                raise TypeError("shortlist must be a list")
            return [_topic_from_payload(item) for item in items]
        except (FileNotFoundError, TypeError, ValueError, KeyError):
            return []

    def add_shortlist(self, topic: ScoredTopic) -> None:
        topics = [item for item in self.list_shortlist() if _topic_id(item) != _topic_id(topic)]
        topics.append(topic)
        self._atomic_write("shortlist.json", [_topic_payload(item) for item in topics])

    def remove_shortlist(self, topic_id: str) -> bool:
        topics = self.list_shortlist()
        remaining = [item for item in topics if _topic_id(item) != normalize_topic(topic_id)]
        if len(remaining) == len(topics):
            return False
        self._atomic_write("shortlist.json", [_topic_payload(item) for item in remaining])
        return True

    def _load_snapshot(self, filename: str) -> TrendSnapshot | None:
        try:
            with (self.base_dir / filename).open(encoding="utf-8") as handle:
                return _snapshot_from_payload(json.load(handle))
        except (FileNotFoundError, TypeError, ValueError, KeyError):
            return None

    def _atomic_write(self, filename: str, payload: Any) -> None:
        target = self.base_dir / filename
        fd, temp_name = tempfile.mkstemp(prefix=f"{target.stem}-", suffix=".tmp", dir=self.base_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


def _snapshot_payload(snapshot: TrendSnapshot) -> dict[str, Any]:
    return {
        "collected_at": snapshot.collected_at.isoformat(),
        "topics": [_topic_payload(topic) for topic in snapshot.topics],
        "source_status": {
            source: getattr(status, "value", str(status))
            for source, status in snapshot.source_status.items()
        },
    }


def _snapshot_from_payload(payload: Any) -> TrendSnapshot:
    if not isinstance(payload, Mapping):
        raise TypeError("snapshot must be an object")
    topics = payload["topics"]
    source_status = payload["source_status"]
    if not isinstance(topics, list):
        raise TypeError("snapshot topics must be a list")
    if not isinstance(source_status, Mapping):
        raise TypeError("snapshot source_status must be an object")
    return TrendSnapshot(
        collected_at=_datetime_from_payload(payload["collected_at"]),
        topics=tuple(_topic_from_payload(item) for item in topics),
        source_status={
            source: SourceStatus(status) for source, status in source_status.items()
        },
    )


def _topic_payload(topic: ScoredTopic) -> dict[str, Any]:
    return {
        "topic": topic.topic,
        "classification": topic.classification,
        "retention_potential": topic.retention_potential,
        "components": dict(topic.components),
        "confidence_label": topic.confidence_label,
        "evidence": [_signal_payload(signal) for signal in topic.evidence],
        "angles": list(topic.angles),
    }


def _topic_from_payload(payload: Any) -> ScoredTopic:
    if not isinstance(payload, Mapping):
        raise TypeError("topic must be an object")
    components = payload["components"]
    evidence = payload["evidence"]
    angles = payload["angles"]
    if not isinstance(components, Mapping):
        raise TypeError("topic components must be an object")
    if not isinstance(evidence, list):
        raise TypeError("topic evidence must be a list")
    if not isinstance(angles, list):
        raise TypeError("topic angles must be a list")
    return ScoredTopic(
        topic=payload["topic"],
        classification=payload["classification"],
        retention_potential=payload["retention_potential"],
        components=components,
        confidence_label=payload["confidence_label"],
        evidence=tuple(_signal_from_payload(item) for item in evidence),
        angles=tuple(angles),
    )


def _signal_payload(signal: TrendSignal) -> dict[str, Any]:
    return {
        "topic": signal.topic,
        "market": signal.market,
        "rank": signal.rank,
        "collected_at": signal.collected_at.isoformat(),
        "source": signal.source,
        "source_reference": signal.source_reference,
        "source_confidence": signal.source_confidence,
    }


def _signal_from_payload(payload: Any) -> TrendSignal:
    if not isinstance(payload, Mapping):
        raise TypeError("evidence must be an object")
    return TrendSignal(
        topic=payload["topic"],
        market=payload["market"],
        rank=payload["rank"],
        collected_at=_datetime_from_payload(payload["collected_at"]),
        source=payload["source"],
        source_reference=payload["source_reference"],
        source_confidence=payload.get("source_confidence", 0.5),
    )


def _datetime_from_payload(value: Any) -> datetime:
    if not isinstance(value, str):
        raise TypeError("datetime must be an ISO string")
    return datetime.fromisoformat(value)


def _topic_id(topic: ScoredTopic) -> str:
    return normalize_topic(topic.topic)
