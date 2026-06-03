import json
from pathlib import Path
import unittest

from app.models.schema import VideoParams


class TestSubtitleBackgroundSettings(unittest.TestCase):
    def test_all_locales_include_subtitle_background_labels(self):
        """
        WebUI 新增字幕背景开关和颜色选择器后，所有已有语言都必须包含对应
        翻译 key，避免某些语言界面直接显示英文内部 key。
        """
        i18n_dir = Path(__file__).parent.parent.parent / "webui" / "i18n"
        required_keys = {
            "Enable Subtitle Background",
            "Subtitle Background Color",
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
        UI 会根据开关向后端传递 False 或颜色字符串。这里验证 schema 仍然
        接受这两种值，避免后续依赖或类型调整破坏 WebUI 与合成逻辑的契约。
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
