import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID

import requests

from app.services.upload_post import UploadPostService


class TestUploadPostTimeoutId(unittest.TestCase):
    def test_lost_upload_response_retains_a_client_supplied_tracking_id(self):
        config = {"upload_post_enabled": True, "upload_post_api_key": "test-key", "upload_post_username": "creator"}
        for error in (requests.exceptions.ReadTimeout("response lost"), requests.exceptions.ConnectionError("connection dropped")):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as directory:
                video = Path(directory) / "video.mp4"
                video.write_bytes(b"local fixture")
                with patch("app.services.upload_post.config.app", config), patch(
                    "app.services.upload_post.requests.post", side_effect=error
                ) as post:
                    result = UploadPostService().upload_video(str(video), "title", platforms=["tiktok"])
                self.assertEqual(post.call_count, 1)
                request_id = dict(post.call_args.kwargs["data"]).get("request_id")
                self.assertTrue(request_id, "Send a client ID before the response can be lost")
                UUID(request_id)
                self.assertEqual(result["request_id"], request_id)
                self.assertFalse(result["success"])
                self.assertIn("unconfirmed", result["error"])
                self.assertIn(request_id, result["error"])
                self.assertTrue(post.call_args.kwargs["files"]["video"].closed)

    def test_definitive_client_rejection_is_not_labelled_unconfirmed(self):
        config = {"upload_post_enabled": True, "upload_post_api_key": "test-key", "upload_post_username": "creator"}
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "video.mp4"
            video.write_bytes(b"local fixture")
            response = Mock(status_code=400)
            response.raise_for_status.side_effect = requests.exceptions.HTTPError("bad platform", response=response)
            with patch("app.services.upload_post.config.app", config), patch(
                "app.services.upload_post.requests.post", return_value=response
            ) as post:
                result = UploadPostService().upload_video(str(video), "title", platforms=["tiktok"])
            self.assertFalse(result["success"])
            self.assertNotIn("unconfirmed", result["error"])
            self.assertEqual(post.call_count, 1)

    def test_gateway_timeout_retains_id_without_republishing(self):
        config = {"upload_post_enabled": True, "upload_post_api_key": "test-key", "upload_post_username": "creator"}
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "video.mp4"
            video.write_bytes(b"local fixture")
            response = Mock(status_code=504)
            response.raise_for_status.side_effect = requests.exceptions.HTTPError("gateway timeout", response=response)
            with patch("app.services.upload_post.config.app", config), patch(
                "app.services.upload_post.requests.post", return_value=response
            ) as post:
                result = UploadPostService().upload_video(str(video), "title", platforms=["tiktok"])
            self.assertFalse(result["success"])
            self.assertIn("unconfirmed", result["error"])
            self.assertEqual(result["request_id"], dict(post.call_args.kwargs["data"])["request_id"])
            self.assertEqual(post.call_count, 1)
