import sys
import json
import threading
import time
import unittest
from pathlib import Path

import fakeredis

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models import const
from app.controllers.manager.base_manager import TaskManager
from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.controllers.manager.redis_manager import RedisTaskManager
from app.services import task as tm
from app.services.state import MemoryState, RedisState


class _IdempotencyClaimContract:
    """Shared claim/lease contract for the memory and Redis adapters."""

    def test_first_owner_claims_pending_submission(self):
        outcome = self.state.reserve_idempotent_task("k1", "h1", "owner-1")
        self.assertEqual(outcome, const.IDEMPOTENCY_CREATED)
        self.assertEqual(
            self.state.get_idempotency("k1"),
            {
                "params_hash": "h1",
                "phase": const.IDEMPOTENCY_PHASE_PENDING,
                "owner_token": "owner-1",
            },
        )

    def test_identical_request_observes_live_pending_owner(self):
        self.state.reserve_idempotent_task("k1", "h1", "owner-1")
        outcome = self.state.reserve_idempotent_task("k1", "h1", "owner-2")
        self.assertEqual(outcome, const.IDEMPOTENCY_PENDING)

    def test_different_parameters_conflict_while_pending(self):
        self.state.reserve_idempotent_task("k1", "h1", "owner-1")
        outcome = self.state.reserve_idempotent_task("k1", "h2", "owner-2")
        self.assertEqual(outcome, const.IDEMPOTENCY_CONFLICT)

    def test_owner_abort_makes_claim_immediately_recoverable(self):
        self.state.reserve_idempotent_task("k1", "h1", "owner-1")
        self.assertTrue(self.state.abort_idempotent_task("k1", "owner-1"))
        outcome = self.state.reserve_idempotent_task("k1", "h1", "owner-2")
        self.assertEqual(outcome, const.IDEMPOTENCY_CREATED)

    def test_stale_owner_cannot_abort_newer_claim(self):
        self.state.reserve_idempotent_task(
            "k1", "h1", "owner-1", lease_seconds=0.05
        )
        time.sleep(0.06)
        self.assertEqual(
            self.state.reserve_idempotent_task("k1", "h1", "owner-2"),
            const.IDEMPOTENCY_CREATED,
        )
        self.assertFalse(self.state.abort_idempotent_task("k1", "owner-1"))
        self.assertEqual(
            self.state.get_idempotency("k1")["owner_token"], "owner-2"
        )

    def test_concurrent_identical_claims_have_one_owner(self):
        results = []
        results_lock = threading.Lock()

        def reserve(index):
            outcome = self.state.reserve_idempotent_task(
                "same-key", "same-hash", f"owner-{index}"
            )
            with results_lock:
                results.append(outcome)

        threads = [threading.Thread(target=reserve, args=(index,)) for index in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(results.count(const.IDEMPOTENCY_CREATED), 1)
        self.assertEqual(results.count(const.IDEMPOTENCY_PENDING), 19)


class TestMemoryStateIdempotency(_IdempotencyClaimContract, unittest.TestCase):
    def setUp(self):
        self.state = MemoryState()


class TestRedisStateIdempotency(_IdempotencyClaimContract, unittest.TestCase):
    def setUp(self):
        state = RedisState.__new__(RedisState)
        state._redis = fakeredis.FakeStrictRedis()
        self.state = state


class _SubmissionAcceptanceContract:
    """The state adapter and real queue manager publish acceptance together."""

    def test_accepted_submission_is_immediately_recoverable_while_queued(self):
        self.manager.current_tasks = self.manager.max_concurrent_tasks
        self.assertEqual(
            self.state.reserve_idempotent_task("task-1", "hash-1", "owner-1"),
            const.IDEMPOTENCY_CREATED,
        )

        outcome = self.manager.submit_idempotent(
            state=self.state,
            task_id="task-1",
            params_hash="hash-1",
            owner_token="owner-1",
            task_fields={"state": const.TASK_STATE_QUEUED, "request_id": "req-1"},
            func=tm.start,
            task_kwargs={"task_id": "task-1"},
        )

        self.assertEqual(outcome, const.IDEMPOTENCY_ACCEPTED)
        self.assertEqual(self.manager.queue_size(), 1)
        self.assertEqual(self.state.get_task("task-1")["state"], const.TASK_STATE_QUEUED)
        self.assertEqual(
            self.state.get_idempotency("task-1")["phase"],
            const.IDEMPOTENCY_PHASE_ACCEPTED,
        )
        self.assertEqual(
            self.state.reserve_idempotent_task("task-1", "hash-1", "owner-2"),
            const.IDEMPOTENCY_DUPLICATE,
        )

    def test_thread_start_failure_retains_queued_work(self):
        # 无后台 dispatcher 后，线程创建失败时 check_queue 回滚并发名额并把任务
        # 放回队列；工作保留在队列中，由下一次 check_queue（如其它任务完成时）
        # 拉起。submit_idempotent 的调用方仍安全地收到 ACCEPTED。
        self.assertEqual(
            self.state.reserve_idempotent_task("task-2", "hash-2", "owner-1"),
            const.IDEMPOTENCY_CREATED,
        )

        def always_fail(*args, **kwargs):
            raise RuntimeError("thread start failed")

        original_execute = self.manager.execute_task
        self.manager.execute_task = always_fail
        try:
            outcome = self.manager.submit_idempotent(
                state=self.state,
                task_id="task-2",
                params_hash="hash-2",
                owner_token="owner-1",
                task_fields={"state": const.TASK_STATE_QUEUED, "request_id": "req-2"},
                func=tm.start,
                task_kwargs={"task_id": "task-2"},
            )
        finally:
            self.manager.execute_task = original_execute

        self.assertEqual(outcome, const.IDEMPOTENCY_ACCEPTED)
        self.assertEqual(self.manager.current_tasks, 0)
        self.assertEqual(self.manager.queue_size(), 1)
        self.assertEqual(
            self.state.get_task("task-2")["state"], const.TASK_STATE_QUEUED
        )
        self.assertEqual(
            self.state.get_idempotency("task-2")["phase"],
            const.IDEMPOTENCY_PHASE_ACCEPTED,
        )

    def test_reaccept_after_task_deletion(self):
        # 已完成并删除的任务可以携带新的幂等键重新提交：接受流程不依赖旧记录。
        self.state.update_task(
            "task-reused", state=const.TASK_STATE_COMPLETE, progress=100
        )
        self.state.delete_task("task-reused")
        self.manager.current_tasks = self.manager.max_concurrent_tasks
        self.assertEqual(
            self.state.reserve_idempotent_task(
                "task-reused", "new-hash", "new-owner"
            ),
            const.IDEMPOTENCY_CREATED,
        )

        outcome = self.manager.submit_idempotent(
            state=self.state,
            task_id="task-reused",
            params_hash="new-hash",
            owner_token="new-owner",
            task_fields={"state": const.TASK_STATE_QUEUED},
            func=tm.start,
            task_kwargs={"task_id": "task-reused"},
        )

        self.assertEqual(outcome, const.IDEMPOTENCY_ACCEPTED)
        self.assertEqual(self.manager.queue_size(), 1)
        self.assertEqual(
            self.state.get_idempotency("task-reused")["phase"],
            const.IDEMPOTENCY_PHASE_ACCEPTED,
        )


class TestMemorySubmissionAcceptance(
    _SubmissionAcceptanceContract, unittest.TestCase
):
    def setUp(self):
        self.state = MemoryState()
        self.manager = InMemoryTaskManager(max_concurrent_tasks=1, max_queued_tasks=2)


class TestRedisSubmissionAcceptance(_SubmissionAcceptanceContract, unittest.TestCase):
    def _new_manager(self):
        manager = RedisTaskManager.__new__(RedisTaskManager)
        manager.redis_client = self.redis_client
        TaskManager.__init__(manager, max_concurrent_tasks=1, max_queued_tasks=2)
        return manager

    def setUp(self):
        self.redis_client = fakeredis.FakeStrictRedis()
        state = RedisState.__new__(RedisState)
        state._redis = self.redis_client
        self.state = state
        self.manager = self._new_manager()

    def test_task_is_not_partially_visible_before_transaction_executes(self):
        self.manager.current_tasks = self.manager.max_concurrent_tasks
        self.state.reserve_idempotent_task("task-3", "hash-3", "owner-1")
        enqueue_reached = threading.Event()
        allow_exec = threading.Event()
        original_enqueue = self.manager.enqueue_transaction

        def pause_before_exec(pipe, task):
            original_enqueue(pipe, task)
            enqueue_reached.set()
            allow_exec.wait(timeout=2)

        self.manager.enqueue_transaction = pause_before_exec
        outcomes = []

        def submit():
            outcomes.append(
                self.manager.submit_idempotent(
                    state=self.state,
                    task_id="task-3",
                    params_hash="hash-3",
                    owner_token="owner-1",
                    task_fields={
                        "state": const.TASK_STATE_QUEUED,
                        "request_id": "req-3",
                    },
                    func=tm.start,
                    task_kwargs={"task_id": "task-3"},
                )
            )

        thread = threading.Thread(target=submit)
        thread.start()
        self.assertTrue(enqueue_reached.wait(timeout=2))
        self.assertIsNone(self.state.get_task("task-3"))
        self.assertEqual(
            self.state.get_idempotency("task-3")["phase"],
            const.IDEMPOTENCY_PHASE_PENDING,
        )
        self.assertEqual(self.manager.queue_size(), 0)
        allow_exec.set()
        thread.join(timeout=2)

        self.assertEqual(outcomes, [const.IDEMPOTENCY_ACCEPTED])
        self.assertIsNotNone(self.state.get_task("task-3"))
        self.assertEqual(self.manager.queue_size(), 1)

    def test_watch_conflict_retries_without_partial_publication(self):
        self.manager.current_tasks = self.manager.max_concurrent_tasks
        self.state.reserve_idempotent_task("task-4", "hash-4", "owner-1")
        enqueue_reached = threading.Event()
        allow_exec = threading.Event()
        original_enqueue = self.manager.enqueue_transaction
        calls = 0

        def pause_first_exec(pipe, task):
            nonlocal calls
            calls += 1
            original_enqueue(pipe, task)
            if calls == 1:
                enqueue_reached.set()
                allow_exec.wait(timeout=2)

        self.manager.enqueue_transaction = pause_first_exec
        outcomes = []

        thread = threading.Thread(
            target=lambda: outcomes.append(
                self.manager.submit_idempotent(
                    state=self.state,
                    task_id="task-4",
                    params_hash="hash-4",
                    owner_token="owner-1",
                    task_fields={"state": const.TASK_STATE_QUEUED},
                    func=tm.start,
                    task_kwargs={"task_id": "task-4"},
                )
            )
        )
        thread.start()
        self.assertTrue(enqueue_reached.wait(timeout=2))
        self.state._redis.rpush(self.manager.queue, "competing-job")
        allow_exec.set()
        thread.join(timeout=2)

        self.assertEqual(outcomes, [const.IDEMPOTENCY_ACCEPTED])
        self.assertGreaterEqual(calls, 2)
        self.assertEqual(self.manager.queue_size(), 2)
        self.assertIsNotNone(self.state.get_task("task-4"))

    def test_wrong_type_task_key_never_accepts_or_enqueues(self):
        self.manager.current_tasks = self.manager.max_concurrent_tasks
        self.state.reserve_idempotent_task("task-5", "hash-5", "owner-1")
        self.state._redis.set("task-5", "collision")

        outcome = self.manager.submit_idempotent(
            state=self.state,
            task_id="task-5",
            params_hash="hash-5",
            owner_token="owner-1",
            task_fields={"state": const.TASK_STATE_QUEUED},
            func=tm.start,
            task_kwargs={"task_id": "task-5"},
        )

        self.assertEqual(outcome, const.IDEMPOTENCY_STALE)
        self.assertEqual(self.manager.queue_size(), 0)
        self.assertEqual(
            self.state.get_idempotency("task-5")["phase"],
            const.IDEMPOTENCY_PHASE_PENDING,
        )

    def test_wrong_type_queue_key_aborts_without_publishing_task(self):
        self.manager.current_tasks = self.manager.max_concurrent_tasks
        self.state.reserve_idempotent_task("task-6", "hash-6", "owner-1")
        self.state._redis.set(self.manager.queue, "not-a-list")

        with self.assertRaises(TypeError):
            self.manager.submit_idempotent(
                state=self.state,
                task_id="task-6",
                params_hash="hash-6",
                owner_token="owner-1",
                task_fields={"state": const.TASK_STATE_QUEUED},
                func=tm.start,
                task_kwargs={"task_id": "task-6"},
            )

        self.assertIsNone(self.state.get_task("task-6"))
        self.assertIsNone(self.state.get_idempotency("task-6"))
        self.assertEqual(self.state._redis.get(self.manager.queue), b"not-a-list")

    def test_serialization_failure_aborts_before_exec(self):
        self.manager.current_tasks = self.manager.max_concurrent_tasks
        self.state.reserve_idempotent_task("task-7", "hash-7", "owner-1")

        with self.assertRaises(TypeError):
            self.manager.submit_idempotent(
                state=self.state,
                task_id="task-7",
                params_hash="hash-7",
                owner_token="owner-1",
                task_fields={"state": const.TASK_STATE_QUEUED},
                func=tm.start,
                task_kwargs={"task_id": "task-7", "bad": object()},
            )

        self.assertIsNone(self.state.get_task("task-7"))
        self.assertIsNone(self.state.get_idempotency("task-7"))
        self.assertEqual(self.manager.queue_size(), 0)

    def test_lease_expiry_during_transaction_cannot_accept_stale_owner(self):
        self.manager.current_tasks = self.manager.max_concurrent_tasks
        self.state.reserve_idempotent_task(
            "task-8", "hash-8", "owner-1", lease_seconds=0.05
        )
        original_enqueue = self.manager.enqueue_transaction
        enqueue_reached = threading.Event()
        allow_exec = threading.Event()

        def expire_before_exec(pipe, task):
            original_enqueue(pipe, task)
            enqueue_reached.set()
            allow_exec.wait(timeout=2)

        self.manager.enqueue_transaction = expire_before_exec
        outcomes = []
        thread = threading.Thread(
            target=lambda: outcomes.append(
                self.manager.submit_idempotent(
                    state=self.state,
                    task_id="task-8",
                    params_hash="hash-8",
                    owner_token="owner-1",
                    task_fields={"state": const.TASK_STATE_QUEUED},
                    func=tm.start,
                    task_kwargs={"task_id": "task-8"},
                )
            )
        )
        thread.start()
        self.assertTrue(enqueue_reached.wait(timeout=2))
        # Force the key-removal event real Redis emits when the lease expires;
        # fakeredis does not invalidate WATCH from passive clock advance alone.
        self.state._redis.delete("idem:task-8")
        allow_exec.set()
        thread.join(timeout=2)

        self.assertEqual(outcomes, [const.IDEMPOTENCY_STALE])
        self.assertIsNone(self.state.get_task("task-8"))
        self.assertIsNone(self.state.get_idempotency("task-8"))
        self.assertEqual(self.manager.queue_size(), 0)

    def test_concurrent_redis_owners_accept_exactly_one_queue_item(self):
        self.manager.current_tasks = self.manager.max_concurrent_tasks
        outcomes = []
        outcomes_lock = threading.Lock()

        def submit(index):
            owner = f"owner-{index}"
            deadline = time.monotonic() + 2
            while True:
                outcome = self.state.reserve_idempotent_task(
                    "task-9", "hash-9", owner
                )
                if outcome == const.IDEMPOTENCY_CREATED:
                    outcome = self.manager.submit_idempotent(
                        state=self.state,
                        task_id="task-9",
                        params_hash="hash-9",
                        owner_token=owner,
                        task_fields={"state": const.TASK_STATE_QUEUED},
                        func=tm.start,
                        task_kwargs={"task_id": "task-9"},
                    )
                    break
                if outcome != const.IDEMPOTENCY_PENDING:
                    break
                if time.monotonic() >= deadline:
                    self.fail("pending owner did not accept before deadline")
                time.sleep(0.005)
            with outcomes_lock:
                outcomes.append(outcome)

        threads = [threading.Thread(target=submit, args=(index,)) for index in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(outcomes.count(const.IDEMPOTENCY_ACCEPTED), 1)
        self.assertEqual(outcomes.count(const.IDEMPOTENCY_DUPLICATE), 19)
        self.assertEqual(self.manager.queue_size(), 1)

    def test_stale_owner_cannot_abort_new_owner_after_acceptance(self):
        self.manager.current_tasks = self.manager.max_concurrent_tasks
        self.state.reserve_idempotent_task(
            "task-10", "hash-10", "old-owner", lease_seconds=0.02
        )
        time.sleep(0.03)
        self.assertEqual(
            self.state.reserve_idempotent_task(
                "task-10", "hash-10", "new-owner"
            ),
            const.IDEMPOTENCY_CREATED,
        )
        self.assertEqual(
            self.manager.submit_idempotent(
                state=self.state,
                task_id="task-10",
                params_hash="hash-10",
                owner_token="new-owner",
                task_fields={"state": const.TASK_STATE_QUEUED},
                func=tm.start,
                task_kwargs={"task_id": "task-10"},
            ),
            const.IDEMPOTENCY_ACCEPTED,
        )

        self.assertFalse(self.state.abort_idempotent_task("task-10", "old-owner"))
        self.assertEqual(
            self.state.get_idempotency("task-10")["phase"],
            const.IDEMPOTENCY_PHASE_ACCEPTED,
        )
        self.assertEqual(self.manager.queue_size(), 1)

    def test_accepted_record_has_24_hour_ttl(self):
        self.manager.current_tasks = self.manager.max_concurrent_tasks
        self.state.reserve_idempotent_task("task-11", "hash-11", "owner-1")
        self.manager.submit_idempotent(
            state=self.state,
            task_id="task-11",
            params_hash="hash-11",
            owner_token="owner-1",
            task_fields={"state": const.TASK_STATE_QUEUED},
            func=tm.start,
            task_kwargs={"task_id": "task-11"},
        )

        ttl = self.state._redis.ttl("idem:task-11")
        self.assertGreaterEqual(ttl, 86399)
        self.assertLessEqual(ttl, 86400)

    def test_malformed_reservation_is_rejected_without_mutation(self):
        self.state._redis.set("idem:task-12", "not-json", ex=60)

        with self.assertRaises(json.JSONDecodeError):
            self.state.reserve_idempotent_task(
                "task-12", "hash-12", "owner-1"
            )

        self.assertEqual(self.state._redis.get("idem:task-12"), b"not-json")
        self.assertIsNone(self.state.get_task("task-12"))


if __name__ == "__main__":
    unittest.main()