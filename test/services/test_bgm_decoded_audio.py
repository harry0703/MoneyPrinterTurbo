import io
import subprocess
import sys
import wave
from unittest.mock import patch

import pytest

from app.services import bgm
from app.utils import utils
from test.services.fake_ffmpeg_process import FakeFfmpegProcess

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


def ffmpeg_process(stdout=b"", stderr=b"", returncode=0):
    return patch.object(
        bgm.subprocess,
        "Popen",
        return_value=FakeFfmpegProcess(stdout, stderr, returncode),
    )


def test_decode_error_is_rejected_even_when_ffmpeg_exits_zero(tmp_path):
    """FFmpeg 6.1 reports "Header missing" for a damaged MP3 but still exits 0
    under -xerror, so the message on stderr has to fail validation."""
    target = tmp_path / "damaged.mp3"
    target.write_bytes(b"not empty")
    with ffmpeg_process(
        FRAMECRC_HEADER + FRAMECRC_PACKET, b"[mp3float @ 0x1] Header missing\n"
    ):
        with pytest.raises(bgm.BgmUploadError, match="decodable audio stream"):
            bgm.validate_audio_file(str(target))


def test_audio_is_counted_from_decoded_packets_not_progress_time(tmp_path):
    """FFmpeg 6.1 reports out_time_us=0 for a clip shorter than about 0.13 s,
    so decoded packets, not progress time, show that audio was decoded."""
    target = tmp_path / "short.wav"
    target.write_bytes(b"not empty")
    with ffmpeg_process(
        FRAMECRC_HEADER + FRAMECRC_PACKET + b"out_time_us=0\nprogress=end\n"
    ):
        bgm.validate_audio_file(str(target))


def test_output_without_decoded_packets_is_rejected(tmp_path):
    target = tmp_path / "empty.wav"
    target.write_bytes(b"not empty")
    with ffmpeg_process(FRAMECRC_HEADER):
        with pytest.raises(bgm.BgmUploadError, match="nonempty decodable audio"):
            bgm.validate_audio_file(str(target))


class CountingLines:
    """Yields framecrc lines and records how many were read."""

    def __init__(self, lines):
        self._lines = lines
        self.read = 0

    def __iter__(self):
        for line in self._lines:
            self.read += 1
            yield line


def test_output_is_read_to_the_end_after_the_first_packet(tmp_path):
    """FFmpeg has to finish so an error late in the file still fails the upload."""
    target = tmp_path / "long.wav"
    target.write_bytes(b"not empty")
    lines = CountingLines([FRAMECRC_PACKET] * 50)
    process = FakeFfmpegProcess(stdout=lines, returncode=1)
    with patch.object(bgm.subprocess, "Popen", return_value=process):
        with pytest.raises(bgm.BgmUploadError, match="decodable audio stream"):
            bgm.validate_audio_file(str(target))
    assert lines.read == 50


def test_stderr_beyond_the_kept_head_is_drained_and_still_rejects(tmp_path):
    target = tmp_path / "noisy.mp3"
    target.write_bytes(b"not empty")
    noise = b"[mp3float @ 0x1] Header missing\n" * 100_000
    with ffmpeg_process(FRAMECRC_HEADER + FRAMECRC_PACKET, noise):
        with pytest.raises(bgm.BgmUploadError, match="decodable audio stream"):
            bgm.validate_audio_file(str(target))


def test_streamed_output_of_a_real_process_is_scanned_without_buffering():
    script = (
        "import sys\n"
        "sys.stdout.write('#format: frame checksums\\n')\n"
        "for _ in range(200_000):\n"
        "    sys.stdout.write('0, 0, 0, 1600, 3200, 0x00000000\\n')\n"
        "sys.stderr.write('warning\\n')\n"
    )
    returncode, saw_packet, stderr_head = bgm._decode_first_audio_stream(
        [sys.executable, "-c", script], 30
    )
    assert (returncode, saw_packet, stderr_head) == (0, True, b"warning\n")


def test_hung_process_is_killed_at_the_timeout():
    with pytest.raises(subprocess.TimeoutExpired):
        bgm._decode_first_audio_stream(
            [sys.executable, "-c", "import time; time.sleep(60)"], 1
        )


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
