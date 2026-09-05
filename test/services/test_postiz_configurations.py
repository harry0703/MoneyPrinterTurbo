"""
Reviewer-requested coverage for the four Postiz publishing configurations:

1. Postiz-only configuration
2. Mixed-provider configuration (Postiz + upload_post)
3. Partial-failure configuration
4. Key backup/restore configuration for publishing provider API keys
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch, PropertyMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import task as tm
from app.services import postiz as postiz_module
from app.services.state import MemoryState

_BASE_POSTIZ_CONFIG = {
    "postiz_enabled": True,
    "postiz_api_key": "test-key",
    "postiz_platforms": ["youtube"],
    "postiz_auto_upload": True,
    "postiz_youtube_privacy_status": "public",
    "postiz_youtube_integration_id": "yt-int-id",
    "postiz_max_pending_tasks": 5,
}


def _upload_then_post_side_effect():
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

    return post_side_effect


class TestPostizConfigurations(unittest.TestCase):
    """Postiz-only, mixed-provider, partial-failure, and key-backup coverage."""

    def test_postiz_only_configuration_invokes_only_postiz(self):
        """When upload_post is off and Postiz is configured, only Postiz uploads."""
        state = MemoryState()
        state.update_task(
            "postiz-only",
            state=tm.const.TASK_STATE_COMPLETE,
            progress=100,
            videos=["final.mp4"],
            cross_post_state=tm.const.CROSS_POST_STATE_PENDING,
        )
        postiz_service = tm.PUBLISHING_PROVIDER_REGISTRY["postiz"]

        with (
            patch.object(tm.sm, "state", state),
            patch.object(tm.upload_post.upload_post_service, "is_configured", return_value=False),
            patch.object(postiz_service, "is_configured", return_value=True),
            patch.object(type(postiz_service), "auto_upload", new_callable=PropertyMock, return_value=True),
            patch.object(type(postiz_service), "platforms", new_callable=PropertyMock, return_value=["youtube"]),
            patch.object(
                tm.llm,
                "generate_social_metadata",
                return_value={"title": "Coffee", "caption": "Sip.", "hashtags": []},
            ),
            patch.object(
                postiz_service,
                "upload_video",
                return_value={"success": True, "results": [{"platform": "youtube", "success": True}]},
            ) as postiz_upload,
            patch.object(tm.upload_post.upload_post_service, "upload_video") as upload_post_upload,
        ):
            tm._run_cross_post(
                "postiz-only",
                ("final.mp4",),
                "Coffee",
                "A short coffee story.",
                "en",
                ("youtube",),
                "public",
            )

        postiz_upload.assert_called_once()
        upload_post_upload.assert_not_called()
        task = state.get_task("postiz-only")
        self.assertEqual(task["cross_post_state"], tm.const.CROSS_POST_STATE_COMPLETE)

    def test_mixed_provider_configuration_invokes_both_providers(self):
        """When both upload_post and Postiz are configured, both upload_video run."""
        state = MemoryState()
        state.update_task(
            "mixed-provider",
            state=tm.const.TASK_STATE_COMPLETE,
            progress=100,
            videos=["final.mp4"],
            cross_post_state=tm.const.CROSS_POST_STATE_PENDING,
        )
        postiz_service = tm.PUBLISHING_PROVIDER_REGISTRY["postiz"]
        upload_service = tm.upload_post.upload_post_service

        with (
            patch.object(tm.sm, "state", state),
            patch.object(upload_service, "is_configured", return_value=True),
            patch.object(type(upload_service), "auto_upload", new_callable=PropertyMock, return_value=True),
            patch.object(type(upload_service), "platforms", new_callable=PropertyMock, return_value=["tiktok"]),
            patch.object(postiz_service, "is_configured", return_value=True),
            patch.object(type(postiz_service), "auto_upload", new_callable=PropertyMock, return_value=True),
            patch.object(type(postiz_service), "platforms", new_callable=PropertyMock, return_value=["youtube"]),
            patch.object(
                tm.llm,
                "generate_social_metadata",
                return_value={"title": "Coffee", "caption": "Sip.", "hashtags": []},
            ),
            patch.object(upload_service, "upload_video", return_value={"success": True}) as upload_post_upload,
            patch.object(postiz_service, "upload_video", return_value={"success": True}) as postiz_upload,
        ):
            tm._run_cross_post(
                "mixed-provider",
                ("final.mp4",),
                "Coffee",
                "A short coffee story.",
                "en",
                ("youtube", "tiktok"),
                "public",
            )

        upload_post_upload.assert_called_once()
        postiz_upload.assert_called_once()
        task = state.get_task("mixed-provider")
        self.assertEqual(task["cross_post_state"], tm.const.CROSS_POST_STATE_COMPLETE)

    @patch("app.services.postiz.config.app", {**_BASE_POSTIZ_CONFIG, "postiz_platforms": ["youtube", "instagram"]})
    @patch("app.services.postiz.os.path.exists", return_value=True)
    @patch("builtins.open", mock_open(read_data=b"fake"))
    @patch("app.services.postiz.requests.post")
    def test_partial_failure_configuration_reports_overall_failure(self, mock_post, _exists):
        """YouTube success + Instagram missing integration ID must yield success=False."""
        mock_post.side_effect = _upload_then_post_side_effect()
        service = postiz_module.PostizService()
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

    def test_key_backup_restore_includes_postiz_credentials(self):
        """Postiz API key and integration IDs must round-trip through key backup."""
        from test.services import test_webui_settings_transfer as backup_tests

        sections = backup_tests._sample_config_sections()
        payload = backup_tests.build_key_backup_payload(sections, "1.3.4")
        restored = backup_tests.parse_key_backup(backup_tests._encode(payload), sections)

        self.assertEqual(restored["app"]["postiz_api_key"], "postiz-key-456")
        self.assertEqual(restored["app"]["postiz_youtube_integration_id"], "yt-int")
        self.assertEqual(restored["app"]["postiz_instagram_integration_id"], "ig-int")
        self.assertEqual(restored["app"]["postiz_tiktok_integration_id"], "tt-int")
        self.assertEqual(restored["app"]["postiz_x_integration_id"], "x-int")
        self.assertEqual(restored["app"]["postiz_linkedin_integration_id"], "li-int")
        self.assertEqual(restored["app"]["postiz_reddit_integration_id"], "rd-int")
        self.assertEqual(restored["app"]["postiz_reddit_subreddit"], "videos")


if __name__ == "__main__":
    unittest.main()
