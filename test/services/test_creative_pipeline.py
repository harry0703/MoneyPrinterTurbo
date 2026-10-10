import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.controllers.v1 import creative as creative_controller
from app.models import const
from app.models.exception import HttpException
from app.services.creative import pipeline as creative_pipeline

TASK_ID = "task-1"


def _task(state, progress=0):
    return {"task_id": TASK_ID, "state": state, "progress": progress}


class PipelineStatusTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.task_dir = os.path.join(self._tmp.name, "tasks", TASK_ID)
        os.makedirs(self.task_dir, exist_ok=True)
        self._patcher = patch(
            "app.services.creative.pipeline.utils.task_dir",
            return_value=self.task_dir,
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    def _touch(self, name, content="placeholder"):
        path = os.path.join(self.task_dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    def _write_json(self, name, payload):
        with open(os.path.join(self.task_dir, name), "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def _stage(self, status, name):
        return next(stage for stage in status["stages"] if stage["name"] == name)

    def _build(self, state, progress=0):
        return creative_pipeline.build_pipeline_status(
            TASK_ID, task=_task(state, progress)
        )

    def _full_timeline(self, asset):
        return {
            "version": 1,
            "task_id": TASK_ID,
            "shots": [
                {"index": 1, "source": "stock", "duration": 5.0, "asset_path": asset},
            ],
        }

    def _all_pre_rough_cut_artifacts(self):
        self._write_json("creative_brief.json", {"topic": "harbor"})
        self._write_json("script.json", {"video_script": "narration"})
        self._write_json("shot_plan.json", {"version": 1, "task_id": TASK_ID, "shots": []})
        self._touch("audio.mp3")
        self._touch("subtitle.srt")

    def test_unknown_task_returns_none(self):
        with patch.object(
            creative_pipeline.sm.state, "get_task", return_value=None
        ):
            self.assertIsNone(
                creative_pipeline.build_pipeline_status(TASK_ID)
            )

    def test_uses_state_store_when_task_omitted(self):
        with patch.object(
            creative_pipeline.sm.state,
            "get_task",
            return_value=_task(const.TASK_STATE_PROCESSING, 10),
        ):
            status = creative_pipeline.build_pipeline_status(TASK_ID)
        self.assertEqual(status["task_state"], const.TASK_STATE_PROCESSING)
        self.assertEqual(status["progress"], 10)

    def test_fresh_processing_task_marks_brief_active(self):
        status = self._build(const.TASK_STATE_PROCESSING)
        self.assertEqual(status["state_name"], "processing")
        self.assertEqual(self._stage(status, "brief")["status"], "active")
        self.assertEqual(self._stage(status, "brief")["detail"], "current stage")
        self.assertEqual(self._stage(status, "script")["status"], "pending")
        self.assertEqual(self._stage(status, "publish")["status"], "pending")
        self.assertEqual(status["shots"], [])
        self.assertEqual(status["available_actions"], [])

    def test_processing_marks_first_open_stage_active(self):
        self._write_json("creative_brief.json", {"topic": "harbor"})
        self._write_json("script.json", {"video_script": "narration"})
        self._write_json("shot_plan.json", {"version": 1, "task_id": TASK_ID, "shots": []})
        status = self._build(const.TASK_STATE_PROCESSING)
        done = [stage["name"] for stage in status["stages"] if stage["status"] == "done"]
        self.assertEqual(done, ["brief", "script", "shot_plan"])
        self.assertEqual(self._stage(status, "audio")["status"], "active")

    def test_materials_partial_is_active_without_current_marker(self):
        asset = self._touch("assets/shot_001/a1.mp4")
        self._write_json(
            "rough_cut.json",
            {
                "version": 1,
                "task_id": TASK_ID,
                "shots": [
                    {"index": 1, "source": "stock", "duration": 5.0, "asset_path": asset},
                    {
                        "index": 2,
                        "source": "comfyui",
                        "duration": 5.0,
                        "asset_path": os.path.join(self.task_dir, "a2.mp4"),
                    },
                ],
            },
        )
        status = self._build(const.TASK_STATE_PROCESSING)
        materials = self._stage(status, "materials")
        self.assertEqual(materials["status"], "active")
        self.assertEqual(materials["detail"], "1/2 shot assets resolved")
        self.assertEqual(self._stage(status, "rough_cut")["status"], "pending")
        self.assertTrue(status["shots"][0]["asset_exists"])
        self.assertFalse(status["shots"][1]["asset_exists"])

    def test_waiting_for_director_lists_director_actions(self):
        self._all_pre_rough_cut_artifacts()
        asset = self._touch("assets/shot_001/a1.mp4")
        self._write_json("rough_cut.json", self._full_timeline(asset))
        self._touch("rough_cut.mp4")
        status = self._build(const.TASK_STATE_WAITING_FOR_DIRECTOR)
        self.assertEqual(status["state_name"], "waiting_for_director")
        self.assertEqual(self._stage(status, "materials")["status"], "done")
        self.assertEqual(self._stage(status, "rough_cut")["status"], "done")
        self.assertEqual(self._stage(status, "director_review")["status"], "active")
        self.assertEqual(self._stage(status, "final_video")["status"], "pending")
        self.assertIn("approve", status["available_actions"])
        self.assertIn("regenerate_shot", status["available_actions"])
        self.assertTrue(status["shots"][0]["asset_exists"])

    def test_complete_task_marks_every_stage_done(self):
        self._all_pre_rough_cut_artifacts()
        asset = self._touch("assets/shot_001/a1.mp4")
        self._write_json("rough_cut.json", self._full_timeline(asset))
        self._touch("rough_cut.mp4")
        self._touch("final-1.mp4")
        self._write_json("qc_report.json", {"issues": []})
        status = self._build(const.TASK_STATE_COMPLETE, 100)
        self.assertEqual(status["state_name"], "complete")
        statuses = {stage["name"]: stage["status"] for stage in status["stages"]}
        self.assertEqual(set(statuses), set(creative_pipeline.STAGE_NAMES))
        self.assertTrue(all(value == "done" for value in statuses.values()))
        self.assertEqual(status["available_actions"], ["qc", "premiere"])

    def test_complete_without_final_video_marks_failed(self):
        self._all_pre_rough_cut_artifacts()
        asset = self._touch("assets/shot_001/a1.mp4")
        self._write_json("rough_cut.json", self._full_timeline(asset))
        self._touch("rough_cut.mp4")
        status = self._build(const.TASK_STATE_COMPLETE, 100)
        self.assertEqual(self._stage(status, "final_video")["status"], "failed")
        self.assertEqual(self._stage(status, "publish")["status"], "pending")

    def test_complete_without_subtitle_marks_skipped(self):
        self._all_pre_rough_cut_artifacts()
        os.remove(os.path.join(self.task_dir, "subtitle.srt"))
        asset = self._touch("assets/shot_001/a1.mp4")
        self._write_json("rough_cut.json", self._full_timeline(asset))
        self._touch("rough_cut.mp4")
        self._touch("final-1.mp4")
        self._write_json("qc_report.json", {"issues": []})
        status = self._build(const.TASK_STATE_COMPLETE, 100)
        self.assertEqual(self._stage(status, "subtitle")["status"], "skipped")
        self.assertEqual(self._stage(status, "brief")["status"], "done")

    def test_failed_task_marks_first_missing_stage_failed(self):
        self._write_json("creative_brief.json", {"topic": "harbor"})
        self._write_json("script.json", {"video_script": "narration"})
        status = self._build(const.TASK_STATE_FAILED)
        self.assertEqual(status["state_name"], "failed")
        self.assertEqual(self._stage(status, "brief")["status"], "done")
        self.assertEqual(self._stage(status, "script")["status"], "done")
        self.assertEqual(self._stage(status, "shot_plan")["status"], "failed")
        self.assertEqual(self._stage(status, "audio")["status"], "pending")
        self.assertEqual(self._stage(status, "final_video")["status"], "pending")
        self.assertEqual(self._stage(status, "qc")["status"], "pending")
        self.assertEqual(status["available_actions"], [])

    def test_failed_task_after_rough_cut_marks_final_video_failed(self):
        self._all_pre_rough_cut_artifacts()
        asset = self._touch("assets/shot_001/a1.mp4")
        self._write_json("rough_cut.json", self._full_timeline(asset))
        self._touch("rough_cut.mp4")
        status = self._build(const.TASK_STATE_FAILED)
        self.assertEqual(self._stage(status, "rough_cut")["status"], "done")
        final_video = self._stage(status, "final_video")
        self.assertEqual(final_video["status"], "failed")
        self.assertEqual(self._stage(status, "qc")["status"], "pending")

    def test_corrupt_rough_cut_json_is_ignored(self):
        with open(
            os.path.join(self.task_dir, "rough_cut.json"), "w", encoding="utf-8"
        ) as handle:
            handle.write("{not json")
        status = self._build(const.TASK_STATE_PROCESSING)
        self.assertEqual(self._stage(status, "materials")["status"], "pending")
        self.assertEqual(status["shots"], [])


class PipelineControllerTestCase(unittest.TestCase):
    def _request(self):
        return SimpleNamespace(headers={"x-task-id": "request-456"})

    def test_pipeline_returns_status_payload(self):
        payload = {
            "task_id": TASK_ID,
            "task_state": const.TASK_STATE_COMPLETE,
            "state_name": "complete",
            "progress": 100,
            "stages": [],
            "shots": [],
            "available_actions": ["qc", "premiere"],
        }
        with patch.object(
            creative_controller.creative_pipeline,
            "build_pipeline_status",
            return_value=payload,
        ):
            response = creative_controller.get_pipeline_status(
                self._request(), TASK_ID
            )
        self.assertEqual(response["status"], 200)
        self.assertEqual(response["data"]["task_id"], TASK_ID)

    def test_pipeline_unknown_task_raises_404(self):
        with patch.object(
            creative_controller.creative_pipeline,
            "build_pipeline_status",
            return_value=None,
        ):
            with self.assertRaises(HttpException) as raised:
                creative_controller.get_pipeline_status(self._request(), TASK_ID)
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
