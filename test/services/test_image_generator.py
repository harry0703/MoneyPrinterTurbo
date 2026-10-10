# -*- coding: utf-8 -*-
import base64
import io
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from app.config import config
from app.services import image as image_service


def _png_bytes(width=64, height=64, color=(200, 100, 50)):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _image_response(payload, status_code=200):
    return SimpleNamespace(json=lambda: payload, status_code=status_code)


class TestImageGeneratorService(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.original_proxy_config = dict(config.proxy)
        self.save_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.save_dir, ignore_errors=True)

        config.app["openai_image_base_url"] = "https://ai.example.com/v1"
        config.app["openai_image_api_keys"] = ["sk-test-key-123"]
        config.app["openai_image_model"] = "dall-e-3"
        config.app["openai_image_size"] = "1024x1024"
        config.app.pop("openai_image_prompt_template", None)
        config.proxy.clear()

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        config.proxy.clear()
        config.proxy.update(self.original_proxy_config)

    def test_is_image_service_configured(self):
        self.assertTrue(image_service.is_image_service_configured())
        config.app["openai_image_base_url"] = ""
        self.assertFalse(image_service.is_image_service_configured())

    def test_format_image_prompt(self):
        prompt = "a cute red panda"
        self.assertEqual(image_service.format_image_prompt(prompt), "a cute red panda")

        formatted = image_service.format_image_prompt(prompt, "photo of {prompt}, 4k")
        self.assertEqual(formatted, "photo of a cute red panda, 4k")

        formatted_term = image_service.format_image_prompt(prompt, "cinematic {term}")
        self.assertEqual(formatted_term, "cinematic a cute red panda")

    def test_generate_images_b64(self):
        img_bytes = _png_bytes(width=100, height=100)
        b64_str = base64.b64encode(img_bytes).decode("ascii")
        mock_resp = _image_response({"data": [{"b64_json": b64_str}]})

        with patch("app.services.image.requests.post", return_value=mock_resp):
            results = image_service.generate_images(
                prompt="futuristic city",
                save_dir=self.save_dir,
            )

        self.assertEqual(len(results), 1)
        self.assertTrue(os.path.isfile(results[0]["path"]))
        self.assertEqual(results[0]["width"], 100)
        self.assertEqual(results[0]["height"], 100)
        self.assertEqual(results[0]["prompt"], "futuristic city")

    def test_generate_multiple_images(self):
        img1 = _png_bytes(width=80, height=80)
        img2 = _png_bytes(width=90, height=90)
        b64_1 = base64.b64encode(img1).decode("ascii")
        b64_2 = base64.b64encode(img2).decode("ascii")
        mock_resp1 = _image_response({"data": [{"b64_json": b64_1}]})
        mock_resp2 = _image_response({"data": [{"b64_json": b64_2}]})

        with patch("app.services.image.requests.post", side_effect=[mock_resp1, mock_resp2]) as mock_post:
            results = image_service.generate_images(
                prompt="two cats playing",
                n=2,
                save_dir=self.save_dir,
            )

        self.assertEqual(len(results), 2)
        self.assertEqual(mock_post.call_count, 2)
        self.assertTrue(os.path.isfile(results[0]["path"]))
        self.assertTrue(os.path.isfile(results[1]["path"]))

    def test_generate_images_missing_config(self):
        config.app["openai_image_base_url"] = ""
        with self.assertRaises(ValueError):
            image_service.generate_images("test prompt", save_dir=self.save_dir)

    def test_generate_with_reference_image(self):
        sample_bytes = _png_bytes(width=64, height=64)
        out_bytes = _png_bytes(width=120, height=120)
        b64_out = base64.b64encode(out_bytes).decode("ascii")
        mock_vision_resp = SimpleNamespace(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": "detailed blueprint layout"}}]},
            text="",
        )
        mock_img_resp = _image_response({"data": [{"b64_json": b64_out}]})

        with patch("app.services.image.requests.post", side_effect=[mock_vision_resp, mock_img_resp]) as mock_post:
            results = image_service.generate_images(
                prompt="anime girl style",
                n=1,
                save_dir=self.save_dir,
                reference_image_bytes=sample_bytes,
            )

        self.assertEqual(len(results), 1)
        self.assertTrue(os.path.isfile(results[0]["path"]))
        self.assertEqual(mock_post.call_count, 2)
        gen_call = mock_post.call_args_list[1][1]
        self.assertEqual(gen_call["json"]["model"], "dall-e-3")
        self.assertIn("detailed blueprint layout", gen_call["json"]["prompt"])

    def test_list_saved_images(self):
        img_bytes = _png_bytes(width=50, height=50)
        image_service.save_image_bytes(img_bytes, save_dir=self.save_dir, prefix="test1")
        image_service.save_image_bytes(img_bytes, save_dir=self.save_dir, prefix="test2")

        saved = image_service.list_saved_images(save_dir=self.save_dir)
        self.assertEqual(len(saved), 2)
        self.assertTrue(os.path.isfile(saved[0]["path"]))
