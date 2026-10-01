import io
import wave
from unittest.mock import patch

import pytest

from app.services import bgm


def wav_bytes(frames):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * frames)
    return output.getvalue()


def test_header_only_wav_rejected_by_real_ffmpeg(tmp_path):
    target = tmp_path / "empty.wav"
    target.write_bytes(wav_bytes(0))
    assert target.stat().st_size > 0
    with pytest.raises(bgm.BgmUploadError, match="audio"):
        bgm.validate_audio_file(str(target))


def test_empty_upload_rejected_and_staging_removed(tmp_path):
    with patch.object(bgm, "uploaded_bgm_dir", return_value=str(tmp_path)):
        with pytest.raises(bgm.BgmUploadError, match="audio"):
            bgm.save_bgm_upload("empty.wav", io.BytesIO(wav_bytes(0)))
    assert list(tmp_path.iterdir()) == []


def test_silence_with_positive_frames_remains_valid(tmp_path):
    target = tmp_path / "valid-silence.wav"
    target.write_bytes(wav_bytes(1600))
    bgm.validate_audio_file(str(target))
