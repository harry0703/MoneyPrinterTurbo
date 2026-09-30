import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx
from openai import OpenAI

from app.services import voice


def test_mimo_lost_paid_response_is_not_replayed_and_client_closes():
    submitted = []
    clients = []
    options = []

    def response_lost(request):
        submitted.append(request)
        raise httpx.ReadTimeout("response lost after submission", request=request)

    def client_factory(**kwargs):
        options.append(kwargs)
        client = OpenAI(
            **kwargs,
            http_client=httpx.Client(
                transport=httpx.MockTransport(response_lost), trust_env=False
            ),
        )
        clients.append(client)
        return client

    with (
        tempfile.TemporaryDirectory() as temp_dir,
        patch.object(voice.config, "app", {"mimo_api_key": "fixture-key"}),
        patch.object(voice, "OpenAI", side_effect=client_factory),
        patch("openai._base_client.time.sleep"),
    ):
        result = voice.mimo_tts("Hello", "fixture-voice", 1.0, str(Path(temp_dir) / "voice.mp3"))
        assert result is None
        assert list(Path(temp_dir).iterdir()) == []

    assert len(submitted) == 1
    assert len(clients) == 1
    assert clients[0].is_closed()
    assert options[0]["max_retries"] == 0
    assert options[0]["timeout"] > 0
