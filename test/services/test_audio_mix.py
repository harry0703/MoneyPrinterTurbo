import unittest

import numpy as np
from moviepy import AudioClip

from app.services import audio_mix


class TestAudioMix(unittest.TestCase):
    def test_duck_envelope_has_smooth_attack_hold_and_release(self):
        times = np.array([0.0, 0.35, 0.5, 0.75, 1.0, 1.225, 1.5])
        gains = audio_mix.duck_gain_at(
            times, [(0.5, 1.0)], duck_gain=0.2,
            attack_seconds=0.2, release_seconds=0.4,
        )
        np.testing.assert_allclose(gains, [1.0, 0.8, 0.2, 0.2, 0.2, 0.65, 1.0])

    def test_music_clip_gain_changes_without_changing_duration(self):
        source = AudioClip(
            lambda t: (
                np.ones((len(t), 1), dtype=float)
                if np.ndim(t)
                else np.ones(1, dtype=float)
            ), duration=2, fps=100
        )
        ducked = audio_mix.duck_music_clip(
            source, [(0.5, 1.0)], duck_gain=0.25,
            attack_seconds=0.1, release_seconds=0.4,
        )
        self.assertEqual(ducked.duration, source.duration)
        self.assertAlmostEqual(float(ducked.get_frame(0.2)[0]), 1.0)
        self.assertAlmostEqual(float(ducked.get_frame(0.75)[0]), 0.25)
        self.assertAlmostEqual(float(ducked.get_frame(1.2)[0]), 0.625)
        source.close()
        ducked.close()

    def test_voice_normalization_is_bounded_and_limiter_prevents_over_peak(self):
        quiet = AudioClip(
            lambda t: np.full((len(t), 1), 0.1) if np.ndim(t) else np.array([0.1]),
            duration=1, fps=100,
        )
        normalized, gain = audio_mix.normalize_voice_clip(quiet, target_peak=0.75)
        self.assertEqual(gain, 2.0)  # bounded amplification, not a 7.5x boost
        self.assertAlmostEqual(float(normalized.get_frame(0.5)[0]), 0.2)
        hot = AudioClip(
            lambda t: np.full((len(t), 1), 1.5) if np.ndim(t) else np.array([1.5]),
            duration=1, fps=100,
        )
        guarded, guard_gain, peak = audio_mix.peak_guard_clip(hot, peak_limit=0.95)
        self.assertAlmostEqual(peak, 1.5)
        self.assertAlmostEqual(float(guarded.get_frame(0.5)[0]), 0.95)
        self.assertLess(guard_gain, 1.0)
        for clip in (quiet, normalized, hot, guarded):
            clip.close()


if __name__ == "__main__":
    unittest.main()
