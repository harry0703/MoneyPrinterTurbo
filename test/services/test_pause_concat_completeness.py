from pathlib import Path
import wave

import pytest

from app.services import voice


def write_pcm(target, frames=2400):
    with wave.open(str(target), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(24000)
        writer.writeframes(b"\x01\x00" * frames)


@pytest.mark.parametrize("bad_chunk", ["missing", "empty", "invalid", "header_only", "truncated"])
@pytest.mark.parametrize("existing", [False, True])
def test_concat_requires_every_audio_chunk(tmp_path, bad_chunk, existing):
    good = tmp_path / "good.wav"
    bad = tmp_path / "bad.wav"
    output = tmp_path / "narration.wav"
    write_pcm(good)
    if bad_chunk == "empty":
        bad.write_bytes(b"")
    elif bad_chunk == "invalid":
        bad.write_bytes(b"not audio")
    elif bad_chunk == "header_only":
        write_pcm(bad, frames=0)
    elif bad_chunk == "truncated":
        write_pcm(bad)
        bad.write_bytes(bad.read_bytes()[:-2])
    if existing:
        output.write_bytes(b"previous complete narration")
    assert voice._concat_audio_files([str(good), str(bad)], str(output)) is False
    assert output.read_bytes() == b"previous complete narration" if existing else not output.exists()


def test_pause_tts_propagates_lost_chunk_without_replaying_synthesis(tmp_path, monkeypatch):
    calls = []

    def synthesize(**kwargs):
        calls.append(kwargs["text"])
        write_pcm(kwargs["voice_file"])
        maker = voice.ensure_legacy_submaker_fields(voice.SubMaker())
        return voice.populate_legacy_submaker_with_full_text(maker, kwargs["text"], 0.1)

    original_concat = voice._concat_audio_files

    def lose_last_chunk(files, output):
        Path(files[-1]).unlink()
        return original_concat(files, output)

    monkeypatch.setattr(voice, "_single_tts", synthesize)
    monkeypatch.setattr(voice, "_concat_audio_files", lose_last_chunk)
    output = tmp_path / "narration.mp3"
    output.write_bytes(b"previous complete narration")
    assert voice.tts("First [pause: 0.1s] Last", "en-US-JennyNeural", 1.0, str(output)) is None
    assert calls == ["First", "Last"]
    assert output.read_bytes() == b"previous complete narration"
