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
        self.assertEqual(restored["app"]["postiz_api_url"], "http://self-hosted:8004")
        self.assertEqual(restored["app"]["postiz_youtube_integration_id"], "yt-int")
        self.assertEqual(restored["app"]["postiz_instagram_integration_id"], "ig-int")
        self.assertEqual(restored["app"]["postiz_tiktok_integration_id"], "tt-int")
        self.assertEqual(restored["app"]["postiz_x_integration_id"], "x-int")
        self.assertEqual(restored["app"]["postiz_linkedin_integration_id"], "li-int")
        self.assertEqual(restored["app"]["postiz_reddit_integration_id"], "rd-int")
        self.assertEqual(restored["app"]["postiz_reddit_subreddit"], "videos")

    # ------------------------------------------------------------------
    # Publishing-target snapshot: queue-time destinations survive live
    # config changes before execution.
    # ------------------------------------------------------------------
    def test_snapshot_freezes_postiz_tiktok_despite_live_config_change(self):
        """Queue TikTok snapshot, flip live config to YouTube, run worker.

        Execution must still use the TikTok snapshot (platforms, privacy,
        music flag, integration IDs) and never read the live values.
        """
        state = MemoryState()
        state.update_task(
            "snapshot-tiktok",
            state=tm.const.TASK_STATE_COMPLETE,
            progress=100,
            videos=["final.mp4"],
            cross_post_state=tm.const.CROSS_POST_STATE_PENDING,
        )
        postiz_service = tm.PUBLISHING_PROVIDER_REGISTRY["postiz"]
        snapshot = [
            {
                "provider": "postiz",
                "platforms": ["tiktok"],
                "youtube_privacy_status": "public",
                "extra": {
                    "tiktok_auto_add_music": "yes",
                    "reddit_subreddit": "",
                    "integration_ids": {"tiktok": "tt-int-id"},
                },
            }
        ]

        def _forbidden_platforms(_self):
            raise AssertionError("worker must not read provider.platforms at execution")

        def _forbidden_privacy(_self):
            raise AssertionError(
                "worker must not read provider.youtube_privacy_status at execution"
            )

        with (
            patch.object(tm.sm, "state", state),
            patch.object(
                tm.llm,
                "generate_social_metadata",
                return_value={"title": "Coffee", "caption": "Sip.", "hashtags": []},
            ),
            patch.object(
                postiz_service,
                "upload_video",
                return_value={"success": True, "results": [{"platform": "tiktok", "success": True}]},
            ) as postiz_upload,
            patch.object(tm.upload_post.upload_post_service, "upload_video") as upload_post_upload,
            patch.object(tm.PUBLISHING_PROVIDER_REGISTRY["postiz"], "is_configured") as live_configured,
            patch.object(type(postiz_service), "platforms", new_callable=PropertyMock, side_effect=_forbidden_platforms),
            patch.object(type(postiz_service), "youtube_privacy_status", new_callable=PropertyMock, side_effect=_forbidden_privacy),
        ):
            live_configured.side_effect = AssertionError(
                "worker must not call provider.is_configured at execution"
            )
            # Legacy positional args deliberately disagree (YouTube/private):
            # the snapshot path must ignore them entirely.
            tm._run_cross_post(
                "snapshot-tiktok",
                ("final.mp4",),
                "Coffee",
                "A short coffee story.",
                "en",
                ("youtube",),
                "private",
                snapshot,
            )

        postiz_upload.assert_called_once()
        call = postiz_upload.call_args
        self.assertEqual(call.kwargs["platforms"], ["tiktok"])
        self.assertEqual(call.kwargs["youtube_privacy_status"], "public")
        self.assertEqual(call.kwargs["tiktok_auto_add_music"], "yes")
        self.assertEqual(call.kwargs["integration_ids"], {"tiktok": "tt-int-id"})
        upload_post_upload.assert_not_called()
        task = state.get_task("snapshot-tiktok")
        self.assertEqual(task["cross_post_state"], tm.const.CROSS_POST_STATE_COMPLETE)

    def test_snapshot_freezes_upload_post_destinations(self):
        """Upload-Post users path: snapshot platforms + privacy win over live."""
        state = MemoryState()
        state.update_task(
            "snapshot-upload-post",
            state=tm.const.TASK_STATE_COMPLETE,
            progress=100,
            videos=["final.mp4"],
            cross_post_state=tm.const.CROSS_POST_STATE_PENDING,
        )
        upload_service = tm.upload_post.upload_post_service
        snapshot = [
            {
                "provider": "upload_post",
                "platforms": ["tiktok", "instagram"],
                "youtube_privacy_status": "private",
                "extra": {"privacy_level": "PUBLIC_TO_EVERYONE"},
            }
        ]

        def _forbidden_platforms(_self):
            raise AssertionError("worker must not read provider.platforms at execution")

        with (
            patch.object(tm.sm, "state", state),
            patch.object(
                tm.llm,
                "generate_social_metadata",
                return_value={"title": "Coffee", "caption": "Sip.", "hashtags": []},
            ),
            patch.object(
                tm.PUBLISHING_PROVIDER_REGISTRY["postiz"],
                "is_configured",
                return_value=False,
            ),
            patch.object(upload_service, "is_configured") as live_configured,
            patch.object(type(upload_service), "platforms", new_callable=PropertyMock, side_effect=_forbidden_platforms),
            patch.object(
                upload_service,
                "upload_video",
                return_value={"success": True},
            ) as upload_post_upload,
        ):
            live_configured.side_effect = AssertionError(
                "worker must not call provider.is_configured at execution"
            )
            tm._run_cross_post(
                "snapshot-upload-post",
                ("final.mp4",),
                "Coffee",
                "A short coffee story.",
                "en",
                ("youtube",),
                "public",
                snapshot,
            )

        upload_post_upload.assert_called_once()
        call = upload_post_upload.call_args
        self.assertEqual(call.kwargs["platforms"], ["tiktok", "instagram"])
        self.assertEqual(call.kwargs["privacy_level"], "PUBLIC_TO_EVERYONE")
        self.assertTrue(call.kwargs["skip_config_check"])
        task = state.get_task("snapshot-upload-post")
        self.assertEqual(task["cross_post_state"], tm.const.CROSS_POST_STATE_COMPLETE)

    def test_schedule_cross_post_passes_snapshot_to_worker(self):
        """Queue-time snapshot must reach the background worker verbatim."""
        from app.models.schema import VideoParams

        snapshot = [
            {
                "provider": "postiz",
                "platforms": ["tiktok"],
                "youtube_privacy_status": "public",
                "extra": {
                    "tiktok_auto_add_music": "yes",
                    "reddit_subreddit": "",
                    "integration_ids": {"tiktok": "tt-int-id"},
                },
            }
        ]
        state = MemoryState()
        with (
            patch.object(tm.sm, "state", state),
            patch.object(tm._cross_post_slots, "acquire", return_value=True),
            patch.object(tm._cross_post_slots, "release"),
            patch.object(tm, "_register_cross_post_future"),
            patch.object(tm._cross_post_executor, "submit") as submit,
        ):
            error = tm._schedule_cross_post(
                task_id="snapshot-plumbing",
                video_paths=["final.mp4"],
                params=VideoParams(video_subject="Coffee"),
                video_script="A short coffee story.",
                platforms=["tiktok"],
                youtube_privacy_status="public",
                publishing_snapshot=snapshot,
            )

        self.assertIsNone(error)
        submit.assert_called_once()
        # Merged submit order is (..., privacy, snapshot, kids): the snapshot
        # is second-to-last now that the upstream audience flag trails it.
        submitted_snapshot = submit.call_args.args[-2]
        self.assertEqual(submitted_snapshot, snapshot)
        self.assertIsInstance(submit.call_args.args[-1], bool)

    def test_snapshot_builder_captures_postiz_integration_ids(self):
        """Queue-time builder must freeze platforms, privacy, and extras."""
        postiz_service = tm.PUBLISHING_PROVIDER_REGISTRY["postiz"]
        with (
            patch.object(postiz_service, "is_configured", return_value=True),
            patch.object(type(postiz_service), "auto_upload", new_callable=PropertyMock, return_value=True),
            patch.object(type(postiz_service), "platforms", new_callable=PropertyMock, return_value=["tiktok"]),
            patch.object(type(postiz_service), "youtube_privacy_status", new_callable=PropertyMock, return_value="unlisted"),
            patch.object(tm.upload_post.upload_post_service, "is_configured", return_value=False),
            patch.dict(
                tm.config.app,
                {
                    "postiz_tiktok_auto_add_music": "yes",
                    "postiz_reddit_subreddit": "videos",
                    "postiz_tiktok_integration_id": "tt-int-id",
                },
                clear=False,
            ),
        ):
            snapshots = tm._snapshot_publishing_targets()

            self.assertEqual(len(snapshots), 1)
            entry = snapshots[0]
            self.assertEqual(entry["provider"], "postiz")
            self.assertEqual(entry["platforms"], ["tiktok"])
            self.assertEqual(entry["youtube_privacy_status"], "unlisted")
            self.assertEqual(entry["extra"]["tiktok_auto_add_music"], "yes")
            self.assertEqual(entry["extra"]["reddit_subreddit"], "videos")
            self.assertEqual(entry["extra"]["integration_ids"], {"tiktok": "tt-int-id"})
            # The snapshot must hold a copy: mutating it leaves live config alone.
            live_platforms = postiz_service.platforms
            entry["platforms"].append("youtube")
            self.assertEqual(list(postiz_service.platforms), list(live_platforms))
            self.assertNotEqual(entry["platforms"], live_platforms)

    def test_snapshot_builder_freezes_endpoint_credentials_and_username(self):
        """Endpoint/auth/account are queue-time values, not live reads."""
        postiz_service = tm.PUBLISHING_PROVIDER_REGISTRY["postiz"]
        upload_service = tm.upload_post.upload_post_service
        with (
            patch.object(postiz_service, "is_configured", return_value=True),
            patch.object(type(postiz_service), "auto_upload", new_callable=PropertyMock, return_value=True),
            patch.object(type(postiz_service), "platforms", new_callable=PropertyMock, return_value=["youtube"]),
            patch.object(upload_service, "is_configured", return_value=True),
            patch.object(type(upload_service), "auto_upload", new_callable=PropertyMock, return_value=True),
            patch.object(type(upload_service), "platforms", new_callable=PropertyMock, return_value=["tiktok"]),
            patch.dict(
                tm.config.app,
                {
                    "postiz_api_url": "http://instance-a:8004",
                    "postiz_api_key": "key-a",
                    "postiz_youtube_integration_id": "yt-int-id",
                    "upload_post_username": "queued-user",
                },
                clear=False,
            ),
        ):
            snapshots = tm._snapshot_publishing_targets()

        by_provider = {entry["provider"]: entry for entry in snapshots}
        self.assertEqual(by_provider["postiz"]["extra"]["api_url"], "http://instance-a:8004")
        self.assertEqual(by_provider["postiz"]["extra"]["api_key"], "key-a")
        self.assertEqual(by_provider["upload_post"]["extra"]["username"], "queued-user")

    def test_worker_passes_frozen_endpoint_credentials_and_username(self):
        """Live config changes before execution must not reach the providers."""
        postiz_service = tm.PUBLISHING_PROVIDER_REGISTRY["postiz"]
        upload_service = tm.upload_post.upload_post_service
        snapshot = [
            {
                "provider": "postiz",
                "platforms": ["youtube"],
                "youtube_privacy_status": "private",
                "extra": {
                    "tiktok_auto_add_music": "no",
                    "reddit_subreddit": "",
                    "integration_ids": {"youtube": "yt-A"},
                    "api_url": "http://instance-a:8004",
                    "api_key": "key-a",
                },
            },
            {
                "provider": "upload_post",
                "platforms": ["tiktok"],
                "youtube_privacy_status": "public",
                "extra": {
                    "privacy_level": "PUBLIC_TO_EVERYONE",
                    "username": "queued-user",
                },
            },
        ]
        results: list = []
        with (
            patch.object(
                tm.llm,
                "generate_social_metadata",
                return_value={"title": "Coffee", "caption": "Sip.", "hashtags": []},
            ),
            patch.object(
                postiz_service, "upload_video", return_value={"success": True}
            ) as postiz_upload,
            patch.object(
                upload_service, "upload_video", return_value={"success": True}
            ) as upload_post_upload,
        ):
            tm._run_cross_post_from_snapshot(
                "frozen-endpoint",
                ("final.mp4",),
                "Coffee",
                "A short coffee story.",
                "en",
                snapshot,
                results,
            )

        postiz_kwargs = postiz_upload.call_args[1]
        self.assertEqual(postiz_kwargs.get("api_url"), "http://instance-a:8004")
        self.assertEqual(postiz_kwargs.get("api_key"), "key-a")
        upload_kwargs = upload_post_upload.call_args[1]
        self.assertEqual(upload_kwargs.get("username"), "queued-user")

    def test_worker_legacy_snapshot_without_frozen_keys_falls_back_live(self):
        """Snapshots built before the freeze (no new keys) keep working."""
        postiz_service = tm.PUBLISHING_PROVIDER_REGISTRY["postiz"]
        snapshot = [
            {
                "provider": "postiz",
                "platforms": ["youtube"],
                "youtube_privacy_status": "public",
                "extra": {
                    "tiktok_auto_add_music": "no",
                    "reddit_subreddit": "",
                    "integration_ids": {"youtube": "yt-int-id"},
                },
            }
        ]
        results: list = []
        with (
            patch.object(
                tm.llm,
                "generate_social_metadata",
                return_value={"title": "Coffee", "caption": "Sip.", "hashtags": []},
            ),
            patch.object(
                postiz_service, "upload_video", return_value={"success": True}
            ) as postiz_upload,
        ):
            tm._run_cross_post_from_snapshot(
                "legacy-snapshot",
                ("final.mp4",),
                "Coffee",
                "A short coffee story.",
                "en",
                snapshot,
                results,
            )

        postiz_kwargs = postiz_upload.call_args[1]
        self.assertIsNone(postiz_kwargs.get("api_url"))
        self.assertIsNone(postiz_kwargs.get("api_key"))


if __name__ == "__main__":
    unittest.main()
