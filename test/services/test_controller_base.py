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
                self.assertIn("invalid token", raised.exception.message)

    def test_verify_token_rejects_every_request_when_api_key_is_unset(self):
        """
        api_key 未配置时不能因为“空配置等于空请求头”而放行，否则默认配置下
        受保护接口会退化成匿名可用。
        """
        config.app["api_key"] = ""

        for headers in ({}, {"x-api-key": ""}, {"x-api-key": "anything"}):
            with self.subTest(headers=headers):
                with self.assertRaises(HttpException) as raised:
                    base.verify_token(self._request(dict(headers)))

                self.assertEqual(raised.exception.status_code, 401)

    def test_v1_routers_require_authentication(self):
        """两个 V1 路由都必须挂载鉴权依赖，避免任何一个入口保持匿名。"""
        from app.controllers.v1 import llm as llm_controller
        from app.controllers.v1 import video as video_controller

        for module in (video_controller, llm_controller):
            with self.subTest(router=module.__name__):
                self.assertTrue(module.router.dependencies, module.__name__)

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
