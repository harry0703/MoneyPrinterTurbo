import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.upload_post import UploadPostService


_CONFIG_BASE = {
    "upload_post_enabled": True,
    "upload_post_api_key": "test-key",
    "upload_post_username": "testuser",
    "upload_post_platforms": ["tiktok", "instagram", "youtube"],
    "upload_post_auto_upload": True,
    "upload_post_youtube_privacy_status": "unlisted",
}


def _mock_response(success=True):
    r = MagicMock()
    r.json.return_value = {"success": success, "request_id": "abc123"}
    r.raise_for_status = MagicMock()
    return r


class TestUploadPostYouTube(unittest.TestCase):

    @patch("app.services.upload_post.config.app", _CONFIG_BASE)
    @patch("app.services.upload_post.os.path.exists", return_value=True)
    @patch("builtins.open", mock_open(read_data=b"fake"))
    @patch("app.services.upload_post.requests.post")
    def test_youtube_fields_en_payload(self, mock_post, _exists):
        mock_post.return_value = _mock_response()
        svc = UploadPostService()

        svc.upload_video("/fake/v.mp4", "Título", youtube_extra={
            "youtube_title": "Mi Short",
            "youtube_description": "Descripción",
            "tags": ["ia", "shorts"],
            "privacyStatus": "unlisted",
        })

        data = mock_post.call_args[1]["data"]
        self.assertEqual(data["youtube_title"], "Mi Short")
        self.assertEqual(data["youtube_description"], "Descripción")
        self.assertEqual(data["tags[0]"], "ia")
        self.assertEqual(data["tags[1]"], "shorts")
        self.assertEqual(data["privacyStatus"], "unlisted")
        self.assertIs(data["containsSyntheticMedia"], True)

    @patch("app.services.upload_post.config.app", _CONFIG_BASE)
    @patch("app.services.upload_post.os.path.exists", return_value=True)
    @patch("builtins.open", mock_open(read_data=b"fake"))
    @patch("app.services.upload_post.requests.post")
    def test_contains_synthetic_media_siempre_true(self, mock_post, _exists):
        mock_post.return_value = _mock_response()
        svc = UploadPostService()

        # ponytail: containsSyntheticMedia forzado a True aunque se pase False
        svc.upload_video("/fake/v.mp4", "T", youtube_extra={"containsSyntheticMedia": False})

        data = mock_post.call_args[1]["data"]
        self.assertIs(data["containsSyntheticMedia"], True)

    @patch("app.services.upload_post.config.app", {
        **_CONFIG_BASE,
        "upload_post_platforms": ["tiktok", "instagram"],
    })
    @patch("app.services.upload_post.os.path.exists", return_value=True)
    @patch("builtins.open", mock_open(read_data=b"fake"))
    @patch("app.services.upload_post.requests.post")
    def test_tiktok_instagram_sin_youtube_fields(self, mock_post, _exists):
        mock_post.return_value = _mock_response()
        svc = UploadPostService()
        svc.upload_video("/fake/v.mp4", "T")

        data = mock_post.call_args[1]["data"]
        self.assertNotIn("youtube_title", data)
        self.assertNotIn("containsSyntheticMedia", data)
        self.assertNotIn("privacyStatus", data)

    @patch("app.services.upload_post.config.app", {
        **_CONFIG_BASE,
        "upload_post_platforms": ["tiktok"],
    })
    @patch("app.services.upload_post.os.path.exists", return_value=True)
    @patch("builtins.open", mock_open(read_data=b"fake"))
    @patch("app.services.upload_post.requests.post")
    def test_youtube_extra_ignorado_si_youtube_no_en_platforms(self, mock_post, _exists):
        mock_post.return_value = _mock_response()
        svc = UploadPostService()
        svc.upload_video("/fake/v.mp4", "T", youtube_extra={"youtube_title": "irrelevante"})

        data = mock_post.call_args[1]["data"]
        self.assertNotIn("youtube_title", data)


if __name__ == "__main__":
    unittest.main()
