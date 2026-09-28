"""ModelBest VoxCPM provider tests without external credentials or network access."""

import base64
import io
import json
import subprocess
import wave
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


def _wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 160)
    return buffer.getvalue()


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


def test_voxcpm_tts_sends_identity_and_delivery_references_as_data_uris(
    monkeypatch, tmp_path, voxcpm_config
):
    response = SimpleNamespace(
        status_code=400,
        text="invalid request",
        close=lambda: None,
    )
    post = Mock(return_value=response)
    monkeypatch.setattr(voice.requests, "post", post)
    reference_audio = _wav_bytes()
    prompt_audio = _wav_bytes()
    prompt_text = "准确的演绎示范逐字稿。"

    assert (
        voice.voxcpm_tts(
            "Hello",
            "default",
            str(tmp_path / "voice.mp3"),
            reference_audio=reference_audio,
            prompt_audio=prompt_audio,
            prompt_text=prompt_text,
        )
        is None
    )
    assert post.call_args.kwargs["json"]["ref_audio"] == (
        "data:audio/wav;base64," + base64.b64encode(reference_audio).decode("ascii")
    )
    assert post.call_args.kwargs["json"]["prompt_audio"] == (
        "data:audio/wav;base64," + base64.b64encode(prompt_audio).decode("ascii")
    )
    assert post.call_args.kwargs["json"]["prompt_text"] == prompt_text


@pytest.mark.parametrize(
    ("prompt_audio", "prompt_text"),
    [(_wav_bytes(), ""), (None, "演绎示范")],
)
def test_voxcpm_tts_requires_prompt_audio_and_text_together(
    monkeypatch,
    tmp_path,
    voxcpm_config,
    prompt_audio,
    prompt_text,
):
    post = Mock()
    monkeypatch.setattr(voice.requests, "post", post)

    assert (
        voice.voxcpm_tts(
            "Hello",
            "default",
            str(tmp_path / "voice.mp3"),
            reference_audio=_wav_bytes(),
            prompt_audio=prompt_audio,
            prompt_text=prompt_text,
        )
        is None
    )
    post.assert_not_called()


def test_voxcpm_tts_rejects_invalid_reference_audio_without_request(
    monkeypatch, tmp_path, voxcpm_config
):
    post = Mock()
    monkeypatch.setattr(voice.requests, "post", post)

    assert (
        voice.voxcpm_tts(
            "Hello",
            "default",
            str(tmp_path / "voice.mp3"),
            reference_audio=b"not-a-wav",
        )
        is None
    )
    post.assert_not_called()


def test_prepare_voxcpm_reference_audio_bounds_conversion_and_cleans_temps(monkeypatch):
    source_audio = b"uploaded-reference"
    temporary_paths = []

    def convert(command, **_kwargs):
        input_path = Path(command[command.index("-i") + 1])
        output_path = Path(command[-1])
        temporary_paths.extend([input_path, output_path])
        assert input_path.read_bytes() == source_audio
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b"\x00\x00" * 160)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(voice.subprocess, "run", convert)

    normalized = voice.prepare_voxcpm_reference_audio(source_audio, ".mp3")

    assert normalized == _wav_bytes()
    assert all(not path.exists() for path in temporary_paths)


def test_prepare_voxcpm_reference_audio_rejects_oversized_upload(monkeypatch):
    monkeypatch.setattr(voice, "VOXCPM_REFERENCE_AUDIO_MAX_UPLOAD_BYTES", 2)

    with pytest.raises(ValueError, match="exceeds"):
        voice.prepare_voxcpm_reference_audio(b"123", ".wav")


def test_prepare_voxcpm_reference_audio_reports_conversion_timeout(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("ffmpeg", 15)

    monkeypatch.setattr(voice.subprocess, "run", timeout)

    with pytest.raises(ValueError, match="timed out"):
        voice.prepare_voxcpm_reference_audio(b"audio", ".wav")


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
    assert post.call_count == 1


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
    sleep = Mock()
    monkeypatch.setattr(voice.time, "sleep", sleep)
    output = tmp_path / "existing.mp3"
    output.write_bytes(b"previous-audio")

    assert voice.voxcpm_tts("Hello", "default", str(output)) is None
    assert output.read_bytes() == b"previous-audio"
    assert post.call_count == 3
    assert sleep.call_args_list == [((1.0,),), ((2.0,),)]


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
def test_voxcpm_auth_and_invalid_parameter_errors_fail_without_retry(
    monkeypatch, tmp_path, voxcpm_config, status_code
):
    response = SimpleNamespace(
        status_code=status_code,
        text="invalid request",
        close=lambda: None,
    )
    post = Mock(return_value=response)
    monkeypatch.setattr(voice.requests, "post", post)
    sleep = Mock()
    monkeypatch.setattr(voice.time, "sleep", sleep)

    output = tmp_path / "existing.mp3"
    output.write_bytes(b"previous-audio")

    assert voice.voxcpm_tts("Hello", "default", str(output)) is None
    assert output.read_bytes() == b"previous-audio"
    post.assert_called_once()
    sleep.assert_not_called()
