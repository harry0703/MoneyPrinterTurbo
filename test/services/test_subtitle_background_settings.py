import json
from pathlib import Path
import unittest

import numpy as np

from app.models.schema import SubtitleRequest, VideoParams
from app.services import video


class TestSubtitleBackgroundSettings(unittest.TestCase):
    def test_subtitle_background_is_disabled_by_default(self):
        """새 작업과 독립 자막 엔드포인트 모두, 사용자가 지정하지 않으면 자막 배경을 그려서는 안 된다."""
        video_params = VideoParams(video_subject="default subtitle background")
        subtitle_request = SubtitleRequest(video_script="default subtitle background")

        self.assertFalse(video_params.text_background_color)
        self.assertFalse(subtitle_request.text_background_color)

    def test_all_locales_include_subtitle_background_labels(self):
        """
        WebUI 에 자막 배경 스위치와 색상 선택기를 추가한 뒤에는 기존 모든 언어가 해당 번역 key 를
        갖고 있어야 한다. 일부 언어 화면에 영어 내부 key 가 그대로 보이는 것을 막기 위해서다.
        """
        i18n_dir = Path(__file__).parent.parent.parent / "webui" / "i18n"
        required_keys = {
            "Enable Subtitle Background",
            "Subtitle Background Color",
            "Subtitle Colors Are Indistinguishable",
            "Subtitle Font Does Not Support Text",
            "No Voice",
        }

        for locale_file in i18n_dir.glob("*.json"):
            with self.subTest(locale=locale_file.name):
                data = json.loads(locale_file.read_text(encoding="utf-8"))
                translations = data.get("Translation", {})
                missing_keys = required_keys - translations.keys()

                self.assertEqual(missing_keys, set())

    def test_video_params_accepts_disabled_and_colored_subtitle_background(self):
        """
        UI 는 스위치에 따라 백엔드에 False 또는 색상 문자열을 넘긴다. 여기서는 schema 가 두 값을 모두
        받아들이는지 검증해, 이후 의존성이나 타입 변경이 WebUI 와 합성 로직의 계약을 깨지 않게 한다.
        """
        base_params = {
            "video_subject": "subtitle background smoke",
        }

        disabled_params = VideoParams(
            **base_params,
            text_background_color=False,
        )
        colored_params = VideoParams(
            **base_params,
            text_background_color="#123456",
        )

        self.assertFalse(disabled_params.text_background_color)
        self.assertEqual(colored_params.text_background_color, "#123456")

    def test_visible_text_position_centers_actual_mask_bounds(self):
        """
        TextClip 의 캔버스에는 글꼴 행 높이와 baseline 여백이 들어 있어, 캔버스를 그대로 가운데 두면
        자막이 배경 안에서 아래로 치우쳐 보인다. 여기서는 가짜 mask 로 '보이는 글자 픽셀이 캔버스
        아래쪽 절반에 있는' 상황을 흉내 내, helper 가 실제로 보이는 영역 기준으로 y 를 다시 계산하는지 검증한다.
        """

        class FakeMask:
            def get_frame(self, _):
                mask = np.zeros((46, 100), dtype=float)
                mask[12:46, 10:90] = 1.0
                return mask

        class FakeTextClip:
            w = 100
            h = 46
            mask = FakeMask()

        x, y = video._get_visible_center_position(
            FakeTextClip(), container_width=100, container_height=93
        )

        self.assertEqual(x, 0)
        # 보이는 픽셀 높이가 34px 이므로 93px 컨테이너에서는 위아래로 각각 약 29px 이 남는다.
        # mask 의 위쪽이 12px 부터 시작하므로 TextClip 자체는 18px 위로 올라가야 한다.
        self.assertEqual(y, 18)

    def test_detects_indistinguishable_subtitle_colors(self):
        invisible_params = VideoParams(
            video_subject="subtitle color validation",
            text_fore_color="#000000",
            text_background_color="#000000",
            stroke_color="#000000",
            stroke_width=1.5,
        )
        different_outline_params = VideoParams(
            video_subject="subtitle color validation",
            text_fore_color="#000000",
            text_background_color="#000000",
            stroke_color="#FFFFFF",
            stroke_width=1.5,
        )
        background_disabled_params = VideoParams(
            video_subject="subtitle color validation",
            text_fore_color="#000000",
            text_background_color=False,
            stroke_color="#000000",
            stroke_width=1.5,
        )

        self.assertTrue(
            video.subtitle_colors_are_indistinguishable(invisible_params)
        )
        self.assertTrue(
            video.subtitle_colors_are_indistinguishable(different_outline_params)
        )
        self.assertFalse(
            video.subtitle_colors_are_indistinguishable(background_disabled_params)
        )

    def test_detects_font_without_chinese_glyphs(self):
        fonts_dir = (
            Path(__file__).parent.parent.parent / "resource" / "fonts"
        )

        self.assertFalse(
            video.subtitle_font_supports_text(
                # 글꼴에 CJK 글리프가 없다는 것을 검증하는 값이라 CJK 샘플을 유지한다.
                str(fonts_dir / "BeVietnamPro-Bold.ttf"), "人工智能改变生活"
            )
        )
        self.assertTrue(
            video.subtitle_font_supports_text(
                str(fonts_dir / "MicrosoftYaHeiBold.ttc"), "人工智能改变生活"
            )
        )
        self.assertTrue(
            video.subtitle_font_supports_text(
                str(fonts_dir / "BeVietnamPro-Bold.ttf"), "Artificial intelligence"
            )
        )

    def test_wrap_text_keeps_closing_punctuation_with_text(self):
        """
        공백 없는 CJK 장문을 글자 단위로 나눌 때, 마침표 같은 닫는 부호가 한 줄을 혼자 차지해서는 안 된다.
        그러면 자막 배경이 점 하나 때문에 높아진다. 여기서는 큰 글자의 CJK 장문 경계 상황을 재현한다.
        """
        font_path = (
            Path(__file__).parent.parent.parent
            / "resource"
            / "fonts"
            / "MicrosoftYaHeiBold.ttc"
        )

        wrapped_text, _ = video.wrap_text(
            # 아래 문장도 CJK 줄바꿈 동작 자체가 검증 대상이라 원문을 유지한다.
            "如果你调整字号，中文笔画也不能被黑色背景遮挡。",
            max_width=1642,
            font=str(font_path),
            fontsize=72,
        )

        self.assertNotIn("\n。", wrapped_text)
        self.assertIn("挡。", wrapped_text)
