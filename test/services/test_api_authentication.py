import asyncio
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import asgi
from app.config import config


class TestAPIAuthenticationHTTP(unittest.TestCase):
    """从真实 ASGI 入口验证 V1 API 的可选鉴权，覆盖两个业务路由组。"""

    def setUp(self):
        self.original_app_config = dict(config.app)
        self.client = TestClient(asgi.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def test_empty_key_preserves_existing_open_access(self):
        """默认空 Key 不要求请求头，保证旧客户端和本地 WebUI 继续工作。"""

        config.app["api_key"] = ""

        response = self.client.get("/api/v1/tasks")

        self.assertEqual(response.status_code, 200)

    def test_video_routes_require_matching_key_when_configured(self):
        """视频路由在启用保护后必须统一拒绝缺失和错误的 Key。"""

        config.app["api_key"] = "video-secret"

        missing = self.client.get("/api/v1/tasks")
        wrong = self.client.get(
            "/api/v1/tasks",
            headers={"x-api-key": "wrong"},
        )
        accepted = self.client.get(
            "/api/v1/tasks",
            headers={"x-api-key": "video-secret"},
        )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(accepted.status_code, 200)

    def test_llm_routes_authenticate_before_request_validation(self):
        """LLM 路由必须先鉴权，未认证请求不得进入会产生费用的业务逻辑。"""

        config.app["api_key"] = "llm-secret"

        # 请求模型提供了默认值，空请求也可能真实调用大模型。这里隔离外部
        # 服务并核对调用次数，既验证鉴权顺序，也避免测试消耗用户的 API。
        with patch(
            "app.controllers.v1.llm.llm.generate_script",
            return_value="mocked script",
        ) as generate_script:
            missing = self.client.post("/api/v1/scripts", json={})
            accepted = self.client.post(
                "/api/v1/scripts",
                json={},
                headers={"x-api-key": "llm-secret"},
            )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(accepted.status_code, 200)
        generate_script.assert_called_once()

    def test_openapi_documents_api_key_header_for_v1_routes(self):
        """Swagger 必须显示 x-api-key，避免启用保护后只能靠猜测请求格式。"""

        schema = self.client.get("/openapi.json").json()
        parameters = schema["paths"]["/api/v1/tasks"]["get"]["parameters"]

        self.assertTrue(
            any(
                parameter["in"] == "header" and parameter["name"] == "x-api-key"
                for parameter in parameters
            )
        )

    def test_duplicate_api_key_headers_are_rejected(self):
        """重复凭据的解释可能因代理不同而变化，因此无论顺序都必须拒绝。"""

        config.app["api_key"] = "video-secret"

        correct_first = self.client.get(
            "/api/v1/tasks",
            headers=[
                ("x-api-key", "video-secret"),
                ("x-api-key", "wrong"),
            ],
        )
        wrong_first = self.client.get(
            "/api/v1/tasks",
            headers=[
                ("x-api-key", "wrong"),
                ("x-api-key", "video-secret"),
            ],
        )

        self.assertEqual(correct_first.status_code, 401)
        self.assertEqual(wrong_first.status_code, 401)

    def test_latin1_and_utf8_encodings_preserve_existing_key_access(self):
        """Raw ASGI headers preserve both encodings without client transcoding."""

        async def status_for(raw_key):
            messages = []

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message):
                messages.append(message)

            scope = {
                "type": "http", "asgi": {"version": "3.0"},
                "http_version": "1.1", "scheme": "http", "method": "GET",
                "path": "/api/v1/tasks", "raw_path": b"/api/v1/tasks",
                "root_path": "", "query_string": b"",
                "headers": [(b"host", b"testserver"), (b"x-api-key", raw_key)],
                "client": ("127.0.0.1", 12345), "server": ("testserver", 80),
            }
            await asgi.app(scope, receive, send)
            return next(m["status"] for m in messages if m["type"] == "http.response.start")

        config.app["api_key"] = "é"
        for raw_key in (b"\xe9", b"\xc3\xa9"):
            with self.subTest(encoding=raw_key):
                self.assertEqual(asyncio.run(status_for(raw_key)), 200)
        for raw_key in (b"\xe8", b"\xc3\xa8"):
            with self.subTest(wrong_encoding=raw_key):
                self.assertEqual(asyncio.run(status_for(raw_key)), 401)

    def test_unicode_key_authenticates_from_utf8_header_bytes(self):
        """TOML 支持 Unicode Key；客户端按 UTF-8 发送同一 Key 时必须通过。"""

        config.app["api_key"] = "密钥-é"
        raw_key = "密钥-é".encode("utf-8")

        accepted = self.client.get("/api/v1/tasks", headers=[(b"x-api-key", raw_key)])
        wrong = self.client.get(
            "/api/v1/tasks", headers=[(b"x-api-key", "错误-é".encode("utf-8"))]
        )
        task_file = self.client.get(
            "/tasks/missing/final-1.mp4", headers=[(b"x-api-key", raw_key)]
        )

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(wrong.status_code, 401)
        self.assertNotEqual(task_file.status_code, 401)


if __name__ == "__main__":
    unittest.main()
