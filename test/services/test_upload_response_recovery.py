from unittest.mock import MagicMock, patch
import pytest
from app.services.upload_post import UploadPostService

@pytest.mark.parametrize("payload", [None, [], {"success": "true"}, {"success": True}])
def test_unconfirmed_upload_response_retains_sent_recovery_id(tmp_path, payload):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"video fixture")
    response = MagicMock(status_code=200)
    if payload is None:
        response.json.side_effect = ValueError("truncated JSON")
    else:
        response.json.return_value = payload
    service = UploadPostService({"upload_post_enabled": True, "upload_post_api_key": "fake-key", "upload_post_username": "test-user"})
    with patch("app.services.upload_post.requests.post", return_value=response) as post:
        result = service.upload_video(str(video), "Title", platforms=["tiktok"])
    sent_id = dict(post.call_args.kwargs["data"])["request_id"]
    assert result["success"] is False
    assert result["request_id"] == sent_id
    assert sent_id in result["error"] and "unconfirmed" in result["error"]
    post.assert_called_once()

def test_provider_rejection_remains_a_confirmed_failure(tmp_path):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"video fixture")
    response = MagicMock(status_code=200)
    response.json.return_value = {"success": False, "error": "invalid title"}
    service = UploadPostService({"upload_post_enabled": True, "upload_post_api_key": "fake-key", "upload_post_username": "test-user"})
    with patch("app.services.upload_post.requests.post", return_value=response):
        assert service.upload_video(str(video), "Title", platforms=["tiktok"]) == response.json.return_value
