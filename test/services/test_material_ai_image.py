import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.models.schema import VideoAspect
from app.services import material


class TestImageProviderSetting(unittest.TestCase):
    def setUp(self):
        self._app = config.app
        config.app = {}

    def tearDown(self):
        config.app = self._app

    def test_namespaced_key_wins(self):
        config.app = {
            "openai_image_api_key": "img-key",
            "openai_api_key": "llm-key",
        }
        self.assertEqual(
            material._image_provider_setting("openai", "api_key"), "img-key"
        )

    def test_falls_back_to_shared_llm_key_for_reading(self):
        config.app = {"openai_api_key": "llm-key"}
        self.assertEqual(
            material._image_provider_setting("openai", "api_key"), "llm-key"
        )

    def test_legacy_spaced_key_fallback(self):
        config.app = {"stability ai_api_key": "legacy"}
        self.assertEqual(
            material._image_provider_setting("stability_ai", "api_key"), "legacy"
        )

    def test_model_name_never_falls_back_to_llm_chat_model(self):
        config.app = {"openai_model_name": "gpt-4o-mini"}
        self.assertEqual(material._image_provider_setting("openai", "model_name"), "")

    def test_pollinations_base_url_never_falls_back_to_text_endpoint(self):
        config.app = {"pollinations_base_url": "https://text.pollinations.ai/openai"}
        self.assertEqual(
            material._image_provider_setting("pollinations", "base_url"), ""
        )


class TestOpenaiImageSize(unittest.TestCase):
    def test_dall_e_3_uses_hd_sizes(self):
        self.assertEqual(
            material._openai_image_size("dall-e-3", VideoAspect.portrait), (1024, 1792)
        )
        self.assertEqual(
            material._openai_image_size("dall-e-3", VideoAspect.landscape),
            (1792, 1024),
        )

    def test_dall_e_2_only_supports_squares(self):
        self.assertEqual(
            material._openai_image_size("dall-e-2", VideoAspect.portrait), (1024, 1024)
        )

    def test_gpt_image_sizes(self):
        self.assertEqual(
            material._openai_image_size("gpt-image-1", VideoAspect.portrait),
            (1024, 1536),
        )
        self.assertEqual(
            material._openai_image_size("gpt-image-1", VideoAspect.landscape),
            (1536, 1024),
        )

    def test_square_aspect(self):
        self.assertEqual(
            material._openai_image_size("dall-e-3", VideoAspect.square), (1024, 1024)
        )


class TestPollinationsRequest(unittest.TestCase):
    def test_prompt_slashes_are_percent_encoded(self):
        with mock.patch.object(material, "requests") as requests_mock:
            response = mock.Mock()
            response.content = b"png-bytes"
            requests_mock.get.return_value = response
            material._generate_image_pollinations(
                "black/white cat ../admin", "", "", "", 64, 64
            )
        url = requests_mock.get.call_args[0][0]
        self.assertNotIn("/black", url.replace("/prompt/", "", 1).replace("https://image.pollinations.ai", ""))
        self.assertIn("black%2Fwhite%20cat%20..%2Fadmin", url)


class TestGenerateAiImagesInputs(unittest.TestCase):
    def test_caller_prompt_list_is_not_mutated_by_random_mode(self):
        terms = [f"term-{i}" for i in range(20)]
        original = list(terms)
        with mock.patch.object(
            config, "app", {"image_provider": "pollinations"}
        ), mock.patch.object(
            material, "_generate_image_pollinations", return_value=b"png"
        ), mock.patch.object(
            material.Image, "open"
        ), mock.patch.object(
            material, "convert_image_to_video", return_value="clip.mp4"
        ), mock.patch.object(
            material.utils, "task_dir", return_value="/tmp"
        ), mock.patch.object(
            material.os, "makedirs"
        ), mock.patch(
            "builtins.open", mock.mock_open()
        ):
            result = material.generate_ai_images(
                task_id="t", prompt=terms, audio_duration=1.0
            )
        self.assertTrue(result)
        self.assertEqual(terms, original)


if __name__ == "__main__":
    unittest.main()
