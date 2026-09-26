"""Build a conservative scene timeline from narration and subtitle cues."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

from app.models.production_plan import (
    ProductionPlan,
    ReviewFinding,
    ScenePlan,
    StageRecord,
)
from app.utils import utils


_SENTENCE_ENDINGS = frozenset(".!?。！？\n")
_SRT_TIME_RANGE = re.compile(
    r"^\s*(\d{2}:\d{2}:\d{2},\d{1,3})\s*-->\s*"
    r"(\d{2}:\d{2}:\d{2},\d{1,3})\s*$"
)
_WORDS = re.compile(r"\w+", re.UNICODE)


def _words(text: str) -> list[str]:
    return _WORDS.findall(text.casefold())


def _split_spans(script: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    index = 0
    while index < len(script):
        char = script[index]
        decimal_point = (
            char == "."
            and index > 0
            and index + 1 < len(script)
            and script[index - 1].isdigit()
            and script[index + 1].isdigit()
        )
        if char in _SENTENCE_ENDINGS and not decimal_point:
            end = index + 1
            while end < len(script) and script[end] in _SENTENCE_ENDINGS:
                end += 1
            while end < len(script) and script[end].isspace():
                end += 1
            if script[start:end].strip():
                spans.append((start, end))
                start = end
            index = end
            continue
        index += 1
    if start < len(script):
        if script[start:].strip() or not spans:
            spans.append((start, len(script)))
        else:
            previous_start, _ = spans[-1]
            spans[-1] = (previous_start, len(script))
    return spans


def _seconds(timestamp: str) -> float:
    hours, minutes, seconds = timestamp.replace(",", ":").split(":")[:3]
    milliseconds = timestamp.rsplit(",", 1)[1]
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(milliseconds.ljust(3, "0")) / 1000
    )


def _subtitle_boundaries(
    script: str,
    spans: list[tuple[int, int]],
    subtitle_items: Sequence[tuple[int, str, str]],
    audio_duration: float,
) -> list[float] | None:
    word_starts: list[float] = []
    cue_words: list[str] = []
    previous_end = 0.0
    for _, time_range, cue_text in subtitle_items:
        match = _SRT_TIME_RANGE.fullmatch(time_range)
        if match is None:
            return None
        start, end = _seconds(match[1]), _seconds(match[2])
        words = _words(cue_text)
        if (
            not words
            or start < previous_end
            or end <= start
            or end > audio_duration + 0.1
        ):
            return None
        cue_words.extend(words)
        word_starts.extend(
            start + (end - start) * index / len(words) for index in range(len(words))
        )
        previous_end = end
    if not word_starts or cue_words != _words(script):
        return None

    boundaries = [0.0]
    word_offset = 0
    for start, end in spans[:-1]:
        word_offset += len(_words(script[start:end]))
        if word_offset <= 0 or word_offset >= len(word_starts):
            return None
        boundaries.append(word_starts[word_offset])
    boundaries.append(audio_duration)
    if any(right <= left for left, right in zip(boundaries, boundaries[1:])):
        return None
    return boundaries


def _estimated_boundaries(
    script: str, spans: list[tuple[int, int]], audio_duration: float
) -> list[float]:
    weights = [max(len(_words(script[start:end])), 1) for start, end in spans]
    total = sum(weights)
    boundaries = [0.0]
    running = 0
    for weight in weights[:-1]:
        running += weight
        boundaries.append(audio_duration * running / total)
    boundaries.append(audio_duration)
    return boundaries


def build_scene_plan(
    task_id: str,
    script: str,
    audio_duration: float,
    subtitle_items: Sequence[tuple[int, str, str]],
    *,
    custom_audio: bool = False,
) -> ProductionPlan:
    """Create exact script spans, using subtitle timing only when text matches."""
    spoken_script = utils.remove_pause_tags(script)
    if not spoken_script or not math.isfinite(audio_duration) or audio_duration <= 0:
        raise ValueError(
            "scene planning requires spoken text and positive audio duration"
        )
    spans = _split_spans(spoken_script)
    if not spans:
        raise ValueError("scene planning requires at least one spoken scene")

    boundaries = _subtitle_boundaries(
        spoken_script, spans, subtitle_items, audio_duration
    )
    timing_source = "subtitle" if boundaries is not None else "estimated"
    findings: list[ReviewFinding] = []
    if boundaries is None:
        boundaries = _estimated_boundaries(spoken_script, spans, audio_duration)
        findings.append(
            ReviewFinding(
                code="timing_estimated",
                severity="warning",
                reason="Subtitle text or timing could not be aligned to the narration; scene timing is estimated.",
            )
        )
    if custom_audio:
        findings.append(
            ReviewFinding(
                code="custom_audio_alignment_review",
                severity="warning",
                reason="Custom audio alignment requires a human check against the spoken words.",
            )
        )

    needs_review = bool(findings)
    scenes = [
        ScenePlan(
            scene_id=f"scene-{index:03d}",
            narration=spoken_script[start:end],
            narration_start=start,
            narration_end=end,
            start_seconds=boundaries[index - 1],
            end_seconds=boundaries[index],
            timing_source=timing_source,
            intent="narration",
            subtitle_text=spoken_script[start:end].strip(),
            review_status="needs_review" if needs_review else "pending",
        )
        for index, (start, end) in enumerate(spans, start=1)
    ]
    return ProductionPlan(
        task_id=task_id,
        narration_script=spoken_script,
        scenes=scenes,
        stages=[
            StageRecord(
                stage="scene_planning",
                status="needs_review" if needs_review else "complete",
                model_name="local",
                prompt_version="deterministic-v1",
            )
        ],
        review_findings=findings,
    )
