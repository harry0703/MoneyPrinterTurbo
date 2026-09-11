"""ModelBest VoxCPM provider tests without external credentials or network access."""

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.config import config
from app.services import voice


class _FakeSegment:
    def __init__(self, duration_ms=1600):
        self.duration_ms = duration_ms

    def __len__(self):
        return self.duration_ms

    def export(self, target, format):
        assert format == "mp3"
        Path(target).write_bytes(b"encoded-mp3")


def _sse_event(event_type, **payload):
    return f"data: {json.dumps({'type': event_type, **payload})}"


def _sse_lines(*events):
    lines = []
    for event in events:
        lines.extend([event, ""])
    return lines


@pytest.fixture
def voxcpm_config(monkeypatch):
    settings = {
        "api_key": "test-key",
        "base_url": "https://api.modelbest.cn/v1/",
        "model_id": "voxcpm-tts-test",
        "voice_id": "default",
    }
    monkeypatch.setattr(config, "voxcpm", settings)
    return settings


def test_voice_helpers_and_dispatch():
    assert voice.get_voxcpm_voices("default") == ["voxcpm:default"]
    assert voice.is_voxcpm_voice("voxcpm:default")
    assert not voice.is_voxcpm_voice("fish_audio:default")
    assert not voice.is_azure_v1_voice("voxcpm:default")

    sentinel = object()
    with pytest.MonkeyPatch.context() as monkeypatch:
        implementation = Mock(return_value=sentinel)
        monkeypatch.setattr(voice, "voxcpm_tts", implementation)
        result = voice.tts("hello", "voxcpm:default", 1.2, "out.mp3", 0.8)

    assert result is sentinel
    implementation.assert_called_once_with("hello", "default", "out.mp3", 1.2, 0.8)


def test_voxcpm_tts_assembles_sse_wav_and_converts_to_mp3(
    monkeypatch, tmp_path, voxcpm_config
):
    audio_chunks = [b"RIFF", b"WAVE"]
    response = SimpleNamespace(
        status_code=200,
        text="",
        iter_lines=lambda decode_unicode: _sse_lines(
            _sse_event("speech.audio.delta", audio=base64.b64encode(audio_chunks[0]).decode()),
            _sse_event("speech.audio.delta", audio=base64.b64encode(audio_chunks[1]).decode()),
            _sse_event("speech.audio.done", usage={"total_tokens": 1}),
        ),
        close=Mock(),
    )
    post = Mock(return_value=response)
    monkeypatch.setattr(voice.requests, "post", post)

    captured = {}

    def from_file(source, format):
        captured["source"] = source.read()
        captured["format"] = format
        return _FakeSegment()

    monkeypatch.setattr("pydub.AudioSegment.from_file", from_file)
    monkeypatch.setattr(voice, "AudioFileClip", Mock(return_value=SimpleNamespace(
        duration=1.6, close=lambda: None
    )))

    output = tmp_path / "voice.mp3"
    maker = voice.voxcpm_tts("Hello VoxCPM.", "default", str(output))

    assert maker is not None
    assert output.read_bytes() == b"encoded-mp3"
    assert captured == {"source": b"".join(audio_chunks), "format": "wav"}
    assert getattr(maker, "subs", []) == ["Hello VoxCPM"]
    assert post.call_args.kwargs["json"] == {
        "model": "voxcpm-tts-test",
        "input": "Hello VoxCPM.",
        "voice": "default",
        "response_format": "wav",
        "stream": True,
    }
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert post.call_args.kwargs["headers"]["Accept"] == "text/event-stream"
    assert post.call_args.kwargs["stream"] is True
    assert post.call_args.kwargs["timeout"] == (10, 120)
    response.close.assert_called_once()


@pytest.mark.parametrize(
    "events",
    [
        _sse_lines(_sse_event("speech.audio.done")),
        _sse_lines(_sse_event("speech.audio.delta", audio="not base64")),
        _sse_lines(_sse_event("speech.audio.delta", audio=base64.b64encode(b"audio").decode())),
        ["data: {invalid json}", ""],
    ],
)
def test_voxcpm_tts_failure_never_overwrites_existing_audio(
    monkeypatch, tmp_path, voxcpm_config, events
):
    response = SimpleNamespace(
        status_code=200,
        text="",
        iter_lines=lambda decode_unicode: events,
        close=lambda: None,
    )
    post = Mock(return_value=response)
    monkeypatch.setattr(voice.requests, "post", post)
    output = tmp_path / "existing.mp3"
    output.write_bytes(b"previous-audio")

    assert voice.voxcpm_tts("Hello", "default", str(output)) is None
    assert output.read_bytes() == b"previous-audio"
    assert post.call_count == 3


def test_voxcpm_requires_key_and_model_without_making_requests(monkeypatch, tmp_path):
    post = Mock()
    monkeypatch.setattr(voice.requests, "post", post)
    monkeypatch.setattr(config, "voxcpm", {"api_key": "", "model_id": "model"})
    assert voice.voxcpm_tts("Hello", "default", str(tmp_path / "voice.mp3")) is None

    monkeypatch.setattr(config, "voxcpm", {"api_key": "key", "model_id": ""})
    assert voice.voxcpm_tts("Hello", "default", str(tmp_path / "voice.mp3")) is None
    post.assert_not_called()


def test_voxcpm_http_error_is_retried_and_preserves_output(
    monkeypatch, tmp_path, voxcpm_config
):
    response = SimpleNamespace(
        status_code=503,
        text="temporarily unavailable",
        close=lambda: None,
    )
    post = Mock(return_value=response)
    monkeypatch.setattr(voice.requests, "post", post)
    output = tmp_path / "existing.mp3"
    output.write_bytes(b"previous-audio")

    assert voice.voxcpm_tts("Hello", "default", str(output)) is None
    assert output.read_bytes() == b"previous-audio"
    assert post.call_count == 3
