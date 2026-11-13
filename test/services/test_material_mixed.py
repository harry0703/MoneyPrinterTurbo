# -*- coding: utf-8 -*-
"""
``video_source = "mixed"``: per-term choice between free Pixabay footage and
the configured OpenAI-compatible image API (e.g. Google Gemini).

Mirrors the mocking style already used for the plain "openai_image" and
"pexels"/"pixabay" sources in this test package: network calls, the 24h
search cache, and task-artifact persistence are all replaced with
``unittest.mock`` so these tests need no real network access, API key, or
billing.
"""
import unittest
from unittest.mock import patch

import pydantic

from app.config import config
from app.models.schema import VideoParams
from app.services import material


class TestAssignMixedSources(unittest.TestCase):
    """Pure unit tests for the per-term source assignment, no mocking needed."""

    def test_ratio_splits_api_and_pixabay_by_count(self):
        terms = ["one", "two", "three", "four"]
        assignments = material._assign_mixed_sources(terms, 0.5, "ratio")
        self.assertEqual(len(assignments), 4)
        self.assertEqual(assignments.count("api"), 2)
        self.assertEqual(assignments.count("pixabay"), 2)

    def test_ratio_spreads_api_slots_across_the_timeline(self):
        # 8 关键词 ratio=0.25 应该得到 2 个 API term，且不能挤在最前面——
        # 否则脚本靠后的内容永远用不上生成图片。
        terms = [f"term-{index}" for index in range(8)]
        assignments = material._assign_mixed_sources(terms, 0.25, "ratio")
        self.assertEqual(assignments.count("api"), 2)
        api_indices = [i for i, choice in enumerate(assignments) if choice == "api"]
        self.assertNotEqual(api_indices, [0, 1])

    def test_ratio_zero_is_all_pixabay(self):
        terms = ["a", "b", "c"]
        assignments = material._assign_mixed_sources(terms, 0.0, "ratio")
        self.assertEqual(assignments, ["pixabay", "pixabay", "pixabay"])

    def test_ratio_one_is_all_api(self):
        terms = ["a", "b", "c"]
        assignments = material._assign_mixed_sources(terms, 1.0, "ratio")
        self.assertEqual(assignments, ["api", "api", "api"])

    def test_alternate_strategy_ignores_ratio(self):
        terms = ["one", "two", "three", "four"]
        assignments = material._assign_mixed_sources(terms, 0.0, "alternate")
        self.assertEqual(assignments, ["api", "pixabay", "api", "pixabay"])

    def test_prompt_based_routes_abstract_and_concrete_terms(self):
        terms = ["freedom", "shipyard", "legacy", "tank"]
        assignments = material._assign_mixed_sources(terms, 0.5, "prompt_based")
        self.assertEqual(assignments, ["api", "pixabay", "api", "pixabay"])

    def test_prompt_based_falls_back_to_alternate_for_unmatched_terms(self):
        terms = ["something", "else", "entirely", "unrelated"]
        assignments = material._assign_mixed_sources(terms, 0.5, "prompt_based")
        self.assertEqual(assignments, ["api", "pixabay", "api", "pixabay"])

    def test_empty_terms_returns_empty_assignment(self):
        self.assertEqual(material._assign_mixed_sources([], 0.5, "ratio"), [])


class TestVideoParamsMixedValidation(unittest.TestCase):
    """``source_mix_ratio``/``source_mix_strategy`` validation on VideoParams."""

    def test_defaults(self):
        params = VideoParams(video_subject="test")
        self.assertEqual(params.source_mix_ratio, 0.5)
        self.assertEqual(params.source_mix_strategy, "ratio")

    def test_ratio_out_of_range_is_rejected(self):
        with self.assertRaises(pydantic.ValidationError):
            VideoParams(video_subject="test", source_mix_ratio=1.5)
        with self.assertRaises(pydantic.ValidationError):
            VideoParams(video_subject="test", source_mix_ratio=-0.1)

    def test_unknown_strategy_is_rejected(self):
        with self.assertRaises(pydantic.ValidationError):
            VideoParams(video_subject="test", source_mix_strategy="random_guess")

    def test_valid_strategies_are_accepted(self):
        for strategy in ("ratio", "alternate", "prompt_based"):
            params = VideoParams(video_subject="test", source_mix_strategy=strategy)
            self.assertEqual(params.source_mix_strategy, strategy)


class TestDownloadVideosMixed(unittest.TestCase):
    """End-to-end ``download_videos(source="mixed")`` wiring, fully mocked."""

    def setUp(self):
        self.original_app_config = dict(config.app)
        config.app["openai_image_base_url"] = "https://img.example.com/v1"
        config.app["openai_image_api_keys"] = ["sk-test-key"]
        config.app["openai_image_model"] = "test-image-model"
        config.app["material_directory"] = ""

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def _pixabay_item(self, term):
        item = material.MaterialInfo()
        item.provider = "pixabay"
        item.url = f"https://pixabay.example/{term}.mp4"
        item.duration = 5
        item.source_info = {
            "provider": "pixabay",
            "search_term": term,
            "asset_id": term,
        }
        return item

    def _generated_item(self, term):
        item = material.MaterialInfo()
        item.provider = "openai_image"
        item.url = f"/tmp/generated-{term}.png"
        item.duration = 5
        item.source_info = {
            "provider": "openai_image",
            "search_term": term,
            "rendition": {"id": None, "width": 1024, "height": 1024},
        }
        return item

    def test_mixed_source_calls_both_providers_by_ratio(self):
        terms = ["one", "two", "three", "four"]

        def fake_generate_images_openai(search_term, **kwargs):
            return [self._generated_item(search_term)]

        def fake_search_videos_pixabay(search_term, minimum_duration, video_aspect):
            return [self._pixabay_item(search_term)]

        def fake_save_video(video_url, save_dir=""):
            return f"/tmp/{video_url.rsplit('/', 1)[-1]}"

        with (
            patch.object(
                material,
                "generate_images_openai",
                side_effect=fake_generate_images_openai,
            ) as generate_mock,
            patch.object(
                material,
                "search_videos_pixabay",
                side_effect=fake_search_videos_pixabay,
            ) as search_mock,
            patch.object(material, "save_video", side_effect=fake_save_video),
            patch.object(
                material,
                "_render_openai_image_video",
                return_value="/tmp/rendered.mp4",
            ),
            patch.object(
                material.material_cache,
                "load_material_search_cache",
                return_value=None,
            ),
            patch.object(material.material_cache, "save_material_search_cache"),
            patch.object(
                material.task_artifacts, "patch_script_data", return_value=True
            ),
        ):
            result = material.download_videos(
                task_id="mixed-ratio",
                search_terms=terms,
                source="mixed",
                audio_duration=20,
                max_clip_duration=5,
                source_mix_ratio=0.5,
                source_mix_strategy="ratio",
            )

        # 4 个关键词、ratio=0.5 应该各产出 2 个片段，总共 4 段覆盖 20 秒配音。
        self.assertEqual(generate_mock.call_count, 2)
        self.assertEqual(search_mock.call_count, 2)
        self.assertEqual(len(result), 4)

    def test_mixed_source_alternate_strategy_keeps_script_order(self):
        terms = ["alpha", "beta", "gamma", "delta"]
        call_order = []

        def fake_generate_images_openai(search_term, **kwargs):
            call_order.append(("api", search_term))
            return [self._generated_item(search_term)]

        def fake_search_videos_pixabay(search_term, minimum_duration, video_aspect):
            call_order.append(("pixabay", search_term))
            return [self._pixabay_item(search_term)]

        def fake_save_video(video_url, save_dir=""):
            return f"/tmp/{video_url.rsplit('/', 1)[-1]}"

        with (
            patch.object(
                material,
                "generate_images_openai",
                side_effect=fake_generate_images_openai,
            ),
            patch.object(
                material,
                "search_videos_pixabay",
                side_effect=fake_search_videos_pixabay,
            ),
            patch.object(material, "save_video", side_effect=fake_save_video),
            patch.object(
                material,
                "_render_openai_image_video",
                return_value="/tmp/rendered.mp4",
            ),
            patch.object(
                material.material_cache,
                "load_material_search_cache",
                return_value=None,
            ),
            patch.object(material.material_cache, "save_material_search_cache"),
            patch.object(
                material.task_artifacts, "patch_script_data", return_value=True
            ),
        ):
            material.download_videos(
                task_id="mixed-alternate",
                search_terms=terms,
                source="mixed",
                audio_duration=20,
                max_clip_duration=5,
                source_mix_ratio=0.5,
                source_mix_strategy="alternate",
            )

        self.assertEqual(
            call_order,
            [
                ("api", "alpha"),
                ("pixabay", "beta"),
                ("api", "gamma"),
                ("pixabay", "delta"),
            ],
        )

    def test_mixed_source_stops_once_required_duration_is_covered(self):
        terms = ["one", "two", "three", "four"]

        def fake_generate_images_openai(search_term, **kwargs):
            return [self._generated_item(search_term)]

        def fake_search_videos_pixabay(search_term, minimum_duration, video_aspect):
            return [self._pixabay_item(search_term)]

        def fake_save_video(video_url, save_dir=""):
            return f"/tmp/{video_url.rsplit('/', 1)[-1]}"

        with (
            patch.object(
                material,
                "generate_images_openai",
                side_effect=fake_generate_images_openai,
            ) as generate_mock,
            patch.object(
                material,
                "search_videos_pixabay",
                side_effect=fake_search_videos_pixabay,
            ) as search_mock,
            patch.object(material, "save_video", side_effect=fake_save_video),
            patch.object(
                material,
                "_render_openai_image_video",
                return_value="/tmp/rendered.mp4",
            ),
            patch.object(
                material.material_cache,
                "load_material_search_cache",
                return_value=None,
            ),
            patch.object(material.material_cache, "save_material_search_cache"),
            patch.object(
                material.task_artifacts, "patch_script_data", return_value=True
            ),
        ):
            # 每段 5 秒，只需要 10 秒配音：按 alternate 顺序，第 2 段
            # (pixabay) 结束后就该停止，不应该再付费生成第 3 张图片。
            result = material.download_videos(
                task_id="mixed-stop-early",
                search_terms=terms,
                source="mixed",
                audio_duration=10,
                max_clip_duration=5,
                source_mix_ratio=0.5,
                source_mix_strategy="alternate",
            )

        self.assertEqual(len(result), 2)
        self.assertEqual(generate_mock.call_count, 1)
        self.assertEqual(search_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
