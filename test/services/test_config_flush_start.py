from unittest.mock import Mock, patch

import pytest

from app.config import config


def test_failed_config_flush_thread_start_can_be_retried():
    section = config._SynchronizedConfig({"model": "old"})
    with config._pending_config_lock:
        original_scheduled = config._pending_config_flush_scheduled
        original_updates = dict(config._pending_config_updates)
        config._pending_config_flush_scheduled = False
        config._pending_config_updates[config._pending_update_key(section, "model")] = (section, "model", "new")
    first = Mock()
    first.start.side_effect = RuntimeError("cannot start thread")
    second = Mock()
    try:
        with patch.object(config.threading, "Thread", side_effect=[first, second]) as factory:
            with pytest.raises(RuntimeError, match="cannot start thread"):
                config._schedule_deferred_config_flush()
            assert not config._pending_config_flush_scheduled
            assert config.snapshot_config_with_pending(section)["model"] == "new"
            config._schedule_deferred_config_flush()
            assert config._pending_config_flush_scheduled
            assert factory.call_count == 2
            second.start.assert_called_once_with()
    finally:
        with config._pending_config_lock:
            config._pending_config_flush_scheduled = original_scheduled
            config._pending_config_updates.clear()
            config._pending_config_updates.update(original_updates)


def test_failed_config_flush_thread_construction_clears_reservation():
    with config._pending_config_lock:
        original = config._pending_config_flush_scheduled
        config._pending_config_flush_scheduled = False
    try:
        with patch.object(config.threading, "Thread", side_effect=RuntimeError("cannot construct thread")):
            with pytest.raises(RuntimeError, match="cannot construct thread"):
                config._schedule_deferred_config_flush()
        assert not config._pending_config_flush_scheduled
    finally:
        with config._pending_config_lock:
            config._pending_config_flush_scheduled = original
