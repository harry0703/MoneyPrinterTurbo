from unittest.mock import Mock

import pytest
from app.config import config
from app.services import voice


@pytest.mark.parametrize("status", [301, 302, 307, 308])
@pytest.mark.parametrize("provider", ["siliconflow", "minimax", "compatible", "fish", "voxcpm"])
def test_speech_redirect_is_terminal_and_preserves_existing_audio(monkeypatch, tmp_path, provider, status):
    response = Mock(status_code=status, text="redirect", content=b"not audio")
    response.headers = {"Location": "https://other-host.test/speech"}
    post = Mock(return_value=response)
    decode = Mock(side_effect=AssertionError("redirect response must not be decoded"))
    monkeypatch.setattr(voice.requests, "post", post)
    monkeypatch.setattr(voice, "AudioFileClip", decode)
    monkeypatch.setattr(config, "siliconflow", {"api_key": "test-key"})
    monkeypatch.setattr(config, "minimax_tts", {"api_key": "test-key"})
    monkeypatch.setattr(voice, "get_minimax_tts_api_key", lambda: "test-key")
    monkeypatch.setattr(voice, "get_minimax_tts_endpoint", lambda: "https://api.test/t2a")
    monkeypatch.setattr(voice, "get_fish_audio_api_key", lambda: "test-key")
    monkeypatch.setattr(config, "voxcpm", {"api_key": "test-key", "model_id": "test-model"})
    monkeypatch.setattr(voice.time, "sleep", lambda _: None)
    output = tmp_path / "previous.mp3"
    output.write_bytes(b"last successful narration")
    calls = {
        "siliconflow": lambda: voice.siliconflow_tts("hello", "model", "voice", 1, str(output)),
        "minimax": lambda: voice.minimax_tts("hello", "voice", 1, str(output)),
        "compatible": lambda: voice._openai_compatible_tts("test", "https://api.test", "test-key", "model", "voice", "hello", 1, str(output)),
        "fish": lambda: voice.fish_audio_tts("hello", str(output)),
        "voxcpm": lambda: voice.voxcpm_tts("hello", "voice", str(output)),
    }
    assert calls[provider]() is None
    post.assert_called_once()
    assert post.call_args.kwargs["allow_redirects"] is False
    response.json.assert_not_called()
    decode.assert_not_called()
    assert output.read_bytes() == b"last successful narration"
    assert list(tmp_path.iterdir()) == [output]
    if provider == "voxcpm":
        response.close.assert_called_once()
