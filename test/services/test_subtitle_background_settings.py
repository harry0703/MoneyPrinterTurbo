import json
from pathlib import Path
import unittest

import numpy as np

from app.models.schema import SubtitleRequest, VideoParams
from app.services import video


class TestSubtitleBackgroundSettings(unittest.TestCase):
    def test_subtitle_background_is_disabled_by_default(self):
        """Neither new tasks nor the standalone subtitle endpoint should render a subtitle background unless the user asks for one."""
        video_params = VideoParams(video_subject="default subtitle background")
        subtitle_request = SubtitleRequest(video_script="default subtitle background")

        self.assertFalse(video_params.text_background_color)
        self.assertFalse(subtitle_request.text_background_color)

    def test_all_locales_include_subtitle_background_labels(self):
        """
        After the WebUI added the subtitle-background toggle and color picker, every existing
        language must carry the new translation keys so no UI shows raw English internal keys.
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
        The UI sends either False or a color string to the backend via the toggle. Verify the
        schema keeps accepting both values so later dependency or type changes never break the
        WebUI-to-composition contract.
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
        A TextClip's canvas includes font line-height and baseline whitespace; centering the canvas
        directly makes subtitles look too low in the background. Use a fake mask simulating
        "visible text pixels in the lower half" and verify the helper recomputes y from the actually
        visible region.
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
        # The visible pixel height is 34px inside a 93px container, leaving about 29px top and bottom;
        # since the mask starts 12px from the top, the TextClip itself must move up to 18px.
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
        When long Chinese sentences wrap by character, closing punctuation like a period must not
        occupy its own line, or the subtitle background gets stretched by a lone dot. Reproduce
        this edge case with a long sentence at large font size.
        """
        font_path = (
            Path(__file__).parent.parent.parent
            / "resource"
            / "fonts"
            / "MicrosoftYaHeiBold.ttc"
        )

        wrapped_text, _ = video.wrap_text(
            "如果你调整字号，中文笔画也不能被黑色背景遮挡。",
            max_width=1642,
            font=str(font_path),
            fontsize=72,
        )

        self.assertNotIn("\n。", wrapped_text)
        self.assertIn("挡。", wrapped_text)
