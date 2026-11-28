"""Lightweight, CPU-only lip sync from narration amplitude.

This is an amplitude envelope, not phoneme recognition: it measures how loud
the narration is in each video frame and maps that to four mouth states. The
interface is deliberately small so a phoneme-timed backend can replace
``analyze_audio`` later without touching the renderer.
"""

from __future__ import annotations

import array
import math
import subprocess
from pathlib import Path

from app.services.cartoon_animation.expressions import mouth_state
from app.services.cartoon_animation.models import AnimationError

# 8 kHz mono is plenty for an envelope and keeps a five second clip at 40 kB.
SAMPLE_RATE = 8000

# Representative openness for each of the four named mouth states.
STATE_OPENNESS = {
    "closed": 0.0,
    "slightly_open": 0.2,
    "half_open": 0.5,
    "open": 0.9,
}


def decode_samples(path: str | Path, *, sample_rate: int = SAMPLE_RATE) -> array.array:
    """Decode any FFmpeg-readable audio file to signed 16-bit mono samples."""
    from app.utils import utils

    source = Path(path)
    if not source.is_file():
        raise AnimationError(f"narration audio not found: {source}")
    command = [
        utils.get_ffmpeg_binary(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vn",
        "-f",
        "s16le",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=False, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AnimationError(f"cannot decode narration audio: {source}") from exc
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise AnimationError(
            f"cannot decode narration audio: {source}: {message or result.returncode}"
        )
    samples = array.array("h")
    payload = result.stdout
    if len(payload) % 2:
        payload = payload[:-1]
    samples.frombytes(payload)
    if not samples:
        raise AnimationError(f"narration audio has no samples: {source}")
    return samples


def frame_amplitudes(
    samples: array.array,
    fps: int,
    duration: float,
    *,
    sample_rate: int = SAMPLE_RATE,
) -> list[float]:
    """Root-mean-square amplitude per video frame."""
    if fps <= 0 or duration <= 0:
        raise AnimationError("lip sync needs a positive fps and duration")
    frame_count = max(1, int(round(duration * fps)))
    window = max(1, int(round(sample_rate / fps)))
    total = len(samples)
    amplitudes: list[float] = []
    for index in range(frame_count):
        start = min(total, index * window)
        end = min(total, start + window)
        if end <= start:
            amplitudes.append(0.0)
            continue
        chunk = samples[start:end]
        energy = sum(value * value for value in chunk) / len(chunk)
        amplitudes.append(math.sqrt(energy))
    return amplitudes


def normalize_amplitudes(amplitudes: list[float]) -> list[float]:
    """Scale RMS values to 0..1 using a robust peak, not the absolute max."""
    if not amplitudes:
        return []
    ordered = sorted(amplitudes)
    peak = ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))]
    if peak <= 0.5:
        return [0.0 for _ in amplitudes]
    return [min(1.0, value / peak) for value in amplitudes]


def states_from_amplitudes(
    amplitudes: list[float],
    *,
    min_hold: int = 2,
    attack: float = 0.65,
    release: float = 0.35,
) -> list[float]:
    """Turn RMS values into stable mouth openness values.

    A fast attack and slower release smooth the envelope, then runs shorter
    than ``min_hold`` frames are merged so the mouth never flickers.
    """
    if min_hold < 0:
        raise AnimationError("lip sync min_hold must not be negative")
    if not 0.0 <= attack <= 1.0 or not 0.0 <= release <= 1.0:
        raise AnimationError("lip sync attack and release must be between 0 and 1")
    if not amplitudes:
        return []
    normalized = normalize_amplitudes(amplitudes)
    smoothed: list[float] = []
    previous = 0.0
    for value in normalized:
        factor = attack if value > previous else release
        previous = previous + (value - previous) * factor
        smoothed.append(previous)

    quantized = [STATE_OPENNESS[mouth_state(value)] for value in smoothed]
    return _enforce_min_hold(quantized, min_hold)


def _enforce_min_hold(values: list[float], min_hold: int) -> list[float]:
    if min_hold <= 1 or len(values) < 2:
        return values
    result = list(values)
    index = 0
    while index < len(result):
        end = index + 1
        while end < len(result) and result[end] == result[index]:
            end += 1
        if end - index < min_hold:
            neighbour = result[end] if end < len(result) else None
            replacement = neighbour
            if replacement is None:
                for back in range(index - 1, -1, -1):
                    if result[back] != result[index]:
                        replacement = result[back]
                        break
            if replacement is not None:
                for position in range(index, end):
                    result[position] = replacement
        index = max(end, index + 1)
    return result


def analyze_audio(
    path: str | Path,
    fps: int,
    duration: float,
    *,
    min_hold: int = 2,
    sample_rate: int = SAMPLE_RATE,
) -> tuple[float, ...]:
    """Return one mouth openness value per frame for a narration file."""
    samples = decode_samples(path, sample_rate=sample_rate)
    amplitudes = frame_amplitudes(samples, fps, duration, sample_rate=sample_rate)
    return tuple(states_from_amplitudes(amplitudes, min_hold=min_hold))
