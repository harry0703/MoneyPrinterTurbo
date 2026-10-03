from unittest.mock import mock_open, patch

import pytest

from app.services.upload_post import UploadPostService


@pytest.mark.parametrize("extra", [None, {}, {"youtube_title": "A title"}])
@pytest.mark.parametrize("privacy", ["private", "unlisted"])
def test_youtube_uses_configured_privacy_without_generated_metadata(extra, privacy):
    values = {
        "upload_post_api_key": "fixture-key",
        "upload_post_username": "fixture-user",
        "upload_post_enabled": True,
        "upload_post_platforms": ["youtube"],
        "upload_post_youtube_privacy_status": privacy,
    }
    with (
        patch("app.services.upload_post.config.app", values),
        patch("app.services.upload_post.os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=b"fixture")),
        patch("app.services.upload_post.requests.post") as post,
    ):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {
            "success": True, "results": {"youtube": {"success": True}},
        }
        UploadPostService().upload_video("fixture.mp4", "Title", youtube_extra=extra)
        data = post.call_args.kwargs["data"]
        assert [value for key, value in data if key == "privacyStatus"] == [privacy]


def test_explicit_queued_youtube_privacy_wins_over_current_configuration():
    values = {
        "upload_post_api_key": "fixture-key", "upload_post_username": "fixture-user",
        "upload_post_enabled": True, "upload_post_platforms": ["youtube"],
        "upload_post_youtube_privacy_status": "public",
    }
    with (
        patch("app.services.upload_post.config.app", values),
        patch("app.services.upload_post.os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=b"fixture")),
        patch("app.services.upload_post.requests.post") as post,
    ):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"success": False}
        UploadPostService().upload_video("fixture.mp4", "Title", youtube_extra={"privacyStatus": "private"})
        assert dict(post.call_args.kwargs["data"])["privacyStatus"] == "private"
