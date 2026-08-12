import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi.testclient import TestClient

import app.asgi as asgi
from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.controllers.v1 import video as video_controller
from app.models import const
from app.services import state as sm


class _RecordingTaskManager(InMemoryTaskManager):
    """Real in-memory acceptance/queue path without running video generation."""

    def __init__(self, max_concurrent_tasks=1, max_queued_tasks=100):
        super().__init__(max_concurrent_tasks, max_queued_tasks)
        self.started = []

    def execute_task(self, func, *args, **kwargs):
        self.started.append(kwargs["task_id"])


class _BrokenQueueManager(_RecordingTaskManager):
    def enqueue_transaction(self, pipeline, task):
        raise RuntimeError("injected queue failure")


class TestIdempotentVideoSubmission(unittest.TestCase):
    def setUp(self):
        self.original_state = sm.state
        self.original_manager = video_controller.task_manager
        sm.state = sm.MemoryState()
        self.manager = _RecordingTaskManager()
        video_controller.task_manager = self.manager
        self.client = TestClient(asgi.app)
        self.base_body = {
            "video_subject": "idempotent test",
            "voice_name": "zh-CN-XiaoyiNeural-Female",
            "video_source": "local",
        }

    def tearDown(self):
        video_controller.task_manager = self.original_manager
        sm.state = self.original_state

    def test_backward_compatible_server_generated_id(self):
        response = self.client.post("/api/v1/videos", json=self.base_body)
        self.assertEqual(response.status_code, 200)
        task_id = response.json()["data"]["task_id"]
        self.assertEqual(self.manager.started, [task_id])

    def test_client_key_is_accepted_and_retrievable(self):
        key = "11111111-1111-1111-1111-111111111111"
        response = self.client.post(
            "/api/v1/videos", json={**self.base_body, "idempotency_key": key}
        )
        lookup = self.client.get(f"/api/v1/tasks/{key}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["task_id"], key)
        self.assertEqual(lookup.status_code, 200)
        self.assertEqual(lookup.json()["data"]["state"], const.TASK_STATE_QUEUED)
        self.assertEqual(self.manager.started, [key])

    def test_duplicate_of_accepted_queued_work_returns_existing_id(self):
        key = "22222222-2222-2222-2222-222222222222"
        body = {**self.base_body, "idempotency_key": key}
        self.manager.current_tasks = self.manager.max_concurrent_tasks

        first = self.client.post("/api/v1/videos", json=body)
        second = self.client.post("/api/v1/videos", json=body)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["data"]["task_id"], key)
        self.assertEqual(self.manager.queue_size(), 1)
        self.assertEqual(self.manager.started, [])

    def test_queued_work_dispatches_when_capacity_returns(self):
        key = "77777777-7777-7777-7777-777777777777"
        body = {**self.base_body, "idempotency_key": key}
        self.manager.current_tasks = self.manager.max_concurrent_tasks
        first = self.client.post("/api/v1/videos", json=body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.manager.started, [])

        # 无后台 dispatcher 后，队列工作由并发工作线程完成时触发的
        # task_done -> check_queue 拉起；这里模拟一个并发槽位释放。
        with self.manager.lock:
            self.manager.current_tasks = 0
        self.manager.check_queue()

        self.assertEqual(self.manager.started, [key])
        self.assertEqual(self.manager.queue_size(), 0)

    def test_payload_conflict_returns_stable_409(self):
        key = "33333333-3333-3333-3333-333333333333"
        self.client.post(
            "/api/v1/videos", json={**self.base_body, "idempotency_key": key}
        )
        response = self.client.post(
            "/api/v1/videos",
            json={
                **self.base_body,
                "video_subject": "different",
                "idempotency_key": key,
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("idempotency_conflict", response.json()["message"])

    def test_concurrent_identical_submissions_are_accepted_once(self):
        key = "44444444-4444-4444-4444-444444444444"
        body = {**self.base_body, "idempotency_key": key}
        responses = []
        responses_lock = threading.Lock()

        def submit():
            response = self.client.post("/api/v1/videos", json=body)
            with responses_lock:
                responses.append(response.status_code)

        threads = [threading.Thread(target=submit) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(sorted(responses), [200] * 10)
        self.assertEqual(self.manager.started, [key])
        self.assertEqual(
            sm.state.get_idempotency(key)["phase"],
            const.IDEMPOTENCY_PHASE_ACCEPTED,
        )

    def test_queue_rejection_aborts_claim_and_allows_retry(self):
        key = "55555555-5555-5555-5555-555555555555"
        body = {**self.base_body, "idempotency_key": key}
        full_manager = _RecordingTaskManager(
            max_concurrent_tasks=1, max_queued_tasks=0
        )
        full_manager.current_tasks = 1
        video_controller.task_manager = full_manager

        rejected = self.client.post("/api/v1/videos", json=body)
        self.assertEqual(rejected.status_code, 429)
        self.assertIsNone(sm.state.get_idempotency(key))
        self.assertIsNone(sm.state.get_task(key))

        video_controller.task_manager = self.manager
        retried = self.client.post("/api/v1/videos", json=body)
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(self.manager.started, [key])

    def test_unexpected_pre_acceptance_failure_aborts_claim(self):
        key = "66666666-6666-6666-6666-666666666666"
        video_controller.task_manager = _BrokenQueueManager()
        client = TestClient(asgi.app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/videos", json={**self.base_body, "idempotency_key": key}
        )

        self.assertEqual(response.status_code, 500)
        self.assertIsNone(sm.state.get_idempotency(key))
        self.assertIsNone(sm.state.get_task(key))

    def test_invalid_uuid_is_rejected(self):
        response = self.client.post(
            "/api/v1/videos",
            json={**self.base_body, "idempotency_key": "not-a-uuid"},
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
