import tempfile
import unittest
from pathlib import Path

from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.utils import utils


def _remount_tasks_staticfiles(directory: str):
    """Point the /tasks mount at *directory*, returning the previous app.

    ``app.asgi`` bakes ``utils.task_dir()`` into its StaticFiles mount at
    import time. The conftest fixture redirects ``utils.task_dir`` per-test,
    so the mount must be re-pointed at the test-scoped directory; otherwise
    these tests serve from the production directory while creating files in
    the temp redirect (404). Previous mount app is returned for tearDown
    restore so no state leaks between tests.
    """
    previous = None
    for route in asgi.app.routes:
        if getattr(route, "path", "") == "/tasks":
            previous = route.app
            route.app = StaticFiles(directory=directory, html=True)
    return previous


class TestTaskStaticFiles(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        # 普通静态文件测试验证默认开放模式，不能依赖开发者本机是否启用了 Key。
        config.app["api_key"] = ""
        self._previous_tasks_app = _remount_tasks_staticfiles(utils.task_dir())
        self.client = TestClient(asgi.app)

    def tearDown(self):
        if self._previous_tasks_app is not None:
            for route in asgi.app.routes:
                if getattr(route, "path", "") == "/tasks":
                    route.app = self._previous_tasks_app
        config.app.clear()
        config.app.update(self.original_app_config)

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

    def test_configured_key_protects_task_file(self):
        """配置 Key 后，任务文件必须拒绝缺失或错误凭据，只接受正确请求头。"""

        config.app["api_key"] = "task-file-secret"
        with tempfile.TemporaryDirectory(
            prefix="static-task-auth-", dir=utils.task_dir()
        ) as task_directory:
            task_path = Path(task_directory)
            artifact = task_path / "artifact.txt"
            artifact.write_text("protected task artifact", encoding="utf-8")
            artifact_url = f"/tasks/{task_path.name}/{artifact.name}"

            missing = self.client.get(artifact_url)
            wrong = self.client.get(
                artifact_url,
                headers={"x-api-key": "wrong"},
            )
            accepted = self.client.get(
                artifact_url,
                headers={"x-api-key": "task-file-secret"},
            )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.text, "protected task artifact")

    def test_configured_key_does_not_protect_health_or_docs(self):
        """健康检查和 Swagger 文档保持公开，方便部署探针与人工配置。"""

        config.app["api_key"] = "task-file-secret"

        self.assertEqual(self.client.get("/ping").status_code, 200)
        self.assertEqual(self.client.get("/docs").status_code, 200)

    def test_unconfigured_cors_rejects_task_file_preflight(self):
        """默认同源模式必须拒绝第三方网页对任务文件发起预检。"""

        config.app["api_key"] = "task-file-secret"

        response = self.client.options(
            "/tasks/example/artifact.txt",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-api-key",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("access-control-allow-origin", response.headers)

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

            response = self.client.get(f"/tasks/{task_path.name}/{exposed_link.name}")

        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"must not be served", response.content)


if __name__ == "__main__":
    unittest.main()
