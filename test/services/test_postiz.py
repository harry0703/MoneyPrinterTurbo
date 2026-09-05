import sys
import unittest
from datetime import datetime, timedelta
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


def _upload_then_post_side_effect(post_json=None):
    """Return a requests.post side_effect that mocks upload then create-post."""

    def post_side_effect(url, headers=None, files=None, json=None, *args, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if url.endswith("/upload"):
            resp.json.return_value = {"id": "media123", "path": "/media/path/video.mp4"}
        elif url.endswith("/posts"):
            resp.json.return_value = post_json if post_json is not None else [{"postId": "post456"}]
        else:
            resp.json.return_value = {}
        return resp

    return post_side_effect


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
    # _api_base – hosted vs self-hosted Public API URLs
    # ---------------------------------------------------------------------
    def test_api_base_normalizes_hosted_and_self_hosted_urls(self):
        cases = [
            ("http://localhost:8004", "http://localhost:8004/public/v1"),
            ("http://localhost:8004/", "http://localhost:8004/public/v1"),
            ("https://api.postiz.com", "https://api.postiz.com/public/v1"),
            ("https://api.postiz.com/", "https://api.postiz.com/public/v1"),
            ("https://api.postiz.com/public/v1", "https://api.postiz.com/public/v1"),
            ("https://api.postiz.com/public/v1/", "https://api.postiz.com/public/v1"),
            (
                "http://localhost:8004/api/public/v1",
                "http://localhost:8004/api/public/v1",
            ),
            (
                "http://localhost:8004/api/public/v1/",
                "http://localhost:8004/api/public/v1",
            ),
        ]
        for api_url, expected in cases:
            with self.subTest(api_url=api_url):
                with patch(
                    "app.services.postiz.config.app",
                    {**_BASE_CONFIG, "postiz_api_url": api_url},
                ):
                    service = PostizService()
                    self.assertEqual(service._api_base(), expected)

    # ---------------------------------------------------------------------
    # upload_video – successful path
    # ---------------------------------------------------------------------
    @patch("app.services.postiz.config.app", _BASE_CONFIG)
    @patch("app.services.postiz.os.path.exists", return_value=True)
    @patch("builtins.open", mock_open(read_data=b"fake video data"))
    @patch("app.services.postiz.requests.post")
    def test_upload_video_success(self, mock_post, _exists):
        mock_post.side_effect = _upload_then_post_side_effect()

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
    # Partial failure: YouTube ok + Instagram missing integration ID
    # ---------------------------------------------------------------------
    @patch(
        "app.services.postiz.config.app",
        {
            **_BASE_CONFIG,
            "postiz_platforms": ["youtube", "instagram"],
            "postiz_youtube_integration_id": "yt-int-id",
        },
    )
    @patch("app.services.postiz.os.path.exists", return_value=True)
    @patch("builtins.open", mock_open(read_data=b"fake"))
    @patch("app.services.postiz.requests.post")
    def test_upload_video_partial_failure_is_not_overall_success(self, mock_post, _exists):
        mock_post.side_effect = _upload_then_post_side_effect()
        service = PostizService()
        result = service.upload_video(
            "/fake/video.mp4",
            "Title",
            platforms=["youtube", "instagram"],
        )

        self.assertFalse(result.get("success"))
        self.assertIn("instagram", result.get("error", "").lower())
        by_platform = {item["platform"]: item for item in result["results"]}
        self.assertTrue(by_platform["youtube"]["success"])
        self.assertFalse(by_platform["instagram"]["success"])
        self.assertIn("integration ID", by_platform["instagram"]["error"])

    # ---------------------------------------------------------------------
    # Provider payloads vs documented schemas
    # ---------------------------------------------------------------------
    def _capture_create_post_payloads(self, mock_post):
        payloads = []
        for call in mock_post.call_args_list:
            url = call.args[0] if call.args else call.kwargs.get("url", "")
            if str(url).endswith("/posts"):
                payloads.append(call.kwargs.get("json") or {})
        return payloads

    @patch(
        "app.services.postiz.config.app",
        {
            **_BASE_CONFIG,
            "postiz_platforms": ["instagram"],
            "postiz_instagram_integration_id": "ig-int-id",
        },
    )
    @patch("app.services.postiz.os.path.exists", return_value=True)
    @patch("builtins.open", mock_open(read_data=b"fake"))
    @patch("app.services.postiz.requests.post")
    def test_instagram_settings_use_reels_post_type(self, mock_post, _exists):
        mock_post.side_effect = _upload_then_post_side_effect()
        service = PostizService()
        result = service.upload_video("/fake/video.mp4", "Reel Title", platforms=["instagram"])

        self.assertTrue(result.get("success"))
        payload = self._capture_create_post_payloads(mock_post)[0]
        settings = payload["posts"][0]["settings"]
        self.assertEqual(settings["__type"], "instagram")
        self.assertEqual(settings["post_type"], "reels")
        self.assertEqual(payload["posts"][0]["integration"]["id"], "ig-int-id")

    @patch(
        "app.services.postiz.config.app",
        {
            **_BASE_CONFIG,
            "postiz_platforms": ["tiktok"],
            "postiz_tiktok_integration_id": "tt-int-id",
            "postiz_tiktok_auto_add_music": True,
        },
    )
    @patch("app.services.postiz.os.path.exists", return_value=True)
    @patch("builtins.open", mock_open(read_data=b"fake"))
    @patch("app.services.postiz.requests.post")
    def test_tiktok_auto_add_music_coerces_bool_to_string(self, mock_post, _exists):
        mock_post.side_effect = _upload_then_post_side_effect()
        service = PostizService()
        result = service.upload_video("/fake/video.mp4", "TikTok Title", platforms=["tiktok"])

        self.assertTrue(result.get("success"))
        settings = self._capture_create_post_payloads(mock_post)[0]["posts"][0]["settings"]
        self.assertEqual(settings["__type"], "tiktok")
        self.assertEqual(settings["autoAddMusic"], "yes")
        self.assertIsInstance(settings["autoAddMusic"], str)
        self.assertNotIsInstance(settings["autoAddMusic"], bool)

    @patch(
        "app.services.postiz.config.app",
        {
            **_BASE_CONFIG,
            "postiz_platforms": ["tiktok"],
            "postiz_tiktok_integration_id": "tt-int-id",
        },
    )
    @patch("app.services.postiz.os.path.exists", return_value=True)
    @patch("builtins.open", mock_open(read_data=b"fake"))
    @patch("app.services.postiz.requests.post")
    def test_tiktok_auto_add_music_defaults_to_no(self, mock_post, _exists):
        mock_post.side_effect = _upload_then_post_side_effect()
        service = PostizService()
        result = service.upload_video("/fake/video.mp4", "TikTok Title", platforms=["tiktok"])

        self.assertTrue(result.get("success"))
        settings = self._capture_create_post_payloads(mock_post)[0]["posts"][0]["settings"]
        self.assertEqual(settings["autoAddMusic"], "no")
        self.assertIn(settings["autoAddMusic"], {"yes", "no"})
        self.assertNotIsInstance(settings["autoAddMusic"], bool)

    @patch(
        "app.services.postiz.config.app",
        {
            **_BASE_CONFIG,
            "postiz_platforms": ["x", "linkedin", "reddit"],
            "postiz_x_integration_id": "x-int-id",
            "postiz_linkedin_integration_id": "li-int-id",
            "postiz_reddit_integration_id": "rd-int-id",
            "postiz_reddit_subreddit": "videos",
        },
    )
    @patch("app.services.postiz.os.path.exists", return_value=True)
    @patch("builtins.open", mock_open(read_data=b"fake"))
    @patch("app.services.postiz.requests.post")
    def test_x_linkedin_reddit_settings_and_integration_ids(self, mock_post, _exists):
        mock_post.side_effect = _upload_then_post_side_effect()
        service = PostizService()
        result = service.upload_video(
            "/fake/video.mp4",
            "Multi Title",
            platforms=["x", "linkedin", "reddit"],
        )

        self.assertTrue(result.get("success"))
        payloads = self._capture_create_post_payloads(mock_post)
        by_type = {item["posts"][0]["settings"]["__type"]: item for item in payloads}

        self.assertEqual(by_type["x"]["posts"][0]["integration"]["id"], "x-int-id")
        self.assertEqual(by_type["x"]["posts"][0]["settings"]["who_can_reply_post"], "everyone")

        self.assertEqual(by_type["linkedin"]["posts"][0]["integration"]["id"], "li-int-id")
        self.assertEqual(by_type["linkedin"]["posts"][0]["settings"]["post_as_images_carousel"], False)

        reddit_post = by_type["reddit"]["posts"][0]
        self.assertEqual(reddit_post["integration"]["id"], "rd-int-id")
        self.assertEqual(reddit_post["settings"]["subreddit"][0]["value"]["subreddit"], "videos")

    # ---------------------------------------------------------------------
    # check_status – success and failure paths
    # ---------------------------------------------------------------------
    @patch("app.services.postiz.config.app", _BASE_CONFIG)
    @patch("app.services.postiz.requests.get")
    def test_check_status_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [
            {"postId": "other", "status": "published"},
            {"postId": "post456", "status": "processing"},
        ]
        mock_get.return_value = mock_resp

        service = PostizService()
        result = service.check_status("post456")

        mock_get.assert_called_once()
        called_url = mock_get.call_args[0][0]
        self.assertTrue(called_url.endswith("/posts"))
        params = mock_get.call_args.kwargs.get("params") or mock_get.call_args[1]["params"]
        self.assertIn("startDate", params)
        self.assertIn("endDate", params)
        start = datetime.fromisoformat(params["startDate"])
        end = datetime.fromisoformat(params["endDate"])
        self.assertGreaterEqual(end - start, timedelta(days=6))
        self.assertLessEqual(end - start, timedelta(days=8))
        headers = mock_get.call_args.kwargs.get("headers") or mock_get.call_args[1]["headers"]
        self.assertEqual(headers.get("Authorization"), "test-key")
        self.assertFalse(headers.get("Authorization", "").startswith("Bearer "))

        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("request_id"), "post456")
        self.assertEqual(result.get("status"), "processing")
        self.assertEqual(len(result.get("posts", [])), 1)
        self.assertEqual(result["posts"][0]["postId"], "post456")

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
