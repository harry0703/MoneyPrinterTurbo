# -*- coding: utf-8 -*-
import array
import math
import tempfile
import unittest
import wave
from pathlib import Path

from app.services.cartoon_animation import AnimationError, mouth_state
from app.services.cartoon_animation import lip_sync


def tone(samples: int, frequency: float = 220.0, rate: int = 8000, amplitude: int = 12000):
    return array.array(
        "h",
        (
            int(amplitude * math.sin(2 * math.pi * frequency * index / rate))
            for index in range(samples)
        ),
    )


class TestMouthStates(unittest.TestCase):
    def test_four_named_states(self):
        self.assertEqual(mouth_state(0.0), "closed")
        self.assertEqual(mouth_state(0.2), "slightly_open")
        self.assertEqual(mouth_state(0.5), "half_open")
        self.assertEqual(mouth_state(0.95), "open")

    def test_frame_amplitudes_track_loud_and_silent_windows(self):
        silence = array.array("h", [0] * 8000)
        loud = tone(8000)
        amplitudes = lip_sync.frame_amplitudes(silence + loud, fps=10, duration=2.0)
        self.assertEqual(len(amplitudes), 20)
        self.assertEqual(max(amplitudes[:10]), 0)
        self.assertGreater(min(amplitudes[10:]), 1000)

    def test_normalisation_uses_a_robust_peak(self):
        normalized = lip_sync.normalize_amplitudes([0, 1000, 2000, 3000, 100000])
        self.assertEqual(normalized[0], 0)
        self.assertLessEqual(max(normalized), 1.0)
        self.assertGreater(normalized[3], 0)

    def test_silence_produces_a_closed_mouth(self):
        states = lip_sync.states_from_amplitudes([0.0] * 12)
        self.assertEqual(set(states), {0.0})

    def test_min_hold_removes_single_frame_flicker(self):
        amplitudes = [0, 0, 0, 1, 0, 0, 0, 0]
        raw = lip_sync.states_from_amplitudes(
            amplitudes, min_hold=1, attack=1, release=1
        )
        stable = lip_sync.states_from_amplitudes(
            amplitudes, min_hold=3, attack=1, release=1
        )
        self.assertEqual(raw[3], 0.9)
        self.assertEqual(set(stable), {0.0})
        self.assertEqual(len(stable), len(raw))

    def test_attack_and_release_are_smoother_than_raw(self):
        amplitudes = [0, 1, 0, 1, 0, 1, 0, 1]
        smoothed = lip_sync.states_from_amplitudes(
            amplitudes, min_hold=1, attack=0.5, release=0.2
        )
        self.assertEqual(len(smoothed), len(amplitudes))
        self.assertEqual(smoothed[0], 0.0)
        self.assertLess(smoothed[1], 0.9)

    def test_invalid_parameters_are_rejected(self):
        with self.assertRaisesRegex(AnimationError, "min_hold"):
            lip_sync.states_from_amplitudes([0.1], min_hold=-1)
        with self.assertRaisesRegex(AnimationError, "attack"):
            lip_sync.states_from_amplitudes([0.1], attack=2)


class TestAudioAnalysis(unittest.TestCase):
    def _write_wav(self, path: Path, silence_seconds: float, tone_seconds: float) -> None:
        rate = 8000
        with wave.open(str(path), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(rate)
            payload = array.array("h", [0] * int(rate * silence_seconds))
            payload.extend(tone(int(rate * tone_seconds)))
            target.writeframes(payload.tobytes())

    def test_analyzes_a_real_audio_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary, "narration.wav")
            self._write_wav(source, 0.5, 1.0)
            track = lip_sync.analyze_audio(source, fps=10, duration=1.5)
        self.assertEqual(len(track), 15)
        self.assertEqual(set(track[:4]), {0.0})
        self.assertTrue(any(value > 0 for value in track[6:]))

    def test_missing_and_empty_audio_are_rejected(self):
        with self.assertRaisesRegex(AnimationError, "not found"):
            lip_sync.analyze_audio("nope.mp3", fps=10, duration=1.0)
        with tempfile.TemporaryDirectory() as temporary:
            empty = Path(temporary, "empty.wav")
            with wave.open(str(empty), "wb") as target:
                target.setnchannels(1)
                target.setsampwidth(2)
                target.setframerate(8000)
                target.writeframes(b"")
            with self.assertRaisesRegex(AnimationError, "no samples"):
                lip_sync.analyze_audio(empty, fps=10, duration=1.0)


if __name__ == "__main__":
    unittest.main()
