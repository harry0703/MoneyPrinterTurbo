import os
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from redis.exceptions import ResponseError

from app.services.state import RedisState


WRONGTYPE = "WRONGTYPE Operation against a key holding the wrong kind of value"


def test_non_hash_task_lookup_returns_absent():
    state = RedisState.__new__(RedisState)
    state._redis = Mock()
    state._redis.hgetall.side_effect = ResponseError(WRONGTYPE)
    assert state.get_task("task_queue") is None


def test_task_lookup_does_not_hide_unrelated_redis_errors():
    state = RedisState.__new__(RedisState)
    state._redis = Mock()
    state._redis.hgetall.side_effect = ResponseError("NOAUTH Authentication required")
    with pytest.raises(ResponseError, match="NOAUTH"):
        state.get_task("task-id")


def test_scan_skips_key_that_changes_type_before_hash_probe():
    state = RedisState.__new__(RedisState)
    state._redis = MagicMock()
    state._redis.scan.return_value = (0, [b"changed", b"task-id"])
    pipeline = state._redis.pipeline.return_value.__enter__.return_value
    pipeline.execute.return_value = [ResponseError(WRONGTYPE), b"task-id"]
    assert state.list_task_ids() == ["task-id"]
    pipeline.execute.assert_called_once_with(raise_on_error=False)


def test_scan_does_not_hide_unrelated_probe_errors():
    state = RedisState.__new__(RedisState)
    state._redis = MagicMock()
    state._redis.scan.return_value = (0, [b"task-id"])
    pipeline = state._redis.pipeline.return_value.__enter__.return_value
    pipeline.execute.return_value = [ResponseError("NOPERM no permissions")]
    with pytest.raises(ResponseError, match="NOPERM"):
        state.list_task_ids()


@pytest.mark.skipif(not os.getenv("MPT_TEST_REDIS_HOST"), reason="MPT_TEST_REDIS_HOST not set")
def test_real_redis_non_hash_lookup_and_scan_type_change():
    state = RedisState(host=os.environ["MPT_TEST_REDIS_HOST"], port=int(os.getenv("MPT_TEST_REDIS_PORT", "6379")), db=int(os.getenv("MPT_TEST_REDIS_DB", "15")))
    key = f"ci-type-change-{uuid4()}"
    client = state._redis
    try:
        client.rpush(key, "queue-item")
        assert state.get_task(key) is None
        client.delete(key)
        state.update_task(key)
        def scan_then_change_type(*args, **kwargs):
            client.delete(key)
            client.rpush(key, "now-a-list")
            return 0, [key.encode()]
        proxy = Mock(wraps=client)
        proxy.scan.side_effect = scan_then_change_type
        state._redis = proxy
        assert state.list_task_ids() == []
    finally:
        client.delete(key)
