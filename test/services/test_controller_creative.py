import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.controllers.manager.base_manager import TaskQueueFullError
from app.controllers.v1 import creative as creative_controller
from app.models import const
from app.models.exception import HttpException
from app.services import rough_cut
from app.services import state as sm
from app.services import task as task_service

TASK_ID = "task-456"


class CreativeControllerTestCase(unittest.TestCase):
    def _request(self):
        return SimpleNamespace(headers={"x-task-id": "request-456"})

    def _waiting_task(self):
        return {
            "task_id": TASK_ID,
            "state": const.TASK_STATE_WAITING_FOR_DIRECTOR,
            "progress": 60,
        }

    def tearDown(self):
        sm.state.delete_task(TASK_ID)

    def test_approve_schedules_resume(self):
        with (
            patch.object(
                creative_controller.sm.state,
                "get_task",
                return_value=self._waiting_task(),
            ),
            patch.object(
                creative_controller.video_controller.task_manager, "add_task"
            ) as add_task,
            patch.object(task_service, "resume_after_director") as resume,
        ):
            response = creative_controller.approve_rough_cut(
                self._request(), TASK_ID
            )
        self.assertEqual(response["status"], 200)
        self.assertEqual(response["data"]["task_id"], TASK_ID)
        self.assertEqual(response["data"]["state"], const.TASK_STATE_PROCESSING)
        add_task.assert_called_once_with(resume, task_id=TASK_ID)

    def test_approve_rejects_task_not_waiting(self):
        task = {"task_id": TASK_ID, "state": const.TASK_STATE_PROCESSING}
        with patch.object(
            creative_controller.sm.state, "get_task", return_value=task
        ):
            with self.assertRaises(HttpException) as raised:
                creative_controller.approve_rough_cut(self._request(), TASK_ID)
        self.assertEqual(raised.exception.status_code, 409)

    def test_approve_rejects_missing_task(self):
        with patch.object(
            creative_controller.sm.state, "get_task", return_value=None
        ):
            with self.assertRaises(HttpException) as raised:
                creative_controller.approve_rough_cut(self._request(), TASK_ID)
        self.assertEqual(raised.exception.status_code, 409)

    def test_approve_returns_429_when_queue_full(self):
        with (
            patch.object(
                creative_controller.sm.state,
                "get_task",
                return_value=self._waiting_task(),
            ),
            patch.object(
                creative_controller.video_controller.task_manager,
                "add_task",
                side_effect=TaskQueueFullError("queue full"),
            ),
        ):
            with self.assertRaises(HttpException) as raised:
                creative_controller.approve_rough_cut(self._request(), TASK_ID)
        self.assertEqual(raised.exception.status_code, 429)

    def test_resume_endpoint_uses_same_gate(self):
        with patch.object(
            creative_controller.sm.state, "get_task", return_value=None
        ):
            with self.assertRaises(HttpException) as raised:
                creative_controller.resume_rough_cut(self._request(), TASK_ID)
        self.assertEqual(raised.exception.status_code, 409)

    def test_get_rough_cut_returns_timeline(self):
        timeline = {"version": 1, "shots": []}
        with patch.object(
            creative_controller.rough_cut, "load_rough_cut", return_value=timeline
        ):
            response = creative_controller.get_rough_cut(self._request(), TASK_ID)
        self.assertEqual(response["status"], 200)
        self.assertEqual(response["data"]["task_id"], TASK_ID)
        self.assertEqual(response["data"]["rough_cut"], timeline)

    def test_get_rough_cut_missing_returns_404(self):
        with patch.object(
            creative_controller.rough_cut, "load_rough_cut", return_value=None
        ):
            with self.assertRaises(HttpException) as raised:
                creative_controller.get_rough_cut(self._request(), TASK_ID)
        self.assertEqual(raised.exception.status_code, 404)

    def test_reorder_endpoint_forwards_order(self):
        body = creative_controller.ReorderShotsRequest(order=[2, 1])
        with patch.object(
            creative_controller.rough_cut,
            "reorder_shots",
            return_value={"shots": []},
        ) as reorder:
            response = creative_controller.reorder_shots(
                self._request(), body, TASK_ID
            )
        reorder.assert_called_once_with(TASK_ID, [2, 1])
        self.assertEqual(response["data"]["rough_cut"], {"shots": []})

    def test_duration_endpoint_forwards_value(self):
        body = creative_controller.ShotDurationRequest(duration=2.5)
        with patch.object(
            creative_controller.rough_cut,
            "set_shot_duration",
            return_value={"shots": []},
        ) as duration:
            creative_controller.set_shot_duration(
                self._request(), body, TASK_ID, 3
            )
        duration.assert_called_once_with(TASK_ID, 3, 2.5)

    def test_replace_endpoint_forwards_asset(self):
        body = creative_controller.ReplaceShotRequest(asset_path="/data/x.png")
        with patch.object(
            creative_controller.rough_cut,
            "replace_shot_asset",
            return_value={"shots": []},
        ) as replace:
            creative_controller.replace_shot_asset(
                self._request(), body, TASK_ID, 2
            )
        replace.assert_called_once_with(TASK_ID, 2, "/data/x.png")

    def test_delete_endpoint_forwards_index(self):
        with patch.object(
            creative_controller.rough_cut,
            "delete_shot",
            return_value={"shots": []},
        ) as delete:
            creative_controller.delete_shot(self._request(), TASK_ID, 1)
        delete.assert_called_once_with(TASK_ID, 1)

    def test_regenerate_endpoint_forwards_prompt_and_provider(self):
        body = creative_controller.RegenerateShotRequest(
            prompt="p", provider="comfyui"
        )
        with patch.object(
            creative_controller.rough_cut,
            "regenerate_shot",
            return_value={"shots": []},
        ) as regen:
            creative_controller.regenerate_shot(self._request(), body, TASK_ID, 4)
        regen.assert_called_once_with(TASK_ID, 4, prompt="p", provider="comfyui")

    def test_action_maps_rough_cut_error_status(self):
        with patch.object(
            creative_controller.rough_cut,
            "delete_shot",
            side_effect=rough_cut.RoughCutError("boom", status_code=409),
        ):
            with self.assertRaises(HttpException) as raised:
                creative_controller.delete_shot(self._request(), TASK_ID, 1)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("request-456", raised.exception.message)


class TestCreativeEndpointsHTTP(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.task_dir = os.path.join(self._tmp.name, "tasks", TASK_ID)
        os.makedirs(self.task_dir, exist_ok=True)
        sm.state.update_task(
            TASK_ID,
            state=const.TASK_STATE_WAITING_FOR_DIRECTOR,
            progress=60,
            params={},
        )

    def tearDown(self):
        sm.state.delete_task(TASK_ID)
        self._tmp.cleanup()
        shutil.rmtree(self._tmp.name, ignore_errors=True)

    def test_rough_cut_endpoint_over_http(self):
        from fastapi.testclient import TestClient

        from app import asgi

        with (
            patch(
                "app.services.rough_cut.utils.task_dir",
                return_value=self.task_dir,
            ),
            patch.object(task_service, "recover_interrupted_cross_posts"),
        ):
            with TestClient(asgi.app) as client:
                response = client.get(
                    f"/api/v1/creative/tasks/{TASK_ID}/rough_cut"
                )
                self.assertEqual(response.status_code, 404)
                with open(
                    os.path.join(self.task_dir, "rough_cut.json"),
                    "w",
                    encoding="utf-8",
                ) as handle:
                    json.dump({"version": 1, "shots": [{"index": 1}]}, handle)
                response = client.get(
                    f"/api/v1/creative/tasks/{TASK_ID}/rough_cut"
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json()["data"]["task_id"], TASK_ID
                )

    def test_approve_endpoint_over_http(self):
        from fastapi.testclient import TestClient

        from app import asgi

        with (
            patch.object(task_service, "recover_interrupted_cross_posts"),
            patch.object(task_service, "resume_after_director") as resume,
            patch.object(
                creative_controller.video_controller.task_manager, "add_task"
            ) as add_task,
        ):
            with TestClient(asgi.app) as client:
                response = client.post(
                    f"/api/v1/creative/tasks/{TASK_ID}/approve"
                )
        self.assertEqual(response.status_code, 200)
        add_task.assert_called_once_with(resume, task_id=TASK_ID)

    def test_approve_409_over_http(self):
        from fastapi.testclient import TestClient

        from app import asgi

        sm.state.update_task(
            TASK_ID, state=const.TASK_STATE_COMPLETE, progress=100
        )
        with patch.object(task_service, "recover_interrupted_cross_posts"):
            with TestClient(asgi.app) as client:
                response = client.post(
                    f"/api/v1/creative/tasks/{TASK_ID}/approve"
                )
        self.assertEqual(response.status_code, 409)

    def test_premiere_download_over_http(self):
        from fastapi.testclient import TestClient

        from app import asgi

        with patch.object(
            creative_controller.creative_premiere,
            "build_premiere_zip",
            return_value=(b"PK-34payload", "premiere-task-456.zip"),
        ):
            with TestClient(asgi.app) as client:
                response = client.get(
                    f"/api/v1/creative/tasks/{TASK_ID}/premiere",
                    headers={"x-task-id": "request-456"},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/zip")
        self.assertIn(
            'filename="premiere-task-456.zip"',
            response.headers["content-disposition"],
        )
        self.assertEqual(response.content, b"PK-34payload")

    def test_premiere_download_404_over_http(self):
        from fastapi.testclient import TestClient

        from app import asgi

        with patch.object(
            creative_controller.creative_premiere,
            "build_premiere_zip",
            side_effect=creative_controller.creative_premiere.PremiereExportError(
                "no rough cut timeline found for task"
            ),
        ):
            with TestClient(asgi.app) as client:
                response = client.get(
                    f"/api/v1/creative/tasks/{TASK_ID}/premiere",
                    headers={"x-task-id": "request-456"},
                )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
