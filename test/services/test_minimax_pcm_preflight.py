"""Do not submit raw audio formats the local validation path cannot decode."""

import io
import wave
from unittest.mock import Mock, patch

import numpy as np
import pytest

from app.services import voice


def _pcm():
    samples = np.sin(np.arange(6400) * (2 * np.pi * 440 / 32000)) * 10000
    return samples.astype("<i2").tobytes()


def test_pcm_setting_fails_before_paid_submission(tmp_path):
    output = tmp_path / "speech.mp3"
    output.write_bytes(b"previous narration")
    response = Mock(status_code=200)
    response.json.return_value = {
        "base_resp": {"status_code": 0},
        "data": {"status": 2, "audio": _pcm().hex()},
    }
    with patch.dict(voice.config.minimax_tts, {"api_key": "fixture", "audio_format": "pcm"}), \
            patch.object(voice.requests, "post", return_value=response) as post:
        assert voice.minimax_tts("Hello.", "voice-id", 1, str(output)) is None
    post.assert_not_called()
    assert output.read_bytes() == b"previous narration"


def test_native_container_validator_rejects_headerless_pcm(tmp_path):
    output = tmp_path / "speech.mp3"
    with pytest.raises(ValueError, match="fully decoded"):
        voice._write_validated_minimax_audio(_pcm(), str(output))
    assert not output.exists()


def test_native_container_audio_still_publishes(tmp_path):
    wav = io.BytesIO()
    with wave.open(wav, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(32000)
        audio.writeframes(_pcm())
    output = tmp_path / "speech.wav"
    duration = voice._write_validated_minimax_audio(wav.getvalue(), str(output))
    assert 0.19 <= duration <= 0.21
    assert output.read_bytes() == wav.getvalue()
