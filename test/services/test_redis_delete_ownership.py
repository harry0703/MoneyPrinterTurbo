"""Redis 任务删除必须保留被复用的键，且不改变正常删除与错误传播。"""

import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from redis.exceptions import ResponseError

from app.config import config
from app.controllers.v1 import video
from app.models import const
from app.models.exception import HttpException
from app.services.state import RedisState, _DELETE_OWNED_TASK_SCRIPT


def test_delete_checks_ownership_and_deletes_in_one_command():
    state = RedisState.__new__(RedisState)
    state._redis = Mock()

    assert state.delete_task("task-1") is None

    state._redis.eval.assert_called_once_with(_DELETE_OWNED_TASK_SCRIPT, 1, "task-1")
    state._redis.delete.assert_not_called()
    state._redis.type.assert_not_called()
    state._redis.hget.assert_not_called()


@pytest.mark.parametrize("error", ["NOPERM no permissions", "NOAUTH Authentication required"])
def test_delete_does_not_hide_errors_or_fall_back_to_unsafe_delete(error):
    state = RedisState.__new__(RedisState)
    state._redis = Mock()
    state._redis.eval.side_effect = ResponseError(error)

    with pytest.raises(ResponseError, match=error):
        state.delete_task("task-1")

    state._redis.delete.assert_not_called()


@pytest.fixture
def native_state():
    host = os.getenv("MPT_TEST_REDIS_HOST")
    if not host:
        pytest.skip("MPT_TEST_REDIS_HOST not set")
    state = RedisState(
        host=host,
        port=int(os.getenv("MPT_TEST_REDIS_PORT", "6379")),
        db=int(os.getenv("MPT_TEST_REDIS_DB", "15")),
    )
    key = f"ci-delete-owner-{uuid4()}"
    try:
        yield state, key
    finally:
        state._redis.delete(key)
        state._redis.close()


REPLACEMENT_KINDS = ["foreign_hash", "mismatched_task", "queue", "string", "set", "sorted_set", "stream"]


def _replace_task_key(state, key, kind):
    client = state._redis
    client.delete(key)
    if kind == "foreign_hash":
        client.hset(key, mapping={"owner": "other-service", "value": "retained"})
    elif kind == "mismatched_task":
        client.hset(key, mapping={"task_id": "different-task", "value": "retained"})
    elif kind == "queue":
        client.rpush(key, "queued-task")
    elif kind == "string":
        client.set(key, "retained")
    elif kind == "set":
        client.sadd(key, "retained")
    elif kind == "sorted_set":
        client.zadd(key, {"retained": 1})
    elif kind == "stream":
        client.xadd(key, {"value": "retained"})
    else:
        raise AssertionError(f"unexpected replacement kind: {kind}")
    client.pexpire(key, 60000)
    return client.dump(key)


@pytest.mark.parametrize("kind", REPLACEMENT_KINDS)
def test_delete_preserves_repurposed_key_and_expiry(native_state, kind):
    state, key = native_state
    state.update_task(key, state=const.TASK_STATE_COMPLETE, progress=100)
    assert state.get_task(key)["state"] == const.TASK_STATE_COMPLETE
    before = _replace_task_key(state, key, kind)
    assert state.get_task(key) is None

    state.delete_task(key)
    state.delete_task(key)

    assert state._redis.dump(key) == before
    assert 0 < state._redis.pttl(key) <= 60000


@pytest.mark.parametrize("present", [False, True])
def test_delete_owned_and_absent_tasks_is_idempotent(native_state, present):
    state, key = native_state
    if present:
        state.update_task(key, state=const.TASK_STATE_COMPLETE, progress=100)
    state.delete_task(key)
    state.delete_task(key)
    assert not state._redis.exists(key)


def test_delete_accepts_matching_unicode_task_marker(native_state):
    state, key = native_state
    unicode_key = f"{key}-任务"
    try:
        state.update_task(unicode_key, state=const.TASK_STATE_COMPLETE)
        assert state.get_task(unicode_key)["task_id"] == unicode_key
        state.delete_task(unicode_key)
        assert not state._redis.exists(unicode_key)
    finally:
        state._redis.delete(unicode_key)


def test_concurrent_replacement_and_delete_always_preserve_foreign_key(native_state):
    state, key = native_state
    with ThreadPoolExecutor(max_workers=2) as executor:
        for _ in range(50):
            state._redis.delete(key)
            state.update_task(key, state=const.TASK_STATE_COMPLETE)
            barrier = Barrier(2)

            def replace():
                barrier.wait(timeout=5)
                # 整个替换在 Redis 事务中执行；无论它先于还是后于删除，外部键都应保留。
                with state._redis.pipeline() as transaction:
                    transaction.delete(key)
                    transaction.set(key, "other-service")
                    transaction.execute()

            def delete():
                barrier.wait(timeout=5)
                state.delete_task(key)

            futures = [executor.submit(replace), executor.submit(delete)]
            for future in futures:
                future.result(timeout=5)
            assert state._redis.get(key) == b"other-service"


@pytest.fixture
def deletion_client(native_state, tmp_path):
    state, _ = native_state
    application = FastAPI()
    application.include_router(video.router)

    @application.exception_handler(HttpException)
    async def handle_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={"message": exc.message})

    with (
        patch.object(video.sm, "state", state),
        patch.object(video.utils, "task_dir", return_value=str(tmp_path)),
        patch.object(config, "app", dict(config.app, api_key="test-delete-api-key")),
        TestClient(application) as client,
    ):
        yield client


@pytest.mark.parametrize("kind", REPLACEMENT_KINDS)
def test_http_delete_preserves_key_repurposed_after_directory_cleanup(
    native_state, deletion_client, tmp_path, kind
):
    state, key = native_state
    state.update_task(key, state=const.TASK_STATE_COMPLETE, progress=100)
    task_dir = tmp_path / key
    task_dir.mkdir()
    (task_dir / "artifact.txt").write_text("generated artifact", encoding="utf-8")
    original_rmtree = shutil.rmtree
    retained = []

    def cleanup_then_repurpose(path, *args, **kwargs):
        assert Path(path) == task_dir
        original_rmtree(path, *args, **kwargs)
        # 在真实路由读完任务并清理目录后、删除 Redis 记录前，确定性插入键复用。
        retained.append(_replace_task_key(state, key, kind))

    with patch.object(video.shutil, "rmtree", side_effect=cleanup_then_repurpose):
        response = deletion_client.delete(
            f"/api/v1/tasks/{key}", headers={"x-api-key": "test-delete-api-key"}
        )

    assert response.status_code == 200
    assert not task_dir.exists()
    assert retained
    assert state._redis.dump(key) == retained[0]
    assert state._redis.pttl(key) > 0


@pytest.mark.parametrize(
    "control,expected", [("foreign", 404), ("busy", 409), ("unauthorized", 401), ("owned", 200)]
)
def test_http_deletion_keeps_existing_guards(native_state, deletion_client, tmp_path, control, expected):
    state, key = native_state
    if control == "foreign":
        state._redis.set(key, "other-service")
    else:
        state.update_task(
            key,
            state=const.TASK_STATE_PROCESSING if control == "busy" else const.TASK_STATE_COMPLETE,
            progress=100,
        )
    task_dir = tmp_path / key
    task_dir.mkdir()
    before = state._redis.dump(key)

    response = deletion_client.delete(
        f"/api/v1/tasks/{key}",
        headers={} if control == "unauthorized" else {"x-api-key": "test-delete-api-key"},
    )

    assert response.status_code == expected
    if expected == 200:
        assert not state._redis.exists(key)
        assert not task_dir.exists()
    else:
        assert state._redis.dump(key) == before
        assert task_dir.exists()
