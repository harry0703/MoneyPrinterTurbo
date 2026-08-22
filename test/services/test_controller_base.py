import unittest
from types import SimpleNamespace

from app.config import config
from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException


class TestControllerAuthentication(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    @staticmethod
    def _request(headers=None):
        return SimpleNamespace(
            headers=headers or {},
            url="http://localhost/api/v1/tasks",
        )

    def test_get_task_id_reuses_header_or_generates_uuid(self):
        """
        客户端提供 request ID 时需要原样保留，缺失时则生成可记录到日志和
        错误响应中的 UUID，保证两种入口都有可追踪标识。
        """
        self.assertEqual(
            base.get_task_id(self._request({"x-task-id": "request-123"})),
            "request-123",
        )

        generated = base.get_task_id(self._request())
        self.assertEqual(len(generated), 36)
        self.assertEqual(generated.count("-"), 4)

    def test_verify_token_accepts_matching_key(self):
        """配置了 API Key 时，相同请求头必须正常通过鉴权。"""
        config.app["api_key"] = "secret"

        result = base.verify_token(self._request({"x-api-key": "secret"}))

        self.assertIsNone(result)

    def test_verify_token_is_disabled_when_key_is_empty(self):
        """Empty configuration preserves the existing unauthenticated API."""
        for configured_key in (None, "", "   "):
            with self.subTest(configured_key=configured_key):
                config.app["api_key"] = configured_key
                self.assertIsNone(base.verify_token(self._request()))

    def test_verify_token_rejects_missing_or_wrong_key(self):
        """
        缺失和错误的 API Key 都必须返回 401，并保留客户端 request ID，
        避免鉴权失败在日志中无法与调用方请求对应。
        """
        config.app["api_key"] = "secret"

        for provided_key in (None, "wrong"):
            with self.subTest(provided_key=provided_key):
                headers = {"x-task-id": "auth-request"}
                if provided_key is not None:
                    headers["x-api-key"] = provided_key

                with self.assertRaises(HttpException) as raised:
                    base.verify_token(self._request(headers))

                self.assertEqual(raised.exception.status_code, 401)
                self.assertEqual(
                    raised.exception.message,
                    "invalid or missing API key",
                )
                self.assertNotIn("localhost", raised.exception.message)

    def test_v1_routers_register_optional_authentication_dependency(self):
        """Both LLM and video APIs must share the optional authentication gate."""
        from app.controllers.v1 import llm, video

        for router in (llm.router, video.router):
            with self.subTest(prefix=router.prefix):
                self.assertEqual(len(router.dependencies), 1)
                self.assertIs(router.dependencies[0].dependency, base.verify_token)

    def test_configured_key_protects_v1_routes_but_not_health_check(self):
        """The ASGI app must enforce the key without hiding its health endpoint."""
        from fastapi.testclient import TestClient

        from app.asgi import app

        config.app["api_key"] = "secret"
        client = TestClient(app)

        unauthorized = client.get("/api/v1/tasks")
        authorized = client.get(
            "/api/v1/tasks",
            headers={"x-api-key": "secret"},
        )
        health = client.get("/ping")

        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(
            unauthorized.json()["message"],
            "invalid or missing API key",
        )
        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), "pong")

    def test_new_router_preserves_common_prefix_and_dependencies(self):
        """所有 V1 路由都应复用统一前缀，并仅在传入时设置鉴权依赖。"""
        dependency = object()

        plain_router = new_router()
        protected_router = new_router(dependencies=[dependency])

        self.assertEqual(plain_router.prefix, "/api/v1")
        self.assertEqual(plain_router.tags, ["V1"])
        self.assertEqual(protected_router.dependencies, [dependency])


if __name__ == "__main__":
    unittest.main()
