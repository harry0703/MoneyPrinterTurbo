import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

# Ensure the project root is on sys.path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.postiz import PostizService

# Base configuration with all required fields for a successful configuration
_BASE_CONFIG = {
    "postiz_enabled": True,
    "postiz_api_key": "test-key",
    "postiz_platforms": ["youtube"],
    "postiz_auto_upload": True,
    "postiz_youtube_privacy_status": "public",
    "postiz_youtube_integration_id": "yt-int-id",
    "postiz_max_pending_tasks": 5,
}


class TestPostizService(unittest.TestCase):
    # ---------------------------------------------------------------------
    # Configuration checks
    # ---------------------------------------------------------------------
    @patch("app.services.postiz.config.app", {**_BASE_CONFIG, "postiz_enabled": False})
    def test_is_configured_disabled(self):
        service = PostizService()
        self.assertFalse(service.is_configured())

    @patch("app.services.postiz.config.app", {**_BASE_CONFIG, "postiz_api_key": ""})
    def test_is_configured_missing_key(self):
        service = PostizService()
        self.assertFalse(service.is_configured())

    @patch(
        "app.services.postiz.config.app",
        {k: v for k, v in _BASE_CONFIG.items() if k != "postiz_youtube_integration_id"},
    )
    def test_is_configured_missing_integration(self):
        service = PostizService()
        self.assertFalse(service.is_configured())

    @patch("app.services.postiz.config.app", _BASE_CONFIG)
    def test_is_configured_success(self):
        service = PostizService()
        self.assertTrue(service.is_configured())

    # ---------------------------------------------------------------------
    # upload_video – successful path
    # ---------------------------------------------------------------------
    @patch("app.services.postiz.config.app", _BASE_CONFIG)
    @patch("app.services.postiz.os.path.exists", return_value=True)
    @patch("builtins.open", mock_open(read_data=b"fake video data"))
    @patch("app.services.postiz.requests.post")
    def test_upload_video_success(self, mock_post, _exists):
        # Mock upload endpoint and posts endpoint with distinct responses
        def post_side_effect(url, headers=None, files=None, json=None, *args, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if url.endswith("/upload"):
                resp.json.return_value = {"id": "media123", "path": "/media/path/video.mp4"}
            elif url.endswith("/posts"):
                resp.json.return_value = [{"postId": "post456"}]
            else:
                resp.json.return_value = {}
            return resp

        mock_post.side_effect = post_side_effect

        service = PostizService()
        result = service.upload_video("/fake/video.mp4", "Test Title")

        # Verify overall success
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("media_id"), "media123")
        # Verify per‑platform result contains the post ID
        self.assertEqual(len(result.get("results", [])), 1)
        platform_result = result["results"][0]
        self.assertEqual(platform_result.get("platform"), "youtube")
        self.assertTrue(platform_result.get("success"))
        self.assertEqual(platform_result.get("post_id"), "post456")

        # Verify two POST calls were made – upload then post creation
        self.assertEqual(mock_post.call_count, 2)
        # First call (upload) must contain the raw API key without Bearer prefix
        upload_headers = mock_post.call_args_list[0][1]["headers"]
        self.assertEqual(upload_headers.get("Authorization"), "test-key")
        self.assertFalse(upload_headers.get("Authorization").startswith("Bearer "))

    # ---------------------------------------------------------------------
    # upload_video – missing local file
    # ---------------------------------------------------------------------
    @patch("app.services.postiz.config.app", _BASE_CONFIG)
    @patch("app.services.postiz.os.path.exists", return_value=False)
    @patch("app.services.postiz.requests.post")
    def test_upload_video_missing_file(self, mock_post, _exists):
        service = PostizService()
        result = service.upload_video("/nonexistent/video.mp4", "Title")
        self.assertFalse(result.get("success"))
        self.assertIn("Video file not found", result.get("error", ""))
        mock_post.assert_not_called()

    # ---------------------------------------------------------------------
    # upload_video – no integration ID configured
    # ---------------------------------------------------------------------
    @patch(
        "app.services.postiz.config.app",
        {k: v for k, v in _BASE_CONFIG.items() if k != "postiz_youtube_integration_id"},
    )
    @patch("app.services.postiz.os.path.exists", return_value=True)
    @patch("builtins.open", mock_open(read_data=b"fake"))
    @patch("app.services.postiz.requests.post")
    def test_upload_video_no_integration_id(self, mock_post, _exists):
        service = PostizService()
        result = service.upload_video("/fake/video.mp4", "Title")
        self.assertFalse(result.get("success"))
        self.assertIn("Postiz not configured", result.get("error", ""))
        mock_post.assert_not_called()

    # ---------------------------------------------------------------------
    # upload_video – request error handling during upload
    # ---------------------------------------------------------------------
    @patch("app.services.postiz.config.app", _BASE_CONFIG)
    @patch("app.services.postiz.os.path.exists", return_value=True)
    @patch("builtins.open", mock_open(read_data=b"fake"))
    @patch("app.services.postiz.requests.post")
    def test_upload_video_request_error(self, mock_post, _exists):
        mock_post.side_effect = Exception("network failure")
        service = PostizService()
        result = service.upload_video("/fake/video.mp4", "Title")
        self.assertFalse(result.get("success"))
        self.assertIn("network failure", result.get("error", ""))
        # Only one POST should have been attempted before the exception
        self.assertEqual(mock_post.call_count, 1)

    # ---------------------------------------------------------------------
    # check_status – success and failure paths
    # ---------------------------------------------------------------------
    @patch("app.services.postiz.config.app", _BASE_CONFIG)
    @patch("app.services.postiz.requests.get")
    def test_check_status_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"id": "post456", "status": "processing"}
        mock_get.return_value = mock_resp

        service = PostizService()
        result = service.check_status("post456")
        self.assertEqual(result, {"id": "post456", "status": "processing"})
        mock_get.assert_called_once()
        # URL should be the generic /posts endpoint (no request ID appended)
        self.assertTrue(mock_get.call_args[0][0].endswith("/posts"))

    @patch("app.services.postiz.config.app", _BASE_CONFIG)
    @patch("app.services.postiz.requests.get")
    def test_check_status_error(self, mock_get):
        mock_get.side_effect = Exception("unreachable")
        service = PostizService()
        result = service.check_status("post456")
        self.assertFalse(result.get("success"))
        self.assertIn("unreachable", result.get("error", ""))

    # ---------------------------------------------------------------------
    # Authorization header – ensure raw key without Bearer prefix
    # ---------------------------------------------------------------------
    @patch("app.services.postiz.config.app", _BASE_CONFIG)
    def test_auth_header_no_bearer(self):
        service = PostizService()
        headers = service._auth_headers()
        self.assertEqual(headers.get("Authorization"), "test-key")
        self.assertFalse(headers.get("Authorization").startswith("Bearer "))


if __name__ == "__main__":
    unittest.main()
