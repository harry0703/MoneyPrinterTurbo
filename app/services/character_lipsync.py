from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_right
from pathlib import Path

import numpy as np
from loguru import logger
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError


# Keep the lipsync analyzer lightweight in memory/time during web renders.
MAX_LIPSYNC_AUDIO_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class LipSyncFrame:
    start: float
    end: float
    openness: float


class CharacterLipSyncService:
    # Visual lipsync usually needs a slight lead to feel synchronized to human perception.
    VISUAL_SYNC_LEAD_SECONDS = 0.06

    def analyze(
        self,
        audio_path: str | None,
        duration: float,
        window_ms: int = 120,
    ) -> list[LipSyncFrame]:
        if not audio_path or not Path(audio_path).exists():
            return self._neutral_timeline(duration)
        if Path(audio_path).stat().st_size > MAX_LIPSYNC_AUDIO_BYTES:
            logger.warning(f"audio too large for lipsync analysis, disabling lipsync: {audio_path}")
            return self._neutral_timeline(duration)

        try:
            audio = AudioSegment.from_file(audio_path).set_channels(1)
        except (CouldntDecodeError, OSError, IOError, ValueError) as exc:
            logger.warning(f"failed to load audio for lipsync, disabling lipsync: {exc}")
            return self._neutral_timeline(duration)
        samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
        if samples.size == 0:
            return self._neutral_timeline(duration)

        max_amplitude = float(1 << max(1, (audio.sample_width * 8) - 1))
        normalized_samples = samples / max(1.0, max_amplitude)
        window_samples = max(1, int(audio.frame_rate * (window_ms / 1000)))
        rms_values: list[float] = []

        for start_index in range(0, normalized_samples.size, window_samples):
            chunk = normalized_samples[start_index : start_index + window_samples]
            if chunk.size == 0:
                continue
            rms_values.append(float(np.sqrt(np.mean(np.square(chunk)))))

        if not rms_values:
            return self._neutral_timeline(duration)

        levels = np.array(rms_values, dtype=np.float32)
        reference_level = float(np.percentile(levels, 95)) or float(np.max(levels)) or 1.0
        levels = np.clip(levels / max(reference_level, 1e-6), 0.0, 1.0)
        if levels.size >= 3:
            levels = np.convolve(levels, np.array([0.2, 0.6, 0.2], dtype=np.float32), mode="same")
        # Reduce ambient-noise influence and expand speech dynamics so the
        # mouth animation is visible in real narrations.
        noise_floor = float(np.percentile(levels, 25))
        if noise_floor < 0.98:
            levels = np.clip((levels - noise_floor) / max(1e-6, 1.0 - noise_floor), 0.0, 1.0)
        levels = np.power(levels, 0.75)
        levels = np.clip(levels * 1.15, 0.0, 1.0)
        levels = np.clip(levels, 0.0, 1.0)
        levels = self._smooth_envelope(levels)
        levels = self._enhance_visual_dynamics(levels)

        timeline: list[LipSyncFrame] = []
        window_seconds = window_ms / 1000
        resolved_duration = max(0.0, float(duration or (len(levels) * window_seconds)))
        for index, level in enumerate(levels):
            start_time = index * window_seconds
            if start_time >= resolved_duration:
                break
            end_time = min(resolved_duration, start_time + window_seconds)
            timeline.append(LipSyncFrame(start=start_time, end=end_time, openness=float(level)))

        return timeline or self._neutral_timeline(duration)

    def openness_at(self, timeline: list[LipSyncFrame], timestamp: float) -> float:
        if not timeline:
            return 0.0
        timestamp = max(0.0, timestamp + self.VISUAL_SYNC_LEAD_SECONDS)
        if timestamp <= timeline[0].start:
            return timeline[0].openness
        if timestamp >= timeline[-1].end:
            return timeline[-1].openness

        starts = [frame.start for frame in timeline]
        current_index = max(0, min(len(timeline) - 1, bisect_right(starts, timestamp) - 1))
        current_frame = timeline[current_index]
        if current_index == 0:
            previous_openness = current_frame.openness
        else:
            previous_openness = timeline[current_index - 1].openness

        span = max(1e-6, current_frame.end - current_frame.start)
        t = float(np.clip((timestamp - current_frame.start) / span, 0.0, 1.0))
        return (previous_openness * (1.0 - t)) + (current_frame.openness * t)

    def _neutral_timeline(self, duration: float) -> list[LipSyncFrame]:
        resolved_duration = max(0.0, float(duration or 0.0))
        return [LipSyncFrame(start=0.0, end=resolved_duration, openness=0.0)]

    def _smooth_envelope(self, levels: np.ndarray) -> np.ndarray:
        if levels.size <= 1:
            return levels
        smoothed = np.zeros_like(levels)
        smoothed[0] = levels[0]
        attack = 0.72
        release = 0.32
        for index in range(1, levels.size):
            previous = smoothed[index - 1]
            target = levels[index]
            ratio = attack if target > previous else release
            smoothed[index] = previous + ((target - previous) * ratio)
        return np.clip(smoothed, 0.0, 1.0)

    def _enhance_visual_dynamics(self, levels: np.ndarray) -> np.ndarray:
        if levels.size == 0:
            return levels
        # Suppress micro-motion during near-silence and expand speech contrast.
        gate = 0.08
        remapped = np.clip((levels - gate) / max(1e-6, 1.0 - gate), 0.0, 1.0)
        remapped = np.power(remapped, 0.62)
        remapped = np.clip(remapped * 1.22, 0.0, 1.0)
        return remapped