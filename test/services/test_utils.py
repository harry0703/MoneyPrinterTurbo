import os
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.utils import utils


class TestUtilsTaskDir(unittest.TestCase):
    def setUp(self):
        self.task_id = "22222222-2222-2222-2222-222222222222"
        self.tasks_root = utils.task_dir()
        self.expected_dir = os.path.join(
            self.tasks_root,
            "video-de-chamanismo-profundo__22222222-2222-2222-2222-222222222222",
        )

    def tearDown(self):
        if os.path.isdir(self.expected_dir):
            shutil.rmtree(self.expected_dir)
        legacy_dir = os.path.join(self.tasks_root, self.task_id)
        if os.path.isdir(legacy_dir):
            shutil.rmtree(legacy_dir)

    def test_ensure_task_dir_uses_related_title_and_preserves_uuid(self):
        created_dir = utils.ensure_task_dir(self.task_id, "Video de chamanismo profundo")

        self.assertEqual(created_dir, self.expected_dir)
        self.assertTrue(os.path.isdir(created_dir))
        self.assertEqual(utils.task_dir(self.task_id), self.expected_dir)


if __name__ == "__main__":
    unittest.main()