import unittest
from unittest.mock import patch

from app.controllers.v1 import llm as llm_controller
from app.models.schema import (
    RollSubjectRequest,
    VideoScriptRequest,
    VideoSocialMetadataRequest,
    VideoTermsRequest,
)


class TestLlmController(unittest.TestCase):
    def test_roll_next_subject_uses_history_and_mode(self):
        body = RollSubjectRequest(
            video_subject="Coffee",
            video_language="en-US",
            based_on_recent=False,
        )

        with (
            patch.object(
                llm_controller.tm,
                "collect_subject_history",
                return_value=(['Coffee history'], ['Coffee history', 'Tea history']),
            ),
            patch.object(
                llm_controller.llm,
                "generate_next_video_subject",
                return_value="A random astronomy topic",
            ) as generate,
        ):
            response = llm_controller.roll_next_subject(None, body)

        self.assertEqual(
            response,
            {
                "status": 200,
                "data": {
                    "video_subject": "A random astronomy topic",
                    "based_on_recent": False,
                },
            },
        )
        generate.assert_called_once_with(
            video_subject="Coffee",
            recent_subjects=["Coffee history"],
            language="en-US",
            based_on_recent=False,
            excluded_subjects=["Coffee history", "Tea history"],
        )

    def test_generate_video_script_forwards_all_prompt_fields(self):
        """文案接口不能丢失高级提示词或段落数量。"""
        body = VideoScriptRequest(
            video_subject="Coffee",
            video_language="en",
            paragraph_number=2,
            video_script_prompt="Friendly tone",
            custom_system_prompt="Return narration only.",
        )

        with patch.object(
            llm_controller.llm,
            "generate_script",
            return_value="Generated script",
        ) as generate:
            response = llm_controller.generate_video_script(None, body)

        self.assertEqual(
            response,
            {"status": 200, "data": {"video_script": "Generated script"}},
        )
        generate.assert_called_once_with(
            video_subject="Coffee",
            language="en",
            paragraph_number=2,
            video_script_prompt="Friendly tone",
            custom_system_prompt="Return narration only.",
        )

    def test_generate_video_terms_forwards_order_matching_mode(self):
        """素材顺序匹配开关必须继续传递到关键词生成服务。"""
        body = VideoTermsRequest(
            video_subject="Coffee",
            video_script="First beans, then brewing.",
            amount=4,
            match_materials_to_script=True,
        )

        with patch.object(
            llm_controller.llm,
            "generate_terms",
            return_value=["beans", "brewing"],
        ) as generate:
            response = llm_controller.generate_video_terms(None, body)

        self.assertEqual(
            response,
            {"status": 200, "data": {"video_terms": ["beans", "brewing"]}},
        )
        generate.assert_called_once_with(
            video_subject="Coffee",
            video_script="First beans, then brewing.",
            amount=4,
            match_script_order=True,
        )

    def test_generate_social_metadata_returns_service_payload(self):
        """社交平台元数据接口应保持服务层结果的响应结构。"""
        body = VideoSocialMetadataRequest(
            video_subject="Coffee",
            video_script="Morning coffee.",
            language="en",
            platform="youtube_shorts",
        )
        metadata = {
            "title": "Morning Coffee",
            "caption": "Start the day.",
            "hashtags": ["#coffee"],
        }

        with patch.object(
            llm_controller.llm,
            "generate_social_metadata",
            return_value=metadata,
        ) as generate:
            response = llm_controller.generate_video_social_metadata(None, body)

        self.assertEqual(response, {"status": 200, "data": metadata})
        generate.assert_called_once_with(
            video_subject="Coffee",
            video_script="Morning coffee.",
            language="en",
            platform="youtube_shorts",
        )


if __name__ == "__main__":
    unittest.main()
