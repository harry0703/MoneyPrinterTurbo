import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import asgi
from app.utils import utils


class TestTaskStaticFiles(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(asgi.app)

    def test_serves_regular_task_file(self):
        with tempfile.TemporaryDirectory(
            prefix="static-task-", dir=utils.task_dir()
        ) as task_directory:
            task_path = Path(task_directory)
            artifact = task_path / "artifact.txt"
            artifact.write_text("task artifact", encoding="utf-8")

            response = self.client.get(f"/tasks/{task_path.name}/{artifact.name}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "task artifact")

    def test_does_not_serve_symlink_to_file_outside_tasks(self):
        with (
            tempfile.TemporaryDirectory(
                prefix="static-task-", dir=utils.task_dir()
            ) as task_directory,
            tempfile.TemporaryDirectory(
                prefix="static-secret-", dir=utils.storage_dir(create=True)
            ) as external_directory,
        ):
            task_path = Path(task_directory)
            secret = Path(external_directory) / "secret.txt"
            secret.write_text("must not be served", encoding="utf-8")
            exposed_link = task_path / "secret.txt"

            try:
                exposed_link.symlink_to(secret)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            response = self.client.get(
                f"/tasks/{task_path.name}/{exposed_link.name}"
            )

        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"must not be served", response.content)


if __name__ == "__main__":
    unittest.main()
