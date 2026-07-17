import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image as PILImage

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.models.schema import VideoParams, VideoAspect
from app.services import material
from app.services import state as sm
from app.services import task as task_service
from app.models import const


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


class TestEnhancePromptWithLlm(unittest.TestCase):
    def test_error_response_falls_back_to_original_prompt(self):
        with mock.patch("app.services.llm._generate_response", return_value="Error: quota exceeded"):
            self.assertEqual(material.enhance_prompt_with_llm("a cat"), "a cat")

    def test_empty_response_falls_back_to_original_prompt(self):
        with mock.patch("app.services.llm._generate_response", return_value="   "):
            self.assertEqual(material.enhance_prompt_with_llm("a cat"), "a cat")

    def test_exception_falls_back_to_original_prompt(self):
        with mock.patch(
            "app.services.llm._generate_response", side_effect=RuntimeError("down")
        ):
            self.assertEqual(material.enhance_prompt_with_llm("a cat"), "a cat")

    def test_successful_response_is_used(self):
        with mock.patch(
            "app.services.llm._generate_response",
            return_value="a majestic cat at golden hour",
        ):
            self.assertEqual(
                material.enhance_prompt_with_llm("a cat", "script context"),
                "a majestic cat at golden hour",
            )


class TestGenerateAiImagesGuards(unittest.TestCase):
    def _run(self, app):
        with mock.patch.object(config, "app", app), mock.patch.object(
            material.utils, "task_dir", return_value=tempfile.mkdtemp()
        ):
            return material.generate_ai_images(task_id="t", prompt=["x"])

    def test_unknown_provider_is_rejected(self):
        self.assertEqual(self._run({"image_provider": "stability-ai"}), [])

    def test_openai_without_any_key_is_rejected(self):
        self.assertEqual(self._run({"image_provider": "openai"}), [])

    def test_stability_without_key_is_rejected(self):
        self.assertEqual(self._run({"image_provider": "stability_ai"}), [])

    def test_midjourney_without_base_url_is_rejected(self):
        self.assertEqual(self._run({"image_provider": "midjourney"}), [])


class TestConvertImageToVideo(unittest.TestCase):
    def test_every_effect_renders_a_clip(self):
        tmpdir = tempfile.mkdtemp()
        for effect in material.ZoomEffect:
            with self.subTest(effect=effect):
                image_path = os.path.join(tmpdir, f"{effect.name}.png")
                PILImage.new("RGB", (64, 64), (200, 30, 30)).save(image_path)
                video_path = material.convert_image_to_video(
                    image_path=image_path, video_duration=1, effect=effect
                )
                self.assertTrue(video_path.endswith(".mp4"))
                self.assertGreater(os.path.getsize(video_path), 0)

    def test_unreadable_image_returns_empty_string(self):
        self.assertEqual(
            material.convert_image_to_video(image_path="/nonexistent.png"), ""
        )


class TestGenerateAiImagesPipeline(unittest.TestCase):
    @staticmethod
    def _png_bytes():
        buf = io.BytesIO()
        PILImage.new("RGB", (64, 64), (10, 120, 240)).save(buf, format="PNG")
        return buf.getvalue()

    def test_pollinations_pipeline_creates_video_and_stops_at_duration(self):
        tmpdir = tempfile.mkdtemp()
        app = {"image_provider": "pollinations", "material_directory": tmpdir}
        with mock.patch.object(config, "app", app), mock.patch.object(
            material, "_generate_image_pollinations", return_value=self._png_bytes()
        ) as generate:
            videos = material.generate_ai_images(
                task_id="t",
                prompt=["sunset", "ocean", "forest"],
                max_clip_duration=1,
                audio_duration=0.5,
            )
        self.assertEqual(len(videos), 1)
        self.assertTrue(os.path.isfile(videos[0]))
        generate.assert_called_once()

    def test_non_image_bytes_exhaust_retries_and_return_empty(self):
        tmpdir = tempfile.mkdtemp()
        app = {"image_provider": "pollinations", "material_directory": tmpdir}
        with mock.patch.object(config, "app", app), mock.patch.object(
            material, "_generate_image_pollinations", return_value=b"<html>rate limited</html>"
        ) as generate, mock.patch.object(material.time, "sleep") as sleep:
            videos = material.generate_ai_images(
                task_id="t", prompt=["sunset"], audio_duration=1.0
            )
        self.assertEqual(videos, [])
        self.assertEqual(generate.call_count, 3)
        self.assertTrue(sleep.called)


class TestGetVideoMaterialsAiImage(unittest.TestCase):
    def _params(self):
        params = VideoParams(video_subject="test subject")
        params.video_source = "ai_image"
        params.video_script = "a short script"
        return params

    def test_success_returns_generated_paths(self):
        with mock.patch.object(
            task_service.material, "generate_ai_images", return_value=["/tmp/clip.mp4"]
        ):
            result = task_service.get_video_materials(
                "task-ai-ok", self._params(), ["term"], audio_duration=10
            )
        self.assertEqual(result, ["/tmp/clip.mp4"])

    def test_failure_records_error_and_stage(self):
        task_id = "task-ai-fail"
        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=50)
        with mock.patch.object(
            task_service.material, "generate_ai_images", return_value=[]
        ):
            result = task_service.get_video_materials(
                task_id, self._params(), ["term"], audio_duration=10
            )
        self.assertIsNone(result)
        failed = sm.state.get_task(task_id)
        self.assertEqual(failed["state"], const.TASK_STATE_FAILED)
        self.assertEqual(failed["failed_stage"], "materials")
        self.assertIn("failed to generate AI images", failed["error"])
        self.assertEqual(failed["progress"], 50)


if __name__ == "__main__":
    unittest.main()
