from __future__ import annotations

import re
import unicodedata
from types import MappingProxyType
from typing import Iterable

from app.services.trends.models import ScoredTopic, TopicCandidate, TrendSignal, TrendSnapshot


_COMPONENT_WEIGHTS = {
    "listenability": 30,
    "momentum": 20,
    "curiosity": 15,
    "durability": 10,
    "cross_platform": 10,
    "faceless_fit": 10,
    "evidence_confidence": 5,
}
_UNSAFE = re.compile(
    r"\b(?:graphic (?:death|violence|injury|footage)|(?:build|make|construct) (?:a )?bomb|bomb instructions|suicide instructions)\b",
    re.IGNORECASE,
)
_LISTENABLE = re.compile(r"\b(?:mystery|history|science|space|ocean|future|story|exploration)\b", re.IGNORECASE)
_CURIOSITY = re.compile(r"\b(?:why|how|mystery|secret|unknown|explained|hidden)\b", re.IGNORECASE)
_FACELESS = re.compile(r"\b(?:science|space|ocean|history|technology|nature|exploration)\b", re.IGNORECASE)


def normalize_topic(text: str) -> str:
    return " ".join(
        "".join(
            " " if unicodedata.category(character).startswith("P") else character
            for character in text.casefold()
        ).split()
    )


def is_safe_topic(text: str) -> bool:
    return bool(normalize_topic(text)) and not bool(_UNSAFE.search(text))


def cluster_signals(signals: Iterable[TrendSignal]) -> list[TopicCandidate]:
    grouped: dict[str, list[TrendSignal]] = {}
    for signal in signals:
        normalized = normalize_topic(signal.topic)
        if normalized:
            grouped.setdefault(normalized, []).append(signal)
    return [
        TopicCandidate(
            topic=items[0].topic,
            normalized_topic=normalized,
            signals=tuple(items),
            markets=frozenset(item.market for item in items),
        )
        for normalized, items in grouped.items()
    ]


def score_topic(candidate: TopicCandidate, previous: TrendSnapshot | None) -> ScoredTopic:
    evidence = candidate.signals
    average_rank = sum(max(1, signal.rank) for signal in evidence) / max(len(evidence), 1)
    rank_strength = _clamp((101 - average_rank) / 100)
    market_strength = _clamp((len(candidate.markets) - 1) / 3)
    source_strength = _clamp(
        sum(_clamp(signal.source_confidence) for signal in evidence) / max(len(evidence), 1)
    )
    prior = _prior_topic(candidate, previous)
    prior_strength = 1.0 if prior else 0.0
    text = candidate.topic
    components = {
        "listenability": _points(_LISTENABLE.search(text) is not None, "listenability"),
        "momentum": _points(rank_strength, "momentum"),
        "curiosity": _points(_CURIOSITY.search(text) is not None, "curiosity"),
        "durability": _points(
            max(prior_strength, _LISTENABLE.search(text) is not None), "durability"
        ),
        "cross_platform": _points(market_strength, "cross_platform"),
        "faceless_fit": _points(_FACELESS.search(text) is not None, "faceless_fit"),
        "evidence_confidence": _points(source_strength, "evidence_confidence"),
    }
    retention_potential = sum(components.values())
    confidence_label = "high" if source_strength >= 0.8 else "medium" if source_strength >= 0.5 else "low"
    classification = _classification(candidate, previous, prior, source_strength, retention_potential)
    return ScoredTopic(
        topic=candidate.topic,
        classification=classification,
        retention_potential=retention_potential,
        components=MappingProxyType(components),
        confidence_label=confidence_label,
        evidence=evidence,
        angles=_angles(candidate.topic),
    )


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _points(value: float | bool, component: str) -> int:
    return round(_clamp(float(value)) * _COMPONENT_WEIGHTS[component])


def _prior_topic(candidate: TopicCandidate, previous: TrendSnapshot | None) -> ScoredTopic | None:
    if previous is None:
        return None
    return next((topic for topic in previous.topics if normalize_topic(topic.topic) == candidate.normalized_topic), None)


def _classification(
    candidate: TopicCandidate,
    previous: TrendSnapshot | None,
    prior: ScoredTopic | None,
    source_strength: float,
    retention_potential: int,
) -> str:
    if not is_safe_topic(candidate.topic) or not candidate.signals or source_strength < 0.25:
        return "unverified"
    if previous is None:
        return "emerging"
    if prior and retention_potential >= 60:
        return "durable"
    if len(candidate.markets) >= 2 and retention_potential >= 45:
        return "fast"
    return "emerging"


def _angles(topic: str) -> tuple[str, ...]:
    return (f"Why {topic} matters", f"The surprising story behind {topic}")
