import io
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.asgi import app
from app.config import config
from app.models.exception import HttpException

PROJECT_ROOT = Path(__file__).parent.parent.parent


class TestApiAuthentication(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        config.app["api_key"] = "test-token"
        self.client = TestClient(app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def test_script_route_rejects_missing_api_key_when_configured(self):
        with patch("app.services.llm.generate_script", return_value="safe"):
            response = self.client.post(
                "/api/v1/scripts",
                json={"video_subject": "security test", "paragraph_number": 1},
            )

        self.assertEqual(response.status_code, 401)

    def test_script_route_accepts_valid_api_key_when_configured(self):
        with patch("app.services.llm.generate_script", return_value="safe"):
            response = self.client.post(
                "/api/v1/scripts",
                headers={"x-api-key": "test-token"},
                json={"video_subject": "security test", "paragraph_number": 1},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["video_script"], "safe")

    def test_script_route_rejects_empty_api_key_configuration(self):
        config.app["api_key"] = ""

        with patch("app.services.llm.generate_script", return_value="safe"):
            response = self.client.post(
                "/api/v1/scripts",
                headers={"x-api-key": ""},
                json={"video_subject": "security test", "paragraph_number": 1},
            )

        self.assertEqual(response.status_code, 401)


class TestUploadLimits(unittest.TestCase):
    def test_upload_writer_rejects_files_larger_than_limit(self):
        from app.controllers.v1.video import _write_upload_file_with_limit

        upload = type("Upload", (), {"file": io.BytesIO(b"abcd")})()
        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = os.path.join(temp_dir, "sample.mp3")

            with self.assertRaises(HttpException) as context:
                _write_upload_file_with_limit(
                    upload_file=upload,
                    save_path=save_path,
                    max_bytes=3,
                    request_id="req-1",
                )

            self.assertEqual(context.exception.status_code, 413)
            self.assertFalse(os.path.exists(save_path))


class TestSecretRedaction(unittest.TestCase):
    def test_redact_secret_preserves_only_short_prefix_and_suffix(self):
        from app.utils.secrets import redact_secret

        self.assertEqual(redact_secret("sk-1234567890abcdef"), "sk-************cdef")


class TestDeploymentConfig(unittest.TestCase):
    def test_example_config_documents_app_api_key(self):
        with open(PROJECT_ROOT / "config.example.toml", "rb") as fp:
            example_config = tomllib.load(fp)

        self.assertIn("api_key", example_config["app"])
        self.assertEqual(example_config["app"]["api_key"], "")

    def test_docker_compose_persists_config_toml(self):
        with open(PROJECT_ROOT / "docker-compose.yml", encoding="utf-8") as fp:
            compose_config = yaml.safe_load(fp)

        self.assertIn(
            "./config.toml:/MoneyPrinterTurbo/config.toml",
            compose_config["x-common-volumes"],
        )


if __name__ == "__main__":
    unittest.main()
