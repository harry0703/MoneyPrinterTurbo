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


class _RecordingTaskManager:
    """Stand-in for the production task manager.

    Captures enqueued tasks instead of spawning worker threads so the
    idempotency contract can be asserted without running real video generation.
    """

    def __init__(self):
        self.enqueued = []
        self.lock = threading.Lock()

    def add_task(self, func, *args, **kwargs):
        with self.lock:
            self.enqueued.append(kwargs.get("task_id"))


def _client_with(manager):
    video_controller.task_manager = manager
    return TestClient(asgi.app)


class TestIdempotentVideoSubmission(unittest.TestCase):
    def setUp(self):
        self.manager = _RecordingTaskManager()
        self.client = _client_with(self.manager)
        self.base_body = {
            "video_subject": "idempotent test",
            "voice_name": "zh-CN-XiaoyiNeural-Female",
            "video_source": "local",
        }

    def tearDown(self):
        # Restore the module-level singleton so other tests are unaffected.
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


class TestQueueRejectionClearsIdempotency(unittest.TestCase):
    def setUp(self):
        self.base_body = {
            "video_subject": "rejection test",
            "voice_name": "zh-CN-XiaoyiNeural-Female",
            "video_source": "local",
        }

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

    def tearDown(self):
        video_controller.task_manager = None


if __name__ == "__main__":
    unittest.main()
