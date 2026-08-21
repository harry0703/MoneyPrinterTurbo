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
        """Appending footage sources must not overwrite the script, keywords, and parameters historical task recovery depends on."""
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
        """After the atomic-write replacement, stay fully compatible with the Pydantic parameters the task pipeline passes in."""
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
        """A standalone footage download has no task record; skip silently instead of creating a broken JSON file."""
        updated = task_artifacts.patch_script_data(
            "standalone",
            material_sources=[],
        )

        self.assertFalse(updated)
        self.assertFalse((self.task_dir / "script.json").exists())

    def test_patch_invalid_script_returns_false_without_overwrite(self):
        """On corrupted historical JSON, keep the original file, log the error, and let the video pipeline continue."""
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


if __name__ == "__main__":
    unittest.main()
