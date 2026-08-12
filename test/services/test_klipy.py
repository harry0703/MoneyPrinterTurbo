import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.services import klipy


def _media_variant(url: str, width: int, height: int) -> dict:
    return {"url": url, "width": width, "height": height, "size": 1024}


def _gif_item(slug: str = "meme-slug") -> dict:
    return {
        "id": 1,
        "slug": slug,
        "title": "Mind Blown Meme",
        "type": "gif",
        "file": {
            "hd": {"mp4": _media_variant("https://static.klipy.com/hd.mp4", 640, 408)},
            "md": {"mp4": _media_variant("https://static.klipy.com/md.mp4", 480, 306)},
            "sm": {"mp4": _media_variant("https://static.klipy.com/sm.mp4", 288, 184)},
        },
    }


def _fake_response(payload, status_code: int = 200, headers=None) -> SimpleNamespace:
    return SimpleNamespace(
        status_code=status_code,
        headers=headers or {},
        json=lambda: payload,
        raise_for_status=lambda: None,
    )


class TestKlipySearch(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.original_proxy_config = dict(config.proxy)
        config.app["klipy_api_keys"] = ["klipy-key"]
        config.proxy.clear()

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        config.proxy.clear()
        config.proxy.update(self.original_proxy_config)

    def test_search_returns_smallest_variant_covering_min_width(self):
        """
        叠加层只占画面一小部分，下载 hd 变体会浪费带宽和解码时间。
        """
        payload = {"result": True, "data": {"data": [_gif_item()]}}
        with patch(
            "app.services.klipy.requests.get", return_value=_fake_response(payload)
        ):
            gifs = klipy.search_gifs("mind blown", min_width=400)

        self.assertEqual(len(gifs), 1)
        self.assertEqual(gifs[0].url, "https://static.klipy.com/md.mp4")
        self.assertEqual(gifs[0].width, 480)
        self.assertEqual(gifs[0].slug, "meme-slug")

    def test_search_falls_back_to_largest_variant(self):
        payload = {"result": True, "data": {"data": [_gif_item()]}}
        with patch(
            "app.services.klipy.requests.get", return_value=_fake_response(payload)
        ):
            gifs = klipy.search_gifs("mind blown", min_width=4000)

        self.assertEqual(gifs[0].url, "https://static.klipy.com/hd.mp4")

    def test_search_skips_items_without_mp4(self):
        item = {"slug": "no-mp4", "title": "Sticker", "file": {"md": {"webp": {}}}}
        payload = {"result": True, "data": {"data": [item, _gif_item()]}}
        with patch(
            "app.services.klipy.requests.get", return_value=_fake_response(payload)
        ):
            gifs = klipy.search_gifs("thumbs up")

        self.assertEqual([gif.slug for gif in gifs], ["meme-slug"])

    def test_search_rejects_non_https_urls(self):
        item = _gif_item()
        item["file"] = {
            "md": {"mp4": _media_variant("http://evil.test/x.mp4", 480, 306)}
        }
        payload = {"result": True, "data": {"data": [item]}}
        with patch(
            "app.services.klipy.requests.get", return_value=_fake_response(payload)
        ):
            gifs = klipy.search_gifs("mind blown")

        self.assertEqual(gifs, [])

    def test_rate_limited_response_returns_empty_list(self):
        """
        测试 Key 每小时只有 100 次调用，触发限流时必须安静降级而不是让整条任务失败。
        """
        response = _fake_response(
            {}, status_code=429, headers={"x-ratelimit-remaining": "0"}
        )
        with patch("app.services.klipy.requests.get", return_value=response):
            gifs = klipy.search_gifs("mind blown")

        self.assertEqual(gifs, [])
        self.assertEqual(klipy.get_rate_limit_remaining(), 0)

    def test_request_failure_returns_empty_list(self):
        with patch("app.services.klipy.requests.get", side_effect=RuntimeError("boom")):
            self.assertEqual(klipy.search_gifs("mind blown"), [])

    def test_unsupported_payload_returns_empty_list(self):
        with patch(
            "app.services.klipy.requests.get",
            return_value=_fake_response({"result": False}),
        ):
            self.assertEqual(klipy.search_gifs("mind blown"), [])

    def test_missing_api_key_raises(self):
        config.app.pop("klipy_api_keys", None)
        with self.assertRaises(ValueError):
            klipy.get_api_key()

    def test_search_uses_tls_verification_by_default(self):
        config.app.pop("tls_verify", None)
        payload = {"result": True, "data": {"data": [_gif_item()]}}
        with patch(
            "app.services.klipy.requests.get", return_value=_fake_response(payload)
        ) as mocked_get:
            klipy.search_gifs("mind blown")

        self.assertTrue(mocked_get.call_args.kwargs["verify"])

    def test_api_key_never_reaches_logs_on_failure(self):
        messages = []
        with (
            patch(
                "app.services.klipy.requests.get",
                side_effect=RuntimeError(
                    "connection to https://api.klipy.com/api/v1/klipy-key/gifs/search failed"
                ),
            ),
            patch("app.services.klipy.logger.error", side_effect=messages.append),
        ):
            klipy.search_gifs("mind blown")

        self.assertTrue(messages)
        self.assertNotIn("klipy-key", " ".join(messages))


class TestKlipyFetch(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        config.app["klipy_api_keys"] = ["klipy-key"]

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def test_fetch_skips_excluded_slugs(self):
        """
        同一条视频里重复出现同一个梗图会显得廉价，已用过的素材必须跳过。
        """
        gifs = [
            klipy.GifInfo(
                slug="used", title="a", url="https://x/a.mp4", width=480, height=270
            ),
            klipy.GifInfo(
                slug="fresh", title="b", url="https://x/b.mp4", width=480, height=270
            ),
        ]
        with (
            patch("app.services.klipy.search_gifs", return_value=gifs),
            patch("app.services.klipy.save_gif", return_value="/tmp/gif.mp4"),
        ):
            gif = klipy.fetch_gif("mind blown", exclude_slugs={"used"})

        self.assertIsNotNone(gif)
        self.assertEqual(gif.slug, "fresh")
        self.assertEqual(gif.url, "/tmp/gif.mp4")

    def test_fetch_returns_none_when_download_fails(self):
        gifs = [
            klipy.GifInfo(
                slug="a", title="a", url="https://x/a.mp4", width=480, height=270
            )
        ]
        with (
            patch("app.services.klipy.search_gifs", return_value=gifs),
            patch("app.services.klipy.save_gif", return_value=""),
        ):
            self.assertIsNone(klipy.fetch_gif("mind blown"))


if __name__ == "__main__":
    unittest.main()
