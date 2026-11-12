"""A /videos request without voice_name narrates with the voice that /audio and /subtitle use."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.controllers.v1 import video as video_controller
from app.models.schema import TaskVideoRequest
from app.services import voice

DEFAULT_VOICE_NAME = "zh-CN-XiaoxiaoNeural-Female"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(config.app, "api_key", "")
    return TestClient(asgi.app)


def queued_voice(client, endpoint, body):
    """Return the voice_name of the task that a request queues."""
    with (
        patch.object(video_controller.sm.state, "update_task"),
        patch.object(video_controller.task_manager, "add_task") as add_task,
    ):
        response = client.post(endpoint, json=body)
    assert response.status_code == 200
    return add_task.call_args.kwargs["params"].voice_name


def test_video_request_without_voice_uses_the_audio_and_subtitle_voice(client):
    assert (
        queued_voice(client, "/api/v1/audio", {"video_script": "Coffee"})
        == DEFAULT_VOICE_NAME
    )
    assert (
        queued_voice(client, "/api/v1/subtitle", {"video_script": "Coffee"})
        == DEFAULT_VOICE_NAME
    )
    assert (
        queued_voice(client, "/api/v1/videos", {"video_subject": "Coffee"})
        == DEFAULT_VOICE_NAME
    )


def test_api_docs_show_the_default_voice_for_video_requests(client):
    # The API docs at /docs and /redoc show this default.
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert (
        schemas["TaskVideoRequest"]["properties"]["voice_name"]["default"]
        == DEFAULT_VOICE_NAME
    )


def test_default_video_voice_is_an_edge_voice():
    # Edge TTS rejects an empty voice with "Invalid voice ''." before it connects.
    voice_name = voice.parse_voice_name(
        TaskVideoRequest(video_subject="Coffee").voice_name
    )
    assert voice.create_edge_tts_communicate("Coffee", voice_name, "+0%")
