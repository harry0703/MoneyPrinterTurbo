import os
from uuid import uuid4

import pytest
from app.services.state import RedisState


@pytest.fixture
def redis_state():
    host = os.getenv("MPT_TEST_REDIS_HOST")
    if not host:
        pytest.skip("MPT_TEST_REDIS_HOST not set")
    return RedisState(host=host, port=int(os.getenv("MPT_TEST_REDIS_PORT", "6379")), db=int(os.getenv("MPT_TEST_REDIS_DB", "15")))


@pytest.mark.parametrize("kind", ["foreign_hash", "queue", "mismatched_marker"])
def test_patch_does_not_mutate_non_task_redis_keys(redis_state, kind):
    key = "ci-patch-owner-" + str(uuid4())
    client = redis_state._redis
    try:
        if kind == "queue":
            client.rpush(key, "queued-task")
            before = client.lrange(key, 0, -1)
        else:
            client.hset(key, mapping={"foreign_field": "untouched", **({"task_id": "another-task"} if kind == "mismatched_marker" else {})})
            before = client.hgetall(key)
        assert redis_state.get_task(key) is None
        assert redis_state.patch_task(key, progress=50) is False
        assert (client.lrange(key, 0, -1) if kind == "queue" else client.hgetall(key)) == before
    finally:
        client.delete(key)


def test_owned_task_patch_preserves_fields_and_missing_task_stays_missing(redis_state):
    key = "ci-patch-positive-" + str(uuid4())
    try:
        redis_state.update_task(key, state=1, progress=10, narration="keep")
        assert redis_state.patch_task(key, progress=50) is True
        task = redis_state.get_task(key)
        assert task["narration"] == "keep"
        assert task["progress"] == 50
        redis_state.delete_task(key)
        assert redis_state.patch_task(key, progress=99) is False
        assert not redis_state._redis.exists(key)
    finally:
        redis_state._redis.delete(key)
