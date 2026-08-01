import unittest
from unittest.mock import patch

from app.controllers.v1 import llm as llm_controller
from app.models.schema import (
    VideoScriptRequest,
    VideoSocialMetadataRequest,
    VideoTermsRequest,
)


class TestLlmController(unittest.TestCase):
    def test_generate_video_script_forwards_all_prompt_fields(self):
        """대본 엔드포인트는 고급 프롬프트나 문단 수를 잃어버려서는 안 된다."""
        body = VideoScriptRequest(
            video_subject="Coffee",
            video_language="en",
            paragraph_number=2,
            video_script_prompt="Friendly tone",
            custom_system_prompt="Return narration only.",
            script_style="story",
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
            script_style="story",
        )

    def test_generate_video_terms_forwards_order_matching_mode(self):
        """소재 순서 매칭 스위치는 키워드 생성 서비스까지 계속 전달돼야 한다."""
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
        """소셜 플랫폼 메타데이터 엔드포인트는 서비스 계층 결과의 응답 구조를 유지해야 한다."""
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
