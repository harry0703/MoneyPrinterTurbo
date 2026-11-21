"""Queue capacity is shared by every manager using the Redis list."""

import os
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

import redis

from app.controllers.manager.base_manager import TaskQueueFullError
from app.controllers.manager.redis_manager import RedisTaskManager
from app.models import const
from app.models.schema import VideoParams
from app.services import state as sm
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
        self.addCleanup(
            self.managers[0].redis_client.delete,
            queue,
            f"{queue}:running",
            f"{queue}:running:tasks",
        )
        # A slot and the task it runs are settled in one Redis operation, so
        # the task records have to live in the same Redis as the queue.
        state_patcher = patch.object(
            sm, "state", sm.RedisState(host=host, port=port, db=db)
        )
        self.state = state_patcher.start()
        self.addCleanup(state_patcher.stop)
        self.addCleanup(self.state._redis.close)
        self._task_ids = {}

    def _id(self, name):
        """Return this test's own ID for ``name``; the record is removed after."""
        if name not in self._task_ids:
            self._task_ids[name] = f"{name}-{uuid4()}"
            self.addCleanup(self.state.delete_task, self._task_ids[name])
        return self._task_ids[name]

    def _slot_of(self, manager, task_id):
        owners = manager.redis_client.hgetall(manager.running_tasks_key)
        tokens = [
            token.decode("utf-8")
            for token, owner in owners.items()
            if owner.decode("utf-8") == task_id
        ]
        self.assertEqual(len(tokens), 1)
        return tokens[0]

    def _wait_until_idle(self, manager):
        deadline = time.monotonic() + 5
        while manager.current_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(manager.current_tasks, 0)

    def _admit_task_whose_worker_dies(self, manager, task_id, progress=30):
        """Reserve a running slot the way add_task() does, without a worker."""
        self.state.update_task(task_id, progress=progress)
        with patch.object(manager, "execute_task"):
            manager.add_task(
                tm.start,
                task_id=task_id,
                params=VideoParams(video_subject="Coffee"),
            )
        return self._slot_of(manager, task_id)

    def test_expired_slot_fails_the_task_its_worker_left_processing(self):
        manager = self.managers[0]
        manager.max_concurrent_tasks = 1
        token = self._admit_task_whose_worker_dies(manager, self._id("crashed"))

        # The lease is still valid: the worker may simply be busy.
        self.assertEqual(manager.fail_tasks_of_expired_slots(), 0)
        self.assertEqual(
            self.state.get_task(self._id("crashed"))["state"], const.TASK_STATE_PROCESSING
        )

        # No heartbeat renews the lease of a killed process.
        manager.redis_client.zadd(manager.running_slots_key, {token: 0})
        self.assertEqual(self.managers[1].fail_tasks_of_expired_slots(), 1)

        task = self.state.get_task(self._id("crashed"))
        self.assertEqual(task["state"], const.TASK_STATE_FAILED)
        self.assertEqual(task["failed_stage"], "worker")
        self.assertIn("worker process stopped", task["error"])
        self.assertEqual(task["progress"], 30)
        self.assertFalse(tm.is_task_busy(task))
        self.assertEqual(manager.redis_client.hlen(manager.running_tasks_key), 0)
        self.assertEqual(manager.fail_tasks_of_expired_slots(), 0)

    def test_task_is_failed_after_a_new_request_reclaimed_its_slot(self):
        manager = self.managers[0]
        for item in self.managers:
            item.max_concurrent_tasks = 1
        token = self._admit_task_whose_worker_dies(manager, self._id("crashed"))
        manager.redis_client.zadd(manager.running_slots_key, {token: 0})

        # Admission prunes the expired lease and gives the slot to the new
        # task, so the crashed slot no longer has a deadline to compare.
        replacement = self._admit_task_whose_worker_dies(
            self.managers[1], self._id("replacement"), progress=0
        )
        self.assertIsNone(
            manager.redis_client.zscore(manager.running_slots_key, token)
        )

        self.assertEqual(manager.fail_tasks_of_expired_slots(), 1)
        self.assertEqual(
            self.state.get_task(self._id("crashed"))["state"], const.TASK_STATE_FAILED
        )
        self.assertEqual(
            self.state.get_task(self._id("replacement"))["state"],
            const.TASK_STATE_PROCESSING,
        )
        self.assertEqual(
            manager.redis_client.hkeys(manager.running_tasks_key),
            [replacement.encode("utf-8")],
        )

    def test_expired_slot_keeps_the_result_of_a_finished_task(self):
        manager = self.managers[0]
        manager.max_concurrent_tasks = 1
        token = self._admit_task_whose_worker_dies(manager, self._id("finished"))
        # The worker finished, then lost Redis before releasing its slot.
        self.state.update_task(
            self._id("finished"),
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            videos=["final-1.mp4"],
        )
        manager.redis_client.zadd(manager.running_slots_key, {token: 0})

        self.assertEqual(manager.fail_tasks_of_expired_slots(), 0)

        task = self.state.get_task(self._id("finished"))
        self.assertEqual(task["state"], const.TASK_STATE_COMPLETE)
        self.assertEqual(task["videos"], ["final-1.mp4"])
        self.assertNotIn("error", task)
        self.assertEqual(manager.redis_client.hlen(manager.running_tasks_key), 0)

    def test_finished_worker_leaves_no_running_task_behind(self):
        manager = self.managers[0]
        manager.max_concurrent_tasks = 1
        self.state.update_task(self._id("done"))

        def finish(task_id):
            self.state.update_task(
                task_id, state=const.TASK_STATE_COMPLETE, progress=100
            )

        manager.add_task(finish, task_id=self._id("done"))
        self._wait_until_idle(manager)
        self.assertEqual(manager.redis_client.hlen(manager.running_tasks_key), 0)
        self.assertEqual(manager.redis_client.zcard(manager.running_slots_key), 0)
        self.assertEqual(manager.fail_tasks_of_expired_slots(), 0)
        self.assertEqual(
            self.state.get_task(self._id("done"))["state"], const.TASK_STATE_COMPLETE
        )

    def test_restart_dispatcher_fails_the_task_of_a_crashed_worker(self):
        manager = self.managers[0]
        manager.max_concurrent_tasks = 1
        token = self._admit_task_whose_worker_dies(manager, self._id("crashed"))
        manager.redis_client.zadd(manager.running_slots_key, {token: 0})

        # A replacement process only runs its lifespan startup.
        restarted = self.managers[1]
        restarted.max_concurrent_tasks = 1
        restarted.resume_queued_tasks()
        restarted.start_queue_dispatcher()
        self.addCleanup(restarted.stop_queue_dispatcher)

        deadline = time.monotonic() + 2
        while (
            self.state.get_task(self._id("crashed"))["state"] == const.TASK_STATE_PROCESSING
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)

        task = self.state.get_task(self._id("crashed"))
        self.assertEqual(task["state"], const.TASK_STATE_FAILED)
        self.assertEqual(task["failed_stage"], "worker")

    def test_slot_renewed_after_it_was_listed_as_expired_is_left_alone(self):
        manager = self.managers[0]
        manager.max_concurrent_tasks = 1
        task_id = self._id("slow")
        token = self._admit_task_whose_worker_dies(manager, task_id)
        manager.redis_client.zadd(manager.running_slots_key, {token: 0})

        # The worker was only slow: its heartbeat renews the lease after the
        # expired slots were listed and before its task is failed.
        list_expired = manager.redis_client.eval

        def renew_after_listing(*args, **kwargs):
            listed = list_expired(*args, **kwargs)
            manager.redis_client.zadd(
                manager.running_slots_key, {token: manager._lease_deadline_ms()}
            )
            return listed

        with patch.object(
            manager.redis_client, "eval", side_effect=renew_after_listing
        ):
            self.assertEqual(manager.fail_tasks_of_expired_slots(), 0)

        self.assertEqual(
            self.state.get_task(task_id)["state"], const.TASK_STATE_PROCESSING
        )
        self.assertEqual(self._slot_of(manager, task_id), token)

    def test_task_that_completes_during_the_expiry_check_keeps_its_result(self):
        manager = self.managers[0]
        manager.max_concurrent_tasks = 1
        task_id = self._id("just-finished")
        token = self._admit_task_whose_worker_dies(manager, task_id)
        manager.redis_client.zadd(manager.running_slots_key, {token: 0})

        # The worker writes its result at the last moment: after the expiry
        # check has seen the task as processing, right before it writes.
        worker = redis.Redis(
            connection_pool=manager.redis_client.connection_pool
        )
        write = self.state._redis.eval

        def complete_before_write(*args, **kwargs):
            worker.hset(
                task_id,
                mapping={
                    "state": const.TASK_STATE_COMPLETE,
                    "progress": 100,
                    "videos": "['final-1.mp4']",
                },
            )
            return write(*args, **kwargs)

        with patch.object(
            self.state._redis, "eval", side_effect=complete_before_write
        ):
            self.assertEqual(manager.fail_tasks_of_expired_slots(), 0)

        task = self.state.get_task(task_id)
        self.assertEqual(task["state"], const.TASK_STATE_COMPLETE)
        self.assertEqual(task["progress"], 100)
        self.assertEqual(task["videos"], ["final-1.mp4"])
        self.assertNotIn("failed_stage", task)
        self.assertNotIn("error", task)

    def test_crash_right_after_admission_leaves_a_task_that_can_be_failed(self):
        manager = self.managers[0]
        manager.max_concurrent_tasks = 1
        task_id = self._id("admitted")
        self.state.update_task(task_id)

        # The process dies as soon as the admission script has returned.
        with patch.object(manager, "_start_reserved_task"):
            manager.add_task(
                tm.start,
                task_id=task_id,
                params=VideoParams(video_subject="Coffee"),
            )
        [token] = manager.redis_client.zrange(manager.running_slots_key, 0, -1)
        manager.redis_client.zadd(manager.running_slots_key, {token: 0})

        self.assertEqual(self.managers[1].fail_tasks_of_expired_slots(), 1)
        task = self.state.get_task(task_id)
        self.assertEqual(task["state"], const.TASK_STATE_FAILED)
        self.assertEqual(task["failed_stage"], "worker")
        self.assertFalse(tm.is_task_busy(task))

    def test_crash_right_after_queue_pickup_leaves_a_task_that_can_be_failed(self):
        manager = self.managers[0]
        manager.max_concurrent_tasks = 1
        task_id = self._id("picked-up")
        self.state.update_task(task_id)
        manager.enqueue({"func": tm.start, "args": (), "kwargs": {
            "task_id": task_id, "params": VideoParams(video_subject="Coffee")
        }})

        # The process dies after the claim script popped the queue item and
        # reserved its slot, before any Python code handled the payload.
        with patch.object(manager, "_start_reserved_task"):
            manager.check_queue()
        self.assertEqual(manager.queue_size(), 0)
        [token] = manager.redis_client.zrange(manager.running_slots_key, 0, -1)
        manager.redis_client.zadd(manager.running_slots_key, {token: 0})

        self.assertEqual(self.managers[1].fail_tasks_of_expired_slots(), 1)
        task = self.state.get_task(task_id)
        self.assertEqual(task["state"], const.TASK_STATE_FAILED)
        self.assertEqual(task["failed_stage"], "worker")
        self.assertEqual(task["progress"], 0)
        self.assertFalse(tm.is_task_busy(task))
        self.assertEqual(manager.redis_client.hlen(manager.running_tasks_key), 0)

    def _run_worker_that_pauses(self, manager, task_id, outcome):
        """Start a worker that stops mid-task until the returned event is set."""
        self.state.update_task(task_id)
        paused = threading.Event()
        resumed = threading.Event()
        self.addCleanup(resumed.set)

        def pipeline(task_id):
            self.state.update_task(task_id, progress=30)
            paused.set()
            resumed.wait(timeout=5)
            outcome["patched"] = self.state.patch_task(
                task_id, generation_activity={"phase": "rendering"}
            )
            try:
                self.state.update_task(
                    task_id,
                    state=const.TASK_STATE_COMPLETE,
                    progress=100,
                    videos=["final-1.mp4"],
                )
            except Exception as exc:
                outcome["error"] = exc

        manager.add_task(pipeline, task_id=task_id)
        self.assertTrue(paused.wait(timeout=5))
        return resumed

    def test_worker_that_lost_its_slot_cannot_bring_back_a_deleted_task(self):
        manager = self.managers[0]
        manager.max_concurrent_tasks = 1
        task_id = self._id("paused")
        outcome = {}
        resumed = self._run_worker_that_pauses(manager, task_id, outcome)
        token = self._slot_of(manager, task_id)

        # No heartbeat while the process is stopped. Another API process
        # fails the task, and the user deletes it.
        manager.redis_client.zadd(manager.running_slots_key, {token: 0})
        self.assertEqual(self.managers[1].fail_tasks_of_expired_slots(), 1)
        self.assertEqual(
            self.state.get_task(task_id)["state"], const.TASK_STATE_FAILED
        )
        self.state.delete_task(task_id)

        resumed.set()
        self._wait_until_idle(manager)

        self.assertIsNone(self.state.get_task(task_id))
        self.assertFalse(outcome["patched"])
        self.assertIsInstance(outcome["error"], sm.TaskOwnershipLostError)

    def test_worker_that_lost_its_slot_cannot_overwrite_the_failure(self):
        manager = self.managers[0]
        manager.max_concurrent_tasks = 1
        task_id = self._id("paused")
        outcome = {}
        resumed = self._run_worker_that_pauses(manager, task_id, outcome)
        token = self._slot_of(manager, task_id)
        manager.redis_client.zadd(manager.running_slots_key, {token: 0})
        self.assertEqual(self.managers[1].fail_tasks_of_expired_slots(), 1)

        resumed.set()
        self._wait_until_idle(manager)

        task = self.state.get_task(task_id)
        self.assertEqual(task["state"], const.TASK_STATE_FAILED)
        self.assertEqual(task["failed_stage"], "worker")
        self.assertEqual(task["progress"], 30)
        self.assertNotIn("videos", task)
        self.assertNotIn("generation_activity", task)
        self.assertIsInstance(outcome["error"], sm.TaskOwnershipLostError)

    def test_worker_that_still_holds_its_slot_writes_its_result(self):
        manager = self.managers[0]
        manager.max_concurrent_tasks = 1
        task_id = self._id("running")
        outcome = {}
        resumed = self._run_worker_that_pauses(manager, task_id, outcome)

        self.assertEqual(self.managers[1].fail_tasks_of_expired_slots(), 0)
        resumed.set()
        self._wait_until_idle(manager)

        task = self.state.get_task(task_id)
        self.assertEqual(task["state"], const.TASK_STATE_COMPLETE)
        self.assertEqual(task["videos"], ["final-1.mp4"])
        self.assertEqual(task["generation_activity"], {"phase": "rendering"})
        self.assertTrue(outcome["patched"])
        self.assertNotIn("error", outcome)

    def test_task_directory_is_held_until_its_worker_stops(self):
        manager = self.managers[0]
        manager.max_concurrent_tasks = 1
        task_id = self._id("paused")
        resumed = self._run_worker_that_pauses(manager, task_id, {})
        token = self._slot_of(manager, task_id)
        manager.redis_client.zadd(manager.running_slots_key, {token: 0})
        self.assertEqual(self.managers[1].fail_tasks_of_expired_slots(), 1)

        # The task is failed and no longer busy, but its worker still exists
        # and writes the task directory as soon as it resumes.
        self.assertFalse(tm.is_task_busy(self.state.get_task(task_id)))
        self.assertTrue(tm.is_task_directory_held(task_id))

        resumed.set()
        self._wait_until_idle(manager)
        self.assertFalse(tm.is_task_directory_held(task_id))

    def test_running_limit_is_shared_across_manager_instances(self):
        for manager in self.managers:
            manager.max_concurrent_tasks = 1

        with (
            patch.object(self.managers[0], "execute_task") as first_execute,
            patch.object(self.managers[1], "execute_task") as second_execute,
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(
                    pool.map(
                        lambda item: item[0].add_task(
                            tm.start,
                            task_id=item[1],
                            params=VideoParams(video_subject="Coffee"),
                        ),
                        zip(self.managers, ("first", "second")),
                    )
                )

        self.assertEqual(first_execute.call_count + second_execute.call_count, 1)
        self.assertEqual(self.managers[0].redis_client.zcard(
            self.managers[0].running_slots_key
        ), 1)
        self.assertEqual(self.managers[0].queue_size(), 1)

    def test_expired_running_slot_is_reclaimed(self):
        manager = self.managers[0]
        manager.max_concurrent_tasks = 1
        manager.redis_client.zadd(manager.running_slots_key, {"crashed": 0})

        with patch.object(manager, "execute_task") as execute_task:
            manager.add_task(
                tm.start,
                task_id="replacement",
                params=VideoParams(video_subject="Coffee"),
            )

        execute_task.assert_called_once()
        self.assertIsNone(manager.redis_client.zscore(
            manager.running_slots_key, "crashed"
        ))

    def test_restart_dispatcher_claims_queue_when_crashed_lease_expires(self):
        manager = self.managers[0]
        manager.max_concurrent_tasks = 1
        manager.enqueue({"func": tm.start, "args": (), "kwargs": {
            "task_id": "persisted", "params": VideoParams(video_subject="Coffee")
        }})
        manager.redis_client.zadd(
            manager.running_slots_key,
            {"crashed-worker": int(time.time() * 1000) + 200},
        )
        dispatched = threading.Event()

        with patch.object(
            manager,
            "execute_task",
            side_effect=lambda *args, **kwargs: dispatched.set(),
        ):
            manager.resume_queued_tasks()
            self.assertFalse(dispatched.is_set())
            manager.start_queue_dispatcher()
            self.addCleanup(manager.stop_queue_dispatcher)
            self.assertTrue(dispatched.wait(timeout=2))

        self.assertEqual(manager.queue_size(), 0)
        self.assertIsNone(manager.redis_client.zscore(
            manager.running_slots_key, "crashed-worker"
        ))

    def test_simultaneous_managers_cannot_exceed_shared_capacity(self):
        # Start both process-local managers together without coupling the test
        # to a particular Redis command inside add_task(). The Lua admission
        # script is the synchronization boundary now, so mocking queue_size()
        # would only test an obsolete implementation detail.
        barrier = threading.Barrier(2)

        def add(manager):
            barrier.wait(timeout=5)
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
