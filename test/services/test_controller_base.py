import shutil
import unittest
from pathlib import Path
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
        클라이언트가 request ID 를 주면 그대로 유지하고, 없으면 로그와 오류 응답에 기록할 수 있는
        UUID 를 생성해, 두 경로 모두 추적 가능한 식별자를 갖게 한다.
        """
        self.assertEqual(
            base.get_task_id(self._request({"x-task-id": "request-123"})),
            "request-123",
        )

        generated = base.get_task_id(self._request())
        self.assertEqual(len(generated), 36)
        self.assertEqual(generated.count("-"), 4)

    def test_verify_token_accepts_matching_key(self):
        """API 키를 설정했다면 같은 요청 헤더는 인증을 정상적으로 통과해야 한다."""
        config.app["api_key"] = "secret"

        result = base.verify_token(self._request({"x-api-key": "secret"}))

        self.assertIsNone(result)

    def test_verify_token_rejects_missing_or_wrong_key(self):
        """
        API 키가 없거나 틀리면 모두 401 을 반환하고 클라이언트 request ID 를 남겨,
        인증 실패를 로그에서 호출자 요청과 짝지을 수 있게 한다.
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
        api_key 가 설정되지 않았을 때 '빈 설정과 빈 요청 헤더가 같다' 는 이유로 통과시켜서는 안 된다.
        그러면 기본 설정에서 보호된 엔드포인트가 익명으로 열린다.
        """
        config.app["api_key"] = ""

        for headers in ({}, {"x-api-key": ""}, {"x-api-key": "anything"}):
            with self.subTest(headers=headers):
                with self.assertRaises(HttpException) as raised:
                    base.verify_token(self._request(dict(headers)))

                self.assertEqual(raised.exception.status_code, 401)

    def test_v1_routers_require_authentication(self):
        """V1 라우터 두 개 모두 인증 의존성을 달아야 하며, 어느 한쪽도 익명으로 남아서는 안 된다."""
        from app.controllers.v1 import llm as llm_controller
        from app.controllers.v1 import video as video_controller

        for module in (video_controller, llm_controller):
            with self.subTest(router=module.__name__):
                self.assertTrue(module.router.dependencies, module.__name__)

    def test_new_router_preserves_common_prefix_and_dependencies(self):
        """모든 V1 라우터는 통일된 접두사를 재사용하고, 전달됐을 때만 인증 의존성을 설정해야 한다."""
        dependency = object()

        plain_router = new_router()
        protected_router = new_router(dependencies=[dependency])

        self.assertEqual(plain_router.prefix, "/api/v1")
        self.assertEqual(plain_router.tags, ["V1"])
        self.assertEqual(protected_router.dependencies, [dependency])


if __name__ == "__main__":
    unittest.main()


class TestTaskArtifactMountAuthentication(unittest.TestCase):
    """/tasks 정적 마운트가 /api/v1/download 와 같은 인증을 요구하는지 검증한다."""

    def setUp(self):
        self.original_app_config = dict(config.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    @staticmethod
    def _client_and_artifact():
        from fastapi.testclient import TestClient

        from app import asgi
        from app.utils import utils

        task_id = "asgi-auth-test"
        artifact_dir = Path(utils.task_dir()) / task_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact = artifact_dir / "final-1.mp4"
        artifact.write_bytes(b"video-bytes")
        return TestClient(asgi.app), f"/tasks/{task_id}/final-1.mp4", artifact_dir

    def test_task_artifacts_require_the_api_key(self):
        """
        작업 UUID 만 알면 /tasks 로 영상을 받아 갈 수 있으면 안 된다.
        /api/v1/download 가 인증을 요구하는 것과 동일한 산출물이기 때문이다.
        """
        config.app["api_key"] = "secret"
        client, artifact_url, artifact_dir = self._client_and_artifact()
        try:
            self.assertEqual(client.get(artifact_url).status_code, 401)
            self.assertEqual(
                client.get(artifact_url, headers={"x-api-key": "wrong"}).status_code,
                401,
            )

            allowed = client.get(artifact_url, headers={"x-api-key": "secret"})
            self.assertEqual(allowed.status_code, 200)
            self.assertEqual(allowed.content, b"video-bytes")
        finally:
            shutil.rmtree(artifact_dir, ignore_errors=True)

    def test_task_artifacts_are_denied_when_api_key_is_unset(self):
        """api_key 미설정 시 정적 산출물도 API 와 똑같이 fail-closed 여야 한다."""
        config.app["api_key"] = ""
        client, artifact_url, artifact_dir = self._client_and_artifact()
        try:
            self.assertEqual(client.get(artifact_url).status_code, 401)
        finally:
            shutil.rmtree(artifact_dir, ignore_errors=True)

    def test_public_webui_root_stays_anonymous(self):
        """WebUI 공개 자원은 계속 익명 접근이 가능해야 한다."""
        config.app["api_key"] = "secret"
        client, _, artifact_dir = self._client_and_artifact()
        try:
            self.assertEqual(client.get("/").status_code, 200)
        finally:
            shutil.rmtree(artifact_dir, ignore_errors=True)
