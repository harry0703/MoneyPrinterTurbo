import sys
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

    def test_thread_start_failure_keeps_accepted_work_queued(self):
        self.assertEqual(
            self.state.reserve_idempotent_task("task-2", "hash-2", "owner-1"),
            const.IDEMPOTENCY_CREATED,
        )

        original_execute = self.manager.execute_task
        self.manager.execute_task = lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("thread start failed")
        )
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
            self.state.get_idempotency("task-2")["phase"],
            const.IDEMPOTENCY_PHASE_ACCEPTED,
        )


class TestMemorySubmissionAcceptance(
    _SubmissionAcceptanceContract, unittest.TestCase
):
    def setUp(self):
        self.state = MemoryState()
        self.manager = InMemoryTaskManager(max_concurrent_tasks=1, max_queued_tasks=2)


class TestRedisSubmissionAcceptance(_SubmissionAcceptanceContract, unittest.TestCase):
    def setUp(self):
        redis_client = fakeredis.FakeStrictRedis()
        state = RedisState.__new__(RedisState)
        state._redis = redis_client
        manager = RedisTaskManager.__new__(RedisTaskManager)
        manager.redis_client = redis_client
        TaskManager.__init__(manager, max_concurrent_tasks=1, max_queued_tasks=2)
        self.state = state
        self.manager = manager

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


if __name__ == "__main__":
    unittest.main()
