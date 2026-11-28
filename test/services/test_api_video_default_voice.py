"""A /videos request without voice_name narrates with the voice that /audio and /subtitle use.

A request to any of the three that sends "voice_name": null gets that voice too.
"""

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


@pytest.mark.parametrize(
    "endpoint, body",
    [
        ("/api/v1/videos", {"video_subject": "Coffee"}),
        ("/api/v1/audio", {"video_script": "Coffee"}),
        ("/api/v1/subtitle", {"video_script": "Coffee"}),
    ],
    ids=["videos", "audio", "subtitle"],
)
def test_null_voice_name_uses_the_default_voice(client, endpoint, body):
    # Optional[str] accepts null, and the task failed when it reached TTS with
    # "'NoneType' object has no attribute 'strip'", for /videos after the LLM calls.
    assert (
        queued_voice(client, endpoint, {**body, "voice_name": None})
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


def test_aigei_api_requires_confirmation_before_queuing(client):
    body = {"video_subject": "Coffee", "video_source": "aigei", "subtitle_enabled": False}
    with (
        patch.object(video_controller.sm.state, "update_task") as update_task,
        patch.object(video_controller.task_manager, "add_task") as add_task,
    ):
        response = client.post("/api/v1/videos", json=body)
        assert response.status_code == 400
        for confirmation in (False, "true"):
            response = client.post("/api/v1/videos", json={**body, "confirm_aigei_charge": confirmation})
            assert response.status_code in {400, 422}
        update_task.assert_not_called()
        add_task.assert_not_called()

        response = client.post("/api/v1/videos", json={**body, "confirm_aigei_charge": True})
        assert response.status_code == 200
        add_task.assert_called_once()
        queued = add_task.call_args.kwargs["params"]
        assert queued.confirm_aigei_charge is True
        assert "confirm_aigei_charge" not in queued.model_dump()
