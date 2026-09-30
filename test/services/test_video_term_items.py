"""Reject invalid keyword arrays before a video task can be scheduled."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.controllers.v1 import video as video_controller
from app.services import state as sm


class TestVideoTermItems(unittest.TestCase):
    def test_non_string_keywords_are_rejected_before_task_creation(self):
        for terms in ([123], [None], [False], [{"term": "coffee"}], [["coffee"]]):
            with self.subTest(terms=terms):
                manager = InMemoryTaskManager(0)
                state = sm.MemoryState()
                with (
                    patch.dict(config.app, {"api_key": ""}),
                    patch.object(sm, "state", state),
                    patch.object(video_controller, "task_manager", manager),
                    TestClient(asgi.app) as client,
                ):
                    response = client.post("/api/v1/videos", json={
                        "video_subject": "Coffee", "video_terms": terms,
                        "subtitle_enabled": False,
                    })
                    self.assertEqual(response.status_code, 400, response.text)
                    self.assertEqual(manager.queue_size(), 0)
                    self.assertEqual(state.list_task_ids(), [])

    def test_string_and_string_array_keywords_preserve_supported_inputs(self):
        for terms in ("coffee, morning", ["coffee", "早晨"], [], None):
            with self.subTest(terms=terms):
                manager = InMemoryTaskManager(0)
                with (
                    patch.dict(config.app, {"api_key": ""}),
                    patch.object(sm, "state", sm.MemoryState()),
                    patch.object(video_controller, "task_manager", manager),
                    TestClient(asgi.app) as client,
                ):
                    response = client.post("/api/v1/videos", json={
                        "video_subject": "Coffee", "video_terms": terms,
                        "subtitle_enabled": False,
                    })
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(manager.dequeue()["kwargs"]["params"].video_terms, terms)
