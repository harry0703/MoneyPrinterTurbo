import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi.testclient import TestClient

import app.asgi as asgi
from app.controllers.v1 import video as video_controller
from app.controllers.v1.video import _task_committed, _wait_for_committed_task
from app.models import const
from app.services import state as sm


class _RecordingTaskManager:
    """Stand-in for the production task manager.

    Captures enqueued tasks instead of spawning real worker threads so the
    idempotency contract can be asserted without running video generation. It
    also mirrors the production worker's first action: on a successful enqueue
    the real worker calls `sm.state.update_task(state=PROCESSING, progress=5)`
    to transition the provisional QUEUED placeholder to COMMITTED. The duplicate
    wait-loop only returns 200 for committed records, so this transition is what
    lets duplicates resolve. Without it the placeholder stays QUEUED and the
    duplicate correctly times out — which is exactly the contract this stand-in
    exercises for the provisional-vs-committed race.
    """

    def __init__(self):
        self.enqueued = []
        self.lock = threading.Lock()

    def add_task(self, func, *args, **kwargs):
        with self.lock:
            task_id = kwargs.get("task_id")
            self.enqueued.append(task_id)
        # Simulate the worker's committed transition so a duplicate polling for
        # this task resolves to 200 (the work is genuinely accepted).
        sm.state.update_task(
            task_id, state=const.TASK_STATE_PROCESSING, progress=5
        )


def _client_with(manager):
    video_controller.task_manager = manager
    return TestClient(asgi.app)


def _flush_state():
    """Reset the MemoryState singleton between tests so they don't leak records
    into one another, which is what round-3 Standards #4 (non-blocking) flagged:
    submission tests mutated sm.state and never restored it."""
    if hasattr(sm.state, "_tasks"):
        with sm.state._lock:
            sm.state._tasks.clear()
            sm.state._idem.clear()


def _set_memory_state():
    """Replace the global state singleton with a clean MemoryState so the tests
    below run without a live Redis. The production config may bind RedisState at
    import time; these tests exercise the state adapter contract at the
    controller's seam, not the Redis client."""
    sm.state = sm.MemoryState()


class TestIdempotentVideoSubmission(unittest.TestCase):
    def setUp(self):
        _set_memory_state()
        self.manager = _RecordingTaskManager()
        self.client = _client_with(self.manager)
        _flush_state()
        self.base_body = {
            "video_subject": "idempotent test",
            "voice_name": "zh-CN-XiaoyiNeural-Female",
            "video_source": "local",
        }

    def tearDown(self):
        # Restore the module-level singleton so other tests are unaffected, and
        # flush any records this test wrote.
        _flush_state()
        video_controller.task_manager = None

    def test_backward_compatible_server_generated_id(self):
        resp = self.client.post("/api/v1/videos", json=self.base_body)
        self.assertEqual(resp.status_code, 200)
        task_id = resp.json()["data"]["task_id"]
        self.assertEqual(self.manager.enqueued, [task_id])
        self.assertNotEqual(task_id, "")

    def test_client_key_used_as_task_id_and_enqueued_once(self):
        key = "11111111-1111-1111-1111-111111111111"
        body = {**self.base_body, "idempotency_key": key}
        resp = self.client.post("/api/v1/videos", json=body)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["task_id"], key)
        self.assertEqual(self.manager.enqueued, [key])

    def test_sequential_duplicate_returns_existing_id_without_enqueue(self):
        key = "22222222-2222-2222-2222-222222222222"
        body = {**self.base_body, "idempotency_key": key}

        first = self.client.post("/api/v1/videos", json=body)
        second = self.client.post("/api/v1/videos", json=body)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["data"]["task_id"], key)
        # Exactly one task was ever enqueued for the duplicate key.
        self.assertEqual(self.manager.enqueued, [key])

    def test_payload_conflict_returns_409(self):
        key = "33333333-3333-3333-3333-333333333333"
        first_body = {**self.base_body, "idempotency_key": key}
        # Different canonical parameters (different subject) for the same key.
        conflict_body = {**self.base_body, "video_subject": "other", "idempotency_key": key}

        self.client.post("/api/v1/videos", json=first_body)
        resp = self.client.post("/api/v1/videos", json=conflict_body)

        self.assertEqual(resp.status_code, 409)
        self.assertIn("idempotency_conflict", resp.json().get("message", ""))

    def test_invalid_uuid_is_rejected_with_400(self):
        body = {**self.base_body, "idempotency_key": "not-a-uuid"}
        resp = self.client.post("/api/v1/videos", json=body)
        self.assertEqual(resp.status_code, 400)

    def test_concurrent_identical_submissions_enqueue_once(self):
        key = "44444444-4444-4444-4444-444444444444"
        body = {**self.base_body, "idempotency_key": key}

        responses = []
        lock = threading.Lock()

        def submit():
            r = self.client.post("/api/v1/videos", json=body)
            with lock:
                responses.append(r.status_code)

        threads = [threading.Thread(target=submit) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All succeeded, all returned the same client-assigned task id,
        # and exactly one task was enqueued.
        self.assertEqual(sorted(responses), [200] * 10)
        self.assertEqual(self.manager.enqueued, [key])

    def test_ambiguous_response_recovery_looks_up_client_id(self):
        key = "55555555-5555-5555-5555-555555555555"
        body = {**self.base_body, "idempotency_key": key}
        create = self.client.post("/api/v1/videos", json=body)
        task_id = create.json()["data"]["task_id"]
        # Simulate a lost response: the duplicate retry returns the same id,
        # and the client can then look the task up by that id.
        lookup = self.client.get(f"/api/v1/tasks/{task_id}")
        self.assertEqual(lookup.status_code, 200)
        self.assertEqual(lookup.json()["data"]["task_id"], key)


class TestProvisionalVsCommittedSubmission(unittest.TestCase):
    """Round-3 Standards #1 / Spec #1: a duplicate must not surface HTTP 200 for
    a provisional (QUEUED) placeholder the winner may still fail to enqueue.
    These tests prove the committed-vs-provisional distinction directly against
    the committal helper and the wait loop, without relying on concurrent HTTP
    submissions on TestClient's single event loop. The full-path HTTP proof
    (winner rejected -> reservation cleared -> retry succeeds) is covered by
    TestQueueRejectionClearsIdempotency."""

    def setUp(self):
        _set_memory_state()
        self.base_body = {
            "video_subject": "provisional test",
            "voice_name": "zh-CN-XiaoyiNeural-Female",
            "video_source": "local",
        }
        _flush_state()

    def tearDown(self):
        _flush_state()
        video_controller.task_manager = None

    def test_queued_placeholder_is_not_committed(self):
        self.assertFalse(_task_committed(None))
        self.assertFalse(
            _task_committed({"state": const.TASK_STATE_QUEUED}),
            "QUEUED placeholder must not be treated as committed",
        )

    def test_processing_and_terminal_records_are_committed(self):
        self.assertTrue(_task_committed({"state": const.TASK_STATE_PROCESSING}))
        self.assertTrue(_task_committed({"state": const.TASK_STATE_COMPLETE}))
        self.assertTrue(_task_committed({"state": const.TASK_STATE_FAILED}))

    def test_wait_returns_none_when_only_queued_is_ever_visible(self):
        # A winner that published a QUEUED placeholder then died or got stuck:
        # the duplicate polls and never sees a committed record. With a short
        # deadline override this resolves to None (-> 409) quickly.
        key = "77777777-7777-7777-7777-777777777777"
        sm.state.update_task(
            key, state=const.TASK_STATE_QUEUED, request_id="req-stuck"
        )
        with mock.patch(
            "app.controllers.v1.video._DUPLICATE_WAIT_SECONDS", 0.2
        ), mock.patch(
            "app.controllers.v1.video._DUPLICATE_POLL_INTERVAL", 0.01
        ):
            self.assertIsNone(_wait_for_committed_task(key))

    def test_wait_returns_record_once_worker_commits(self):
        # Placeholder starts QUEUED; a concurrent transition to PROCESSING
        # (worker started) makes the duplicate resolve to the committed record.
        key = "88888888-8888-8888-8888-888888888888"
        sm.state.update_task(
            key, state=const.TASK_STATE_QUEUED, request_id="req-w"
        )

        def commit_after_a_bit():
            time.sleep(0.05)
            sm.state.update_task(key, state=const.TASK_STATE_PROCESSING, progress=5)

        with mock.patch(
            "app.controllers.v1.video._DUPLICATE_WAIT_SECONDS", 2.0
        ), mock.patch(
            "app.controllers.v1.video._DUPLICATE_POLL_INTERVAL", 0.01
        ):
            threading.Thread(target=commit_after_a_bit).start()
            existing = _wait_for_committed_task(key)
        self.assertIsNotNone(existing)
        self.assertEqual(existing["state"], const.TASK_STATE_PROCESSING)

    def test_queue_full_cleanup_leaves_key_reclaimable(self):
        # After a winner publishes a QUEUED placeholder then add_task raises
        # TaskQueueFullError, the cleanup clears the reservation + placeholder.
        # The key is reclaimable on a later retry (not stranded as DUPLICATE).
        from app.controllers.manager.base_manager import TaskQueueFullError

        class _FullManager:
            def add_task(self, func, *args, **kwargs):
                raise TaskQueueFullError("task queue is full, please try again later")

        video_controller.task_manager = _FullManager()
        client = TestClient(asgi.app)
        key = "99999999-9999-9999-9999-999999999999"
        body = {**self.base_body, "idempotency_key": key}

        rejected = client.post("/api/v1/videos", json=body)
        self.assertEqual(rejected.status_code, 429)
        # Cleanup must have deleted the placeholder.
        self.assertIsNone(sm.state.get_task(key))
        # The reservation must have been cleared so the key can be re-reserved
        # when retried. We assert directly: a new reservation on the same key
        # succeeds as CREATED (not DUPLICATE or CONFLICT).
        params_hash = video_controller._canonical_params_hash(
            type("_", (), {"model_dump": staticmethod(lambda: self.base_body)})()
        )
        outcome = sm.state.reserve_idempotent_task(key, params_hash)
        self.assertEqual(
            outcome,
            const.IDEMPOTENCY_CREATED,
            "after cleanup the reservation must be gone so a retry can re-reserve",
        )


class TestQueueRejectionClearsIdempotency(unittest.TestCase):
    def setUp(self):
        _set_memory_state()
        self.base_body = {
            "video_subject": "rejection test",
            "voice_name": "zh-CN-XiaoyiNeural-Female",
            "video_source": "local",
        }
        _flush_state()

    def tearDown(self):
        _flush_state()
        video_controller.task_manager = None

    def test_queue_full_rejects_and_allows_later_retry(self):
        # Force the manager to raise TaskQueueFullError on add_task.
        from app.controllers.manager.base_manager import TaskQueueFullError

        class _FullManager:
            def add_task(self, func, *args, **kwargs):
                raise TaskQueueFullError("task queue is full, please try again later")

        video_controller.task_manager = _FullManager()
        client = TestClient(asgi.app)
        key = "66666666-6666-6666-6666-666666666666"
        body = {**self.base_body, "idempotency_key": key}

        rejected = client.post("/api/v1/videos", json=body)
        self.assertEqual(rejected.status_code, 429)

        # A legitimate retry after the queue drains must be accepted (the
        # provisional idempotency state was cleared on rejection).
        recording = _RecordingTaskManager()
        video_controller.task_manager = recording
        retry = client.post("/api/v1/videos", json=body)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json()["data"]["task_id"], key)
        self.assertEqual(recording.enqueued, [key])


if __name__ == "__main__":
    unittest.main()
