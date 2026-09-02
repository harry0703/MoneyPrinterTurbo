from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Mapping


class SourceStatus(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class TrendSignal:
    topic: str
    market: str
    rank: int
    collected_at: datetime
    source: str
    source_reference: str
    source_confidence: float = 0.5


@dataclass(frozen=True, slots=True)
class TopicCandidate:
    topic: str
    normalized_topic: str
    signals: tuple[TrendSignal, ...]
    markets: frozenset[str]


@dataclass(frozen=True, slots=True)
class ScoredTopic:
    topic: str
    classification: str
    retention_potential: int
    components: Mapping[str, int]
    confidence_label: str
    evidence: tuple[TrendSignal, ...]
    angles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TrendSnapshot:
    collected_at: datetime
    topics: tuple[ScoredTopic, ...]
    source_status: Mapping[str, SourceStatus]
    platforms: Mapping[str, tuple[ScoredTopic, ...]] = field(default_factory=dict)
    stale: bool = False
