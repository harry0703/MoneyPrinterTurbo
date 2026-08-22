import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.utils import utils


class TestTaskStaticFiles(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        # 普通静态文件测试验证默认开放模式，不能依赖开发者本机是否启用了 Key。
        config.app["api_key"] = ""
        self.client = TestClient(asgi.app)

    def tearDown(self):
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

    def test_options_request_is_left_to_cors_middleware(self):
        """受保护文件的 CORS 预检不应被 API Key 校验提前拒绝。"""

        config.app["api_key"] = "task-file-secret"

        response = self.client.options(
            "/tasks/example/artifact.txt",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-api-key",
            },
        )

        self.assertEqual(response.status_code, 200)

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
