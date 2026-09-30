"""Short-form HTTP requests must survive the Redis queue boundary."""

import os
import unittest
from uuid import uuid4
from unittest.mock import patch

import redis
from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.controllers.manager.redis_manager import RedisTaskManager
from app.controllers.v1 import video as video_controller
from app.models.schema import AudioRequest, SubtitleRequest
from app.services import state as sm


class TestRedisShortFormRequests(unittest.TestCase):
    def setUp(self):
        host = os.getenv("MPT_TEST_REDIS_HOST", "127.0.0.1")
        port = int(os.getenv("MPT_TEST_REDIS_PORT", "6379"))
        db = int(os.getenv("MPT_TEST_REDIS_DB", "15"))
        self.manager = RedisTaskManager(0, f"redis://{host}:{port}/{db}")
        try:
            self.manager.redis_client.ping()
        except redis.RedisError as exc:
            self.skipTest(f"Redis is unavailable: {exc}")
        self.manager.queue = f"test-short-form:{uuid4()}"
        self.addCleanup(self.manager.redis_client.delete, self.manager.queue)
        self.addCleanup(self.manager.redis_client.close)

    def test_http_requests_round_trip_without_video_only_fields(self):
        for route, model in (("audio", AudioRequest), ("subtitle", SubtitleRequest)):
            with (
                self.subTest(route=route),
                patch.object(video_controller, "task_manager", self.manager),
                patch.object(sm, "state", sm.MemoryState()),
                patch.dict(config.app, {"api_key": ""}),
                TestClient(asgi.app, raise_server_exceptions=False) as client,
            ):
                response = client.post(
                    f"/api/v1/{route}",
                    json={"video_script": "A prepared script", "voice_rate": 1.35},
                )
                self.assertEqual(response.status_code, 200, response.text)
                task_id = response.json()["data"]["task_id"]
                task = self.manager.dequeue()
                self.assertIsNotNone(task)
                self.assertEqual(task["kwargs"]["task_id"], task_id)
                self.assertEqual(task["kwargs"]["stop_at"], route)
                restored = task["kwargs"]["params"]
                self.assertIsInstance(restored, model)
                self.assertEqual(restored.video_script, "A prepared script")
                self.assertEqual(restored.voice_rate, 1.35)
                self.assertNotIn("video_subject", restored.model_dump())

    def test_legacy_short_form_dicts_are_restored_instead_of_discarded(self):
        import json

        for route, model in (("audio", AudioRequest), ("subtitle", SubtitleRequest)):
            with self.subTest(route=route):
                params = model(video_script="Persisted script", voice_rate=1.35)
                payload = {
                    "func": "start",
                    "args": [],
                    "kwargs": {
                        "task_id": f"test-{route}",
                        "params": params.model_dump(),
                        "stop_at": route,
                    },
                }
                self.manager.redis_client.rpush(self.manager.queue, json.dumps(payload))
                task = self.manager.dequeue()
                self.assertIsNotNone(task)
                self.assertEqual(task["kwargs"]["params"], params)
