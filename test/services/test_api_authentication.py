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


if __name__ == "__main__":
    unittest.main()
