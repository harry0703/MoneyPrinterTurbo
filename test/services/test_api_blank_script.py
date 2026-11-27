"""/audio and /subtitle reject a blank video_script before a task is created.

These endpoints narrate the script the client sends. Their request models have
no video_subject, so the pipeline cannot write a script for them: a blank one
was accepted with 200 and then failed the task with
"'AudioRequest' object has no attribute 'video_subject'".
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.controllers.manager.redis_manager import RedisTaskManager
from app.controllers.v1 import video as controller
from app.models import const
from app.models.schema import AudioRequest, SubtitleRequest
from app.services import state as sm

ENDPOINTS = ["/api/v1/audio", "/api/v1/subtitle"]


def post(endpoint, body):
    """Post to the real app; return the response, the queue mock and the task ids."""
    with (
        patch.dict(config.app, {"api_key": ""}),
        patch.object(sm, "state", sm.MemoryState()),
        patch.object(controller.task_manager, "add_task") as add_task,
        TestClient(asgi.app) as client,
    ):
        response = client.post(endpoint, json=body)
        return response, add_task, sm.state.list_task_ids()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize(
    "script", ["", "   ", "\n\t"], ids=["empty", "spaces", "newline"]
)
def test_blank_script_is_rejected_before_a_task_is_created(endpoint, script):
    response, add_task, task_ids = post(endpoint, {"video_script": script})

    assert response.status_code == 400
    assert (
        response.json()["message"] == "body.video_script: Value error, cannot be blank"
    )
    add_task.assert_not_called()
    assert task_ids == []


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_script_with_text_is_queued_unchanged(endpoint):
    script = "  Coffee at night.\n"
    response, add_task, task_ids = post(endpoint, {"video_script": script})

    assert response.status_code == 200
    assert add_task.call_args.kwargs["params"].video_script == script
    assert task_ids == [response.json()["data"]["task_id"]]


def test_videos_request_may_still_leave_the_script_to_the_llm():
    response, add_task, _ = post(
        "/api/v1/videos", {"video_subject": "Coffee", "video_script": ""}
    )

    assert response.status_code == 200
    assert add_task.call_args.kwargs["params"].video_script == ""


@pytest.mark.parametrize(
    "stop_at, model", [("audio", AudioRequest), ("subtitle", SubtitleRequest)]
)
def test_blank_script_task_left_in_redis_fails_at_dequeue(stop_at, model):
    # A task queued before the API rejected a blank script is still in Redis.
    # It is marked failed when it leaves the queue instead of being started.
    params = {**model(video_script="Coffee").model_dump(), "video_script": ""}
    payload = {
        "func": "start",
        "args": [],
        "kwargs": {"task_id": "blank-script", "params": params, "stop_at": stop_at},
    }
    redis_client = MagicMock()
    redis_client.lpop.side_effect = [json.dumps(payload), None]
    with patch(
        "app.controllers.manager.redis_manager.redis.Redis.from_url",
        return_value=redis_client,
    ):
        manager = RedisTaskManager(1, "redis://localhost:6379/0")

    with patch.object(sm, "state", sm.MemoryState()):
        sm.state.update_task("blank-script")
        assert manager.dequeue() is None
        task = sm.state.get_task("blank-script")

    assert task["state"] == const.TASK_STATE_FAILED
    assert task["failed_stage"] == "dequeue"
    assert "video_script" in task["error"]
    assert "cannot be blank" in task["error"]
