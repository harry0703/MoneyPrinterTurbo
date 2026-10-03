from unittest.mock import Mock

import pytest
import requests
from app.services import voice


@pytest.mark.parametrize("failure", [requests.ReadTimeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError])
def test_ambiguous_compatible_speech_outcome_is_not_replayed(monkeypatch, tmp_path, failure):
    post = Mock(side_effect=failure("response lost after synthesis"))
    monkeypatch.setattr(voice.requests, "post", post)
    target = tmp_path / "previous.mp3"
    target.write_bytes(b"last good narration")
    assert voice._openai_compatible_tts("test", "https://server.test/v1", "test-key", "model", "voice", "hello", 1, str(target)) is None
    post.assert_called_once()
    assert target.read_bytes() == b"last good narration"
    assert list(tmp_path.iterdir()) == [target]


def test_connect_timeout_remains_retryable(monkeypatch, tmp_path):
    post = Mock(side_effect=requests.ConnectTimeout("connection not established"))
    monkeypatch.setattr(voice.requests, "post", post)
    target = tmp_path / "not-created.mp3"
    assert voice._openai_compatible_tts("test", "https://server.test/v1", "test-key", "model", "voice", "hello", 1, str(target)) is None
    assert post.call_count == 3
    assert not target.exists()
