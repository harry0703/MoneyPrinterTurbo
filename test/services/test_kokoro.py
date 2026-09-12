"""Kokoro 协议兼容和共享音频传输回归，不依赖外部服务。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from app.config import config
from app.services import voice


@pytest.fixture
def kokoro_config(monkeypatch):
    settings = {"base_url": "http://localhost:8880/v1/", "api_key": "test-key",
                "model_id": "kokoro", "voices": []}
    monkeypatch.setattr(config, "kokoro", settings)
    return settings


@pytest.mark.parametrize("payload", [
    {"voices": ["af_heart", "zf_xiaobei"]},
    {"voices": [{"id": "af_heart", "name": "Heart"}, {"id": "zf_xiaobei"}]},
    ["af_heart", {"id": "zf_xiaobei"}],
])
def test_voice_list_supports_old_and_new_servers(monkeypatch, kokoro_config, payload):
    get = Mock(return_value=SimpleNamespace(status_code=200, json=lambda: payload))
    monkeypatch.setattr(voice.requests, "get", get)
    assert voice.get_kokoro_voices() == ["kokoro:af_heart", "kokoro:zf_xiaobei"]
    get.assert_called_once_with("http://localhost:8880/v1/audio/voices",
                                headers={"Authorization": "Bearer test-key"}, timeout=5)


@pytest.mark.parametrize("entries, expected", [
    ([" af_heart ", "kokoro:af_heart", {"id": " zf_xiaobei "}, None, 2,
      {"name": "invalid"}, {"id": None}, "kokoro:"], ["kokoro:af_heart", "kokoro:zf_xiaobei"]),
    (" af_heart, kokoro:zf_xiaobei, ", ["kokoro:af_heart", "kokoro:zf_xiaobei"]),
    ({"id": "af_heart"}, []), (42, []), (None, []),
])
def test_voice_normalization_rejects_invalid_entries(entries, expected):
    assert voice._normalize_kokoro_voices(entries) == expected


def test_pinned_voices_do_not_request_server(monkeypatch, kokoro_config):
    kokoro_config["voices"] = "af_heart, zf_xiaobei"
    get = Mock(side_effect=AssertionError("manual voices must not request server"))
    monkeypatch.setattr(voice.requests, "get", get)
    assert voice.get_kokoro_voices(fallback=False) == ["kokoro:af_heart", "kokoro:zf_xiaobei"]
    get.assert_not_called()


@pytest.mark.parametrize("failure", [requests.Timeout(), requests.ConnectionError(),
                                     ValueError("invalid JSON"), 401, 500, [], {"voices": None}])
def test_voice_discovery_failure_is_distinguishable(monkeypatch, kokoro_config, failure):
    if isinstance(failure, Exception):
        get = Mock(side_effect=failure)
    else:
        get = Mock(return_value=SimpleNamespace(
            status_code=failure if isinstance(failure, int) else 200,
            json=lambda: failure,
        ))
    monkeypatch.setattr(voice.requests, "get", get)
    assert voice.get_kokoro_voices(fallback=False) == []
    assert voice.get_kokoro_voices() == ["kokoro:af_heart"]


@pytest.mark.parametrize("text", ["", "  ", "...!!!", "😀"])
def test_unspeakable_text_does_not_make_requests(monkeypatch, kokoro_config, tmp_path, text):
    post = Mock()
    monkeypatch.setattr(voice.requests, "post", post)
    assert voice.kokoro_tts(text, "af_heart", str(tmp_path / "test.mp3")) is None
    post.assert_not_called()


@pytest.mark.parametrize("provider", ["kokoro", "chatterbox"])
@pytest.mark.parametrize("rate, expected", [(0.1, 0.25), (1.2, 1.2), (5, 4.0)])
def test_transport_closes_audio_and_preserves_contract(monkeypatch, tmp_path, provider, rate, expected):
    monkeypatch.setattr(config, provider, {
        "base_url": "http://localhost:8880/v1/", "api_key": "key", "model_id": provider,
    })
    post = Mock(return_value=SimpleNamespace(status_code=200, content=b"audio", text=""))
    monkeypatch.setattr(voice.requests, "post", post)
    clip = Mock(duration=1.5)
    monkeypatch.setattr(voice, "AudioFileClip", Mock(return_value=clip))
    output = tmp_path / "output.mp3"
    maker = voice.tts("Hello world.", f"{provider}:af_heart-Female", rate, str(output))
    assert maker is not None
    assert output.read_bytes() == b"audio"
    assert list(tmp_path.iterdir()) == [output]
    clip.close.assert_called_once()
    payload = post.call_args.kwargs["json"]
    assert payload == {"model": provider, "input": "Hello world.", "voice": "af_heart",
                       "response_format": "mp3", "speed": expected}
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer key"


@pytest.mark.parametrize("provider", ["kokoro", "chatterbox"])
@pytest.mark.parametrize("failure", ["empty", "decode", "zero", "nan", "replace", "http", "timeout"])
def test_failed_audio_never_overwrites_output(monkeypatch, tmp_path, provider, failure):
    """失败保留原文件，解码资源与临时文件均释放，包括 Windows 替换失败。"""
    output = tmp_path / "existing.mp3"
    output.write_bytes(b"previous audio")
    post = Mock(return_value=SimpleNamespace(
        status_code=503 if failure == "http" else 200,
        content=b"" if failure == "empty" else b"invalid audio", text="Unavailable"))
    if failure == "timeout":
        post.side_effect = requests.Timeout()
    monkeypatch.setattr(voice.requests, "post", post)
    clip = Mock(duration=0 if failure == "zero" else float("nan") if failure == "nan" else 1)
    reader = Mock(return_value=clip)
    if failure == "decode":
        reader.side_effect = ValueError("invalid audio")
    monkeypatch.setattr(voice, "AudioFileClip", reader)
    if failure == "replace":
        monkeypatch.setattr(voice.os, "replace", Mock(side_effect=PermissionError("in use")))
    assert voice._openai_compatible_tts(
        provider, "http://localhost/v1", "", provider, "af_heart", "Hello", 1, str(output)
    ) is None
    assert output.read_bytes() == b"previous audio"
    assert list(tmp_path.iterdir()) == [output]
    assert post.call_count == 3
    if failure in {"zero", "nan", "replace"}:
        assert clip.close.call_count == 3


def test_transient_error_retries_successfully(monkeypatch, tmp_path):
    responses = [requests.Timeout(), SimpleNamespace(status_code=200, content=b"audio", text="")]
    post = Mock(side_effect=responses)
    monkeypatch.setattr(voice.requests, "post", post)
    monkeypatch.setattr(voice, "AudioFileClip", Mock(return_value=Mock(duration=1)))
    assert voice._openai_compatible_tts("kokoro", "http://localhost/v1", "", "kokoro",
                                        "af_heart", "Hello", 1, str(tmp_path / "a.mp3"))
    assert post.call_count == 2
