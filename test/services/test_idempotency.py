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
from app.controllers.manager.redis_manager import FUNC_MAP, RedisTaskManager
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

    def test_thread_start_failure_is_retried_until_accepted_work_dispatches(self):
        self.assertEqual(
            self.state.reserve_idempotent_task("task-2", "hash-2", "owner-1"),
            const.IDEMPOTENCY_CREATED,
        )

        dispatched = threading.Event()
        attempts = 0

        def fail_once_then_dispatch(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("thread start failed")
            dispatched.set()

        original_execute = self.manager.execute_task
        self.manager.execute_task = fail_once_then_dispatch
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
            self.assertTrue(dispatched.wait(timeout=2))
        finally:
            self.manager.stop_dispatcher()
            self.manager.execute_task = original_execute

        self.assertEqual(outcome, const.IDEMPOTENCY_ACCEPTED)
        self.assertGreaterEqual(attempts, 2)
        self.assertEqual(self.manager.current_tasks, 1)
        self.assertEqual(self.manager.queue_size(), 0)
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
        self.extra_managers = []

    def tearDown(self):
        self.manager.stop_dispatcher()
        for manager in self.extra_managers:
            manager.stop_dispatcher()

    def test_startup_dispatches_work_accepted_before_process_restart(self):
        self.manager.current_tasks = self.manager.max_concurrent_tasks
        self.state.reserve_idempotent_task(
            "restart-task", "restart-hash", "owner-1"
        )
        outcome = self.manager.submit_idempotent(
            state=self.state,
            task_id="restart-task",
            params_hash="restart-hash",
            owner_token="owner-1",
            task_fields={"state": const.TASK_STATE_QUEUED},
            func=tm.start,
            task_kwargs={"task_id": "restart-task"},
        )
        self.assertEqual(outcome, const.IDEMPOTENCY_ACCEPTED)
        self.assertEqual(self.manager.queue_size(), 1)

        dispatched = threading.Event()
        self.manager.execute_task = lambda *args, **kwargs: dispatched.set()
        self.manager.current_tasks = 0
        self.manager.start_dispatcher()

        self.assertTrue(dispatched.wait(timeout=2))
        self.assertEqual(self.manager.queue_size(), 0)

    def test_two_redis_dispatchers_claim_distinct_jobs_without_loss(self):
        second_manager = self._new_manager()
        self.extra_managers.append(second_manager)
        for task_id in ("durable-task-a", "durable-task-b"):
            self.manager.enqueue(
                {
                    "func": tm.start,
                    "args": (),
                    "kwargs": {"task_id": task_id},
                }
            )

        started = []
        started_lock = threading.Lock()
        both_starting = threading.Barrier(2)

        def record_start(*args, **kwargs):
            with started_lock:
                started.append(kwargs["task_id"])
            both_starting.wait(timeout=2)

        self.manager.execute_task = record_start
        second_manager.execute_task = record_start
        dispatchers = [
            threading.Thread(target=manager.check_queue)
            for manager in (self.manager, second_manager)
        ]
        for dispatcher in dispatchers:
            dispatcher.start()
        for dispatcher in dispatchers:
            dispatcher.join(timeout=2)

        self.assertEqual(
            sorted(started), ["durable-task-a", "durable-task-b"]
        )
        self.assertEqual(self.manager.queue_size(), 0)

    def test_acknowledgement_failure_does_not_release_slot_or_lose_next_job(self):
        second_manager = self._new_manager()
        self.extra_managers.append(second_manager)
        started = []

        def acknowledged_start(task_id):
            started.append(task_id)
            self.state.update_task(
                task_id, state=const.TASK_STATE_COMPLETE, progress=100
            )

        FUNC_MAP[acknowledged_start.__name__] = acknowledged_start
        for task_id in ("ack-task-a", "ack-task-b"):
            self.manager.enqueue(
                {
                    "func": acknowledged_start,
                    "args": (),
                    "kwargs": {"task_id": task_id},
                }
            )

        original_acknowledge = self.manager.acknowledge_dispatch
        ack_attempts = 0

        def fail_first_acknowledgement(task):
            nonlocal ack_attempts
            ack_attempts += 1
            if ack_attempts == 1:
                raise RuntimeError("ambiguous Redis acknowledgement")
            original_acknowledge(task)

        self.manager.acknowledge_dispatch = fail_first_acknowledgement
        try:
            self.manager.check_queue()
            second_manager.check_queue()

            deadline = time.monotonic() + 2
            while (
                (ack_attempts < 2 or len(started) < 2)
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
        finally:
            FUNC_MAP.pop(acknowledged_start.__name__, None)
        self.assertEqual(started, ["ack-task-a", "ack-task-b"])
        self.assertEqual(self.manager.current_tasks, 0)
        self.assertEqual(second_manager.current_tasks, 0)
        self.assertGreaterEqual(ack_attempts, 2)
        self.assertEqual(self.manager.queue_size(), 0)

    def test_expired_claim_is_recovered_by_another_redis_dispatcher(self):
        recovering_manager = self._new_manager()
        self.extra_managers.append(recovering_manager)
        self.manager._DISPATCH_CLAIM_SECONDS = 0.05
        self.manager.enqueue(
            {
                "func": tm.start,
                "args": (),
                "kwargs": {"task_id": "crashed-owner-task"},
            }
        )
        claimed = self.manager.dequeue()
        self.assertEqual(claimed["kwargs"]["task_id"], "crashed-owner-task")
        self.assertEqual(self.manager.queue_size(), 0)

        dispatched = threading.Event()
        recovering_manager.execute_task = lambda *args, **kwargs: dispatched.set()
        recovering_manager.start_dispatcher()

        self.assertTrue(dispatched.wait(timeout=2))
        self.assertEqual(recovering_manager.queue_size(), 0)

    def test_active_dispatch_claim_does_not_appear_in_task_listing(self):
        self.state.update_task("listed-task", state=const.TASK_STATE_QUEUED)
        self.manager.enqueue(
            {
                "func": tm.start,
                "args": (),
                "kwargs": {"task_id": "claimed-task"},
            }
        )
        self.manager.dequeue()

        tasks, total = self.state.get_all_tasks(page=1, page_size=10)

        self.assertEqual(total, 1)
        self.assertEqual([task["task_id"] for task in tasks], ["listed-task"])

    def test_wrong_type_dispatch_deadline_key_cannot_partially_claim_job(self):
        self.manager.enqueue(
            {
                "func": tm.start,
                "args": (),
                "kwargs": {"task_id": "wrong-deadline-type-task"},
            }
        )
        self.redis_client.set(
            self.manager._processing_deadlines_key, "not-a-sorted-set"
        )

        with self.assertRaises(TypeError):
            self.manager.check_queue()

        self.assertEqual(self.manager.queue_size(), 1)
        claim_keys = [
            key
            for key in self.redis_client.scan_iter("task_queue:processing:*")
            if key != self.manager._processing_deadlines_key.encode("utf-8")
        ]
        self.assertEqual(claim_keys, [])

    def test_dispatch_claim_remains_recoverable_until_worker_finishes(self):
        worker_started = threading.Event()
        allow_finish = threading.Event()
        task_finished = threading.Event()
        started_tasks = []

        def controlled_start(task_id):
            started_tasks.append(task_id)
            self.state.update_task(
                task_id, state=const.TASK_STATE_PROCESSING, progress=5
            )
            worker_started.set()
            allow_finish.wait(timeout=2)
            self.state.update_task(
                task_id, state=const.TASK_STATE_COMPLETE, progress=100
            )
            task_finished.set()

        FUNC_MAP[controlled_start.__name__] = controlled_start
        self.manager._DISPATCH_CLAIM_SECONDS = 0.3
        shutdown = None
        try:
            self.manager.enqueue(
                {
                    "func": controlled_start,
                    "args": (),
                    "kwargs": {"task_id": "running-claim-task"},
                }
            )
            self.manager.start_dispatcher()
            self.assertTrue(worker_started.wait(timeout=2))
            time.sleep(0.05)

            claim_pattern = "task_queue:processing:*"
            active_claims = [
                key
                for key in self.redis_client.scan_iter(claim_pattern)
                if key != self.manager._processing_deadlines_key.encode("utf-8")
            ]
            self.assertEqual(len(active_claims), 1)

            self.manager.enqueue(
                {
                    "func": controlled_start,
                    "args": (),
                    "kwargs": {"task_id": "queued-during-shutdown"},
                }
            )
            shutdown = threading.Thread(
                target=self.manager.stop_dispatcher_when_idle
            )
            shutdown.start()
            time.sleep(0.5)
            self.manager.recover_expired_dispatches()
            self.assertTrue(shutdown.is_alive())
            self.assertEqual(self.manager.queue_size(), 1)
        finally:
            allow_finish.set()
            FUNC_MAP.pop(controlled_start.__name__, None)

        self.assertTrue(task_finished.wait(timeout=2))
        self.assertIsNotNone(shutdown)
        shutdown.join(timeout=2)
        self.assertFalse(shutdown.is_alive())
        deadline = time.monotonic() + 2
        while self.manager.current_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        active_claims = [
            key
            for key in self.redis_client.scan_iter("task_queue:processing:*")
            if key != self.manager._processing_deadlines_key.encode("utf-8")
        ]
        self.assertEqual(active_claims, [])
        self.assertEqual(started_tasks, ["running-claim-task"])
        self.assertEqual(self.manager.queue_size(), 1)

    def test_unexpected_worker_failure_expires_claim_and_retries_work(self):
        completed = threading.Event()
        attempts = 0

        def recoverable_start(task_id):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("worker exited before durable completion")
            self.state.update_task(
                task_id, state=const.TASK_STATE_COMPLETE, progress=100
            )
            completed.set()

        FUNC_MAP[recoverable_start.__name__] = recoverable_start
        self.manager._DISPATCH_CLAIM_SECONDS = 0.15
        try:
            self.manager.enqueue(
                {
                    "func": recoverable_start,
                    "args": (),
                    "kwargs": {"task_id": "recover-worker-task"},
                }
            )
            self.manager.start_dispatcher()
            self.assertTrue(completed.wait(timeout=2))
        finally:
            FUNC_MAP.pop(recoverable_start.__name__, None)

        self.assertEqual(attempts, 2)
        self.assertEqual(
            self.state.get_task("recover-worker-task")["state"],
            const.TASK_STATE_COMPLETE,
        )
        self.assertEqual(self.manager.queue_size(), 0)

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
