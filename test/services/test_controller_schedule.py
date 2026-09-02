import os
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.services import schedule_store


class TestScheduleControllerHTTP(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        config.app["api_key"] = ""
        self.client = TestClient(asgi.app)

        # sqlite ":memory:" cria um banco por conexão, e schedule_store abre
        # uma conexão nova por chamada; um arquivo temporário isolado por
        # teste é o jeito simples de não persistir estado entre testes nem
        # tocar o storage/schedule.db real.
        tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp_db.close()
        self.tmp_db_path = tmp_db.name
        self.db_env_patch = mock.patch.dict(
            os.environ, {"MPT_SCHEDULE_DB_PATH": self.tmp_db_path}
        )
        self.db_env_patch.start()

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        self.db_env_patch.stop()
        try:
            os.unlink(self.tmp_db_path)
        except OSError:
            pass

    def _create_schedule(self, **overrides):
        body = {
            "occurrences": [
                {"generate_at": "2026-03-05T09:00:00", "video_subject": "Café"},
                {"generate_at": "2026-03-06T09:00:00", "video_subject": "Café"},
            ],
            "params": {"video_subject": "Café"},
        }
        body.update(overrides)
        return self.client.post("/api/v1/schedules", json=body)

    def test_create_schedule_returns_group_id_and_count(self):
        response = self._create_schedule()

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertIn("group_id", data)
        self.assertEqual(data["count"], 2)

    def test_create_schedule_rejects_invalid_generate_at(self):
        response = self._create_schedule(
            occurrences=[{"generate_at": "not-a-date", "video_subject": "x"}]
        )
        self.assertEqual(response.status_code, 400)

    def test_list_schedules_returns_created_occurrences(self):
        self._create_schedule()

        response = self.client.get("/api/v1/schedules")

        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["video_subject"], "Café")
        self.assertEqual(rows[0]["status"], "pending")

    def test_list_schedules_filters_by_status(self):
        self._create_schedule()
        occurrence_id = schedule_store.list_occurrences(
            db_path=self.tmp_db_path
        )[0]["id"]
        schedule_store.mark_dispatched(
            occurrence_id, task_id="task-1", db_path=self.tmp_db_path
        )

        response = self.client.get("/api/v1/schedules", params={"status": "pending"})

        self.assertEqual(len(response.json()["data"]), 1)

    def test_cancel_occurrence_marks_it_cancelled(self):
        self._create_schedule()
        occurrence_id = schedule_store.list_occurrences(
            db_path=self.tmp_db_path
        )[0]["id"]

        response = self.client.delete(f"/api/v1/schedules/occurrence/{occurrence_id}")

        self.assertEqual(response.status_code, 200)
        row = [
            r
            for r in schedule_store.list_occurrences(db_path=self.tmp_db_path)
            if r["id"] == occurrence_id
        ][0]
        self.assertEqual(row["status"], "cancelled")

    def test_cancel_unknown_occurrence_returns_404(self):
        response = self.client.delete("/api/v1/schedules/occurrence/999999")
        self.assertEqual(response.status_code, 404)

    def test_cancel_group_cancels_every_pending_row(self):
        create_response = self._create_schedule()
        group_id = create_response.json()["data"]["group_id"]

        response = self.client.delete(f"/api/v1/schedules/{group_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["cancelled"], 2)


if __name__ == "__main__":
    unittest.main()
