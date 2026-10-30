import pytest

from app.models import const
from app.services.state import RedisState
from test.services.test_state import _FakeRedis


@pytest.mark.parametrize("task_id", ["2026", "None", "False", "[]", "'quoted'"])
def test_redis_preserves_literal_looking_task_ids(task_id):
    state = RedisState.__new__(RedisState)
    state._redis = _FakeRedis([[]])
    state.update_task(task_id, state=const.TASK_STATE_COMPLETE)
    state._redis.batches = [[task_id.encode()]]

    assert state.list_task_ids() == [task_id]
    task = state.get_task(task_id)
    assert task["task_id"] == task_id
    assert state.get_task(task["task_id"]) == task
    assert state.get_all_tasks(page=1, page_size=10) == ([task], 1)


def test_redis_update_preserves_literal_looking_string_values():
    state = RedisState.__new__(RedisState)
    state._redis = _FakeRedis([[]])
    samples = ["2026", "None", "False", "[]", "{'x': 1}", "'quoted'", "line\nnext", "日本語"]
    for index, value in enumerate(samples):
        task_id = f"literal-{index}"
        state.update_task(task_id, state=const.TASK_STATE_COMPLETE, video_subject=value)
        assert state.get_task(task_id)["video_subject"] == value
        assert state._redis.data[task_id.encode()][b"task_id"] == task_id.encode()


def test_redis_patch_preserves_string_and_non_string_types():
    state = RedisState.__new__(RedisState)
    state._redis = _FakeRedis([[]])
    state.update_task("task-literals")
    for value in ["None", "False", "2026", "[]"]:
        assert state.patch_task("task-literals", error=value)
        assert state.get_task("task-literals")["error"] == value
    assert state.patch_task("task-literals", error=None, finished=True, attempts=3, videos=["final.mp4"])
    task = state.get_task("task-literals")
    assert task["error"] is None
    assert task["finished"] is True
    assert task["attempts"] == 3
    assert task["videos"] == ["final.mp4"]


def test_redis_legacy_serialized_records_remain_readable():
    state = RedisState.__new__(RedisState)
    state._redis = _FakeRedis([[]])
    state._redis.data[b"legacy"] = {b"task_id": b"legacy", b"progress": b"20", b"videos": b"['final.mp4']", b"video_subject": b"A cup of tea"}
    task = state.get_task("legacy")
    assert task["progress"] == 20
    assert task["videos"] == ["final.mp4"]
    assert task["video_subject"] == "A cup of tea"
