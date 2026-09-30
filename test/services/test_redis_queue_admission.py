"""Queue capacity is shared by every manager using the Redis list."""

import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

import redis

from app.controllers.manager.base_manager import TaskQueueFullError
from app.controllers.manager.redis_manager import RedisTaskManager
from app.models.schema import VideoParams
from app.services import task as tm


class TestRedisQueueAdmission(unittest.TestCase):
    def setUp(self):
        host = os.getenv("MPT_TEST_REDIS_HOST", "127.0.0.1")
        port = int(os.getenv("MPT_TEST_REDIS_PORT", "6379"))
        db = int(os.getenv("MPT_TEST_REDIS_DB", "15"))
        self.managers = [
            RedisTaskManager(0, f"redis://{host}:{port}/{db}", max_queued_tasks=1)
            for _ in range(2)
        ]
        try:
            self.managers[0].redis_client.ping()
        except redis.RedisError as exc:
            self.skipTest(f"Redis is unavailable: {exc}")
        queue = f"test-admission:{uuid4()}"
        for manager in self.managers:
            manager.queue = queue
            self.addCleanup(manager.redis_client.close)
        self.addCleanup(self.managers[0].redis_client.delete, queue)

    def test_simultaneous_managers_cannot_exceed_shared_capacity(self):
        # Hold both callers after their real LLEN reads. Their local locks are
        # independent, as they are in separate API processes sharing Redis.
        barrier = threading.Barrier(2)

        def add(manager):
            original = manager.queue_size

            def synchronized_size():
                size = original()
                barrier.wait(timeout=5)
                return size

            with patch.object(manager, "queue_size", synchronized_size):
                try:
                    manager.add_task(
                        tm.start,
                        task_id=str(uuid4()),
                        params=VideoParams(video_subject="Coffee"),
                    )
                except TaskQueueFullError:
                    return "rejected"
                return "queued"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(add, self.managers))
        self.assertCountEqual(results, ["queued", "rejected"])
        self.assertEqual(self.managers[0].queue_size(), 1)

    def test_worker_start_failure_can_restore_previously_admitted_task(self):
        manager = self.managers[0]
        manager.max_concurrent_tasks = 1
        manager.enqueue({"func": tm.start, "args": (), "kwargs": {
            "task_id": "original", "params": VideoParams(video_subject="Coffee")
        }})

        def failed_start(*args, **kwargs):
            # A second process admits a fresh task after the first pop. Restoring
            # the old accepted work must remain possible even at the new limit.
            self.managers[1].add_task(
                tm.start, task_id="new", params=VideoParams(video_subject="Tea")
            )
            raise RuntimeError("can't start new thread")

        with patch.object(manager, "execute_task", side_effect=failed_start):
            with self.assertRaisesRegex(RuntimeError, "can't start new thread"):
                manager.check_queue()
        self.assertEqual(manager.current_tasks, 0)
        self.assertEqual(manager.queue_size(), 2)
        restored = [manager.dequeue()["kwargs"]["task_id"] for _ in range(2)]
        self.assertCountEqual(restored, ["original", "new"])
