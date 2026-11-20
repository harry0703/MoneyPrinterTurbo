import io
import subprocess
import wave
from unittest.mock import patch

import pytest

from app.services import bgm
from app.utils import utils

FRAMECRC_HEADER = b"#format: frame checksums\n#version: 2\n"
FRAMECRC_PACKET = b"0,          0,          0,     1600,     3200, 0x00000000\n"


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


def ffmpeg_result(stdout=b"", stderr=b"", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def test_decode_error_is_rejected_even_when_ffmpeg_exits_zero(tmp_path):
    """FFmpeg 6.1 reports "Header missing" for a damaged MP3 but still exits 0
    under -xerror, so the message on stderr has to fail validation."""
    target = tmp_path / "damaged.mp3"
    target.write_bytes(b"not empty")
    outcome = ffmpeg_result(
        FRAMECRC_HEADER + FRAMECRC_PACKET, b"[mp3float @ 0x1] Header missing\n"
    )
    with patch.object(bgm.subprocess, "run", return_value=outcome):
        with pytest.raises(bgm.BgmUploadError, match="decodable audio stream"):
            bgm.validate_audio_file(str(target))


def test_audio_is_counted_from_decoded_packets_not_progress_time(tmp_path):
    """FFmpeg 6.1 reports out_time_us=0 for a clip shorter than about 0.13 s,
    so decoded packets, not progress time, show that audio was decoded."""
    target = tmp_path / "short.wav"
    target.write_bytes(b"not empty")
    outcome = ffmpeg_result(
        FRAMECRC_HEADER + FRAMECRC_PACKET + b"out_time_us=0\nprogress=end\n"
    )
    with patch.object(bgm.subprocess, "run", return_value=outcome):
        bgm.validate_audio_file(str(target))


def test_output_without_decoded_packets_is_rejected(tmp_path):
    target = tmp_path / "empty.wav"
    target.write_bytes(b"not empty")
    with patch.object(
        bgm.subprocess, "run", return_value=ffmpeg_result(FRAMECRC_HEADER)
    ):
        with pytest.raises(bgm.BgmUploadError, match="nonempty decodable audio"):
            bgm.validate_audio_file(str(target))


def test_damaged_mp3_is_rejected_by_real_ffmpeg(tmp_path):
    tone = subprocess.run(
        [
            utils.get_ffmpeg_binary(),
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-f",
            "mp3",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    fifth = len(tone) // 5
    target = tmp_path / "damaged.mp3"
    target.write_bytes(tone[: 2 * fifth] + bytes(fifth) + tone[3 * fifth :])
    with pytest.raises(bgm.BgmUploadError, match="decodable audio stream"):
        bgm.validate_audio_file(str(target))
