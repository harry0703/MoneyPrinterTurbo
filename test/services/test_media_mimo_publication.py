import base64
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import wave

from pydub import AudioSegment
import pytest

from app.services import voice


def mock_provider(monkeypatch):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x01\x00" * 1600)
    completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        audio={"data": base64.b64encode(buffer.getvalue()).decode("ascii")}
    ))])
    client = MagicMock()
    client.__enter__.return_value = client
    client.chat.completions.create.return_value = completion
    monkeypatch.setattr(voice, "OpenAI", lambda **kwargs: client)
    monkeypatch.setitem(voice.config.app, "mimo_api_key", "test-local-key")
    return client


@pytest.mark.parametrize("previous", [None, b"previous complete narration"])
def test_mimo_export_failure_preserves_destination(tmp_path, monkeypatch, previous):
    client = mock_provider(monkeypatch)
    output = tmp_path / "voice.mp3"
    if previous is not None:
        output.write_bytes(previous)

    def failed_export(self, filename, **kwargs):
        Path(filename).write_bytes(b"partial mp3")
        raise OSError("encoder failed")

    monkeypatch.setattr(AudioSegment, "export", failed_export)
    assert voice.mimo_tts("Hello world.", "mimo_default", 1.0, str(output)) is None
    if previous is None:
        assert not output.exists()
    else:
        assert output.read_bytes() == previous
    assert sorted(p.name for p in tmp_path.iterdir()) == ([output.name] if previous is not None else [])
    client.chat.completions.create.assert_called_once()


def test_mimo_success_closes_real_export_before_publication(tmp_path, monkeypatch):
    client = mock_provider(monkeypatch)
    output = tmp_path / "voice.mp3"
    handles = []
    original = AudioSegment.export

    def export(self, *args, **kwargs):
        handle = original(self, *args, **kwargs)
        handles.append(handle)
        return handle

    monkeypatch.setattr(AudioSegment, "export", export)
    maker = voice.mimo_tts("Hello world.", "mimo_default", 1.0, str(output))
    assert maker is not None
    assert len(handles) == 1 and handles[0].closed
    assert voice.get_audio_duration(str(output)) > 0
    assert voice.get_audio_duration(maker) == pytest.approx(0.2)
    assert list(tmp_path.iterdir()) == [output]
    client.chat.completions.create.assert_called_once()


def test_mimo_cleanup_failure_keeps_failed_publication_contract(tmp_path, monkeypatch):
    client = mock_provider(monkeypatch)
    output = tmp_path / "voice.mp3"
    output.write_bytes(b"previous complete narration")
    successes = []

    def cannot_publish(*args):
        raise OSError("destination unavailable")

    def cannot_cleanup(*args):
        raise PermissionError("temporary audio is busy")

    monkeypatch.setattr(voice.os, "replace", cannot_publish)
    monkeypatch.setattr(voice.os, "remove", cannot_cleanup)
    monkeypatch.setattr(voice.logger, "success", successes.append)
    assert voice.mimo_tts("Hello world.", "mimo_default", 1.0, str(output)) is None
    assert output.read_bytes() == b"previous complete narration"
    assert successes == []
    staged = [path for path in tmp_path.iterdir() if path != output]
    assert len(staged) == 1 and staged[0].name.startswith(".mimo-tts-")
    client.chat.completions.create.assert_called_once()
