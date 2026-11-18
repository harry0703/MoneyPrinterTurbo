import numpy as np
import pytest
from moviepy.audio.AudioClip import AudioArrayClip

from app.models.schema import VideoParams
from app.services import video

FPS = 8000


def _tone(seconds, level, channels=2):
    t = np.arange(int(seconds * FPS)) / FPS
    wave = level * np.sin(2 * np.pi * 220 * t)
    return np.stack([wave] * channels, axis=1)


def _narration():
    """2 s of speech, 2 s of pause, 2 s of speech."""
    return AudioArrayClip(
        np.concatenate([_tone(2, 0.5), _tone(2, 0.0), _tone(2, 0.5)]), fps=FPS
    )


def _gain_at(gain, seconds):
    return float(gain[int(seconds / video._DUCK_STEP_SECONDS)])


def test_bgm_duck_is_off_by_default():
    assert VideoParams(video_subject="x").bgm_duck is False


def test_gain_dips_under_speech_and_recovers_in_pauses():
    gain = video._narration_duck_gain(_narration())

    assert _gain_at(gain, 1.5) == pytest.approx(video._DUCK_SPEECH_GAIN, abs=0.05)
    assert _gain_at(gain, 3.8) > 0.95
    assert _gain_at(gain, 5.5) == pytest.approx(video._DUCK_SPEECH_GAIN, abs=0.05)


def test_gain_ignores_narration_loudness():
    loud = video._narration_duck_gain(_narration())
    quiet_clip = AudioArrayClip(
        np.concatenate([_tone(2, 0.05), _tone(2, 0.0), _tone(2, 0.05)]), fps=FPS
    )

    quiet = video._narration_duck_gain(quiet_clip)

    assert np.allclose(loud, quiet, atol=0.02)


def test_silent_narration_leaves_music_untouched():
    silent = AudioArrayClip(_tone(3, 0.0), fps=FPS)

    assert np.all(video._narration_duck_gain(silent) == 1.0)


def test_long_narration_keeps_one_gain_per_10_ms():
    # 24 kHz makes moviepy's chunks non-multiples of the 10 ms window.
    fps, seconds = 24000, 120
    t = np.arange(seconds * fps) / fps
    speech = (t.astype(int) % 2 == 0) * 0.5 * np.sin(2 * np.pi * 220 * t)
    clip = AudioArrayClip(np.stack([speech] * 2, axis=1), fps=fps)

    gain = video._narration_duck_gain(clip)

    assert len(gain) == seconds * 100
    # Speech starts at every even second: the music must be down by its end
    # and back up by the end of the following pause, even 110 s in.
    assert _gain_at(gain, 110.9) == pytest.approx(video._DUCK_SPEECH_GAIN, abs=0.05)
    assert _gain_at(gain, 111.9) > 0.95
    assert _gain_at(gain, 54.9) == pytest.approx(video._DUCK_SPEECH_GAIN, abs=0.05)


def test_opposite_phase_stereo_still_ducks():
    wave = _tone(2, 0.5, channels=1)[:, 0]
    pause = np.zeros(2 * FPS)
    left = np.concatenate([wave, pause])
    clip = AudioArrayClip(np.stack([left, -left], axis=1), fps=FPS)

    gain = video._narration_duck_gain(clip)

    assert _gain_at(gain, 1.5) == pytest.approx(video._DUCK_SPEECH_GAIN, abs=0.05)
    assert _gain_at(gain, 3.8) > 0.95


@pytest.mark.parametrize("channels", [1, 2])
def test_ducked_music_follows_the_envelope(channels):
    music = AudioArrayClip(_tone(8, 0.4, channels), fps=FPS)

    ducked = video._duck_under_narration(music, _narration())

    def peak(start, end):
        # get_frame is what the audio writer calls, with an array of times.
        times = np.arange(int(start * FPS), int(end * FPS)) / FPS
        return float(np.abs(ducked.get_frame(times)).max())

    assert peak(1.0, 1.9) == pytest.approx(0.4 * video._DUCK_SPEECH_GAIN, rel=0.2)
    assert peak(3.8, 3.95) == pytest.approx(0.4, rel=0.1)
    # The narration ends at 6 s; the longer music is back at full level.
    assert peak(7.0, 7.9) == pytest.approx(0.4, rel=0.05)


def test_single_sample_frames_are_scaled_too():
    music = AudioArrayClip(_tone(8, 0.4), fps=FPS)
    ducked = video._duck_under_narration(music, _narration())

    frame = ducked.get_frame(0.5)

    assert frame.shape == (2,)
    assert abs(frame).max() <= 0.4 * 0.5
