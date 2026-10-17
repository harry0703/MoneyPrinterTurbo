import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.creative import qc as creative_qc


def _write_json(task_dir, name, payload):
    with open(os.path.join(task_dir, name), "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def _brief():
    return {
        "topic": "harbor at dawn",
        "audience": "travel",
        "forbidden_elements": ["text overlays"],
    }


def _style():
    return {"name": "dawn", "palette": ["#0b1e3a", "#f2a65a"], "visual_style": "cinematic"}


def _plan(shots=None):
    if shots is None:
        shots = [
            {"index": 1, "source_type": "local", "status": "resolved", "asset_path": "a1.mp4"},
            {"index": 2, "source_type": "local", "status": "resolved", "asset_path": "a2.mp4"},
        ]
    return {"version": 1, "task_id": "task-1", "shots": shots}


def _timeline(shots, total=None):
    cursor = 0.0
    for shot in shots:
        shot.setdefault("in", round(cursor, 3))
        cursor += float(shot["duration"])
        shot.setdefault("out", round(cursor, 3))
    if total is None:
        total = round(cursor, 3)
    return {
        "version": 1,
        "task_id": "task-1",
        "motion": "smooth",
        "created_at": "t0",
        "updated_at": "t0",
        "total_duration": total,
        "shots": shots,
    }


def _shot(index, duration=5.0, asset_path=None, **extra):
    shot = {
        "index": index,
        "source": "local",
        "asset_path": asset_path,
        "provider": "",
        "prompt": "",
        "query": "",
        "duration": duration,
    }
    shot.update(extra)
    return shot


class CreativeQCTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.task_dir = os.path.join(self._tmp.name, "tasks", "task-1")
        os.makedirs(self.task_dir, exist_ok=True)
        self._patcher = patch(
            "app.services.creative.qc.utils.task_dir",
            return_value=self.task_dir,
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    def _write_valid_artifacts(self, assets_real=True):
        _write_json(self.task_dir, "creative_brief.json", _brief())
        _write_json(self.task_dir, "style_profile.json", _style())
        _write_json(self.task_dir, "shot_plan.json", _plan())
        assets = []
        shots = []
        for index in (1, 2):
            asset_path = os.path.join(self.task_dir, f"asset_{index}.mp4")
            if assets_real:
                with open(asset_path, "wb") as handle:
                    handle.write(b"mp4")
                assets.append(asset_path)
            shots.append(_shot(index, asset_path=asset_path))
        _write_json(self.task_dir, "rough_cut.json", _timeline(shots))
        return assets

    def _issues_by_code(self, report):
        return {issue["code"] for issue in report["issues"]}

    def test_clean_artifacts_produce_empty_report(self):
        self._write_valid_artifacts()
        report = creative_qc.write_report("task-1")
        self.assertIsNotNone(report)
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["shots_to_review"], [])
        self.assertEqual(report["version"], 1)
        self.assertEqual(report["task_id"], "task-1")
        self.assertIn("generated_at", report)
        self.assertTrue(os.path.isfile(
            os.path.join(self.task_dir, "qc_report.json")
        ))

    def test_report_shape_and_load(self):
        self._write_valid_artifacts()
        creative_qc.write_report("task-1")
        report = creative_qc.load_report("task-1")
        self.assertIsInstance(report, dict)
        self.assertEqual(sorted(report.keys()),
                         ["generated_at", "issues", "notes",
                          "shots_to_review", "task_id", "version"])

    def test_load_report_none_when_absent(self):
        self.assertIsNone(creative_qc.load_report("task-1"))

    def test_missing_artifacts_are_noted(self):
        _write_json(self.task_dir, "rough_cut.json",
                    _timeline([_shot(1, asset_path="x.mp4")]))
        report = creative_qc.write_report("task-1")
        joined = " ".join(report["notes"])
        for missing in ("creative_brief.json", "style_profile.json",
                        "shot_plan.json"):
            self.assertIn(missing, joined)

    def test_timeline_index_gap_is_issue(self):
        self._write_valid_artifacts()
        timeline = _timeline([_shot(1), _shot(3)])
        _write_json(self.task_dir, "rough_cut.json", timeline)
        report = creative_qc.write_report("task-1")
        self.assertIn("timeline_index_gap", self._issues_by_code(report))

    def test_timeline_start_gap_is_issue(self):
        shots = [_shot(1), _shot(2)]
        shots[0]["in"] = 1.0
        shots[0]["out"] = 6.0
        shots[1]["in"] = 6.0
        shots[1]["out"] = 11.0
        _write_json(self.task_dir, "rough_cut.json", _timeline(shots))
        report = creative_qc.write_report("task-1")
        self.assertIn("timeline_gap", self._issues_by_code(report))

    def test_timeline_inout_mismatch_is_issue(self):
        shots = [_shot(1, duration=5.0)]
        shots[0]["in"] = 0.0
        shots[0]["out"] = 9.0
        _write_json(self.task_dir, "rough_cut.json", _timeline(shots))
        report = creative_qc.write_report("task-1")
        self.assertIn(
            "timeline_inout_mismatch", self._issues_by_code(report)
        )

    def test_timeline_total_mismatch_is_issue(self):
        shots = [_shot(1)]
        _write_json(self.task_dir, "rough_cut.json", _timeline(shots, total=99.0))
        report = creative_qc.write_report("task-1")
        self.assertIn(
            "timeline_total_mismatch", self._issues_by_code(report)
        )

    def test_missing_asset_goes_to_review(self):
        self._write_valid_artifacts(assets_real=False)
        report = creative_qc.write_report("task-1")
        self.assertTrue(
            any(entry["shot_index"] == 1 for entry in report["shots_to_review"])
        )
        reasons = " ".join(entry["reason"] for entry in report["shots_to_review"])
        self.assertIn("asset", reasons)

    def test_duration_out_of_range_goes_to_review(self):
        self._write_valid_artifacts()
        asset = os.path.join(self.task_dir, "asset_short.mp4")
        with open(asset, "wb") as handle:
            handle.write(b"mp4")
        shots = [_shot(1, duration=0.2, asset_path=asset)]
        _write_json(self.task_dir, "rough_cut.json", _timeline(shots))
        report = creative_qc.write_report("task-1")
        self.assertTrue(
            any(entry["shot_index"] == 1 for entry in report["shots_to_review"])
        )

    def test_failed_plan_shot_goes_to_review(self):
        self._write_valid_artifacts()
        plan = _plan()
        plan["shots"][1]["status"] = "failed"
        plan["shots"][1]["error"] = "provider down"
        _write_json(self.task_dir, "shot_plan.json", plan)
        report = creative_qc.write_report("task-1")
        self.assertTrue(
            any(entry["shot_index"] == 2 for entry in report["shots_to_review"])
        )
        reasons = " ".join(entry["reason"] for entry in report["shots_to_review"])
        self.assertIn("failed", reasons)

    def test_plan_shot_missing_in_timeline_is_issue(self):
        self._write_valid_artifacts()
        shots = [_shot(1, asset_path=self._real_asset(1))]
        _write_json(self.task_dir, "rough_cut.json", _timeline(shots))
        report = creative_qc.write_report("task-1")
        self.assertIn(
            "plan_shot_missing_in_timeline", self._issues_by_code(report)
        )

    def _real_asset(self, index):
        path = os.path.join(self.task_dir, f"asset_{index}.mp4")
        if not os.path.isfile(path):
            with open(path, "wb") as handle:
                handle.write(b"mp4")
        return path

    def test_audio_drift_is_note(self):
        self._write_valid_artifacts()
        report = creative_qc.write_report("task-1", audio_duration=30.0)
        self.assertTrue(any("voice" in note for note in report["notes"]))

    def test_audio_match_is_not_noted(self):
        self._write_valid_artifacts()
        report = creative_qc.write_report("task-1", audio_duration=10.0)
        self.assertFalse(any("voice" in note for note in report["notes"]))

    def test_empty_style_profile_is_note(self):
        self._write_valid_artifacts()
        _write_json(self.task_dir, "style_profile.json", {"name": "bare"})
        report = creative_qc.write_report("task-1")
        self.assertTrue(
            any("style profile" in note for note in report["notes"])
        )

    def test_forbidden_elements_are_note(self):
        self._write_valid_artifacts()
        report = creative_qc.write_report("task-1")
        self.assertTrue(
            any("text overlays" in note for note in report["notes"])
        )

    def test_brief_missing_topic_is_issue(self):
        self._write_valid_artifacts()
        _write_json(self.task_dir, "creative_brief.json", {"topic": "  "})
        report = creative_qc.write_report("task-1")
        self.assertIn("brief_missing_topic", self._issues_by_code(report))

    def test_corrupt_json_artifact_is_treated_as_missing(self):
        self._write_valid_artifacts()
        with open(os.path.join(self.task_dir, "rough_cut.json"), "w") as handle:
            handle.write("{not json")
        report = creative_qc.write_report("task-1")
        joined = " ".join(report["notes"])
        self.assertIn("rough_cut.json", joined)


if __name__ == "__main__":
    unittest.main()
