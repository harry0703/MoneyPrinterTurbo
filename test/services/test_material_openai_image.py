# -*- coding: utf-8 -*-
import base64
import io
import os
import shutil
import tempfile
import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import patch

import requests
from PIL import Image

from app.config import config
from app.services import material


def _png_bytes(width=64, height=96, color=(120, 40, 200)):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _image_response(payload, status_code=200):
    return SimpleNamespace(json=lambda: payload, status_code=status_code)


def _download_response(content, status_code=200):
    return SimpleNamespace(
        status_code=status_code,
        content=content,
        headers={"Content-Length": str(len(content))},
        iter_content=lambda chunk_size: iter((content,)),
        close=lambda: None,
    )


class TestOpenAIImageProvider(unittest.TestCase):
    """
    OpenAI-compatible text-to-image material source. Like the other material source tests, requests and time.sleep
    are replaced entirely with unittest.mock, so CI doesn't depend on the real network, real API keys or real billing.
    """

    def setUp(self):
        self.original_app_config = dict(config.app)
        self.original_proxy_config = dict(config.proxy)
        # Assertions run after the generation call returns, so the temp directory can't be destroyed early with a with block;
        # mkdtemp + addCleanup manage its lifetime instead.
        self.save_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.save_dir, ignore_errors=True)
        config.app["openai_image_base_url"] = "https://img.example.com/v1"
        config.app["openai_image_api_keys"] = ["sk-test-key"]
        config.app["openai_image_model"] = "test-image-model"
        # The prompt template and custom size are off by default, and test cases that need them configure them, so a developer's
        # local config.toml settings don't affect assertions in default-behavior scenarios.
        config.app.pop("openai_image_prompt_template", None)
        config.app.pop("openai_image_size", None)
        config.app.pop("tls_verify", None)
        config.proxy.clear()

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        config.proxy.clear()
        config.proxy.update(self.original_proxy_config)

    @staticmethod
    def _generated_item(term, image_path, duration=5):
        item = material.MaterialInfo()
        item.provider = "openai_image"
        item.url = image_path
        item.duration = duration
        item.source_info = {
            "provider": "openai_image",
            "search_term": term,
            "rendition": {"id": None, "width": 736, "height": 1312},
        }
        return item

    # ------------------------------------------------------------------
    # Success path
    # ------------------------------------------------------------------

    def test_generate_images_openai_with_b64_json_response(self):
        """
        A b64_json response must be decoded and saved as a valid PNG, with the rendition written from the real image size
        (handling relay services that return a size different from the request), and duration recording the target clip duration.
        """
        image_data = _png_bytes(width=736, height=1312)
        response = _image_response(
            {"data": [{"b64_json": base64.b64encode(image_data).decode("ascii")}]}
        )

        with patch(
            "app.services.material.requests.post", return_value=response
        ) as post:
            results = material.generate_images_openai(
                "sunrise over mountains",
                minimum_duration=5,
                video_aspect=material.VideoAspect.portrait,
                save_dir=self.save_dir,
            )

        self.assertEqual(len(results), 1)
        item = results[0]
        self.assertEqual(item.provider, "openai_image")
        self.assertEqual(item.duration, 5)
        # The request size uses the official OpenAI-compatible size for the aspect ratio, not the video resolution directly
        self.assertEqual(
            post.call_args.args[0],
            "https://img.example.com/v1/images/generations",
        )
        self.assertEqual(
            post.call_args.kwargs["json"],
            {
                "model": "test-image-model",
                "prompt": "sunrise over mountains",
                "n": 1,
                "size": "1024x1536",
            },
        )
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer sk-test-key",
        )
        # The saved file is a decodable PNG
        self.assertTrue(item.url.endswith(".png"))
        self.assertTrue(os.path.isfile(item.url))
        with Image.open(item.url) as saved:
            self.assertEqual(saved.size, (736, 1312))
        # The rendition records the real image size, not relying on request parameters
        self.assertEqual(
            item.source_info["rendition"],
            {"id": None, "width": 736, "height": 1312},
        )
        self.assertEqual(item.source_info["search_term"], "sunrise over mountains")

    def test_generate_images_openai_with_url_response(self):
        """A url response must download the temporary URL immediately and save it."""
        response = _image_response(
            {"data": [{"url": "https://cdn.example.com/generated/abc.png?sig=1"}]}
        )
        download = _download_response(_png_bytes(width=200, height=300))

        with (
            patch("app.services.material.requests.post", return_value=response),
            patch("app.services.material.requests.get", return_value=download) as get,
        ):
            results = material.generate_images_openai(
                "city at night", minimum_duration=3, save_dir=self.save_dir
            )

        self.assertEqual(len(results), 1)
        self.assertTrue(os.path.isfile(results[0].url))
        # The temporary URL is downloaded as-is; signed query parameters can't be stripped
        self.assertEqual(
            get.call_args.args[0],
            "https://cdn.example.com/generated/abc.png?sig=1",
        )

    def test_generate_images_openai_skips_b64_json_with_invalid_image(self):
        """
        When the compatibility layer returns 200 but the body isn't a decodable image (e.g. an HTML error page disguised as JSON),
        an empty list must be returned per the material source convention so the upper layer skips the keyword, rather than letting the decode
        exception abort the whole task.
        """
        fake_content = b"<html><body>gateway degraded</body></html>"
        response = _image_response(
            {"data": [{"b64_json": base64.b64encode(fake_content).decode("ascii")}]}
        )

        with patch("app.services.material.requests.post", return_value=response):
            results = material.generate_images_openai(
                "sunrise over mountains", minimum_duration=5, save_dir=self.save_dir
            )

        self.assertEqual(results, [])
        self.assertEqual(os.listdir(self.save_dir), [])

    def test_generate_images_openai_skips_url_download_with_invalid_content(self):
        """When a temporary URL downloads non-image content with 200, the same skip path is taken."""
        response = _image_response(
            {"data": [{"url": "https://cdn.example.com/generated/abc.png?sig=1"}]}
        )
        download = _download_response(b"\x89PNG\r\n\x1a\nnot-really-a-png")

        with (
            patch("app.services.material.requests.post", return_value=response),
            patch("app.services.material.requests.get", return_value=download),
        ):
            results = material.generate_images_openai(
                "city at night", minimum_duration=3, save_dir=self.save_dir
            )

        self.assertEqual(results, [])
        self.assertEqual(os.listdir(self.save_dir), [])

    def test_generate_images_openai_propagates_image_write_failure(self):
        """
        When the image decoded successfully but writing the PNG fails, the task must stop. Such failures usually persist
        and affect later keywords; misjudging it as a single bad image and continuing would make paid requests that can't be saved.
        """
        response = _image_response(
            {
                "data": [
                    {"b64_json": base64.b64encode(_png_bytes()).decode("ascii")}
                ]
            }
        )

        with (
            patch("app.services.material.requests.post", return_value=response),
            patch.object(
                Image.Image,
                "save",
                side_effect=OSError("no space left on device"),
            ),
            self.assertRaisesRegex(OSError, "no space left on device"),
        ):
            material.generate_images_openai(
                "city at night", minimum_duration=3, save_dir=self.save_dir
            )

        self.assertEqual(os.listdir(self.save_dir), [])

    # ------------------------------------------------------------------
    # Backoff retries and key rotation
    # ------------------------------------------------------------------

    def test_generate_images_openai_retries_429_with_backoff(self):
        """429 is a transient rate limit and must be retried with backoff rather than failing the task."""
        image_data = _png_bytes()
        responses = [
            _image_response({"error": {"message": "rate limited"}}, status_code=429),
            _image_response(
                {"data": [{"b64_json": base64.b64encode(image_data).decode("ascii")}]}
            ),
        ]

        with (
            tempfile.TemporaryDirectory() as save_dir,
            patch("app.services.material.requests.post", side_effect=responses) as post,
            patch("app.services.material.time.sleep") as sleep,
        ):
            results = material.generate_images_openai(
                "ocean waves", minimum_duration=5, save_dir=save_dir
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(post.call_count, 2)
        # Linear backoff must be waited before the first retry, rather than hammering the remote API immediately
        self.assertEqual(sleep.call_count, 1)
        self.assertEqual(
            sleep.call_args.args[0],
            material.OPENAI_IMAGE_RETRY_BACKOFF_SECONDS[0],
        )

    def test_generate_images_openai_rotates_key_on_401(self):
        """
        401 means the current key was rejected. With multiple keys configured, retries must use get_api_key's
        rotation to switch to the next key, rather than repeatedly using the same rejected key.
        """
        config.app["openai_image_api_keys"] = ["sk-bad-key", "sk-good-key"]
        image_data = _png_bytes()

        responses = [
            _image_response({"error": {"message": "unauthorized"}}, status_code=401),
            _image_response(
                {"data": [{"b64_json": base64.b64encode(image_data).decode("ascii")}]}
            ),
        ]

        with (
            tempfile.TemporaryDirectory() as save_dir,
            patch("app.services.material.requests.post", side_effect=responses) as post,
            patch("app.services.material.time.sleep"),
        ):
            results = material.generate_images_openai(
                "forest fog", minimum_duration=5, save_dir=save_dir
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(post.call_count, 2)
        used_keys = [
            call.kwargs["headers"]["Authorization"] for call in post.call_args_list
        ]
        # Two consecutive requests must use different keys, both from the configured list
        self.assertNotEqual(used_keys[0], used_keys[1])
        for auth in used_keys:
            self.assertIn(auth.replace("Bearer ", ""), ["sk-bad-key", "sk-good-key"])

    def test_generate_images_openai_fails_fast_on_401_with_single_key(self):
        """With only one key, retrying a 401 is pointless and must fail fast with an empty result."""
        response = _image_response(
            {"error": {"message": "unauthorized"}}, status_code=401
        )

        with (
            tempfile.TemporaryDirectory() as save_dir,
            patch("app.services.material.requests.post", return_value=response) as post,
            patch("app.services.material.time.sleep") as sleep,
        ):
            results = material.generate_images_openai(
                "desert dunes", minimum_duration=5, save_dir=save_dir
            )

        self.assertEqual(results, [])
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()

    def test_generate_images_openai_returns_empty_after_retries_exhausted(self):
        """
        Once all retries are exhausted, an empty list is returned per the material source convention, leaving the upper layer to skip the keyword; and no
        leftover files are saved.
        """
        response = _image_response(
            {"error": {"message": "rate limited"}}, status_code=429
        )

        with (
            patch("app.services.material.requests.post", return_value=response) as post,
            patch("app.services.material.time.sleep") as sleep,
        ):
            results = material.generate_images_openai(
                "storm clouds", minimum_duration=5, save_dir=self.save_dir
            )

        self.assertEqual(results, [])
        self.assertEqual(post.call_count, material.OPENAI_IMAGE_MAX_ATTEMPTS)
        self.assertEqual(sleep.call_count, material.OPENAI_IMAGE_MAX_ATTEMPTS - 1)
        # No leftover files were generated
        self.assertEqual(os.listdir(self.save_dir), [])

    def test_generate_images_openai_redacts_api_key_in_failure_detail(self):
        """Failure details must not write the API key into the log in plaintext."""
        config.app["openai_image_api_keys"] = ["sk-secret-123"]
        response = _image_response(
            {"error": {"message": "invalid key sk-secret-123 provided"}},
            status_code=401,
        )

        with (
            tempfile.TemporaryDirectory() as save_dir,
            patch("app.services.material.requests.post", return_value=response),
            patch("app.services.material.logger") as logger,
        ):
            results = material.generate_images_openai(
                "redacted term", minimum_duration=5, save_dir=save_dir
            )

        self.assertEqual(results, [])
        logged = [str(call) for call in logger.error.call_args_list]
        self.assertTrue(logged)
        for message in logged:
            self.assertNotIn("sk-secret-123", message)

    def test_generate_images_openai_retries_generated_image_download(self):
        """
        The image is already billed per piece, so download hiccups must retry the same URL and not fall back to regenerating
        the same image, which would cause duplicate charges.
        """
        response = _image_response(
            {"data": [{"url": "https://cdn.example.com/generated/x.png"}]}
        )
        downloads = [
            _download_response(b"", status_code=502),
            _download_response(_png_bytes()),
        ]

        with (
            tempfile.TemporaryDirectory() as save_dir,
            patch("app.services.material.requests.post", return_value=response) as post,
            patch("app.services.material.requests.get", side_effect=downloads) as get,
            patch("app.services.material.time.sleep"),
        ):
            results = material.generate_images_openai(
                "aurora", minimum_duration=5, save_dir=save_dir
            )

        self.assertEqual(len(results), 1)
        # Download retries hit the same URL, and no second paid generation was triggered
        self.assertEqual(post.call_count, 1)
        self.assertEqual(get.call_count, 2)
        for call in get.call_args_list:
            self.assertEqual(call.args[0], "https://cdn.example.com/generated/x.png")

    def test_generated_image_download_rejects_oversize_body(self):
        """A generated image URL must not buffer an unbounded provider body."""
        response = _download_response(b"too-large")
        response.headers = {}
        closed = []
        response.close = lambda: closed.append(True)
        with (
            patch("app.services.material.requests.get", return_value=response) as get,
            patch("app.services.material.OPENAI_IMAGE_MAX_BYTES", 5, create=True),
            patch("app.services.material.time.sleep"),
        ):
            image_bytes, error = material._openai_image_download_bytes(
                "https://cdn.example.com/generated/x.png", "test-key"
            )

        self.assertIsNone(image_bytes)
        self.assertIn("limit", error)
        self.assertTrue(all(call.kwargs.get("stream") is True for call in get.call_args_list))
        self.assertEqual(closed, [True])

    def test_generated_image_download_rejects_declared_oversize_body(self):
        """An advertised oversize image should be rejected before reading bytes."""
        response = _download_response(b"small")
        response.headers = {"Content-Length": "100"}
        response.iter_content = lambda chunk_size: self.fail("body should not be read")
        with (
            patch("app.services.material.requests.get", return_value=response),
            patch("app.services.material.OPENAI_IMAGE_MAX_BYTES", 5),
        ):
            image_bytes, error = material._openai_image_download_bytes(
                "https://cdn.example.com/generated/x.png", "test-key"
            )

        self.assertIsNone(image_bytes)
        self.assertIn("limit", error)

    def test_generated_image_response_rejects_oversize_base64(self):
        """Do not decode an unbounded inline image from a provider response."""
        response = _image_response(
            {"data": [{"b64_json": base64.b64encode(b"too-large").decode()}]}
        )
        with patch("app.services.material.OPENAI_IMAGE_MAX_BYTES", 5):
            image_bytes, error = material._parse_openai_image_response(response, "test-key")

        self.assertIsNone(image_bytes)
        self.assertIn("limit", error)

    def test_generated_image_decode_rejects_pillow_bomb_warning(self):
        """Small compressed bytes can still expand to too many image pixels."""
        image_bytes = _png_bytes(width=12, height=12)
        with (
            patch.object(Image, "MAX_IMAGE_PIXELS", 100),
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with self.assertRaises(material._OpenAIImageDecodeError):
                material._save_openai_image_file(image_bytes, self.save_dir)

        self.assertEqual(os.listdir(self.save_dir), [])

    def test_generated_image_download_failure_does_not_buy_another_image(self):
        """A confirmed paid result remains a task failure if its URL cannot download."""
        signed_url = "https://cdn.example.com/generated/x.png?token=private"
        response = _image_response(
            {"data": [{"url": signed_url}]}
        )
        with (
            patch("app.services.material.requests.post", return_value=response) as post,
            patch(
                "app.services.material.requests.get",
                side_effect=requests.exceptions.ConnectionError(
                    f"download failed for {signed_url}"
                ),
            ) as get,
            patch("app.services.material.time.sleep"),
            patch("app.services.material.logger") as logger,
        ):
            with self.assertRaisesRegex(RuntimeError, "could not be downloaded"):
                material.download_videos(
                    task_id="test-openai-image-download-failure",
                    search_terms=["first", "second"],
                    source="openai_image",
                    audio_duration=10,
                    max_clip_duration=5,
                )

        self.assertEqual(post.call_count, 1)
        self.assertEqual(get.call_count, material.OPENAI_IMAGE_MAX_DOWNLOAD_ATTEMPTS)
        self.assertNotIn("token=private", str(logger.warning.call_args_list))

    def test_generate_images_openai_returns_empty_on_rejected_request(self):
        """A business rejection (e.g. content policy) returns an empty result without backoff retries."""
        response = _image_response(
            {"error": {"message": "content policy violation"}}, status_code=400
        )

        with (
            tempfile.TemporaryDirectory() as save_dir,
            patch("app.services.material.requests.post", return_value=response) as post,
            patch("app.services.material.time.sleep") as sleep,
        ):
            results = material.generate_images_openai(
                "blocked term", minimum_duration=5, save_dir=save_dir
            )

        self.assertEqual(results, [])
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()

    # ------------------------------------------------------------------
    # Config switches
    # ------------------------------------------------------------------

    def test_is_openai_image_enabled_requires_full_configuration(self):
        """
        Both base_url and model are required; the API key may be empty — a fully local
        ComfyUI/SD gateway usually needs no auth.
        """
        self.assertTrue(material.is_openai_image_enabled())

        config.app["openai_image_base_url"] = ""
        self.assertFalse(material.is_openai_image_enabled())
        config.app["openai_image_base_url"] = "https://img.example.com/v1"

        # Local no-auth gateway: it counts as enabled even without a key
        config.app["openai_image_api_keys"] = []
        self.assertTrue(material.is_openai_image_enabled())
        config.app["openai_image_api_keys"] = ["sk-test-key"]

        config.app["openai_image_model"] = ""
        self.assertFalse(material.is_openai_image_enabled())

    def test_generate_images_openai_sends_no_authorization_without_key(self):
        """
        When no API key is configured, generation must proceed as usual and requests carry no Authorization header,
        for no-auth local ComfyUI/SD gateways.
        """
        config.app["openai_image_api_keys"] = []
        response = _image_response(
            {"data": [{"b64_json": base64.b64encode(_png_bytes()).decode("ascii")}]}
        )

        with (
            patch("app.services.material.requests.post", return_value=response) as post,
        ):
            results = material.generate_images_openai(
                "local gateway", minimum_duration=5, save_dir=self.save_dir
            )

        self.assertEqual(len(results), 1)
        self.assertNotIn("Authorization", post.call_args.kwargs["headers"])

    def test_generate_images_openai_retries_connect_timeout(self):
        """
        A connect-phase timeout means the request never reached the server, so no billed task can have been created,
        and backoff retries are allowed.
        """
        image_data = _png_bytes()
        responses = [
            requests.exceptions.ConnectTimeout("connect timed out"),
            _image_response(
                {"data": [{"b64_json": base64.b64encode(image_data).decode("ascii")}]}
            ),
        ]

        with (
            patch("app.services.material.requests.post", side_effect=responses) as post,
            patch("app.services.material.time.sleep"),
        ):
            results = material.generate_images_openai(
                "connect timeout term", minimum_duration=5, save_dir=self.save_dir
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(post.call_count, 2)

    def test_generate_images_openai_does_not_retry_unconfirmed_errors(self):
        """
        Read timeouts/dropped connections are "unconfirmed": the server may already have generated and charged, and only
        the response didn't come back. Automatic resubmission would cause duplicate generation and duplicate charges, so it must
        fail directly and stop the task, without submitting paid requests for later keywords.
        """
        for error in (
            requests.exceptions.ReadTimeout("read timed out"),
            requests.exceptions.ConnectionError("connection dropped"),
        ):
            with self.subTest(error=type(error).__name__):
                with (
                    patch(
                        "app.services.material.requests.post", side_effect=error
                    ) as post,
                    patch("app.services.material.time.sleep") as sleep,
                ):
                    with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
                        material.generate_images_openai(
                            "unconfirmed term",
                            minimum_duration=5,
                            save_dir=self.save_dir,
                        )

                self.assertEqual(post.call_count, 1)
                sleep.assert_not_called()

    def test_download_videos_openai_image_stops_after_unconfirmed_paid_request(self):
        """Earlier images must not hide a later ambiguous paid submission."""
        image_response = _image_response(
            {"data": [{"b64_json": base64.b64encode(_png_bytes()).decode("ascii")}]}
        )
        config.app["material_directory"] = self.save_dir

        with (
            patch(
                "app.services.material.requests.post",
                side_effect=[
                    image_response,
                    requests.exceptions.ReadTimeout("response lost"),
                    image_response,
                ],
            ) as post,
            patch(
                "app.services.material._render_openai_image_video",
                return_value="/tmp/rendered.mp4",
            ),
            patch("app.services.material._persist_material_sources"),
        ):
            with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
                material.download_videos(
                    task_id="test-openai-image-unconfirmed",
                    search_terms=["first", "uncertain", "third"],
                    source="openai_image",
                    audio_duration=20,
                    max_clip_duration=5,
                )

        self.assertEqual(post.call_count, 2)

    def test_generate_images_openai_size_defaults_and_override(self):
        """
        By default the official OpenAI-compatible size is chosen per aspect ratio (portrait 1024x1536 /
        landscape 1536x1024); once openai_image_size is configured it overrides completely,
        for local gateways that support arbitrary resolutions.
        """
        response = _image_response(
            {"data": [{"b64_json": base64.b64encode(_png_bytes()).decode("ascii")}]}
        )

        with patch(
            "app.services.material.requests.post", return_value=response
        ) as default_post:
            material.generate_images_openai(
                "landscape term",
                minimum_duration=5,
                video_aspect=material.VideoAspect.landscape,
                save_dir=self.save_dir,
            )
        # Landscape defaults to the official OpenAI-compatible size
        self.assertEqual(default_post.call_args.kwargs["json"]["size"], "1536x1024")

        config.app["openai_image_size"] = "1080x1920"
        self.addCleanup(config.app.pop, "openai_image_size", None)

        with patch(
            "app.services.material.requests.post", return_value=response
        ) as post:
            material.generate_images_openai(
                "custom size term", minimum_duration=5, save_dir=self.save_dir
            )

        self.assertEqual(
            post.call_args.kwargs["json"]["size"],
            "1080x1920",
        )

    def test_generate_images_openai_raises_without_base_url(self):
        """When called directly without a configured base_url, an error with config guidance must be raised."""
        config.app["openai_image_base_url"] = ""
        with self.assertRaises(ValueError):
            material.generate_images_openai("term", minimum_duration=5)

    # ------------------------------------------------------------------
    # Prompt template
    # ------------------------------------------------------------------

    def test_generate_images_openai_applies_prompt_template(self):
        """
        When a template with a {term} placeholder is configured, the request prompt must be the template substitution result,
        uniformly appending style modifiers to improve image-text relevance.
        """
        config.app["openai_image_prompt_template"] = (
            "cinematic photo of {term}, photorealistic, high detail"
        )
        response = _image_response(
            {"data": [{"b64_json": base64.b64encode(_png_bytes()).decode("ascii")}]}
        )

        with patch(
            "app.services.material.requests.post", return_value=response
        ) as post:
            material.generate_images_openai(
                "晨光中的玻璃杯", minimum_duration=5, save_dir=self.save_dir
            )

        self.assertEqual(
            post.call_args.kwargs["json"]["prompt"],
            "cinematic photo of 晨光中的玻璃杯, photorealistic, high detail",
        )

    def test_generate_images_openai_sends_raw_term_without_template(self):
        """Without a template, the prompt must be the raw keyword, behaving like older versions."""
        response = _image_response(
            {"data": [{"b64_json": base64.b64encode(_png_bytes()).decode("ascii")}]}
        )

        with patch(
            "app.services.material.requests.post", return_value=response
        ) as post:
            material.generate_images_openai(
                "raw term", minimum_duration=5, save_dir=self.save_dir
            )

        self.assertEqual(post.call_args.kwargs["json"]["prompt"], "raw term")

    def test_generate_images_openai_falls_back_when_template_lacks_placeholder(self):
        """A template without the {term} placeholder can't inject the keyword and must fall back to the raw text."""
        config.app["openai_image_prompt_template"] = "no placeholder here"
        response = _image_response(
            {"data": [{"b64_json": base64.b64encode(_png_bytes()).decode("ascii")}]}
        )

        with patch(
            "app.services.material.requests.post", return_value=response
        ) as post:
            material.generate_images_openai(
                "fallback term", minimum_duration=5, save_dir=self.save_dir
            )

        self.assertEqual(post.call_args.kwargs["json"]["prompt"], "fallback term")

    # ------------------------------------------------------------------
    # download_videos dispatch and on-demand generation
    # ------------------------------------------------------------------

    def test_download_videos_openai_image_generates_on_demand_and_stops(self):
        """
        Text-to-image is billed per image, so it can't generate for every keyword first and then choose. Materials must be generated image by image on demand,
        and once the accumulated effective duration (capped at the clip duration) reaches the required voice-over duration, later keywords
        no longer trigger any paid requests.
        """
        generated = {
            "term-1": [self._generated_item("term-1", "/tmp/img-1.png")],
            "term-2": [self._generated_item("term-2", "/tmp/img-2.png")],
            "term-3": [self._generated_item("term-3", "/tmp/img-3.png")],
        }

        def fake_generate(search_term, minimum_duration, video_aspect, save_dir=""):
            return generated[search_term]

        def fake_render(image_path, clip_duration, image_motion="zoom"):
            return f"{image_path}.mp4"

        with (
            patch(
                "app.services.material.generate_images_openai",
                side_effect=fake_generate,
            ) as generate,
            patch(
                "app.services.material._render_openai_image_video",
                side_effect=fake_render,
            ) as render,
        ):
            result = material.download_videos(
                task_id="test-openai-image-lazy",
                search_terms=["term-1", "term-2", "term-3"],
                source="openai_image",
                audio_duration=8,
                max_clip_duration=5,
            )

        # 5s + 5s > 8s, so the third keyword must not produce a paid generation request
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(
            [call.kwargs["search_term"] for call in generate.call_args_list],
            ["term-1", "term-2"],
        )
        # Each image only counts toward the duration after it's rendered into an mp4 clip
        self.assertEqual(render.call_count, 2)
        self.assertEqual(result, ["/tmp/img-1.png.mp4", "/tmp/img-2.png.mp4"])

    def test_download_videos_openai_image_continues_after_invalid_image(self):
        """
        When the first compatible API response can't be decoded, only that keyword is skipped, and a later valid image can still
        be saved and rendered, verifying the fix covers the real on-demand generation call chain and not just a single function.
        """
        invalid_response = _image_response(
            {
                "data": [
                    {
                        "b64_json": base64.b64encode(
                            b"<html>gateway degraded</html>"
                        ).decode("ascii")
                    }
                ]
            }
        )
        valid_response = _image_response(
            {
                "data": [
                    {"b64_json": base64.b64encode(_png_bytes()).decode("ascii")}
                ]
            }
        )
        config.app["material_directory"] = self.save_dir

        with (
            patch(
                "app.services.material.requests.post",
                side_effect=[invalid_response, valid_response],
            ) as post,
            patch(
                "app.services.material._render_openai_image_video",
                return_value="/tmp/rendered-openai-image.mp4",
            ) as render,
            patch("app.services.material._persist_material_sources"),
        ):
            result = material.download_videos(
                task_id="test-openai-image-invalid-then-valid",
                search_terms=["invalid term", "valid term"],
                source="openai_image",
                audio_duration=5,
                max_clip_duration=5,
            )

        self.assertEqual(post.call_count, 2)
        self.assertEqual(render.call_count, 1)
        self.assertEqual(result, ["/tmp/rendered-openai-image.mp4"])

    def test_download_videos_openai_image_stops_when_duration_exactly_covered(self):
        """Boundary regression: exactly reaching the required duration is enough, so the stop check must be >= rather than >."""
        generated = {
            "term-1": [self._generated_item("term-1", "/tmp/img-1.png")],
            "term-2": [self._generated_item("term-2", "/tmp/img-2.png")],
            "term-3": [self._generated_item("term-3", "/tmp/img-3.png")],
        }

        def fake_generate(search_term, minimum_duration, video_aspect, save_dir=""):
            return generated[search_term]

        with (
            patch(
                "app.services.material.generate_images_openai",
                side_effect=fake_generate,
            ) as generate,
            patch(
                "app.services.material._render_openai_image_video",
                return_value="/tmp/rendered.mp4",
            ),
        ):
            result = material.download_videos(
                task_id="test-openai-image-exact",
                search_terms=["term-1", "term-2", "term-3"],
                source="openai_image",
                audio_duration=10,
                max_clip_duration=5,
            )

        # 5s + 5s == 10s, exactly covered, so the 3rd clip must never be generated
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(len(result), 2)

    def test_download_videos_openai_image_bypasses_search_cache(self):
        """
        Generated results are one-off image files and skip the 24-hour search cache — the cache would make different
        tasks get the same image repeatedly. download_videos must go straight to the on-demand generation branch.
        """
        with (
            patch(
                "app.services.material.generate_images_openai",
                return_value=[self._generated_item("sunrise", "/tmp/img-1.png")],
            ) as generate,
            patch("app.services.material._search_videos_with_cache") as cached_search,
            patch(
                "app.services.material._render_openai_image_video",
                return_value="/tmp/img-1.png.mp4",
            ),
        ):
            result = material.download_videos(
                task_id="test-openai-image-cache-bypass",
                search_terms=["sunrise"],
                source="openai_image",
                audio_duration=5,
                max_clip_duration=5,
            )

        self.assertEqual(generate.call_count, 1)
        cached_search.assert_not_called()
        self.assertEqual(result, ["/tmp/img-1.png.mp4"])

    def test_download_videos_openai_image_skips_rejected_segment(self):
        """
        When an explicitly rejected generation result is empty, skip that keyword and continue with the next clip.
        """
        generated = {
            "term-1": [],  # Generation failed
            "term-2": [self._generated_item("term-2", "/tmp/img-2.png")],
            "term-3": [self._generated_item("term-3", "/tmp/img-3.png")],
        }

        def fake_generate(search_term, minimum_duration, video_aspect, save_dir=""):
            return generated[search_term]

        def fake_render(image_path, clip_duration, image_motion="zoom"):
            return f"{image_path}.mp4"

        with (
            patch(
                "app.services.material.generate_images_openai",
                side_effect=fake_generate,
            ) as generate,
            patch(
                "app.services.material._render_openai_image_video",
                side_effect=fake_render,
            ),
        ):
            result = material.download_videos(
                task_id="test-openai-image-skip",
                search_terms=["term-1", "term-2", "term-3"],
                source="openai_image",
                audio_duration=5,
                max_clip_duration=5,
            )

        self.assertEqual(generate.call_count, 2)
        self.assertEqual(result, ["/tmp/img-2.png.mp4"])

    def test_download_videos_openai_image_stops_after_render_failure(self):
        """A paid image saved locally should not trigger another purchase if render fails."""
        generated_item = self._generated_item("first", "/tmp/img-1.png")
        with (
            patch(
                "app.services.material.generate_images_openai",
                return_value=[generated_item],
            ) as generate,
            patch("app.services.material._render_openai_image_video", return_value=""),
        ):
            with self.assertRaisesRegex(RuntimeError, "could not be rendered"):
                material.download_videos(
                    task_id="test-openai-image-render-failure",
                    search_terms=["first", "second"],
                    source="openai_image",
                    audio_duration=10,
                    max_clip_duration=5,
                )

        self.assertEqual(generate.call_count, 1)

    def test_download_videos_openai_image_skips_generation_without_audio(self):
        """When the voice-over duration isn't positive, return empty-handed rather than paying per image for a task that can never be satisfied."""
        with patch("app.services.material.generate_images_openai") as generate:
            result = material.download_videos(
                task_id="test-openai-image-no-audio",
                search_terms=["term-1"],
                source="openai_image",
                audio_duration=0,
                max_clip_duration=5,
            )

        generate.assert_not_called()
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
