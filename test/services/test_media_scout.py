import builtins
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.services import media_scout


def _fake_response(
    content: bytes, content_type: str, status_code: int = 200
) -> SimpleNamespace:
    return SimpleNamespace(
        status_code=status_code,
        headers={"content-type": content_type},
        content=content,
        raise_for_status=lambda: None,
    )


class TestMediaScout(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.original_proxy_config = dict(config.proxy)
        config.app["photo_scout_enabled"] = True
        config.proxy.clear()

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        config.proxy.clear()
        config.proxy.update(self.original_proxy_config)

    def test_disabled_is_noop(self):
        config.app["photo_scout_enabled"] = False
        with patch("app.services.media_scout._fetch_full_size_urls") as fetch:
            result = media_scout.scout_images("sunset beach")

        self.assertEqual(result, [])
        fetch.assert_not_called()

    def test_search_limit_reads_config(self):
        config.app["photo_scout_search_limit"] = 5
        self.assertEqual(media_scout.search_limit(), 5)

    def test_search_limit_defaults_to_three(self):
        config.app.pop("photo_scout_search_limit", None)
        self.assertEqual(media_scout.search_limit(), 3)

    def test_no_results_returns_empty(self):
        with patch("app.services.media_scout._fetch_full_size_urls", return_value=[]):
            result = media_scout.scout_images("no such thing")

        self.assertEqual(result, [])

    def test_search_failure_returns_empty_not_raise(self):
        with patch(
            "app.services.media_scout._fetch_full_size_urls",
            side_effect=RuntimeError("boom"),
        ):
            result = media_scout.scout_images("sunset beach")

        self.assertEqual(result, [])

    def test_missing_playwright_package_degrades_to_empty(self):
        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "playwright.sync_api" or name.startswith("playwright"):
                raise ImportError("no module named playwright")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_fake_import):
            result = media_scout.scout_images("sunset beach")

        self.assertEqual(result, [])

    def test_ingest_receives_origin_and_provenance(self):
        urls = ["https://a.test/1.jpg"]
        ingested = []

        def _fake_ingest(source, **kwargs):
            ingested.append(kwargs)
            asset = SimpleNamespace(id=1, rel_path="scout/1.jpg")
            return SimpleNamespace(asset=asset, created=True)

        with (
            patch("app.services.media_scout._fetch_full_size_urls", return_value=urls),
            patch(
                "app.services.media_scout.requests.get",
                return_value=_fake_response(b"x" * 6000, "image/jpeg"),
            ),
            patch("app.services.asset_library.ingest_file", side_effect=_fake_ingest),
        ):
            result = media_scout.scout_images("golden retriever puppy")

        self.assertEqual(len(result), 1)
        self.assertEqual(ingested[0]["origin"], "search")
        self.assertEqual(ingested[0]["source_query"], "golden retriever puppy")
        self.assertEqual(ingested[0]["source_url"], "https://a.test/1.jpg")

    def test_rejects_non_image_content_type(self):
        with (
            patch(
                "app.services.media_scout._fetch_full_size_urls",
                return_value=["https://a.test/1.html"],
            ),
            patch(
                "app.services.media_scout.requests.get",
                return_value=_fake_response(b"<html>oops</html>" * 500, "text/html"),
            ),
            patch("app.services.asset_library.ingest_file") as ingest_file,
        ):
            result = media_scout.scout_images("sunset beach")

        self.assertEqual(result, [])
        ingest_file.assert_not_called()

    def test_rejects_undersized_file(self):
        with (
            patch(
                "app.services.media_scout._fetch_full_size_urls",
                return_value=["https://a.test/1.jpg"],
            ),
            patch(
                "app.services.media_scout.requests.get",
                return_value=_fake_response(b"x" * 100, "image/jpeg"),
            ),
            patch("app.services.asset_library.ingest_file") as ingest_file,
        ):
            result = media_scout.scout_images("sunset beach")

        self.assertEqual(result, [])
        ingest_file.assert_not_called()

    def test_extension_taken_from_content_type_not_url(self):
        captured_paths = []

        def _fake_ingest(source, **kwargs):
            captured_paths.append(source)
            asset = SimpleNamespace(id=1, rel_path="scout/1.png")
            return SimpleNamespace(asset=asset, created=True)

        with (
            patch(
                "app.services.media_scout._fetch_full_size_urls",
                return_value=["https://a.test/photo.jpg?ext=lie"],
            ),
            patch(
                "app.services.media_scout.requests.get",
                return_value=_fake_response(b"x" * 6000, "image/png"),
            ),
            patch("app.services.asset_library.ingest_file", side_effect=_fake_ingest),
        ):
            media_scout.scout_images("sunset beach")

        self.assertTrue(captured_paths)
        self.assertTrue(captured_paths[0].endswith(".png"))

    def test_dedup_within_batch_by_content_hash(self):
        urls = ["https://a.test/mirror-1.jpg", "https://b.test/mirror-2.jpg"]
        ingested = []

        def _fake_ingest(source, **kwargs):
            ingested.append(source)
            asset = SimpleNamespace(
                id=len(ingested), rel_path=f"scout/{len(ingested)}.jpg"
            )
            return SimpleNamespace(asset=asset, created=True)

        same_bytes = b"y" * 6000
        with (
            patch("app.services.media_scout._fetch_full_size_urls", return_value=urls),
            patch(
                "app.services.media_scout.requests.get",
                return_value=_fake_response(same_bytes, "image/jpeg"),
            ),
            patch("app.services.asset_library.ingest_file", side_effect=_fake_ingest),
        ):
            result = media_scout.scout_images("duplicate photo")

        self.assertEqual(len(result), 1)
        self.assertEqual(len(ingested), 1)

    def test_recovers_positions_after_broken_links(self):
        urls = [
            "https://a.test/broken-1.jpg",
            "https://a.test/broken-2.jpg",
            "https://a.test/good-3.jpg",
        ]
        ingested = []

        def _fake_ingest(source, **kwargs):
            ingested.append(source)
            asset = SimpleNamespace(
                id=len(ingested), rel_path=f"scout/{len(ingested)}.jpg"
            )
            return SimpleNamespace(asset=asset, created=True)

        def _fake_get(url, **kwargs):
            if "broken" in url:
                raise RuntimeError("connection reset")
            return _fake_response(b"z" * 6000, "image/jpeg")

        with (
            patch("app.services.media_scout._fetch_full_size_urls", return_value=urls),
            patch("app.services.media_scout.requests.get", side_effect=_fake_get),
            patch("app.services.asset_library.ingest_file", side_effect=_fake_ingest),
        ):
            result = media_scout.scout_images("resilient search", limit=1)

        self.assertEqual(len(result), 1)
        self.assertIn("scout-002", ingested[0])

    def test_stops_once_limit_reached(self):
        urls = [f"https://a.test/{i}.jpg" for i in range(5)]
        ingested = []

        def _fake_ingest(source, **kwargs):
            ingested.append(source)
            asset = SimpleNamespace(
                id=len(ingested), rel_path=f"scout/{len(ingested)}.jpg"
            )
            return SimpleNamespace(asset=asset, created=True)

        def _fake_get(url, **kwargs):
            index = url.rsplit("/", 1)[-1].split(".")[0]
            return _fake_response(f"unique-{index}".encode() * 2000, "image/jpeg")

        with (
            patch("app.services.media_scout._fetch_full_size_urls", return_value=urls),
            patch("app.services.media_scout.requests.get", side_effect=_fake_get),
            patch("app.services.asset_library.ingest_file", side_effect=_fake_ingest),
        ):
            result = media_scout.scout_images("many results", limit=2)

        self.assertEqual(len(result), 2)
        self.assertEqual(len(ingested), 2)

    def test_empty_query_is_noop(self):
        with patch("app.services.media_scout._fetch_full_size_urls") as fetch:
            result = media_scout.scout_images("   ")

        self.assertEqual(result, [])
        fetch.assert_not_called()

    def test_ingest_failure_is_skipped_not_raised(self):
        def _raising_ingest(source, **kwargs):
            raise RuntimeError("db down")

        with (
            patch(
                "app.services.media_scout._fetch_full_size_urls",
                return_value=["https://a.test/1.jpg"],
            ),
            patch(
                "app.services.media_scout.requests.get",
                return_value=_fake_response(b"x" * 6000, "image/jpeg"),
            ),
            patch(
                "app.services.asset_library.ingest_file", side_effect=_raising_ingest
            ),
        ):
            result = media_scout.scout_images("sunset beach")

        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
