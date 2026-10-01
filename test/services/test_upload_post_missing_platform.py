import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.services.upload_post import UploadPostService


class TestUploadPostMissingPlatform(unittest.TestCase):
    def upload(self, response, status=None):
        config = {"upload_post_enabled": True, "upload_post_api_key": "test-key", "upload_post_username": "creator"}
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "video.mp4"
            video.write_bytes(b"local fixture")
            reply = Mock(status_code=200)
            reply.json.return_value = response
            with patch("app.services.upload_post.config.app", config), patch(
                "app.services.upload_post.requests.post", return_value=reply
            ) as post, patch.object(UploadPostService, "check_status", return_value=status), patch(
                "app.services.upload_post.time.sleep"
            ):
                result = UploadPostService().upload_video(str(video), "title", platforms=["tiktok", "instagram"])
            self.assertEqual(post.call_count, 1)
            return result

    def test_sync_missing_requested_platform_is_not_success(self):
        result = self.upload({"success": True, "results": {"tiktok": {"success": True}}})
        self.assertFalse(result["success"])
        self.assertIn("instagram", result["error"])
        self.assertTrue(result["results"]["tiktok"]["success"])

    def test_background_list_missing_requested_platform_is_not_success(self):
        result = self.upload({"success": True, "request_id": "remote-id"}, {
            "status": "completed", "results": [{"platform": "tiktok", "success": True}],
        })
        self.assertFalse(result["success"])
        self.assertIn("instagram", result["error"])
        self.assertEqual(result["request_id"], "remote-id")

    def test_complete_platform_response_stays_successful(self):
        for results in ({"tiktok": {"success": True}, "instagram": {"success": True}},
                        [{"platform": "tiktok", "success": True}, {"platform": "instagram", "success": True}]):
            with self.subTest(results=results):
                self.assertTrue(self.upload({"success": True, "results": results})["success"])
