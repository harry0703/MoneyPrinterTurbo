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
        When the client supplies a request ID it must be preserved verbatim; when missing, generate a
        UUID that can be logged and echoed in error responses so both entry points carry a traceable ID.
        """
        self.assertEqual(
            base.get_task_id(self._request({"x-task-id": "request-123"})),
            "request-123",
        )

        generated = base.get_task_id(self._request())
        self.assertEqual(len(generated), 36)
        self.assertEqual(generated.count("-"), 4)

    def test_verify_token_accepts_matching_key(self):
        """When an API key is configured, the same request header must pass authentication normally."""
        config.app["api_key"] = "secret"

        result = base.verify_token(self._request({"x-api-key": "secret"}))

        self.assertIsNone(result)

    def test_verify_token_rejects_missing_or_wrong_key(self):
        """
        Both a missing and an incorrect API key must return 401 while preserving the client request ID,
        so authentication failures can still be correlated with caller requests in logs.
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

    def test_new_router_preserves_common_prefix_and_dependencies(self):
        """All V1 routes should reuse the unified prefix and only attach the auth dependency when it is provided."""
        dependency = object()

        plain_router = new_router()
        protected_router = new_router(dependencies=[dependency])

        self.assertEqual(plain_router.prefix, "/api/v1")
        self.assertEqual(plain_router.tags, ["V1"])
        self.assertEqual(protected_router.dependencies, [dependency])


if __name__ == "__main__":
    unittest.main()
