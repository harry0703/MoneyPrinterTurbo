"""Native provider-payload decoding; no paid synthesis requests."""
import json
import subprocess

import pytest

from app.services.voice import _write_validated_minimax_audio


@pytest.mark.parametrize("source_format,output_format,codec", [
    ("wav", "mp3", "mp3"),
    ("flac", "mp3", "mp3"),
    ("wav", "flac", "flac"),
])
def test_minimax_audio_matches_output_container(tmp_path, source_format, output_format, codec):
    source = tmp_path / ("provider." + source_format)
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=0.3", str(source),
    ], check=True)
    output = tmp_path / ("audio." + output_format)
    duration = _write_validated_minimax_audio(source.read_bytes(), str(output))
    assert 0.25 < duration < 0.5
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output),
    ]))
    assert probe["streams"][0]["codec_name"] == codec


def test_minimax_matching_wav_keeps_original_bytes(tmp_path):
    source = tmp_path / "provider.wav"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=0.3", str(source),
    ], check=True)
    output = tmp_path / "audio.wav"
    _write_validated_minimax_audio(source.read_bytes(), str(output))
    assert output.read_bytes() == source.read_bytes()
