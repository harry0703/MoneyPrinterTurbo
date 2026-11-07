import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models.schema import VideoParams
from app.services import task_artifacts


class TestTaskArtifacts(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.task_dir = Path(self.temp_dir.name)
        self.task_dir_patch = patch(
            "app.services.task_artifacts.utils.task_dir",
            return_value=str(self.task_dir),
        )
        self.task_dir_patch.start()

    def tearDown(self):
        self.task_dir_patch.stop()
        self.temp_dir.cleanup()

    def test_patch_preserves_existing_script_fields(self):
        """补充素材来源时不能覆盖历史任务恢复依赖的文案、关键词和参数。"""
        original = {
            "script": "existing script",
            "search_terms": ["nature"],
            "params": {"video_source": "pixabay"},
        }
        task_artifacts.write_script_data("task-1", original)

        updated = task_artifacts.patch_script_data(
            "task-1",
            material_sources=[
                {
                    "provider": "pixabay",
                    "asset_id": "123",
                    "local_file": "vid-123.mp4",
                }
            ],
        )
        payload = json.loads((self.task_dir / "script.json").read_text())

        self.assertTrue(updated)
        self.assertEqual(payload["script"], original["script"])
        self.assertEqual(payload["search_terms"], original["search_terms"])
        self.assertEqual(payload["params"], original["params"])
        self.assertEqual(payload["material_sources"][0]["asset_id"], "123")
        self.assertEqual(list(self.task_dir.glob(".script.json.*.tmp")), [])

    def test_write_script_data_serializes_video_params(self):
        """原子写入替换旧实现后，仍需完整兼容任务主流程传入的 Pydantic 参数。"""
        params = VideoParams(
            video_subject="test subject",
            video_terms=["city", "night"],
        )

        task_artifacts.write_script_data(
            "task-params",
            {
                "script": "test script",
                "search_terms": ["city"],
                "params": params,
            },
        )
        payload = json.loads((self.task_dir / "script.json").read_text())

        self.assertEqual(payload["params"]["video_subject"], "test subject")
        self.assertEqual(payload["params"]["video_terms"], ["city", "night"])
        self.assertEqual(payload["params"]["video_source"], "pexels")

    def test_patch_missing_script_is_non_blocking(self):
        """独立调用素材下载时没有任务清单，应静默跳过而不是创建残缺 JSON。"""
        updated = task_artifacts.patch_script_data(
            "standalone",
            material_sources=[],
        )

        self.assertFalse(updated)
        self.assertFalse((self.task_dir / "script.json").exists())

    def test_patch_invalid_script_returns_false_without_overwrite(self):
        """历史 JSON 损坏时必须保留原文件、记录错误，并允许视频主流程继续。"""
        target = self.task_dir / "script.json"
        target.write_text("{invalid-json", encoding="utf-8")

        with patch.object(task_artifacts.logger, "warning") as warning:
            updated = task_artifacts.patch_script_data(
                "task-1",
                material_sources=[],
            )

        self.assertFalse(updated)
        self.assertEqual(target.read_text(encoding="utf-8"), "{invalid-json")
        self.assertTrue(warning.called)

    def test_video_plan_uses_separate_versioned_artifact(self):
        plan = {"schema_version": "1.0", "scenes": [{"scene_id": "scene-001"}]}
        task_artifacts.write_script_data("task-plan", {"script": "legacy script"})

        task_artifacts.write_video_plan("task-plan", plan)

        self.assertEqual(task_artifacts.read_video_plan("task-plan"), plan)
        self.assertEqual(
            json.loads((self.task_dir / "script.json").read_text(encoding="utf-8")),
            {"script": "legacy script"},
        )
        self.assertEqual(
            json.loads((self.task_dir / "video_plan.v1.json").read_text(encoding="utf-8")),
            plan,
        )

    def test_missing_video_plan_is_compatible_with_legacy_tasks(self):
        self.assertIsNone(task_artifacts.read_video_plan("legacy-task"))

    def test_scene_media_manifest_is_separate_and_round_trips(self):
        manifest = {
            "schema_version": "1.0",
            "plan_id": "plan-12345678",
            "script_sha256": "a" * 64,
            "assignments": [],
        }
        task_artifacts.write_script_data("task-scene-media", {"script": "legacy"})

        task_artifacts.write_scene_media_manifest("task-scene-media", manifest)

        self.assertEqual(
            task_artifacts.read_scene_media_manifest("task-scene-media"), manifest
        )
        self.assertEqual(
            json.loads((self.task_dir / "script.json").read_text(encoding="utf-8")),
            {"script": "legacy"},
        )
        self.assertTrue((self.task_dir / "scene_media.v1.json").is_file())

    def test_scene_timeline_is_separate_and_round_trips(self):
        timeline = {
            "schema_version": "1.0",
            "plan_id": "plan-test-123",
            "script_sha256": "a" * 64,
            "audio_duration": 4.0,
            "alignment_source": "estimated",
            "synchronization": "estimated",
            "items": [],
        }

        task_artifacts.write_scene_timeline("task-timeline", timeline)

        self.assertEqual(task_artifacts.read_scene_timeline("task-timeline"), timeline)
        self.assertTrue((self.task_dir / "scene_timeline.v1.json").is_file())

    def test_render_metrics_are_persisted_separately(self):
        metrics = [{
            "video_index": 1, "status": "complete", "used_codec": "libx264",
            "render_elapsed_seconds": 3.1, "output_bytes": 12000,
        }]
        task_artifacts.write_video_render_metrics("task-metrics", metrics)
        self.assertEqual(
            task_artifacts.read_video_render_metrics("task-metrics"),
            {"schema_version": "1.0", "renders": metrics},
        )
        self.assertTrue((self.task_dir / "video_render_metrics.v1.json").is_file())


if __name__ == "__main__":
    unittest.main()
