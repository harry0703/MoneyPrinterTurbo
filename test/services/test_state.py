import os
import sys
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models import const
from app.services.state import MemoryState, RedisState


class _FakeRedis:
    def __init__(self, batches):
        self.batches = batches
        self.scan_types = []
        self.data = {}
        for key in [key for batch in batches for key in batch]:
            index = int(key.decode("utf-8").split(":")[-1])
            self.data[key] = {
                b"task_id": key,
                b"state": b"1",
                b"progress": str(index).encode("utf-8"),
            }

    def scan(self, cursor, count, _type=None):
        self.scan_types.append(_type)
        batch_index = int(cursor)
        next_cursor = batch_index + 1
        if next_cursor >= len(self.batches):
            next_cursor = 0
        return next_cursor, self.batches[batch_index]

    def hgetall(self, key):
        if isinstance(key, str):
            key = key.encode("utf-8")
        return self.data[key]

    def exists(self, key):
        if isinstance(key, str):
            key = key.encode("utf-8")
        return key in self.data

    def hset(self, key, field=None, value=None, mapping=None):
        if isinstance(key, str):
            key = key.encode("utf-8")
        target = self.data.setdefault(key, {})
        if mapping:
            target.update(
                {
                    str(item_key).encode("utf-8"): str(item_value).encode("utf-8")
                    for item_key, item_value in mapping.items()
                }
            )
        elif field is not None:
            target[str(field).encode("utf-8")] = str(value).encode("utf-8")

    def eval(self, script, numkeys, key, *arguments):
        if isinstance(key, str):
            key = key.encode("utf-8")
        if key not in self.data:
            return 0

        target = self.data[key]
        for index in range(0, len(arguments), 2):
            field = str(arguments[index]).encode("utf-8")
            value = str(arguments[index + 1]).encode("utf-8")
            target[field] = value
        return 1


class TestMemoryState(unittest.TestCase):
    def test_get_task_and_get_all_tasks_return_isolated_snapshots(self):
        state = MemoryState()
        state.update_task(
            "task-1",
            state=const.TASK_STATE_PROCESSING,
            progress=25,
            videos=["first.mp4"],
        )

        task = state.get_task("task-1")
        task["videos"].append("mutated.mp4")

        tasks, total = state.get_all_tasks(page=1, page_size=10)
        tasks[0]["videos"].append("mutated-again.mp4")

        self.assertEqual(total, 1)
        self.assertEqual(state.get_task("task-1")["videos"], ["first.mp4"])

    def test_concurrent_memory_updates_are_preserved(self):
        state = MemoryState()
        thread_count = 5
        tasks_per_thread = 50

        def update_tasks(thread_index):
            for task_index in range(tasks_per_thread):
                state.update_task(
                    f"task-{thread_index}-{task_index}",
                    state=const.TASK_STATE_PROCESSING,
                    progress=task_index,
                )

        threads = [
            threading.Thread(target=update_tasks, args=(thread_index,))
            for thread_index in range(thread_count)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        tasks, total = state.get_all_tasks(page=1, page_size=thread_count * tasks_per_thread)

        self.assertEqual(total, thread_count * tasks_per_thread)
        self.assertEqual(len(tasks), total)

    def test_patch_task_preserves_generated_outputs(self):
        """Asynchronous publish updates must not overwrite fields of an already-completed video task."""
        state = MemoryState()
        state.update_task(
            "task-1",
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            videos=["final.mp4"],
        )

        patched = state.patch_task(
            "task-1",
            cross_post_state=const.CROSS_POST_STATE_COMPLETE,
            cross_post_results=[{"success": True}],
        )

        self.assertTrue(patched)
        self.assertEqual(
            state.get_task("task-1"),
            {
                "task_id": "task-1",
                "state": const.TASK_STATE_COMPLETE,
                "progress": 100,
                "videos": ["final.mp4"],
                "cross_post_state": const.CROSS_POST_STATE_COMPLETE,
                "cross_post_results": [{"success": True}],
            },
        )
        self.assertFalse(state.patch_task("missing", value="ignored"))


class TestRedisState(unittest.TestCase):
    def _build_state(self, batch_sizes):
        keys = [f"task:{i}".encode("utf-8") for i in range(sum(batch_sizes))]
        batches = []
        offset = 0
        for batch_size in batch_sizes:
            batches.append(keys[offset : offset + batch_size])
            offset += batch_size

        state = RedisState.__new__(RedisState)
        state._redis = _FakeRedis(batches)
        return state

    def test_get_all_tasks_paginates_across_scan_batches(self):
        """
        When Redis SCAN returns keys in batches, pagination slicing must be computed from the
        current batch's start position.

        This case reproduces the PR #890 scenario of 18 tasks with page_size=10:
        10 in the first batch, 8 in the second. The old logic returned an empty first page and
        only 2 items on the second; after the fix the first page returns 10 and the second the
        remaining 8.
        """
        state = self._build_state([10, 8])

        first_page, first_total = state.get_all_tasks(page=1, page_size=10)
        second_page, second_total = state.get_all_tasks(page=2, page_size=10)

        self.assertEqual(first_total, 18)
        self.assertEqual(second_total, 18)
        self.assertEqual(len(first_page), 10)
        self.assertEqual(len(second_page), 8)
        self.assertEqual(
            [task["task_id"] for task in first_page],
            [f"task:{i}" for i in range(10)],
        )
        self.assertEqual(
            [task["task_id"] for task in second_page],
            [f"task:{i}" for i in range(10, 18)],
        )
        self.assertTrue(state._redis.scan_types)
        self.assertEqual(set(state._redis.scan_types), {"HASH"})

    @unittest.skipUnless(
        os.getenv("MPT_TEST_REDIS_HOST"),
        "MPT_TEST_REDIS_HOST not set",
    )
    def test_real_redis_get_all_tasks_ignores_queue_keys(self):
        """A real Redis List queue must not be misread as a Hash by the task list."""
        state = RedisState(
            host=os.environ["MPT_TEST_REDIS_HOST"],
            port=int(os.getenv("MPT_TEST_REDIS_PORT", "6379")),
            db=int(os.getenv("MPT_TEST_REDIS_DB", "15")),
        )
        suffix = uuid.uuid4()
        task_ids = [f"ci-list-{suffix}-{index}" for index in range(3)]
        queue_key = f"ci-queue-{suffix}"

        try:
            for task_id in task_ids:
                state.update_task(
                    task_id,
                    state=const.TASK_STATE_COMPLETE,
                    progress=100,
                )
            state._redis.rpush(queue_key, *task_ids)

            tasks, _ = state.get_all_tasks(page=1, page_size=1000)
            returned_ids = {task["task_id"] for task in tasks}

            self.assertTrue(set(task_ids).issubset(returned_ids))
            self.assertNotIn(queue_key, returned_ids)
        finally:
            state._redis.delete(queue_key, *task_ids)

    def test_patch_task_updates_only_existing_redis_task(self):
        state = self._build_state([1])

        self.assertTrue(
            state.patch_task(
                "task:0",
                cross_post_state=const.CROSS_POST_STATE_FAILED,
                cross_post_error="upload failed",
            )
        )
        task = state.get_task("task:0")
        self.assertEqual(task["progress"], 0)
        self.assertEqual(task["cross_post_state"], const.CROSS_POST_STATE_FAILED)
        self.assertEqual(task["cross_post_error"], "upload failed")
        self.assertFalse(state.patch_task("missing", value="ignored"))

    @unittest.skipUnless(
        os.getenv("MPT_TEST_REDIS_HOST"),
        "MPT_TEST_REDIS_HOST not set",
    )
    def test_real_redis_patch_and_delete_are_atomic(self):
        """Concurrent deletes and partial updates on real Redis must not recreate incomplete tasks."""
        state = RedisState(
            host=os.environ["MPT_TEST_REDIS_HOST"],
            port=int(os.getenv("MPT_TEST_REDIS_PORT", "6379")),
            db=int(os.getenv("MPT_TEST_REDIS_DB", "15")),
        )

        for _ in range(50):
            task_id = f"ci-atomic-{uuid.uuid4()}"
            state.update_task(
                task_id,
                state=const.TASK_STATE_COMPLETE,
                progress=100,
            )
            barrier = threading.Barrier(2)

            def patch_task():
                barrier.wait()
                state.patch_task(
                    task_id,
                    cross_post_state=const.CROSS_POST_STATE_COMPLETE,
                )

            def delete_task():
                barrier.wait()
                state.delete_task(task_id)

            # Future.result() re-raises the worker-thread exception into the test thread, so an actually failed
            # Redis command cannot pass unnoticed with only a printed thread exception.
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(patch_task),
                    executor.submit(delete_task),
                ]
                for future in futures:
                    future.result(timeout=5)

            self.assertIsNone(state.get_task(task_id))


if __name__ == "__main__":
    unittest.main()
