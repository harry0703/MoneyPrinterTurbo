import hashlib
import hmac
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect
from app.services import material


def _fake_response(payload, status_code=200):
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


class TestStoryblocksAuth(unittest.TestCase):
    def test_auth_params_sign_the_resource_path(self):
        app = {"storyblocks_api_keys": ["pub-key:priv-key"]}
        with mock.patch.object(config, "app", app), mock.patch.object(
            material.time, "time", return_value=1700000000
        ):
            params = material._storyblocks_auth_params("/api/v2/videos/search")

        expected = hmac.new(
            b"priv-key1700000000",
            b"/api/v2/videos/search",
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(params["APIKEY"], "pub-key")
        self.assertEqual(params["EXPIRES"], "1700000000")
        self.assertEqual(params["HMAC"], expected)

    def test_key_entry_without_private_part_is_rejected(self):
        app = {"storyblocks_api_keys": ["only-public"]}
        with mock.patch.object(config, "app", app):
            with self.assertRaises(ValueError):
                material._storyblocks_credentials()

    def test_tracking_ids_default_when_unset(self):
        with mock.patch.object(config, "app", {}):
            tracking = material._storyblocks_tracking_params()
        self.assertEqual(tracking["project_id"], "moneyprinterturbo")
        self.assertEqual(tracking["user_id"], "moneyprinterturbo")

    def test_tracking_ids_come_from_config(self):
        app = {"storyblocks_project_id": "proj-1", "storyblocks_user_id": "user-1"}
        with mock.patch.object(config, "app", app):
            tracking = material._storyblocks_tracking_params()
        self.assertEqual(tracking["project_id"], "proj-1")
        self.assertEqual(tracking["user_id"], "user-1")


class TestStoryblocksSearch(unittest.TestCase):
    def _search(self, payload, aspect=VideoAspect.portrait, minimum_duration=5):
        app = {"storyblocks_api_keys": ["pub:priv"]}
        with mock.patch.object(config, "app", app), mock.patch.object(
            material.requests, "get", return_value=_fake_response(payload)
        ) as get:
            items = material.search_videos_storyblocks(
                search_term="ocean waves",
                minimum_duration=minimum_duration,
                video_aspect=aspect,
            )
        return items, get

    def test_results_become_download_endpoint_items(self):
        payload = {
            "results": [
                {"id": 111, "duration": 12},
                {"id": 222, "duration": 3},
                {"id": None, "duration": 30},
                {"id": 333, "duration": "not-a-number"},
            ]
        }
        items, _ = self._search(payload)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].provider, "storyblocks")
        self.assertEqual(
            items[0].url, "https://api.storyblocks.com/api/v2/videos/111/download"
        )
        self.assertEqual(items[0].duration, 12)

    def test_legacy_info_envelope_is_accepted(self):
        payload = {"success": True, "info": [{"id": 9, "duration": 20}]}
        items, _ = self._search(payload)
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].url.endswith("/api/v2/videos/9/download"))

    def test_request_carries_auth_search_and_orientation_params(self):
        items, get = self._search({"results": []}, aspect=VideoAspect.landscape)
        self.assertEqual(items, [])
        query = parse_qs(urlparse(get.call_args.args[0]).query)
        self.assertEqual(query["keywords"], ["ocean waves"])
        self.assertEqual(query["content_type"], ["footage"])
        self.assertEqual(query["orientation"], ["landscape"])
        self.assertEqual(query["min_duration"], ["5"])
        self.assertEqual(query["project_id"], ["moneyprinterturbo"])
        self.assertEqual(query["user_id"], ["moneyprinterturbo"])
        for auth_param in ("APIKEY", "EXPIRES", "HMAC"):
            self.assertIn(auth_param, query)

    def test_unexpected_payload_returns_empty(self):
        items, _ = self._search({"message": "nope"})
        self.assertEqual(items, [])

    def test_network_error_returns_empty(self):
        app = {"storyblocks_api_keys": ["pub:priv"]}
        with mock.patch.object(config, "app", app), mock.patch.object(
            material.requests, "get", side_effect=RuntimeError("boom")
        ):
            items = material.search_videos_storyblocks(
                search_term="x", minimum_duration=5
            )
        self.assertEqual(items, [])


class TestStoryblocksDownloadResolution(unittest.TestCase):
    def test_non_storyblocks_items_pass_through(self):
        item = MaterialInfo()
        item.provider = "pexels"
        item.url = "https://videos.pexels.com/a.mp4"
        self.assertEqual(material._resolve_material_url(item), item.url)

    def _resolve(self, payload):
        item = MaterialInfo()
        item.provider = "storyblocks"
        item.url = "https://api.storyblocks.com/api/v2/videos/111/download"
        app = {"storyblocks_api_keys": ["pub:priv"]}
        with mock.patch.object(config, "app", app), mock.patch.object(
            material.requests, "get", return_value=_fake_response(payload)
        ) as get:
            url = material._resolve_material_url(item)
        return url, get

    def test_v2_url_field_is_used(self):
        url, get = self._resolve({"url": "https://cdn.example/clip.mp4"})
        self.assertEqual(url, "https://cdn.example/clip.mp4")
        params = get.call_args.kwargs["params"]
        self.assertIn("HMAC", params)
        self.assertEqual(params["project_id"], "moneyprinterturbo")

    def test_legacy_info_url_field_is_used(self):
        url, _ = self._resolve({"success": True, "info": {"url": "https://cdn.example/v1.mp4"}})
        self.assertEqual(url, "https://cdn.example/v1.mp4")

    def test_missing_url_raises(self):
        with self.assertRaises(ValueError):
            self._resolve({"success": False, "message": "denied"})


class TestStoryblocksDispatch(unittest.TestCase):
    def test_download_videos_uses_storyblocks_search(self):
        with mock.patch.object(
            material, "search_videos_storyblocks", return_value=[]
        ) as search:
            material.download_videos(
                task_id="t",
                search_terms=["waves"],
                source="storyblocks",
                audio_duration=1.0,
            )
        search.assert_called_once()


if __name__ == "__main__":
    unittest.main()
