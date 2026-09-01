import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.services import series


class TestSeriesService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(dir=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_series_crud_and_task_management(self):
        series_file = os.path.join(self.temp_dir, "series_index.json")
        with patch("app.services.series._get_series_file_path", return_value=series_file):
            # Test empty series list
            all_series = series.list_series()
            self.assertEqual(all_series, [])

            # Test create series
            s1 = series.create_series(name="Travel Vlog 2026", description="My summer adventures")
            self.assertIn("id", s1)
            self.assertEqual(s1["name"], "Travel Vlog 2026")
            self.assertEqual(s1["description"], "My summer adventures")
            self.assertEqual(s1["tasks"], [])

            s2 = series.create_series(name="Tech Reviews")
            self.assertIn("id", s2)

            all_series = series.list_series()
            self.assertEqual(len(all_series), 2)

            # Test get series
            fetched = series.get_series(s1["id"])
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched["name"], "Travel Vlog 2026")

            # Test get non-existent series
            self.assertIsNone(series.get_series("non-existent-id"))

            # Test add tasks to series
            add_res1 = series.add_task_to_series(s1["id"], "task-101", "Day 1 in Tokyo")
            self.assertTrue(add_res1)
            add_res2 = series.add_task_to_series(s1["id"], "task-102", "Day 2 in Kyoto")
            self.assertTrue(add_res2)

            # Test add duplicate task updates title
            series.add_task_to_series(s1["id"], "task-101", "Day 1 in Tokyo (Updated)")

            tasks = series.get_series_tasks(s1["id"])
            self.assertEqual(len(tasks), 2)
            self.assertEqual(tasks[0]["task_id"], "task-101")
            self.assertEqual(tasks[0]["title"], "Day 1 in Tokyo (Updated)")
            self.assertEqual(tasks[1]["task_id"], "task-102")

            # Test remove task from series
            rm_res = series.remove_task_from_series(s1["id"], "task-101")
            self.assertTrue(rm_res)
            tasks_after = series.get_series_tasks(s1["id"])
            self.assertEqual(len(tasks_after), 1)
            self.assertEqual(tasks_after[0]["task_id"], "task-102")

            # Test remove non-existent task
            rm_res_fake = series.remove_task_from_series(s1["id"], "task-999")
            self.assertFalse(rm_res_fake)

            # Test delete series
            del_res = series.delete_series(s1["id"])
            self.assertTrue(del_res)
            self.assertIsNone(series.get_series(s1["id"]))

            all_remaining = series.list_series()
            self.assertEqual(len(all_remaining), 1)
            self.assertEqual(all_remaining[0]["id"], s2["id"])

            # Test delete non-existent series
            del_fake = series.delete_series("non-existent-id")
            self.assertFalse(del_fake)


if __name__ == "__main__":
    unittest.main()
