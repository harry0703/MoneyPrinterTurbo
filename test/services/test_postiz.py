import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

# Ensure the project root is on sys.path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.postiz import PostizService

# Base configuration for enabled and API key present
_BASE_CONFIG = {
    "postiz_enabled": True,
    "postiz_api_key": "test-key",
    "postiz_platforms": ["youtube"],
    "postiz_auto_upload": True,
    "postiz_youtube_privacy_status": "public",
    "postiz_max_pending_tasks": 5,
}

class TestPostizService(unittest.TestCase):
    # ---------------------------------------------------------------------
    # Configuration checks
    # ---------------------------------------------------------------------
    @patch("app.services.postiz.config.app", {**_BASE_CONFIG, "postiz_enabled": False})
    def test_is_configured_disabled(self):
        """Service should report not configured when disabled."""
        service = PostizService()
        self.assertFalse(service.is_configured())

    @patch("app.services.postiz.config.app", {**_BASE_CONFIG, "postiz_api_key": ""})
    def test_is_configured_missing_key(self):
        """Service should report not configured when API key missing."""
        service = PostizService()
        self.assertFalse(service.is_configured())

    @patch("app.services.postiz.config.app", _BASE_CONFIG)
    def test_is_configured_success(self):
        """When enabled and key present, service reports configured."""
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
        """A successful upload should return success=True with IDs."""
        # Mock side‑effect to return different payloads based on URL
        def post_side_effect(url, *args, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if url.endswith("/media"):
                resp.json.return_value = {"id": "media123"}
            elif url.endswith("/posts"):
                resp.json.return_value = {"id": "post456"}
            else:
                resp.json.return_value = {}
            return resp

        mock_post.side_effect = post_side_effect

        service = PostizService()
        result = service.upload_video("/fake/video.mp4", "Test Title")
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("media_id"), "media123")
        self.assertEqual(result.get("post_id"), "post456")
        # Verify that two POST calls were made – one to /media, one to /posts
        self.assertEqual(mock_post.call_count, 2)
        called_urls = [call[0][0] for call in mock_post.call_args_list]
        self.assertTrue(any(url.endswith("/media") for url in called_urls))
        self.assertTrue(any(url.endswith("/posts") for url in called_urls))

    # ---------------------------------------------------------------------
    # upload_video – missing local file
    # ---------------------------------------------------------------------
    @patch("app.services.postiz.config.app", _BASE_CONFIG)
    @patch("app.services.postiz.os.path.exists", return_value=False)
    @patch("app.services.postiz.requests.post")
    def test_upload_video_missing_file(self, mock_post, _exists):
        """When the video file does not exist the method should fail early."""
        service = PostizService()
        result = service.upload_video("/nonexistent/video.mp4", "Title")
        self.assertFalse(result.get("success"))
        self.assertIn("Video file not found", result.get("error", ""))
        mock_post.assert_not_called()

    # ---------------------------------------------------------------------
    # upload_video – request error handling
    # ---------------------------------------------------------------------
    @patch("app.services.postiz.config.app", _BASE_CONFIG)
    @patch("app.services.postiz.os.path.exists", return_value=True)
    @patch("builtins.open", mock_open(read_data=b"fake"))
    @patch("app.services.postiz.requests.post")
    def test_upload_video_request_error(self, mock_post, _exists):
        """If the media upload request raises an exception the method should return a failure."""
        mock_post.side_effect = Exception("network failure")
        service = PostizService()
        result = service.upload_video("/fake/video.mp4", "Title")
        self.assertFalse(result.get("success"))
        self.assertIn("network failure", result.get("error", ""))
        # No second call should be attempted after the exception
        self.assertEqual(mock_post.call_count, 1)

    # ---------------------------------------------------------------------
    # check_status – success and failure paths
    # ---------------------------------------------------------------------
    @patch("app.services.postiz.config.app", _BASE_CONFIG)
    @patch("app.services.postiz.requests.get")
    def test_check_status_success(self, mock_get):
        """A successful status check should return the JSON payload."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"id": "post456", "status": "processing"}
        mock_get.return_value = mock_resp

        service = PostizService()
        result = service.check_status("post456")
        self.assertEqual(result, {"id": "post456", "status": "processing"})
        mock_get.assert_called_once()
        self.assertTrue(mock_get.call_args[0][0].endswith("/posts/post456"))

    @patch("app.services.postiz.config.app", _BASE_CONFIG)
    @patch("app.services.postiz.requests.get")
    def test_check_status_error(self, mock_get):
        """When the request raises an exception the method should return an error dict."""
        mock_get.side_effect = Exception("unreachable")
        service = PostizService()
        result = service.check_status("post456")
        self.assertFalse(result.get("success"))
        self.assertIn("unreachable", result.get("error", ""))

if __name__ == "__main__":
    unittest.main()
