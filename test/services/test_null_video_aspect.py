"""A null video_aspect is rejected before any generation step.

The render reads the frame size from the aspect ratio. A /videos request with
"video_aspect": null was accepted with 200 and failed the task with
"None is not a valid VideoAspect" after the script and narration steps.
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
from app.models.schema import VideoAspect, VideoParams
from app.services import state as sm
from app.services import task


def post_video(body):
    """Post to the real app; return the response, the queue mock and the task ids."""
    with (
        patch.dict(config.app, {"api_key": ""}),
        patch.object(sm, "state", sm.MemoryState()),
        patch.object(controller.task_manager, "add_task") as add_task,
        TestClient(asgi.app) as client,
    ):
        response = client.post(
            "/api/v1/videos", json={"video_subject": "Coffee", **body}
        )
        return response, add_task, sm.state.list_task_ids()


def test_http_rejects_null_aspect_before_a_task_is_created():
    response, add_task, task_ids = post_video({"video_aspect": None})

    assert response.status_code == 400
    assert response.json()["message"] == (
        "body.video_aspect: Input should be '16:9', '9:16' or '1:1'"
    )
    add_task.assert_not_called()
    assert task_ids == []


@pytest.mark.parametrize(
    "body, expected",
    [
        ({}, VideoAspect.portrait),
        ({"video_aspect": "16:9"}, VideoAspect.landscape),
        ({"video_aspect": "9:16"}, VideoAspect.portrait),
        ({"video_aspect": "1:1"}, VideoAspect.square),
    ],
    ids=["omitted", "16:9", "9:16", "1:1"],
)
def test_http_keeps_queuing_requests_with_an_aspect(body, expected):
    response, add_task, _ = post_video(body)

    assert response.status_code == 200
    assert add_task.call_args.kwargs["params"].video_aspect is expected


def run_pipeline(params, stop_at):
    """Run the real pipeline up to the script LLM call; return the task and the call."""
    with (
        patch.object(sm, "state", sm.MemoryState()),
        patch.object(
            task.llm,
            "generate_script",
            side_effect=RuntimeError("generation boundary reached"),
        ) as generate_script,
    ):
        task.start("null-aspect", params, stop_at=stop_at)
        return sm.state.get_task("null-aspect"), generate_script


def test_pipeline_fails_a_null_aspect_video_task_before_generation():
    params = VideoParams(video_subject="Coffee", video_aspect=None)

    failure, generate_script = run_pipeline(params, "video")

    generate_script.assert_not_called()
    assert failure["state"] == const.TASK_STATE_FAILED
    assert failure["failed_stage"] == "preflight"
    assert failure["error"] == "video_aspect cannot be null"


def test_pipeline_does_not_check_the_aspect_of_a_task_that_never_renders():
    params = VideoParams(video_subject="Coffee", video_aspect=None)

    failure, generate_script = run_pipeline(params, "audio")

    generate_script.assert_called_once()
    assert failure["failed_stage"] != "preflight"


def test_null_aspect_video_task_left_in_redis_fails_at_preflight():
    # A /videos task queued before the API rejected a null aspect restores as
    # VideoParams, which keeps the null, so it is still dispatched.
    params = {
        **VideoParams(video_subject="Coffee").model_dump(warnings=False),
        "video_aspect": None,
    }
    payload = {
        "func": "start",
        "args": [],
        "kwargs": {"task_id": "null-aspect", "params": params, "stop_at": "video"},
    }
    redis_client = MagicMock()
    redis_client.eval.return_value = json.dumps(payload)
    with patch(
        "app.controllers.manager.redis_manager.redis.Redis.from_url",
        return_value=redis_client,
    ):
        manager = RedisTaskManager(1, "redis://localhost:6379/0")
    with patch.object(manager, "execute_task") as execute_task:
        manager.check_queue()
    func, *args = execute_task.call_args.args

    with (
        patch.object(sm, "state", sm.MemoryState()),
        patch.object(
            task.llm,
            "generate_script",
            side_effect=RuntimeError("generation boundary reached"),
        ) as generate_script,
    ):
        func(*args, **execute_task.call_args.kwargs)
        failure = sm.state.get_task("null-aspect")

    generate_script.assert_not_called()
    assert failure["failed_stage"] == "preflight"
    assert failure["error"] == "video_aspect cannot be null"
