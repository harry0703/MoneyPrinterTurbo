import json
from functools import partial
from unittest.mock import MagicMock, patch

import pytest

from app.controllers.manager.redis_manager import RedisTaskManager
from app.models import const
from app.models.schema import VideoParams


def make_manager():
    client = MagicMock()
    with patch("app.controllers.manager.redis_manager.redis.Redis.from_url", return_value=client):
        manager = RedisTaskManager(1, "redis://test.invalid")
    return manager, client


def payload(task_id, **kwargs):
    return {"func": "start", "args": [], "kwargs": {"task_id": task_id, "params": VideoParams(video_subject="Tea").model_dump(warnings=False), **kwargs}}


@pytest.mark.parametrize("defect", ["retired_keyword", "missing_params", "duplicate_task_id"])
def test_signature_drift_marks_stale_task_failed_and_drains_queue(defect):
    manager, client = make_manager()
    stale = payload("stale")
    if defect == "retired_keyword":
        stale["kwargs"]["retired_option"] = True
    elif defect == "missing_params":
        del stale["kwargs"]["params"]
    else:
        stale["args"] = ["another-task"]
    client.lpop.side_effect = [json.dumps(stale), json.dumps(payload("valid"))]
    with patch("app.controllers.manager.redis_manager.sm.state") as state:
        task = manager.dequeue()
    assert task["kwargs"]["task_id"] == "valid"
    state.patch_task.assert_called_once()
    assert state.patch_task.call_args.args == ("stale",)
    assert state.patch_task.call_args.kwargs["state"] == const.TASK_STATE_FAILED
    assert state.patch_task.call_args.kwargs["failed_stage"] == "dequeue"


def test_signature_validation_accepts_supported_partial_callables():
    manager, client = make_manager()
    def accepts_request(task_id, params, stop_at="video"):
        pass
    bound = partial(accepts_request, stop_at="audio")
    client.lpop.return_value = json.dumps(payload("valid"))
    with patch.dict("app.controllers.manager.redis_manager.FUNC_MAP", {"start": bound}):
        task = manager.dequeue()
    assert task["func"] is bound
    assert isinstance(task["kwargs"]["params"], VideoParams)
