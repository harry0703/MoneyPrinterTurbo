"""Bounded-memory audio helpers for optional voice-first mixing."""

from __future__ import annotations

import re

import numpy as np
from moviepy import afx
from moviepy.tools import convert_to_seconds

from app.utils.subtitle_reader import file_to_subtitles


_TIMESTAMP = re.compile(r"([0-9]*:[0-9]*:[0-9]*,[0-9]*)")


def subtitle_intervals(subtitle_path: str | None) -> list[tuple[float, float]]:
    intervals = []
    for _index, timing, text in file_to_subtitles(subtitle_path):
        stamps = _TIMESTAMP.findall(timing)
        if len(stamps) != 2 or not text.strip():
            continue
        start, end = (float(convert_to_seconds(stamp)) for stamp in stamps)
        if 0 <= start < end:
            intervals.append((start, end))
    return merge_intervals(intervals)


def merge_intervals(
    intervals: list[tuple[float, float]], *, max_gap: float = 0.30
) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start - merged[-1][1] <= max_gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def duck_gain_at(
    times,
    intervals: list[tuple[float, float]],
    *,
    duck_gain: float = 0.25,
    attack_seconds: float = 0.15,
    release_seconds: float = 0.45,
):
    """Return a smooth gain array; timestamps remain the authoritative cue timing."""
    values = np.asarray(times, dtype=float)
    gains = np.ones_like(values, dtype=float)
    for start, end in intervals:
        attack_start = max(0.0, start - attack_seconds)
        if attack_seconds > 0:
            attack = (values >= attack_start) & (values < start)
            ramp = 1.0 - (values[attack] - attack_start) / attack_seconds
            gains[attack] = np.minimum(gains[attack], duck_gain + (1 - duck_gain) * ramp)
        active = (values >= start) & (values <= end)
        gains[active] = np.minimum(gains[active], duck_gain)
        if release_seconds > 0:
            release = (values > end) & (values < end + release_seconds)
            ramp = (values[release] - end) / release_seconds
            gains[release] = np.minimum(
                gains[release], duck_gain + (1 - duck_gain) * ramp
            )
    return gains


def duck_music_clip(
    clip,
    intervals: list[tuple[float, float]],
    *,
    duck_gain: float = 0.25,
    attack_seconds: float = 0.15,
    release_seconds: float = 0.45,
):
    if not intervals:
        return clip

    def transform(get_frame, times):
        frame = np.asarray(get_frame(times))
        gain = duck_gain_at(
            times,
            intervals,
            duck_gain=duck_gain,
            attack_seconds=attack_seconds,
            release_seconds=release_seconds,
        )
        if frame.ndim > gain.ndim:
            gain = gain[..., np.newaxis]
        return frame * gain

    return clip.transform(transform, keep_duration=True)


def normalize_voice_clip(clip, *, target_peak: float = 0.75, max_gain: float = 2.0):
    peak = float(clip.max_volume())
    if not np.isfinite(peak) or peak <= 1e-8:
        return clip, 1.0
    gain = min(max_gain, target_peak / peak)
    return clip.with_effects([afx.MultiplyVolume(gain)]), gain


def peak_guard_clip(clip, *, peak_limit: float = 0.95):
    """Apply bounded-memory global peak protection to a completed mix."""
    peak = float(clip.max_volume())
    if not np.isfinite(peak) or peak <= peak_limit or peak <= 1e-8:
        return clip, 1.0, peak
    gain = peak_limit / peak
    return clip.with_effects([afx.MultiplyVolume(gain)]), gain, peak
