import unittest
from unittest.mock import patch

from app.models.schema import VideoParams
from app.services import task as tm


class TestBackgroundTaskService(unittest.TestCase):
    def test_start_background_task_starts_thread_once(self):
        params = VideoParams(video_subject="Coffee")

        with patch.object(tm, "threading") as threading_mock:
            thread = object()
            threading_mock.Thread.return_value = thread
            task_id = tm.start_background_task("bg-task", params)

        self.assertEqual(task_id, "bg-task")
        threading_mock.Thread.assert_called_once()
