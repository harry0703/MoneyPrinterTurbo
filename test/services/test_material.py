import os
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.services import material
from app.utils import logging_utils


@contextmanager
def _capture_task_scoped_logs():
    """Collect logs by the same rule as WebUI task logs: keep only records attributed to the current thread."""
    messages = []
    root_thread_id = threading.get_ident()
    handler_id = logger.add(
        lambda message: messages.append(message.record["message"]),
        level="DEBUG",
        filter=lambda record: (
            logging_utils.log_scope_thread_id(record["thread"].id) == root_thread_id
        ),
    )
    try:
        yield messages
    finally:
        logger.remove(handler_id)


class _FakeVideoDownloadResponse:
    def __init__(self, content: bytes):
        self.content_bytes = content

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self.content_bytes


class TestMaterialTlsVerification(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.original_proxy_config = dict(config.proxy)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        config.proxy.clear()
        config.proxy.update(self.original_proxy_config)

    def test_search_pexels_uses_tls_verification_by_default(self):
        """
        The default path must enable TLS verification, so material API keys and returned material URLs
        can't be intercepted or tampered with by a man-in-the-middle on public networks or untrusted proxies.
        """
        config.app["pexels_api_keys"] = ["pexels-key"]
        config.app.pop("tls_verify", None)
        config.proxy.clear()

        fake_response = SimpleNamespace(
            json=lambda: {
                "videos": [
                    {
                        "id": 321,
                        "url": "https://www.pexels.com/video/example-321/?token=drop",
                        "duration": 8,
                        "user": {
                            "id": 654,
                            "name": "Pexels Creator",
                            "url": "https://www.pexels.com/@creator/?key=drop",
                        },
                        "video_files": [
                            {
                                "id": 987,
                                "width": 1080,
                                "height": 1920,
                                "link": "https://example.com/video.mp4",
                            }
                        ],
                    }
                ]
            }
        )

        with patch("app.services.material.requests.get", return_value=fake_response) as get:
            results = material.search_videos_pexels("cat", minimum_duration=1)

        self.assertEqual(len(results), 1)
        self.assertTrue(get.call_args.kwargs["verify"])
        self.assertEqual(results[0].source_info["asset_id"], "321")
        self.assertEqual(
            results[0].source_info["source_page"],
            "https://www.pexels.com/video/example-321/",
        )
        self.assertEqual(
            results[0].source_info["creator"]["profile_page"],
            "https://www.pexels.com/@creator/",
        )
        self.assertEqual(results[0].source_info["rendition"]["id"], "987")

    def test_search_pexels_skips_malformed_entries_without_losing_good_videos(self):
        config.app["pexels_api_keys"] = ["pexels-key"]
        fake_response = SimpleNamespace(
            json=lambda: {
                "videos": [
                    {"id": 1, "duration": "unknown", "video_files": []},
                    {
                        "id": 10,
                        "duration": 8,
                        "video_files": [
                            {
                                "width": float("inf"),
                                "height": 1920,
                                "link": "https://example.com/overflow.mp4",
                            }
                        ],
                    },
                    {
                        "id": 2,
                        "duration": 8,
                        "video_files": [
                            {"width": None, "height": 1920, "link": "bad"},
                            {
                                "id": 22,
                                "width": 1080,
                                "height": 1920,
                                "link": "https://example.com/first.mp4",
                            },
                        ],
                    },
                    {
                        "id": 3,
                        "duration": 8,
                        "video_files": [
                            {
                                "id": 33,
                                "width": 1080,
                                "height": 1920,
                                "link": "https://example.com/second.mp4",
                            }
                        ],
                    },
                ]
            }
        )

        with patch("app.services.material.requests.get", return_value=fake_response):
            results = material.search_videos_pexels("cat", minimum_duration=1)

        self.assertEqual(
            [item.url for item in results],
            ["https://example.com/first.mp4", "https://example.com/second.mp4"],
        )

    def test_search_pixabay_skips_malformed_hit_without_losing_good_video(self):
        config.app["pixabay_api_keys"] = ["pixabay-key"]
        fake_response = SimpleNamespace(
            status_code=200,
            headers={"content-type": "application/json"},
            text="",
            json=lambda: {
                "hits": [
                    {"duration": "unknown", "videos": {}},
                    {
                        "id": 10,
                        "duration": 8,
                        "videos": {
                            "large": {
                                "width": float("inf"),
                                "height": 1920,
                                "url": "https://example.com/overflow.mp4",
                            }
                        },
                    },
                    {
                        "id": 2,
                        "duration": 8,
                        "videos": {
                            "large": {
                                "width": 1080,
                                "height": 1920,
                                "url": "https://example.com/pixabay-good.mp4",
                            }
                        },
                    },
                ]
            },
        )

        with patch("app.services.material.requests.get", return_value=fake_response):
            results = material.search_videos_pixabay("cat", minimum_duration=1)

        self.assertEqual(
            [item.url for item in results],
            ["https://example.com/pixabay-good.mp4"],
        )

    def test_search_coverr_skips_malformed_hit_without_losing_good_video(self):
        config.app["coverr_api_keys"] = ["coverr-key"]
        fake_response = SimpleNamespace(
            json=lambda: {
                "hits": [
                    {"id": "bad", "duration": 8, "urls": ["unexpected"]},
                    {
                        "id": "overflow",
                        "duration": 8,
                        "max_width": float("inf"),
                        "max_height": 1920,
                        "urls": {
                            "mp4_download": "https://example.com/overflow.mp4"
                        },
                    },
                    {
                        "id": "good",
                        "duration": 8,
                        "max_width": 1080,
                        "max_height": 1920,
                        "urls": {
                            "mp4_download": "https://example.com/coverr-good.mp4"
                        },
                    },
                ]
            }
        )

        with patch("app.services.material.requests.get", return_value=fake_response):
            results = material.search_videos_coverr("cat", minimum_duration=1)

        self.assertEqual(
            [item.url for item in results],
            ["https://example.com/coverr-good.mp4"],
        )

    def test_search_pixabay_allows_explicit_tls_disable_for_proxy(self):
        """
        A few corporate proxies use self-signed certificates. That scenario must disable TLS verification via explicit config,
        rather than having the code hardcode it off by default.
        """
        config.app["pixabay_api_keys"] = ["pixabay-key"]
        config.app["tls_verify"] = False
        config.proxy.clear()

        fake_response = SimpleNamespace(
            status_code=200,
            headers={"content-type": "application/json"},
            text="",
            json=lambda: {
                "hits": [
                    {
                        "duration": 8,
                        "videos": {
                            "large": {
                                "width": 1920,
                                "height": 1080,
                                "url": "https://example.com/video.mp4",
                            }
                        },
                    }
                ]
            }
        )

        with patch("app.services.material.requests.get", return_value=fake_response) as get:
            results = material.search_videos_pixabay(
                "cat",
                minimum_duration=1,
                video_aspect=material.VideoAspect.landscape,
            )

        self.assertEqual(len(results), 1)
        self.assertFalse(get.call_args.kwargs["verify"])

    def test_remote_searches_only_return_requested_orientation(self):
        """
        All three material sources must only return materials in the target orientation, so portrait tasks don't mix in landscape materials
        that letterbox into obvious black bars. Pexels uses a remote parameter plus local validation;
        Pixabay and Coverr filter locally by response dimensions.
        """
        config.app["pexels_api_keys"] = ["pexels-key"]
        config.app["pixabay_api_keys"] = ["pixabay-key"]
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.proxy.clear()

        pexels_response = SimpleNamespace(
            json=lambda: {
                "videos": [
                    {
                        "id": 1,
                        "duration": 8,
                        "video_files": [
                            {
                                "id": 11,
                                "width": 1920,
                                "height": 1080,
                                "link": "https://example.com/landscape.mp4",
                            }
                        ],
                    },
                    {
                        "id": 2,
                        "duration": 8,
                        "video_files": [
                            {
                                "id": 22,
                                "width": 1080,
                                "height": 1920,
                                "link": "https://example.com/portrait.mp4",
                            }
                        ],
                    },
                ]
            }
        )
        pixabay_response = SimpleNamespace(
            status_code=200,
            headers={"content-type": "application/json"},
            text="",
            json=lambda: {
                "hits": [
                    {
                        "id": 1,
                        "duration": 8,
                        "videos": {
                            "large": {
                                "width": 1920,
                                "height": 1080,
                                "url": "https://example.com/landscape.mp4",
                            }
                        },
                    },
                    {
                        "id": 2,
                        "duration": 8,
                        "videos": {
                            "large": {
                                "width": 1080,
                                "height": 1920,
                                "url": "https://example.com/portrait.mp4",
                            }
                        },
                    },
                ]
            },
        )
        coverr_response = SimpleNamespace(
            json=lambda: {
                "hits": [
                    {
                        "id": "landscape",
                        "duration": 8,
                        "max_width": 1920,
                        "max_height": 1080,
                        "urls": {
                            "mp4_download": "https://example.com/landscape.mp4"
                        },
                    },
                    {
                        "id": "portrait",
                        "duration": 8,
                        "max_width": 1080,
                        "max_height": 1920,
                        "urls": {
                            "mp4_download": "https://example.com/portrait.mp4"
                        },
                    },
                    {
                        "id": "unknown",
                        "duration": 8,
                        "urls": {"mp4_download": "https://example.com/unknown.mp4"},
                    },
                ]
            }
        )

        with patch(
            "app.services.material.requests.get",
            return_value=pexels_response,
        ) as get:
            pexels_results = material.search_videos_pexels(
                "city",
                minimum_duration=1,
                video_aspect=material.VideoAspect.portrait,
            )
            pexels_url = get.call_args.args[0]
        with patch(
            "app.services.material.requests.get",
            return_value=pixabay_response,
        ):
            pixabay_results = material.search_videos_pixabay(
                "city",
                minimum_duration=1,
                video_aspect=material.VideoAspect.portrait,
            )
        with patch(
            "app.services.material.requests.get",
            return_value=coverr_response,
        ) as get:
            coverr_results = material.search_videos_coverr(
                "city",
                minimum_duration=1,
                video_aspect=material.VideoAspect.portrait,
            )
            coverr_url = get.call_args.args[0]

        self.assertIn("/v1/videos/search?", pexels_url)
        self.assertIn("orientation=portrait", pexels_url)
        self.assertIn("page_size=20", coverr_url)
        self.assertIn("filter=is_vertical%3Atrue", coverr_url)
        for results in (pexels_results, pixabay_results, coverr_results):
            self.assertEqual(
                [item.url for item in results],
                ["https://example.com/portrait.mp4"],
            )

    def test_video_aspect_matching_rejects_unknown_dimensions(self):
        """Materials whose orientation can't be confirmed must not enter the strict landscape/portrait candidate list."""
        self.assertTrue(
            material._matches_video_aspect(
                1080,
                1920,
                material.VideoAspect.portrait,
            )
        )
        self.assertFalse(
            material._matches_video_aspect(
                1920,
                1080,
                material.VideoAspect.portrait,
            )
        )
        self.assertTrue(
            material._matches_video_aspect(
                None,
                None,
                material.VideoAspect.portrait,
                is_vertical=True,
            )
        )
        self.assertFalse(
            material._matches_video_aspect(
                None,
                None,
                material.VideoAspect.portrait,
            )
        )
        self.assertTrue(
            material._matches_video_aspect(
                1080,
                1080,
                material.VideoAspect.square,
            )
        )
        self.assertFalse(
            material._matches_video_aspect(
                1080,
                1920,
                material.VideoAspect.square,
            )
        )
        self.assertFalse(
            material._matches_video_aspect(
                float("inf"), 1920, material.VideoAspect.portrait
            )
        )

    def test_coverr_passes_orientation_filter_to_remote_search(self):
        """Coverr landscape/portrait searches should filter on the server, while square materials keep using local dimension checks."""
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.proxy.clear()
        fake_response = SimpleNamespace(json=lambda: {"hits": []})
        cases = (
            (material.VideoAspect.portrait, "filter=is_vertical%3Atrue"),
            (material.VideoAspect.landscape, "filter=is_vertical%3Afalse"),
            (material.VideoAspect.square, None),
        )

        for aspect, expected_filter in cases:
            with self.subTest(aspect=aspect), patch(
                "app.services.material.requests.get",
                return_value=fake_response,
            ) as get:
                material.search_videos_coverr(
                    "city",
                    minimum_duration=1,
                    video_aspect=aspect,
                )
                request_url = get.call_args.args[0]

            self.assertIn("page_size=20", request_url)
            if expected_filter:
                self.assertIn(expected_filter, request_url)
            else:
                self.assertNotIn("filter=", request_url)

    def test_square_search_preserves_crop_compatible_materials(self):
        """
        Pixabay and Coverr rarely provide native square videos. Square output must keep accepting croppable
        landscape materials, otherwise choosing these two sources would yield an empty list at the search stage.
        """
        config.app["pixabay_api_keys"] = ["pixabay-key"]
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.proxy.clear()
        pixabay_response = SimpleNamespace(
            status_code=200,
            headers={"content-type": "application/json"},
            text="",
            json=lambda: {
                "hits": [
                    {
                        "id": 1,
                        "duration": 8,
                        "videos": {
                            "large": {
                                "width": 1920,
                                "height": 1080,
                                "url": "https://example.com/pixabay-landscape.mp4",
                            }
                        },
                    }
                ]
            },
        )
        coverr_response = SimpleNamespace(
            json=lambda: {
                "hits": [
                    {
                        "id": "landscape",
                        "duration": 8,
                        "max_width": 1920,
                        "max_height": 1080,
                        "urls": {
                            "mp4_download": "https://example.com/coverr-landscape.mp4"
                        },
                    }
                ]
            }
        )

        with patch(
            "app.services.material.requests.get",
            return_value=pixabay_response,
        ):
            pixabay_results = material.search_videos_pixabay(
                "city",
                minimum_duration=1,
                video_aspect=material.VideoAspect.square,
            )
        with patch(
            "app.services.material.requests.get",
            return_value=coverr_response,
        ):
            coverr_results = material.search_videos_coverr(
                "city",
                minimum_duration=1,
                video_aspect=material.VideoAspect.square,
            )

        self.assertEqual(
            [item.url for item in pixabay_results],
            ["https://example.com/pixabay-landscape.mp4"],
        )
        self.assertEqual(
            [item.url for item in coverr_results],
            ["https://example.com/coverr-landscape.mp4"],
        )

    def test_search_pixabay_does_not_log_api_key(self):
        config.app["pixabay_api_keys"] = ["pixabay-secret-key"]
        config.proxy.clear()

        fake_response = SimpleNamespace(
            status_code=200,
            headers={"content-type": "application/json"},
            text="",
            json=lambda: {"hits": []},
        )

        with patch(
            "app.services.material.requests.get", return_value=fake_response
        ), patch("app.services.material.logger.info") as log:
            material.search_videos_pixabay("cat", minimum_duration=1)

        logged_messages = " ".join(str(call.args[0]) for call in log.call_args_list)
        self.assertNotIn("pixabay-secret-key", logged_messages)

    def test_search_pixabay_reports_cloudflare_challenge(self):
        """
        A Cloudflare Challenge returns HTML, not Pixabay API JSON.
        The reason for the server-side block should be stated directly, so users don't just see a context-free JSON parse error.
        """
        config.app["pixabay_api_keys"] = ["pixabay-secret-key"]
        config.proxy.clear()

        fake_response = SimpleNamespace(
            status_code=429,
            headers={
                "content-type": "text/html; charset=UTF-8",
                "cf-mitigated": "challenge",
                "cf-ray": "test-ray",
            },
            text="<html><title>Just a moment...</title></html>",
        )

        with patch(
            "app.services.material.requests.get", return_value=fake_response
        ), patch("app.services.material.logger.error") as log:
            results = material.search_videos_pixabay("nature", minimum_duration=1)

        logged_messages = " ".join(str(call.args[0]) for call in log.call_args_list)
        self.assertEqual(results, [])
        self.assertIn("Cloudflare challenge", logged_messages)
        self.assertIn("cf_ray=test-ray", logged_messages)
        self.assertNotIn("pixabay-secret-key", logged_messages)
        self.assertNotIn("Just a moment", logged_messages)

    def test_search_pixabay_reports_api_rate_limit(self):
        """
        Pixabay's own 429 rate limiting and a Cloudflare HTML Challenge are different problems.
        Keeping Retry-After helps users judge when to retry, while the response body isn't logged.
        """
        config.app["pixabay_api_keys"] = ["pixabay-key"]
        config.proxy.clear()

        fake_response = SimpleNamespace(
            status_code=429,
            headers={
                "content-type": "text/plain; charset=UTF-8",
                "retry-after": "60",
            },
            text="API rate limit exceeded",
        )

        with patch(
            "app.services.material.requests.get", return_value=fake_response
        ), patch("app.services.material.logger.error") as log:
            results = material.search_videos_pixabay("nature", minimum_duration=1)

        logged_messages = " ".join(str(call.args[0]) for call in log.call_args_list)
        self.assertEqual(results, [])
        self.assertIn("API rate limit exceeded", logged_messages)
        self.assertIn("retry_after=60", logged_messages)

    def test_search_pixabay_reports_non_json_response(self):
        """
        Even with status 200, an upstream proxy may return a login page or other non-JSON content.
        That scenario should log the response type rather than exposing the underlying JSONDecodeError.
        """
        config.app["pixabay_api_keys"] = ["pixabay-key"]
        config.proxy.clear()

        def raise_invalid_json():
            raise ValueError("Expecting value: line 1 column 1")

        fake_response = SimpleNamespace(
            status_code=200,
            headers={"content-type": "text/plain"},
            text="unexpected response",
            json=raise_invalid_json,
        )

        with patch(
            "app.services.material.requests.get", return_value=fake_response
        ), patch("app.services.material.logger.error") as log:
            results = material.search_videos_pixabay("nature", minimum_duration=1)

        logged_messages = " ".join(str(call.args[0]) for call in log.call_args_list)
        self.assertEqual(results, [])
        self.assertIn("unexpected non-JSON response", logged_messages)
        self.assertNotIn("Expecting value", logged_messages)

    def test_search_pixabay_redacts_api_key_from_network_error(self):
        """
        requests connection exceptions may echo the full request URL. Exception details should still be kept for troubleshooting,
        but the Pixabay API Key in the URL query parameters must be redacted before it's logged.
        """
        api_key = "pixabay-secret-key"
        config.app["pixabay_api_keys"] = [api_key]
        config.proxy.clear()
        error = requests.ConnectionError(
            "request failed for "
            f"https://pixabay.com/api/videos/?q=nature&key={api_key}"
        )

        with patch(
            "app.services.material.requests.get", side_effect=error
        ), patch("app.services.material.logger.error") as log:
            results = material.search_videos_pixabay("nature", minimum_duration=1)

        logged_messages = " ".join(str(call.args[0]) for call in log.call_args_list)
        self.assertEqual(results, [])
        self.assertIn("ConnectionError", logged_messages)
        self.assertIn("key=***", logged_messages)
        self.assertNotIn(api_key, logged_messages)

    def test_search_pixabay_redacts_proxy_credentials_from_network_error(self):
        """
        Proxy connection exceptions may echo the full proxy URL including auth info. Logs should keep the exception type,
        but must not persist the proxy username and password to log files.
        """
        proxy_url = "http://proxy-user:proxy-password@proxy.example.com:8080"
        config.app["pixabay_api_keys"] = ["pixabay-key"]
        config.proxy.clear()
        config.proxy["http"] = proxy_url
        error = requests.exceptions.ProxyError(
            f"failed to connect to proxy {proxy_url}"
        )

        with patch(
            "app.services.material.requests.get", side_effect=error
        ), patch("app.services.material.logger.error") as log:
            results = material.search_videos_pixabay("nature", minimum_duration=1)

        logged_messages = " ".join(str(call.args[0]) for call in log.call_args_list)
        self.assertEqual(results, [])
        self.assertIn("ProxyError", logged_messages)
        self.assertNotIn("proxy-user", logged_messages)
        self.assertNotIn("proxy-password", logged_messages)

    def test_save_video_uses_tls_verification_by_default(self):
        config.app.pop("tls_verify", None)
        config.proxy.clear()

        fake_response = _FakeVideoDownloadResponse(b"fake-video")

        class FakeVideoFileClip:
            duration = 1
            fps = 24

            def __init__(self, path):
                self.path = path

            def close(self):
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "app.services.material.requests.get", return_value=fake_response
            ) as get, patch("app.services.material.VideoFileClip", FakeVideoFileClip), patch("app.services.material.material_upload._validate_video"):
                video_path = material.save_video(
                    "https://example.com/video.mp4?token=abc", save_dir=temp_dir
                )

            self.assertTrue(os.path.exists(video_path))
            self.assertTrue(get.call_args.kwargs["verify"])

    def test_save_video_streams_chunks_without_materializing_response_content(self):
        class StreamingResponse:
            def __init__(self):
                self.closed = False
                self.chunk_size = None

            @property
            def content(self):
                raise AssertionError("the complete video must not be buffered in memory")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.closed = True

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size):
                self.chunk_size = chunk_size
                yield b"first"
                yield b"second"

        class FakeVideoFileClip:
            duration = 1
            fps = 24

            def __init__(self, path):
                pass

            def close(self):
                pass

        response = StreamingResponse()
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "app.services.material.requests.get", return_value=response
            ) as get, patch("app.services.material.VideoFileClip", FakeVideoFileClip), patch("app.services.material.material_upload._validate_video"):
                video_path = material.save_video(
                    "https://example.com/large.mp4", save_dir=temp_dir
                )

            self.assertEqual(Path(video_path).read_bytes(), b"firstsecond")
            self.assertTrue(response.closed)
            self.assertLessEqual(response.chunk_size, 1024 * 1024)
            self.assertTrue(get.call_args.kwargs["stream"])

    def _save_video_with_chunks(self, chunks, headers=None):
        """Run save_video once with a fake response and return the info logs written meanwhile."""

        class ChunkedResponse(_FakeVideoDownloadResponse):
            def __init__(self):
                super().__init__(b"")
                self.headers = headers or {}

            def iter_content(self, chunk_size):
                yield from chunks

        class FakeVideoFileClip:
            duration = 1
            fps = 24

            def __init__(self, path):
                pass

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "app.services.material.requests.get",
                    return_value=ChunkedResponse(),
                ),
                patch("app.services.material.VideoFileClip", FakeVideoFileClip), patch("app.services.material.material_upload._validate_video"),
                patch.object(material.logger, "info") as info,
            ):
                video_path = material.save_video(
                    "https://example.com/large.mp4?key=secret", save_dir=temp_dir
                )
            self.assertTrue(video_path)
        return [str(call.args[0]) for call in info.call_args_list]

    def test_save_video_reports_progress_during_a_slow_download(self):
        """
        On slow networks a single 4K material can take minutes to download with no logs at all, and the task looks
        stuck. Past the heartbeat interval, the downloaded size, total size and speed must be logged; only the cache
        filename may appear in the log, since the download URL may carry keys and must not be logged.
        """
        megabyte = b"x" * (1024 * 1024)
        with patch.object(material, "_DOWNLOAD_HEARTBEAT_SECONDS", 0):
            messages = self._save_video_with_chunks(
                [megabyte, megabyte, megabyte],
                headers={"Content-Length": str(3 * 1024 * 1024)},
            )

        heartbeats = [m for m in messages if m.startswith("downloading video")]
        self.assertEqual(len(heartbeats), 3)
        self.assertRegex(
            heartbeats[0],
            r"^downloading video vid-[0-9a-f]{32}\.mp4: "
            r"1\.0 of 3\.0 MB \(33%\), \d+\.\d{2} MB/s$",
        )
        self.assertIn("3.0 of 3.0 MB (100%)", heartbeats[2])
        self.assertFalse([m for m in messages if "secret" in m or "example.com" in m])

    def test_save_video_reports_progress_without_a_declared_size(self):
        """Without Content-Length the downloaded size should still be reported, just without a percentage."""
        megabyte = b"x" * (1024 * 1024)
        with patch.object(material, "_DOWNLOAD_HEARTBEAT_SECONDS", 0):
            messages = self._save_video_with_chunks([megabyte, megabyte])

        heartbeats = [m for m in messages if m.startswith("downloading video")]
        self.assertEqual(len(heartbeats), 2)
        self.assertRegex(heartbeats[1], r": 2\.0 MB, \d+\.\d{2} MB/s$")

    def test_save_video_stays_quiet_for_fast_downloads(self):
        """Downloads that finish within the heartbeat interval shouldn't produce extra logs, so small files don't flood."""
        messages = self._save_video_with_chunks([b"small", b"video"])

        self.assertEqual([m for m in messages if m.startswith("downloading video")], [])

    def test_save_video_distinguishes_assets_in_download_query(self):
        """Different paid assets can share a /download path and differ only by query."""
        first_url = "https://cdn.example.com/download?file_id=first"
        second_url = "https://cdn.example.com/download?file_id=second"

        class FakeVideoFileClip:
            duration = 1
            fps = 24

            def __init__(self, path):
                pass

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "app.services.material.requests.get",
                side_effect=[
                    _FakeVideoDownloadResponse(b"first generated scene"),
                    _FakeVideoDownloadResponse(b"second generated scene"),
                ],
            ) as get, patch("app.services.material.VideoFileClip", FakeVideoFileClip), patch("app.services.material.material_upload._validate_video"):
                first_path = material.save_video(first_url, save_dir=temp_dir)
                second_path = material.save_video(second_url, save_dir=temp_dir)
                cached_path = material.save_video(first_url, save_dir=temp_dir)

            self.assertNotEqual(first_path, second_path)
            self.assertEqual(Path(first_path).read_bytes(), b"first generated scene")
            self.assertEqual(Path(second_path).read_bytes(), b"second generated scene")
            self.assertEqual(cached_path, first_path)
            self.assertEqual(get.call_count, 2)

    def test_save_video_cleans_partial_stream_when_download_fails(self):
        class FailingResponse(_FakeVideoDownloadResponse):
            def __init__(self):
                super().__init__(b"partial")
                self.closed = False

            def __exit__(self, *args):
                self.closed = True

            def iter_content(self, chunk_size):
                yield b"partial"
                raise requests.ConnectionError("connection dropped")

        response = FailingResponse()
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("app.services.material.requests.get", return_value=response):
                with self.assertRaises(requests.ConnectionError):
                    material.save_video(
                        "https://example.com/interrupted.mp4", save_dir=temp_dir
                    )

            self.assertTrue(response.closed)
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_save_video_rejects_declared_oversized_download_before_streaming(self):
        class OversizedResponse(_FakeVideoDownloadResponse):
            headers = {"Content-Length": "9"}

            def iter_content(self, chunk_size):
                raise AssertionError("oversized body should not be read")

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("app.services.material.MAX_VIDEO_DOWNLOAD_BYTES", 8, create=True),
                patch(
                    "app.services.material.requests.get",
                    return_value=OversizedResponse(b""),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "download exceeds"):
                    material.save_video("https://example.com/large.mp4", temp_dir)

            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_save_video_stops_undeclared_oversized_stream_and_cleans_temp(self):
        class StreamingResponse(_FakeVideoDownloadResponse):
            def iter_content(self, chunk_size):
                yield b"first"
                yield b"second"

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("app.services.material.MAX_VIDEO_DOWNLOAD_BYTES", 8, create=True),
                patch(
                    "app.services.material.requests.get",
                    return_value=StreamingResponse(b""),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "download exceeds"):
                    material.save_video("https://example.com/stream.mp4", temp_dir)

            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_invalid_download_is_not_reused_as_cached_video(self):
        url = "https://example.com/broken-then-valid.mp4"
        cached_name = f"vid-{material.utils.md5(url)}.mp4"

        class FakeVideoFileClip:
            fps = 24

            def __init__(self, path):
                self.duration = 0 if Path(path).read_bytes() == b"broken" else 1

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "app.services.material.requests.get",
                side_effect=[
                    _FakeVideoDownloadResponse(b"broken"),
                    _FakeVideoDownloadResponse(b"valid"),
                ],
            ) as get, patch("app.services.material.VideoFileClip", FakeVideoFileClip), patch("app.services.material.material_upload._validate_video"):
                self.assertEqual(material.save_video(url, save_dir=temp_dir), "")
                self.assertFalse((Path(temp_dir) / cached_name).exists())
                self.assertEqual(
                    Path(material.save_video(url, save_dir=temp_dir)),
                    Path(temp_dir) / cached_name,
                )

            self.assertEqual(get.call_count, 2)
            self.assertEqual((Path(temp_dir) / cached_name).read_bytes(), b"valid")

    def test_corrupt_existing_cache_is_redownloaded_and_replaced(self):
        """A stale nonempty cache entry must repair itself on the next request."""
        url = "https://example.com/corrupt-cache.mp4"
        cached_name = f"vid-{material.utils.md5(url)}.mp4"

        class FakeVideoFileClip:
            fps = 24

            def __init__(self, path):
                self.duration = 0 if Path(path).read_bytes() == b"corrupt" else 1

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            cached_path = Path(temp_dir) / cached_name
            cached_path.write_bytes(b"corrupt")
            with (
                patch(
                    "app.services.material.requests.get",
                    return_value=_FakeVideoDownloadResponse(b"valid"),
                ) as get,
                patch("app.services.material.VideoFileClip", FakeVideoFileClip),
                patch("app.services.material.material_upload._validate_video"),
            ):
                result = material.save_video(url, save_dir=temp_dir)

            self.assertEqual(Path(result), cached_path)
            self.assertEqual(cached_path.read_bytes(), b"valid")
            get.assert_called_once()

    def test_validation_service_failure_preserves_existing_cache(self):
        """Validator outages must not turn a healthy cached asset into data loss."""
        url = "https://example.com/signed-video.mp4?expires=soon"
        cached_name = f"vid-{material.utils.md5(url)}.mp4"

        class FakeVideoFileClip:
            duration = 1
            fps = 24

            def __init__(self, path):
                pass

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            cached_path = Path(temp_dir) / cached_name
            cached_path.write_bytes(b"healthy cached video")
            with (
                patch("app.services.material.requests.get") as get,
                patch("app.services.material.VideoFileClip", FakeVideoFileClip),
                patch(
                    "app.services.material.material_upload._validate_video",
                    side_effect=material.material_upload.MaterialServiceError(
                        "FFmpeg material validation timed out"
                    ),
                ),
            ):
                result = material.save_video(url, save_dir=temp_dir)

            self.assertEqual(Path(result), cached_path)
            self.assertEqual(cached_path.read_bytes(), b"healthy cached video")
            get.assert_not_called()

    def test_metadata_probe_failure_preserves_existing_cache(self):
        """MoviePy failing to start FFmpeg is not evidence of corrupt media."""
        url = "https://example.com/signed-video.mp4?expires=soon"
        cached_name = f"vid-{material.utils.md5(url)}.mp4"

        with tempfile.TemporaryDirectory() as temp_dir:
            cached_path = Path(temp_dir) / cached_name
            cached_path.write_bytes(b"healthy cached video")
            with (
                patch("app.services.material.requests.get") as get,
                patch(
                    "app.services.material.VideoFileClip",
                    side_effect=FileNotFoundError("MoviePy FFmpeg is unavailable"),
                ),
                patch(
                    "app.services.material.material_upload._validate_video"
                ) as validate,
            ):
                result = material.save_video(url, save_dir=temp_dir)

            self.assertEqual(Path(result), cached_path)
            self.assertEqual(cached_path.read_bytes(), b"healthy cached video")
            # save_video joins with "/", Path uses "\\" on Windows: compare as paths.
            validate.assert_called_once()
            self.assertEqual(Path(validate.call_args.args[0]), cached_path)
            get.assert_not_called()

    def test_nonfinite_video_metadata_is_not_published(self):
        class FakeVideoFileClip:
            duration = float("nan")
            fps = 24

            def __init__(self, path):
                pass

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "app.services.material.requests.get",
                return_value=_FakeVideoDownloadResponse(b"bad metadata"),
            ), patch("app.services.material.VideoFileClip", FakeVideoFileClip), patch("app.services.material.material_upload._validate_video"):
                self.assertEqual(
                    material.save_video("https://example.com/nan.mp4", save_dir=temp_dir),
                    "",
                )
            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_download_videos_accepts_plain_string_concat_mode(self):
        """
        download_videos may be passed a string mode directly by the service layer or tests instead of
        a VideoConcatMode enum. Empty search terms avoid real network requests here, only verifying that
        the string "random" no longer raises AttributeError from accessing `.value`.
        """
        result = material.download_videos(
            task_id="string-concat-mode",
            search_terms=[],
            video_concat_mode="random",
        )

        self.assertEqual(result, [])

    def test_material_source_record_uses_public_whitelist(self):
        """
        The task manifest should only contain traceable public fields, never signature parameters, download URLs,
        extra fields passed by the caller or local absolute paths.
        """
        item = material.MaterialInfo(
            provider="pixabay",
            url="https://cdn.example.com/video.mp4?token=secret",
            duration=12,
            source_info={
                "provider": "pixabay",
                "search_term": "city",
                "asset_id": 123,
                "source_page": "https://pixabay.com/videos/city-123/?key=secret",
                "creator": {
                    "id": 456,
                    "name": "Creator",
                    "profile_page": "https://pixabay.com/users/creator/?token=secret",
                    "email": "private@example.com",
                },
                "rendition": {
                    "id": "large",
                    "width": 1920,
                    "height": 1080,
                    "download_url": "https://cdn.example.com/private",
                },
                "api_key": "must-not-persist",
            },
        )

        record = material._material_source_record(
            item,
            "/Users/example/private/task/vid-123.mp4",
        )
        serialized = str(record)

        self.assertEqual(record["local_file"], "vid-123.mp4")
        self.assertEqual(
            record["source_page"],
            "https://pixabay.com/videos/city-123/",
        )
        self.assertEqual(
            record["creator"]["profile_page"],
            "https://pixabay.com/users/creator/",
        )
        self.assertEqual(
            record["rendition"],
            {"id": "large", "width": 1920, "height": 1080},
        )
        self.assertNotIn("secret", serialized)
        self.assertNotIn("/Users/example", serialized)
        self.assertNotIn("private@example.com", serialized)

    def test_download_videos_can_round_robin_terms_in_script_order(self):
        """
        With script-order material matching enabled, the first keyword's multiple candidates must not fill
        the audio duration first. Two keywords with several candidates each are simulated here, verifying the download order is
        term1 #1, term2 #1, term1 #2, following the script's narrative order.
        """
        search_results = {
            "opening city": [
                material.MaterialInfo(
                    provider="pexels",
                    url="https://v.example/a1.mp4",
                    duration=3,
                    source_info={
                        "provider": "pexels",
                        "search_term": "opening city",
                        "asset_id": "a1",
                    },
                ),
                material.MaterialInfo(
                    provider="pexels",
                    url="https://v.example/a2.mp4",
                    duration=3,
                    source_info={
                        "provider": "pexels",
                        "search_term": "opening city",
                        "asset_id": "a2",
                    },
                ),
            ],
            "middle office": [
                material.MaterialInfo(
                    provider="pexels",
                    url="https://v.example/b1.mp4",
                    duration=3,
                    source_info={
                        "provider": "pexels",
                        "search_term": "middle office",
                        "asset_id": "b1",
                    },
                ),
                material.MaterialInfo(
                    provider="pexels",
                    url="https://v.example/b2.mp4",
                    duration=3,
                    source_info={
                        "provider": "pexels",
                        "search_term": "middle office",
                        "asset_id": "b2",
                    },
                ),
            ],
        }
        downloaded_urls = []

        def fake_search(search_term, minimum_duration, video_aspect):
            return search_results[search_term]

        def fake_save_video(video_url, save_dir=""):
            downloaded_urls.append(video_url)
            return f"/tmp/{video_url.rsplit('/', 1)[-1]}"

        with (
            patch.dict(config.app, {"material_directory": ""}),
            patch.object(material, "search_videos_pexels", side_effect=fake_search),
            patch.object(material, "save_video", side_effect=fake_save_video),
            patch.object(
                material.material_cache,
                "load_material_search_cache",
                return_value=None,
            ),
            patch.object(material.material_cache, "save_material_search_cache"),
            patch.object(
                material.task_artifacts,
                "patch_script_data",
                return_value=True,
            ) as patch_script,
        ):
            result = material.download_videos(
                task_id="ordered-materials",
                search_terms=["opening city", "middle office"],
                source="pexels",
                audio_duration=7,
                max_clip_duration=3,
                match_script_order=True,
            )

        self.assertCountEqual(
            downloaded_urls,
            [
                "https://v.example/a1.mp4",
                "https://v.example/b1.mp4",
                "https://v.example/a2.mp4",
            ],
        )
        self.assertEqual(result, ["/tmp/a1.mp4", "/tmp/b1.mp4", "/tmp/a2.mp4"])
        recorded_sources = patch_script.call_args.kwargs["material_sources"]
        self.assertEqual(
            [source["asset_id"] for source in recorded_sources],
            ["a1", "b1", "a2"],
        )
        self.assertEqual(
            [source["local_file"] for source in recorded_sources],
            ["a1.mp4", "b1.mp4", "a2.mp4"],
        )

    def test_script_order_keeps_the_slot_of_a_repeated_term(self):
        """
        When the script returns to a topic (forest, city, forest, mountain), the
        repeated term gets the same search results. It must keep its own slot and
        use the next unused candidate instead of being dropped, which would move
        every later topic up one slot.
        """

        def fake_search(search_term, minimum_duration, video_aspect):
            return [
                material.MaterialInfo(
                    provider="pexels",
                    url=f"https://v.example/{search_term}-{n}.mp4",
                    duration=10,
                    source_info={
                        "provider": "pexels",
                        "search_term": search_term,
                        "asset_id": f"{search_term}-{n}",
                    },
                )
                for n in (1, 2, 3)
            ]

        def fake_save_video(video_url, save_dir=""):
            return f"/tmp/{video_url.rsplit('/', 1)[-1]}"

        with (
            patch.dict(config.app, {"material_directory": ""}),
            patch.object(material, "search_videos_pexels", side_effect=fake_search),
            patch.object(material, "save_video", side_effect=fake_save_video),
            patch.object(
                material.material_cache,
                "load_material_search_cache",
                return_value=None,
            ),
            patch.object(material.material_cache, "save_material_search_cache"),
            patch.object(
                material.task_artifacts,
                "patch_script_data",
                return_value=True,
            ),
        ):
            result = material.download_videos(
                task_id="ordered-repeated-term",
                search_terms=["forest", "city", "forest", "mountain"],
                source="pexels",
                audio_duration=20,
                max_clip_duration=5,
                match_script_order=True,
            )

        self.assertEqual(
            result,
            [
                "/tmp/forest-1.mp4",
                "/tmp/city-1.mp4",
                "/tmp/forest-2.mp4",
                "/tmp/mountain-1.mp4",
                "/tmp/forest-3.mp4",
            ],
        )

    def test_script_order_uses_next_candidate_after_failed_download(self):
        """
        Regression: in script-order mode, when the first candidate fails to download, the next candidate of the same keyword
        must be tried rather than returning an empty result. Download exceptions must not interrupt the whole flow.
        """
        search_results = {
            "city": [
                material.MaterialInfo(
                    provider="pexels",
                    url="https://v.example/bad.mp4",
                    duration=5,
                    source_info={"provider": "pexels", "asset_id": "bad"},
                ),
                material.MaterialInfo(
                    provider="pexels",
                    url="https://v.example/good.mp4",
                    duration=5,
                    source_info={"provider": "pexels", "asset_id": "good"},
                ),
            ],
        }
        attempted_urls = []

        def fake_search(search_term, minimum_duration, video_aspect):
            return search_results[search_term]

        def fake_save_video(video_url, save_dir=""):
            attempted_urls.append(video_url)
            if "bad" in video_url:
                raise RuntimeError("network down")
            return "/tmp/good.mp4"

        with (
            patch.dict(
                config.app,
                {"material_directory": "", "material_concurrency": 4},
            ),
            patch.object(material, "search_videos_pexels", side_effect=fake_search),
            patch.object(material, "save_video", side_effect=fake_save_video),
            patch.object(
                material.material_cache,
                "load_material_search_cache",
                return_value=None,
            ),
            patch.object(material.material_cache, "save_material_search_cache"),
            patch.object(
                material.task_artifacts,
                "patch_script_data",
                return_value=True,
            ),
        ):
            result = material.download_videos(
                task_id="failed-first-candidate",
                search_terms=["city"],
                source="pexels",
                audio_duration=8,
                max_clip_duration=5,
                match_script_order=True,
            )

        self.assertEqual(
            attempted_urls,
            ["https://v.example/bad.mp4", "https://v.example/good.mp4"],
        )
        self.assertEqual(result, ["/tmp/good.mp4"])

    def test_script_order_does_not_skip_unattempted_candidates(self):
        """
        Regression: in script-order mode, candidates not selected in this round must not advance the index.
        With three keywords of 1 candidate each, where the first round only selects the first two and both fail to download,
        the third candidate must be tried in the next round rather than being skipped by a round-wide shared index
        and returning an empty result.
        """
        search_results = {
            "t1": [
                material.MaterialInfo(
                    provider="pexels",
                    url="https://v.example/x.mp4",
                    duration=5,
                    source_info={"provider": "pexels", "asset_id": "x"},
                ),
            ],
            "t2": [
                material.MaterialInfo(
                    provider="pexels",
                    url="https://v.example/y.mp4",
                    duration=5,
                    source_info={"provider": "pexels", "asset_id": "y"},
                ),
            ],
            "t3": [
                material.MaterialInfo(
                    provider="pexels",
                    url="https://v.example/z.mp4",
                    duration=5,
                    source_info={"provider": "pexels", "asset_id": "z"},
                ),
            ],
        }
        attempted_urls = []

        def fake_search(search_term, minimum_duration, video_aspect):
            return search_results[search_term]

        def fake_save_video(video_url, save_dir=""):
            attempted_urls.append(video_url)
            if "z.mp4" not in video_url:
                raise RuntimeError("network down")
            return "/tmp/z.mp4"

        with (
            patch.dict(
                config.app,
                {"material_directory": "", "material_concurrency": 4},
            ),
            patch.object(material, "search_videos_pexels", side_effect=fake_search),
            patch.object(material, "save_video", side_effect=fake_save_video),
            patch.object(
                material.material_cache,
                "load_material_search_cache",
                return_value=None,
            ),
            patch.object(material.material_cache, "save_material_search_cache"),
            patch.object(
                material.task_artifacts,
                "patch_script_data",
                return_value=True,
            ),
        ):
            result = material.download_videos(
                task_id="unattempted-candidate",
                search_terms=["t1", "t2", "t3"],
                source="pexels",
                audio_duration=6,
                max_clip_duration=5,
                match_script_order=True,
            )

        # The first round selects x, y (10s total exceeds 6s of voice-over) and z isn't tried; after x and y both fail,
        # before the fix z was skipped by the round-wide shared index and the function returned an empty result;
        # after the fix z must be tried in the next round and download successfully.
        self.assertCountEqual(
            attempted_urls,
            [
                "https://v.example/x.mp4",
                "https://v.example/y.mp4",
                "https://v.example/z.mp4",
            ],
        )
        self.assertEqual(result, ["/tmp/z.mp4"])

    def test_default_path_single_material_failure_does_not_abort(self):
        """
        Regression: on the default path, even with concurrency set to 4, when a single-candidate batch downloads serially,
        download exceptions must also be caught and must not interrupt the whole generation flow.
        """
        item = material.MaterialInfo(
            provider="pexels",
            url="https://v.example/only.mp4",
            duration=5,
            source_info={"provider": "pexels", "asset_id": "only"},
        )

        with (
            patch.dict(
                config.app,
                {"material_directory": "", "material_concurrency": 4},
            ),
            patch.object(material, "search_videos_pexels", return_value=[item]),
            patch.object(
                material, "save_video", side_effect=RuntimeError("boom")
            ),
            patch.object(
                material.material_cache,
                "load_material_search_cache",
                return_value=None,
            ),
            patch.object(material.material_cache, "save_material_search_cache"),
            patch.object(
                material.task_artifacts,
                "patch_script_data",
                return_value=True,
            ),
        ):
            result = material.download_videos(
                task_id="single-failure",
                search_terms=["city"],
                source="pexels",
                video_concat_mode=material.VideoConcatMode.sequential,
                audio_duration=10,
                max_clip_duration=5,
            )

        self.assertEqual(result, [])

    def test_default_path_serial_fallback_keeps_selection_order(self):
        """
        With concurrency set to 1, the default path stays strictly serial: download in candidate order,
        stop once the duration is covered, and skip failed downloads to continue with the next candidate.
        """
        items = [
            material.MaterialInfo(
                provider="pexels",
                url=f"https://v.example/{name}.mp4",
                duration=6,
                source_info={"provider": "pexels", "asset_id": name},
            )
            for name in ("a", "b", "c")
        ]
        attempted_urls = []

        def fake_save_video(video_url, save_dir=""):
            attempted_urls.append(video_url)
            if "/b.mp4" in video_url:
                raise RuntimeError("network down")
            return f"/tmp/{video_url.rsplit('/', 1)[-1]}"

        with (
            patch.dict(
                config.app,
                {"material_directory": "", "material_concurrency": 1},
            ),
            patch.object(material, "search_videos_pexels", return_value=items),
            patch.object(material, "save_video", side_effect=fake_save_video),
            patch.object(
                material.material_cache,
                "load_material_search_cache",
                return_value=None,
            ),
            patch.object(material.material_cache, "save_material_search_cache"),
            patch.object(
                material.task_artifacts,
                "patch_script_data",
                return_value=True,
            ),
        ):
            result = material.download_videos(
                task_id="serial-fallback",
                search_terms=["city"],
                source="pexels",
                video_concat_mode=material.VideoConcatMode.sequential,
                audio_duration=10,
                max_clip_duration=6,
            )

        # Serial semantics: a succeeds (6s), b fails and is skipped, c succeeds (12s total covers 10s, so stop).
        self.assertEqual(
            attempted_urls,
            [
                "https://v.example/a.mp4",
                "https://v.example/b.mp4",
                "https://v.example/c.mp4",
            ],
        )
        self.assertEqual(result, ["/tmp/a.mp4", "/tmp/c.mp4"])

    def test_default_path_parallel_download_matches_serial_selection(self):
        """
        Parallel downloads on the default path keep the same selection semantics as serial: accumulate in order, stop once covered;
        failed candidates are made up with later candidates, and the final download set matches serial.
        """
        items = [
            material.MaterialInfo(
                provider="pexels",
                url=f"https://v.example/{name}.mp4",
                duration=6,
                source_info={"provider": "pexels", "asset_id": name},
            )
            for name in ("a", "b", "c", "d")
        ]

        def fake_save_video(video_url, save_dir=""):
            if "/b.mp4" in video_url:
                raise RuntimeError("network down")
            return f"/tmp/{video_url.rsplit('/', 1)[-1]}"

        with (
            patch.dict(
                config.app,
                {"material_directory": "", "material_concurrency": 4},
            ),
            patch.object(material, "search_videos_pexels", return_value=items),
            patch.object(material, "save_video", side_effect=fake_save_video),
            patch.object(
                material.material_cache,
                "load_material_search_cache",
                return_value=None,
            ),
            patch.object(material.material_cache, "save_material_search_cache"),
            patch.object(
                material.task_artifacts,
                "patch_script_data",
                return_value=True,
            ),
        ):
            result = material.download_videos(
                task_id="parallel-selection",
                search_terms=["city"],
                source="pexels",
                video_concat_mode=material.VideoConcatMode.sequential,
                audio_duration=10,
                max_clip_duration=6,
            )

        # Round 1 [a, b]: a succeeds (6s), b fails; round 2 [c] succeeds (12s total, covered, stop).
        # Same download set as the serial logic: {a, c}; d isn't downloaded unnecessarily.
        self.assertEqual(result, ["/tmp/a.mp4", "/tmp/c.mp4"])

    def _download_with_progress(self, *, concurrency, progress_callback, **kwargs):
        """
        Four 6-second candidates with 10 seconds of voice-over: in round 1 [a, b], b fails, and c makes up for it in round 2.
        Returns the download results, shared by the serial, parallel and script-order paths.
        """
        items = [
            material.MaterialInfo(
                provider="pexels",
                url=f"https://v.example/{name}.mp4",
                duration=6,
                source_info={"provider": "pexels", "asset_id": name},
            )
            for name in ("a", "b", "c", "d")
        ]

        def fake_save_video(video_url, save_dir=""):
            if "/b.mp4" in video_url:
                raise RuntimeError("network down")
            return f"/tmp/{video_url.rsplit('/', 1)[-1]}"

        with (
            patch.dict(
                config.app,
                {"material_directory": "", "material_concurrency": concurrency},
            ),
            patch.object(material, "search_videos_pexels", return_value=items),
            patch.object(material, "save_video", side_effect=fake_save_video),
            patch.object(
                material.material_cache,
                "load_material_search_cache",
                return_value=None,
            ),
            patch.object(material.material_cache, "save_material_search_cache"),
            patch.object(
                material.task_artifacts,
                "patch_script_data",
                return_value=True,
            ),
        ):
            return material.download_videos(
                task_id="download-progress",
                search_terms=["city"],
                source="pexels",
                video_concat_mode=material.VideoConcatMode.sequential,
                audio_duration=10,
                max_clip_duration=6,
                progress_callback=progress_callback,
                **kwargs,
            )

    def test_download_videos_reports_covered_duration_as_progress(self):
        """
        The download stage used to set progress to 40% only before starting and jump to 50% only after all materials finished, so on slow
        networks the progress bar sat at 40% for a long time. Each finished material must report the ratio of voice-over duration
        covered; failed candidates don't count, and covering more than needed is capped at 1.0.
        """
        for concurrency in (1, 4):
            with self.subTest(concurrency=concurrency):
                fractions = []
                result = self._download_with_progress(
                    concurrency=concurrency,
                    progress_callback=fractions.append,
                )

                self.assertEqual(result, ["/tmp/a.mp4", "/tmp/c.mp4"])
                self.assertEqual(fractions, [0.6, 1.0])

    def test_script_order_download_reports_progress(self):
        """The script-order material matching path must also report download progress."""
        fractions = []
        result = self._download_with_progress(
            concurrency=1,
            progress_callback=fractions.append,
            match_script_order=True,
        )

        self.assertTrue(result)
        self.assertEqual(fractions[-1], 1.0)
        self.assertEqual(fractions, sorted(fractions))

    def test_failing_progress_callback_does_not_break_download(self):
        """Progress is only display info; a callback error (e.g. state backend unavailable) must not fail the download."""

        def broken_callback(_fraction):
            raise RuntimeError("state backend unavailable")

        with patch.object(material.logger, "warning") as warning:
            result = self._download_with_progress(
                concurrency=1,
                progress_callback=broken_callback,
            )

        self.assertEqual(result, ["/tmp/a.mp4", "/tmp/c.mp4"])
        self.assertTrue(
            [
                call
                for call in warning.call_args_list
                if "progress" in str(call.args[0])
            ]
        )

    def test_each_finished_material_is_logged_with_its_position(self):
        """
        There used to be no per-file logs before a download round finished. Each finished material must log which number it is
        in the round, so users can tell from the logs that downloads are progressing and how many remain.
        """
        items = [
            material.MaterialInfo(
                provider="pexels",
                url=f"https://v.example/{name}.mp4",
                duration=6,
            )
            for name in ("a", "b", "c")
        ]
        downloaded = []

        def fake_save_video(video_url, save_dir=""):
            if "/b.mp4" in video_url:
                return ""
            return f"/tmp/{video_url.rsplit('/', 1)[-1]}"

        with (
            patch.dict(config.app, {"material_concurrency": 1}),
            patch.object(material, "save_video", side_effect=fake_save_video),
            patch.object(material.logger, "info") as info,
        ):
            material._download_materials_in_parallel(
                materials=[("city", item) for item in items],
                material_directory="",
                on_downloaded=lambda item: downloaded.append(item.url),
            )

        messages = [str(call.args[0]) for call in info.call_args_list]
        self.assertEqual(
            [m for m in messages if m.startswith("downloaded material")],
            [
                "downloaded material 1/3: a.mp4",
                "downloaded material 3/3: c.mp4",
            ],
        )
        self.assertEqual(
            downloaded,
            ["https://v.example/a.mp4", "https://v.example/c.mp4"],
        )

    def test_parallel_download_logs_belong_to_the_task_log_scope(self):
        """
        With concurrency above 1, materials download in the material-download thread pool. Logs written by these threads
        must be attributed to the task thread that started the download, otherwise raising concurrency would leave the WebUI
        showing no output at all during downloads.
        """
        items = [
            material.MaterialInfo(
                provider="pexels",
                url=f"https://v.example/{name}.mp4",
                duration=6,
            )
            for name in ("a", "b")
        ]

        def fake_save_video(video_url, save_dir=""):
            name = video_url.rsplit("/", 1)[-1]
            logger.info(f"worker downloading {name}")
            return f"/tmp/{name}"

        with (
            patch.dict(config.app, {"material_concurrency": 4}),
            patch.object(material, "save_video", side_effect=fake_save_video),
            _capture_task_scoped_logs() as messages,
        ):
            material._download_materials_in_parallel(
                materials=[("city", item) for item in items],
                material_directory="",
            )

        self.assertEqual(
            sorted(m for m in messages if m.startswith("worker downloading")),
            ["worker downloading a.mp4", "worker downloading b.mp4"],
        )

    def test_material_concurrency_is_clamped(self):
        """Material concurrency config is clamped to 1~8, and invalid values fall back to the serial default."""
        with patch.dict(config.app, {}, clear=True):
            self.assertEqual(material._get_material_concurrency(), 1)
        with patch.dict(config.app, {"material_concurrency": 0}):
            self.assertEqual(material._get_material_concurrency(), 1)
        with patch.dict(config.app, {"material_concurrency": 99}):
            self.assertEqual(material._get_material_concurrency(), 8)
        with patch.dict(config.app, {"material_concurrency": "bad"}):
            self.assertEqual(material._get_material_concurrency(), 1)
        with patch.dict(config.app, {"material_concurrency": 2}):
            self.assertEqual(material._get_material_concurrency(), 2)

    def test_material_source_persistence_failure_does_not_break_download(self):
        """When recording an auxiliary task record fails, successfully downloaded materials should still be returned normally to the main video flow."""
        item = material.MaterialInfo(
            provider="pexels",
            url="https://v.example/a1.mp4",
            duration=5,
            source_info={"provider": "pexels", "asset_id": "a1"},
        )

        with (
            patch.dict(config.app, {"material_directory": ""}),
            patch.object(material, "search_videos_pexels", return_value=[item]),
            patch.object(material, "save_video", return_value="/tmp/a1.mp4"),
            patch.object(
                material.material_cache,
                "load_material_search_cache",
                return_value=None,
            ),
            patch.object(material.material_cache, "save_material_search_cache"),
            patch.object(
                material.task_artifacts,
                "patch_script_data",
                side_effect=OSError("disk unavailable"),
            ),
            patch.object(material.logger, "warning") as warning,
        ):
            result = material.download_videos(
                task_id="persist-failure",
                search_terms=["city"],
                source="pexels",
                audio_duration=1,
                max_clip_duration=5,
            )

        self.assertEqual(result, ["/tmp/a1.mp4"])
        self.assertTrue(warning.called)


class TestCoverrProvider(unittest.TestCase):
    """
    Coverr video material source (spec: 2026-06-09-coverr-video-provider-design.md).
    requests is replaced entirely with unittest.mock, so CI doesn't depend on the real network or real API keys.
    """

    def setUp(self):
        self.original_app_config = dict(config.app)
        self.original_proxy_config = dict(config.proxy)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        config.proxy.clear()
        config.proxy.update(self.original_proxy_config)

    # ---------------- Tests for search_videos_coverr ----------------

    def test_search_coverr_uses_mp4_download_url(self):
        """
        search_videos_coverr should turn each hit into a MaterialInfo, using urls.mp4_download
        directly as MaterialInfo.url.
        Per Coverr's official docs (api.coverr.co/docs/videos/#download-a-video),
        a GET of mp4_download itself counts toward Coverr's download stats, so no extra PATCH ping is needed.
        Also verify the Authorization header uses the Bearer scheme.
        """
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.app.pop("tls_verify", None)
        config.proxy.clear()

        fake_response = SimpleNamespace(
            json=lambda: {
                "page": 0,
                "pages": 50,
                "page_size": 20,
                "total": 1,
                "hits": [
                    {
                        "id": "S1YbPl1NfI",
                        "duration": 11.625,
                        "aspect_ratio": "16:9",
                        "canonical_url": "https://coverr.co/videos/example?token=drop",
                        "creator": {
                            "id": "creator-1",
                            "name": "Coverr Creator",
                            "profile_url": "https://coverr.co/creators/example?key=drop",
                        },
                        "max_width": 3840,
                        "max_height": 2160,
                        "urls": {
                            "mp4": "https://storage.coverr.co/videos/abc?token=xyz",
                            "mp4_preview": "https://storage.coverr.co/videos/abc/preview?token=xyz",
                            "mp4_download": "https://storage.coverr.co/videos/abc/download?token=xyz",
                        },
                    }
                ],
            }
        )

        with patch(
            "app.services.material.requests.get", return_value=fake_response
        ) as get:
            results = material.search_videos_coverr(
                "nature",
                minimum_duration=5,
                video_aspect=material.VideoAspect.landscape,
            )

        self.assertEqual(len(results), 1)
        item = results[0]
        self.assertEqual(item.provider, "coverr")
        self.assertEqual(item.duration, 11)
        # The url field is the mp4_download URL; there's no more coverr://id|url encoding
        self.assertEqual(
            item.url, "https://storage.coverr.co/videos/abc/download?token=xyz"
        )
        self.assertEqual(item.source_info["asset_id"], "S1YbPl1NfI")
        self.assertEqual(
            item.source_info["source_page"],
            "https://coverr.co/videos/example",
        )
        self.assertEqual(
            item.source_info["creator"]["profile_page"],
            "https://coverr.co/creators/example",
        )
        # Bearer auth + TLS verify on by default
        self.assertEqual(
            get.call_args.kwargs["headers"]["Authorization"], "Bearer coverr-key"
        )
        self.assertTrue(get.call_args.kwargs["verify"])

    def test_search_coverr_uses_tls_verification_by_default(self):
        """Consistent with pexels/pixabay: TLS verification is on by default when not explicitly configured."""
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.app.pop("tls_verify", None)
        config.proxy.clear()

        fake_response = SimpleNamespace(json=lambda: {"hits": []})

        with patch(
            "app.services.material.requests.get", return_value=fake_response
        ) as get:
            material.search_videos_coverr("nature", minimum_duration=1)

        self.assertTrue(get.call_args.kwargs["verify"])

    def test_search_coverr_allows_explicit_tls_disable_for_proxy(self):
        """Corporate self-signed certificate proxy scenarios must be able to disable TLS verification explicitly."""
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.app["tls_verify"] = False
        config.proxy.clear()

        fake_response = SimpleNamespace(json=lambda: {"hits": []})

        with patch(
            "app.services.material.requests.get", return_value=fake_response
        ) as get:
            material.search_videos_coverr("nature", minimum_duration=1)

        self.assertFalse(get.call_args.kwargs["verify"])

    def test_search_coverr_filters_by_min_duration_and_accepts_string(self):
        """
        The Coverr duration field may be a number or a string in different responses,
        and both formats must be accepted; those below minimum_duration should be filtered out.
        """
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.app.pop("tls_verify", None)
        config.proxy.clear()

        fake_response = SimpleNamespace(
            json=lambda: {
                "hits": [
                    {
                        "id": "shortvid",
                        "duration": 3,  # below minimum
                        "urls": {"mp4_download": "https://example.com/a.mp4"},
                    },
                    {
                        "id": "stringdur",
                        "duration": "10.500000",  # string accepted
                        "max_width": 1080,
                        "max_height": 1920,
                        "urls": {"mp4_download": "https://example.com/b.mp4"},
                    },
                ]
            }
        )

        with patch(
            "app.services.material.requests.get", return_value=fake_response
        ):
            results = material.search_videos_coverr("x", minimum_duration=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].duration, 10)
        self.assertEqual(results[0].url, "https://example.com/b.mp4")

    def test_search_coverr_skips_invalid_items(self):
        """Entries missing id or urls.mp4_download should be skipped without raising."""
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.app.pop("tls_verify", None)
        config.proxy.clear()

        fake_response = SimpleNamespace(
            json=lambda: {
                "hits": [
                    {  # missing urls.mp4_download
                        "id": "no-download",
                        "duration": 10,
                        "urls": {"mp4_preview": "https://example.com/preview.mp4"},
                    },
                    {  # missing id
                        "duration": 10,
                        "urls": {"mp4_download": "https://example.com/x.mp4"},
                    },
                    {  # valid baseline
                        "id": "good",
                        "duration": 10,
                        "max_width": 1080,
                        "max_height": 1920,
                        "urls": {"mp4_download": "https://example.com/good.mp4"},
                    },
                ]
            }
        )

        with patch(
            "app.services.material.requests.get", return_value=fake_response
        ):
            results = material.search_videos_coverr("x", minimum_duration=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://example.com/good.mp4")

    def test_search_coverr_returns_empty_on_failure(self):
        """
        On malformed responses / network exceptions the function must return [] rather than raise,
        consistent with pexels/pixabay behavior.
        """
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.app.pop("tls_verify", None)
        config.proxy.clear()

        # Subtest A: malformed response (no "hits" key)
        with self.subTest("malformed response"):
            fake_response = SimpleNamespace(
                json=lambda: {"error": "rate limited"}
            )
            with patch(
                "app.services.material.requests.get", return_value=fake_response
            ):
                results = material.search_videos_coverr("x", minimum_duration=1)
            self.assertEqual(results, [])

        # Subtest B: network exception bubbles up from requests.get
        with self.subTest("network exception"):
            with patch(
                "app.services.material.requests.get",
                side_effect=requests.ConnectionError("boom"),
            ):
                results = material.search_videos_coverr("x", minimum_duration=1)
            self.assertEqual(results, [])

    # ---------------- Tests for download_videos coverr branch ----------------

    def test_download_videos_passes_mp4_download_url_to_save_video(self):
        """
        When source="coverr":
          1. dispatch to search_videos_coverr
          2. coverr items go through the generic download path: save_video receives the mp4_download URL
             (no more coverr://id|url encoding, and no more PATCH ping)
          3. return the saved path
        """
        config.app["coverr_api_keys"] = ["coverr-key"]
        config.app.pop("tls_verify", None)
        config.app.pop("material_directory", None)
        config.proxy.clear()

        fake_item = material.MaterialInfo()
        fake_item.provider = "coverr"
        fake_item.url = "https://storage.coverr.co/videos/abc/download?token=xyz"
        fake_item.duration = 10

        with patch(
            "app.services.material.search_videos_coverr",
            return_value=[fake_item],
        ) as search, patch(
            "app.services.material.save_video",
            return_value="/tmp/coverr-saved.mp4",
        ) as save, patch(
            "app.services.material.material_cache.load_material_search_cache",
            return_value=None,
        ), patch(
            "app.services.material.material_cache.save_material_search_cache",
        ):
            result = material.download_videos(
                task_id="t-coverr",
                search_terms=["nature"],
                source="coverr",
                audio_duration=5,
                max_clip_duration=5,
            )

        # 1. dispatch
        self.assertEqual(search.call_count, 1)

        # 2. save_video receives the mp4_download URL, passed through as-is
        save_url = save.call_args.kwargs.get("video_url") or save.call_args.args[0]
        self.assertEqual(
            save_url, "https://storage.coverr.co/videos/abc/download?token=xyz"
        )

        # 3. The return value is correct
        self.assertEqual(result, ["/tmp/coverr-saved.mp4"])


class TestWaveSpeedProvider(unittest.TestCase):
    """
    WaveSpeed AI text-to-video material source. Like the other material source tests, requests and time.sleep
    are replaced entirely with unittest.mock, so CI doesn't depend on the real network, real API keys or real billing.
    """

    def setUp(self):
        self.original_app_config = dict(config.app)
        self.original_proxy_config = dict(config.proxy)
        config.app["wavespeed_api_keys"] = ["wavespeed-key"]
        config.app.pop("tls_verify", None)
        config.proxy.clear()

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        config.proxy.clear()
        config.proxy.update(self.original_proxy_config)

    @staticmethod
    def _json_response(payload):
        return SimpleNamespace(json=lambda: payload)

    def test_generate_wavespeed_submits_and_polls_to_completion(self):
        """
        The submit request must carry Bearer auth, the model ID path and the three generation parameters prompt/aspect_ratio/duration;
        once polling reaches completed, outputs are turned into MaterialInfo.
        """
        submit_response = self._json_response(
            {"code": 200, "message": "success", "data": {"id": "pred-123"}}
        )
        poll_responses = [
            self._json_response(
                {"code": 200, "data": {"id": "pred-123", "status": "processing"}}
            ),
            self._json_response(
                {
                    "code": 200,
                    "data": {
                        "id": "pred-123",
                        "status": "completed",
                        "outputs": ["https://cdn.example.com/out.mp4?sig=abc"],
                    },
                }
            ),
        ]

        with (
            patch(
                "app.services.material.requests.post", return_value=submit_response
            ) as post,
            patch(
                "app.services.material.requests.get", side_effect=poll_responses
            ) as get,
            patch("app.services.material.time.sleep") as sleep,
        ):
            results = material.generate_videos_wavespeed(
                "sunrise over mountains",
                minimum_duration=5,
                video_aspect=material.VideoAspect.portrait,
            )

        self.assertEqual(len(results), 1)
        item = results[0]
        self.assertEqual(item.provider, "wavespeed")
        # The signed URL must be kept as-is; query parameters can't be stripped, or the download returns 403
        self.assertEqual(item.url, "https://cdn.example.com/out.mp4?sig=abc")
        self.assertEqual(item.duration, 5)
        self.assertEqual(item.source_info["asset_id"], "pred-123")
        self.assertEqual(item.source_info["search_term"], "sunrise over mountains")
        # The output URL is a temporary signed URL and must not be written into the source record
        self.assertNotIn("source_page", item.source_info)

        self.assertIn(
            "/api/v3/bytedance/seedance-2.0-fast/text-to-video",
            post.call_args.args[0],
        )
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer wavespeed-key",
        )
        self.assertEqual(
            post.call_args.kwargs["json"],
            {
                "prompt": "sunrise over mountains",
                "aspect_ratio": "9:16",
                "duration": 5,
            },
        )
        self.assertTrue(post.call_args.kwargs["verify"])
        self.assertIn("/api/v3/predictions/pred-123/result", get.call_args.args[0])
        # In the processing state it must wait for the polling interval rather than spin and hammer the remote API
        self.assertEqual(sleep.call_count, 1)

    def test_generate_wavespeed_uses_configured_model_id(self):
        """Users can switch to any WaveSpeed text-to-video model in config."""
        config.app["wavespeed_text_to_video_model"] = "wavespeed-ai/custom-t2v"
        submit_response = self._json_response({"code": 200, "data": {"id": "pred-9"}})
        poll_response = self._json_response(
            {
                "code": 200,
                "data": {
                    "id": "pred-9",
                    "status": "completed",
                    "outputs": ["https://cdn.example.com/a.mp4"],
                },
            }
        )

        with (
            patch(
                "app.services.material.requests.post", return_value=submit_response
            ) as post,
            patch("app.services.material.requests.get", return_value=poll_response),
        ):
            results = material.generate_videos_wavespeed(
                "city timelapse",
                minimum_duration=3,
                video_aspect=material.VideoAspect.landscape,
            )

        self.assertEqual(len(results), 1)
        self.assertIn("/api/v3/wavespeed-ai/custom-t2v", post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs["json"]["aspect_ratio"], "16:9")

    def test_generate_wavespeed_returns_empty_on_failed_prediction(self):
        """failed/cancelled/timeout all return empty results, letting the upper layer skip the keyword and continue."""
        submit_response = self._json_response({"code": 200, "data": {"id": "pred-fail"}})
        poll_response = self._json_response(
            {
                "code": 200,
                "data": {
                    "id": "pred-fail",
                    "status": "failed",
                    "error": "content policy",
                },
            }
        )

        with (
            patch("app.services.material.requests.post", return_value=submit_response),
            patch("app.services.material.requests.get", return_value=poll_response),
        ):
            results = material.generate_videos_wavespeed("sunrise", minimum_duration=5)

        self.assertEqual(results, [])

    def test_generate_wavespeed_returns_empty_on_rejected_submission(self):
        """A non-200 envelope (e.g. invalid key) must not enter polling and returns an empty result directly."""
        submit_response = self._json_response({"code": 401, "message": "invalid api key"})

        with (
            patch("app.services.material.requests.post", return_value=submit_response),
            patch("app.services.material.requests.get") as get,
        ):
            results = material.generate_videos_wavespeed("sunrise", minimum_duration=5)

        self.assertEqual(results, [])
        get.assert_not_called()

    def test_generate_wavespeed_returns_empty_on_plain_text_client_error(self):
        """
        A 4xx is a clear rejection; even if the response body is plain text from a gateway, it must not be misreported as "possibly billed".
        When a 2xx response body can't be parsed, it's still treated as an unknown state.
        """

        def unreadable():
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

        for status in (401, 429):
            with self.subTest(status=status):
                rejected = SimpleNamespace(status_code=status, json=unreadable)
                with (
                    patch("app.services.material.requests.post", return_value=rejected),
                    patch("app.services.material.requests.get") as get,
                ):
                    results = material.generate_videos_wavespeed(
                        "sunrise", minimum_duration=5
                    )

                self.assertEqual(results, [])
                get.assert_not_called()

        accepted = SimpleNamespace(status_code=200, json=unreadable)
        with patch("app.services.material.requests.post", return_value=accepted):
            with self.assertRaises(material.WaveSpeedUnconfirmedTaskError):
                material.generate_videos_wavespeed("sunrise", minimum_duration=5)

    def test_generate_wavespeed_never_retries_submission_on_network_error(self):
        """
        Not receiving a response to the submission doesn't mean no task was created; resending the POST would cause duplicate generation and duplicate charges.
        So submission is never retried automatically and is raised as "unknown state", letting the upper layer stop placing orders.
        """
        with patch(
            "app.services.material.requests.post",
            side_effect=requests.exceptions.ConnectionError("boom"),
        ) as post:
            with self.assertRaises(material.WaveSpeedUnconfirmedTaskError):
                material.generate_videos_wavespeed("sunrise", minimum_duration=5)

        self.assertEqual(post.call_count, 1)

    def test_generate_wavespeed_treats_server_error_submission_as_unconfirmed(self):
        """A 5xx may happen after the task was created; the state is unknown and it can't be treated as "not charged" and continue."""
        submit_response = SimpleNamespace(
            status_code=502, json=lambda: {"code": 502, "message": "bad gateway"}
        )

        with patch("app.services.material.requests.post", return_value=submit_response):
            with self.assertRaises(material.WaveSpeedUnconfirmedTaskError):
                material.generate_videos_wavespeed("sunrise", minimum_duration=5)

    def test_generate_wavespeed_retries_transient_poll_failures_on_same_task(self):
        """
        When polling hits 429/5xx or a network exception, it must back off and retry with the original prediction id,
        and must never resubmit a paid generation task.
        """
        submit_response = self._json_response({"code": 200, "data": {"id": "pred-r1"}})
        rate_limited = SimpleNamespace(status_code=429, json=lambda: {"code": 429})
        completed = self._json_response(
            {
                "code": 200,
                "data": {
                    "id": "pred-r1",
                    "status": "completed",
                    "outputs": ["https://cdn.example.com/r1.mp4"],
                },
            }
        )

        with (
            patch(
                "app.services.material.requests.post", return_value=submit_response
            ) as post,
            patch(
                "app.services.material.requests.get",
                side_effect=[
                    rate_limited,
                    requests.exceptions.ConnectionError("boom"),
                    completed,
                ],
            ) as get,
            patch("app.services.material.time.sleep") as sleep,
        ):
            results = material.generate_videos_wavespeed("sunrise", minimum_duration=5)

        self.assertEqual(len(results), 1)
        # Submitted only once; all three GETs point to the same prediction id
        self.assertEqual(post.call_count, 1)
        self.assertEqual(get.call_count, 3)
        for call in get.call_args_list:
            self.assertIn("/api/v3/predictions/pred-r1/result", call.args[0])
        # Linear backoff: the n-th retry waits base * n
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1.0, 2.0])

    def test_generate_wavespeed_raises_unconfirmed_after_poll_retries_exhausted(self):
        """
        After consecutive transient failures exceed the limit, the task state is still unknown: the task may still be running remotely.
        It must be raised with the prediction id, rather than treated as a failure that lets the flow keep placing orders.
        """
        submit_response = self._json_response({"code": 200, "data": {"id": "pred-r2"}})

        with (
            patch("app.services.material.requests.post", return_value=submit_response),
            patch(
                "app.services.material.requests.get",
                side_effect=requests.exceptions.ConnectionError("boom"),
            ) as get,
            patch("app.services.material.time.sleep"),
        ):
            with self.assertRaises(material.WaveSpeedUnconfirmedTaskError) as ctx:
                material.generate_videos_wavespeed("sunrise", minimum_duration=5)

        self.assertEqual(ctx.exception.prediction_id, "pred-r2")
        self.assertEqual(get.call_count, material.WAVESPEED_MAX_POLL_RETRIES + 1)

    def test_generate_wavespeed_raises_unconfirmed_on_local_wait_timeout(self):
        """The local wait timed out while the remote task is still running; the state is unknown, so no new tasks may be submitted."""
        submit_response = self._json_response({"code": 200, "data": {"id": "pred-r3"}})
        processing = self._json_response(
            {"code": 200, "data": {"id": "pred-r3", "status": "processing"}}
        )
        clock = iter([0.0, 0.0, material.WAVESPEED_RUN_TIMEOUT_SECONDS + 1])

        with (
            patch("app.services.material.requests.post", return_value=submit_response),
            patch("app.services.material.requests.get", return_value=processing),
            patch(
                "app.services.material.time.monotonic", side_effect=lambda: next(clock)
            ),
            patch("app.services.material.time.sleep"),
        ):
            with self.assertRaises(material.WaveSpeedUnconfirmedTaskError) as ctx:
                material.generate_videos_wavespeed("sunrise", minimum_duration=5)

        self.assertEqual(ctx.exception.prediction_id, "pred-r3")

    def test_download_videos_wavespeed_stops_submitting_after_unconfirmed_task(self):
        """
        Regression: when one clip's task state is unknown, later keywords must never trigger new paid generation
        requests — otherwise the first task may still be running/already completed, causing duplicate generation and extra charges.
        Materials that already downloaded successfully must not make the whole task be wrongly marked as complete.
        """
        first_item = self._generated_item("term-1", "https://cdn.example.com/1.mp4")

        def fake_generate(search_term, minimum_duration, video_aspect):
            if search_term == "term-1":
                return [first_item]
            raise material.WaveSpeedUnconfirmedTaskError(
                "state unknown", prediction_id="pred-stuck"
            )

        with (
            patch(
                "app.services.material.generate_videos_wavespeed",
                side_effect=fake_generate,
            ) as generate,
            patch(
                "app.services.material.save_video",
                return_value="/tmp/1.mp4",
            ),
        ):
            with self.assertRaises(material.WaveSpeedUnconfirmedTaskError) as ctx:
                material.download_videos(
                    task_id="test-wavespeed-unconfirmed",
                    search_terms=["term-1", "term-2", "term-3"],
                    source="wavespeed",
                    audio_duration=100,
                    max_clip_duration=5,
                )

        # Stop immediately after term-2 raises an unknown state; term-3 must not produce a generation request
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(ctx.exception.prediction_id, "pred-stuck")

    def test_download_videos_wavespeed_stops_after_paid_download_failure(self):
        """After download retries are exhausted, the next keyword must not quietly pay again."""
        item = self._generated_item("term-1", "https://cdn.example.com/1.mp4")
        with (
            patch(
                "app.services.material.generate_videos_wavespeed",
                return_value=[item],
            ) as generate,
            patch("app.services.material.save_video", return_value="") as save,
            patch("app.services.material.time.sleep"),
        ):
            with self.assertRaises(material.WaveSpeedDownloadError) as ctx:
                material.download_videos(
                    task_id="test-wavespeed-paid-download-failure",
                    search_terms=["term-1", "term-2"],
                    source="wavespeed",
                    audio_duration=10,
                    max_clip_duration=5,
                )

        self.assertEqual(ctx.exception.prediction_id, "pred-term-1")
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(
            save.call_count, material.WAVESPEED_MAX_DOWNLOAD_RETRIES + 1
        )

    def test_download_videos_wavespeed_retries_original_download_url(self):
        """
        The output was already paid for, so download hiccups must retry the same signed URL first rather than
        submitting another paid generation task.
        """
        item = self._generated_item("term-1", "https://cdn.example.com/1.mp4")

        with (
            patch(
                "app.services.material.generate_videos_wavespeed",
                return_value=[item],
            ) as generate,
            patch(
                "app.services.material.save_video",
                side_effect=[
                    requests.exceptions.ConnectionError("boom"),
                    "/tmp/1.mp4",
                ],
            ) as save,
            patch("app.services.material.time.sleep"),
        ):
            result = material.download_videos(
                task_id="test-wavespeed-download-retry",
                search_terms=["term-1"],
                source="wavespeed",
                audio_duration=5,
                max_clip_duration=5,
            )

        self.assertEqual(result, ["/tmp/1.mp4"])
        # Retries hit the same URL, and no second paid generation was triggered
        self.assertEqual(save.call_count, 2)
        self.assertEqual(generate.call_count, 1)
        for call in save.call_args_list:
            self.assertEqual(
                call.kwargs.get("video_url") or call.args[0],
                "https://cdn.example.com/1.mp4",
            )

    def test_download_videos_wavespeed_bypasses_search_cache(self):
        """
        Generation sources skip the 24-hour search cache: signed URLs expire, and reusing the cache would make different
        tasks get the same generated video repeatedly. download_videos must call the generation function directly.
        """
        generated_item = material.MaterialInfo()
        generated_item.provider = "wavespeed"
        generated_item.url = "https://cdn.example.com/out.mp4?sig=abc"
        generated_item.duration = 5
        generated_item.source_info = {
            "provider": "wavespeed",
            "search_term": "sunrise",
            "asset_id": "pred-123",
        }

        with (
            patch(
                "app.services.material.generate_videos_wavespeed",
                return_value=[generated_item],
            ) as generate,
            patch("app.services.material._search_videos_with_cache") as cached_search,
            patch(
                "app.services.material.save_video",
                return_value="/tmp/wavespeed-saved.mp4",
            ) as save,
        ):
            result = material.download_videos(
                task_id="test-wavespeed",
                search_terms=["sunrise"],
                source="wavespeed",
                audio_duration=5,
                max_clip_duration=5,
            )

        self.assertEqual(generate.call_count, 1)
        cached_search.assert_not_called()
        save_url = save.call_args.kwargs.get("video_url") or save.call_args.args[0]
        self.assertEqual(save_url, "https://cdn.example.com/out.mp4?sig=abc")
        self.assertEqual(result, ["/tmp/wavespeed-saved.mp4"])

    def test_generate_wavespeed_clamps_duration_to_model_minimum(self):
        """
        The WebUI default clip duration is 3 seconds, while the default model only accepts 4-15 seconds; passing it straight through would be rejected by the API.
        The request must be clamped to the model's minimum, and the extra duration is trimmed to the clip duration by the existing editing flow.
        """
        submit_response = self._json_response({"code": 200, "data": {"id": "pred-c1"}})
        poll_response = self._json_response(
            {
                "code": 200,
                "data": {
                    "id": "pred-c1",
                    "status": "completed",
                    "outputs": ["https://cdn.example.com/c1.mp4"],
                },
            }
        )

        with (
            patch(
                "app.services.material.requests.post", return_value=submit_response
            ) as post,
            patch("app.services.material.requests.get", return_value=poll_response),
        ):
            results = material.generate_videos_wavespeed("sunrise", minimum_duration=3)

        self.assertEqual(post.call_args.kwargs["json"]["duration"], 4)
        # MaterialInfo records the actual generated duration, and duration accounting and editing use the real material length
        self.assertEqual(results[0].duration, 4)

    def test_generate_wavespeed_clamps_duration_to_model_maximum(self):
        """Requests above the model's maximum are clamped to the maximum, never submitting a remote request that's bound to fail."""
        submit_response = self._json_response({"code": 200, "data": {"id": "pred-c2"}})
        poll_response = self._json_response(
            {
                "code": 200,
                "data": {
                    "id": "pred-c2",
                    "status": "completed",
                    "outputs": ["https://cdn.example.com/c2.mp4"],
                },
            }
        )

        with (
            patch(
                "app.services.material.requests.post", return_value=submit_response
            ) as post,
            patch("app.services.material.requests.get", return_value=poll_response),
        ):
            results = material.generate_videos_wavespeed("sunrise", minimum_duration=20)

        self.assertEqual(post.call_args.kwargs["json"]["duration"], 15)
        self.assertEqual(results[0].duration, 15)

    def test_generate_wavespeed_duration_bounds_are_configurable(self):
        """When switching to another model, users can adjust the supported duration range in config accordingly."""
        config.app["wavespeed_min_duration"] = 2
        config.app["wavespeed_max_duration"] = 8
        submit_response = self._json_response({"code": 200, "data": {"id": "pred-c3"}})
        poll_response = self._json_response(
            {
                "code": 200,
                "data": {
                    "id": "pred-c3",
                    "status": "completed",
                    "outputs": ["https://cdn.example.com/c3.mp4"],
                },
            }
        )

        with (
            patch(
                "app.services.material.requests.post", return_value=submit_response
            ) as post,
            patch("app.services.material.requests.get", return_value=poll_response),
        ):
            material.generate_videos_wavespeed("sunrise", minimum_duration=3)

        self.assertEqual(post.call_args.kwargs["json"]["duration"], 3)

    @staticmethod
    def _generated_item(term, url, duration=5):
        item = material.MaterialInfo()
        item.provider = "wavespeed"
        item.url = url
        item.duration = duration
        item.source_info = {
            "provider": "wavespeed",
            "search_term": term,
            "asset_id": f"pred-{term}",
        }
        return item

    def test_download_videos_wavespeed_generates_on_demand_and_stops(self):
        """
        Generation is billed per clip, so it can't generate for every keyword first and then choose. Materials must be generated segment by segment on demand,
        and once the accumulated effective duration (capped at the clip duration) exceeds the required voice-over duration, later keywords no longer
        trigger any generation requests.
        """
        generated = {
            "term-1": [self._generated_item("term-1", "https://cdn.example.com/1.mp4")],
            "term-2": [self._generated_item("term-2", "https://cdn.example.com/2.mp4")],
            "term-3": [self._generated_item("term-3", "https://cdn.example.com/3.mp4")],
        }

        def fake_generate(search_term, minimum_duration, video_aspect):
            return generated[search_term]

        with (
            patch(
                "app.services.material.generate_videos_wavespeed",
                side_effect=fake_generate,
            ) as generate,
            patch(
                "app.services.material.save_video",
                side_effect=lambda video_url, save_dir="": f"/tmp/{video_url.rsplit('/', 1)[-1]}",
            ),
        ):
            result = material.download_videos(
                task_id="test-wavespeed-lazy",
                search_terms=["term-1", "term-2", "term-3"],
                source="wavespeed",
                audio_duration=8,
                max_clip_duration=5,
            )

        # 5s + 5s > 8s, so the third keyword must not produce a paid generation request
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(
            [call.kwargs["search_term"] for call in generate.call_args_list],
            ["term-1", "term-2"],
        )
        self.assertEqual(result, ["/tmp/1.mp4", "/tmp/2.mp4"])

    def test_download_videos_wavespeed_stops_when_duration_exactly_covered(self):
        """
        Boundary regression: with 10 seconds of voice-over and 5 seconds per clip, an accumulated total exactly equal to the required duration is already enough,
        and the 3rd keyword must not trigger a paid generation request (the stop check must be >= rather than >).
        """
        generated = {
            "term-1": [self._generated_item("term-1", "https://cdn.example.com/1.mp4")],
            "term-2": [self._generated_item("term-2", "https://cdn.example.com/2.mp4")],
            "term-3": [self._generated_item("term-3", "https://cdn.example.com/3.mp4")],
        }

        def fake_generate(search_term, minimum_duration, video_aspect):
            return generated[search_term]

        with (
            patch(
                "app.services.material.generate_videos_wavespeed",
                side_effect=fake_generate,
            ) as generate,
            patch(
                "app.services.material.save_video",
                side_effect=lambda video_url, save_dir="": f"/tmp/{video_url.rsplit('/', 1)[-1]}",
            ),
        ):
            result = material.download_videos(
                task_id="test-wavespeed-exact",
                search_terms=["term-1", "term-2", "term-3"],
                source="wavespeed",
                audio_duration=10,
                max_clip_duration=5,
            )

        # 5s + 5s == 10s, exactly covered, so the 3rd clip must never be generated
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(result, ["/tmp/1.mp4", "/tmp/2.mp4"])

    def test_download_videos_wavespeed_rejects_nonfinite_duration_before_submission(self):
        """NaN/Infinity must not buy a video for every script keyword."""
        for duration in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(duration=duration):
                with patch("app.services.material.generate_videos_wavespeed") as generate:
                    with self.assertRaisesRegex(ValueError, "finite"):
                        material.download_videos(
                            task_id="test-wavespeed-invalid-duration",
                            search_terms=["term-1", "term-2"],
                            source="wavespeed",
                            audio_duration=duration,
                            max_clip_duration=5,
                        )
                    generate.assert_not_called()

    def test_download_videos_wavespeed_rejects_nonpositive_clip_duration(self):
        """A zero clip duration cannot advance paid coverage."""
        with patch("app.services.material.generate_videos_wavespeed") as generate:
            with self.assertRaisesRegex(ValueError, "clip duration"):
                material.download_videos(
                    task_id="test-wavespeed-invalid-clip",
                    search_terms=["term-1", "term-2"],
                    source="wavespeed",
                    audio_duration=10,
                    max_clip_duration=0,
                )
            generate.assert_not_called()

    def test_download_videos_wavespeed_skips_nonpositive_audio_duration(self):
        """An empty narration must not start a paid generation request."""
        with (
            patch("app.services.material.generate_videos_wavespeed") as generate,
            patch("app.services.material._persist_material_sources"),
        ):
            result = material.download_videos(
                task_id="test-wavespeed-empty-audio",
                search_terms=["term-1", "term-2"],
                source="wavespeed",
                audio_duration=0,
                max_clip_duration=5,
            )
        self.assertEqual(result, [])
        generate.assert_not_called()

    def test_download_videos_wavespeed_skips_failed_segment_and_continues(self):
        """When a single clip's generation fails (empty result), skip that keyword and keep generating later clips."""
        generated = {
            "term-1": [],
            "term-2": [self._generated_item("term-2", "https://cdn.example.com/2.mp4")],
        }

        def fake_generate(search_term, minimum_duration, video_aspect):
            return generated[search_term]

        with (
            patch(
                "app.services.material.generate_videos_wavespeed",
                side_effect=fake_generate,
            ) as generate,
            patch(
                "app.services.material.save_video",
                return_value="/tmp/wavespeed-2.mp4",
            ),
        ):
            result = material.download_videos(
                task_id="test-wavespeed-skip",
                search_terms=["term-1", "term-2"],
                source="wavespeed",
                audio_duration=4,
                max_clip_duration=5,
            )

        self.assertEqual(generate.call_count, 2)
        self.assertEqual(result, ["/tmp/wavespeed-2.mp4"])


if __name__ == "__main__":
    unittest.main()
