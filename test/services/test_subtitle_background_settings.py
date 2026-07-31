import ast
import json
import os
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


# WebUI 의 글꼴 목록(webui/Main.py get_all_fonts)과 CLI 검증(cli.py)이 받아들이는
# 확장자. .otf 는 양쪽 모두 걸러 내므로, 넣어 두어도 선택할 수 없다.
SELECTABLE_FONT_SUFFIXES = {".ttf", ".ttc"}


class TestKoreanSubtitleFont(unittest.TestCase):
    """한국어 로케일을 쓰려면 한글 글리프를 가진 글꼴이 번들되어 있어야 한다."""

    FONTS_DIR = Path(__file__).parent.parent.parent / "resource" / "fonts"

    def test_default_subtitle_font_renders_korean(self):
        """
        기본 글꼴이 한글을 그리지 못하면 자막이 전부 두부(□)로 나온다.
        원본 번들 글꼴은 중국어·일본어용이라 한글 글리프가 없으므로, 기본값이
        한글 지원 글꼴을 가리키는지 고정한다.
        """
        namespace = {}
        source = (Path(__file__).parent.parent.parent / "webui" / "Main.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "DEFAULT_SUBTITLE_SETTINGS"
                for t in node.targets
            ):
                namespace = ast.literal_eval(node.value)
                break

        default_font = namespace.get("font_name")
        self.assertTrue(default_font, "DEFAULT_SUBTITLE_SETTINGS 에 font_name 이 없다")

        font_path = self.FONTS_DIR / default_font
        self.assertTrue(font_path.is_file(), f"기본 글꼴 파일이 없다: {default_font}")
        self.assertTrue(
            video.subtitle_font_supports_text(str(font_path), "한글자막테스트"),
            f"기본 글꼴 {default_font} 이 한글 글리프를 갖고 있지 않다",
        )

    def test_bundled_fonts_cover_every_script_locale(self):
        """
        대본 언어 목록의 각 언어마다 렌더링 가능한 번들 글꼴이 최소 하나는 있어야 한다.
        목록에 언어를 추가하고 글꼴을 빠뜨리면 자막이 조용히 깨진다.
        """
        samples = {
            "ko-KR": "한글자막",
            "ja-JP": "日本語字幕",
            "zh-CN": "中文字幕",
            "en-US": "English",
            "ru-RU": "Русский",
        }
        bundled = [
            str(p)
            for p in self.FONTS_DIR.iterdir()
            if p.suffix.lower() in SELECTABLE_FONT_SUFFIXES
        ]

        for locale, sample in samples.items():
            with self.subTest(locale=locale):
                supported = [
                    os.path.basename(f)
                    for f in bundled
                    if video.subtitle_font_supports_text(f, sample)
                ]
                self.assertTrue(
                    supported, f"{locale} 자막을 그릴 수 있는 번들 글꼴이 없다"
                )

    def test_every_bundled_font_is_selectable(self):
        """
        WebUI 글꼴 목록과 CLI 검증은 .ttf/.ttc 만 받는다. 다른 확장자를
        resource/fonts 에 넣으면 드롭다운에 뜨지 않고 CLI 는 거부하므로,
        번들해 두어도 아무도 쓸 수 없는 글꼴이 된다.
        """
        unusable = sorted(
            p.name
            for p in self.FONTS_DIR.iterdir()
            if p.is_file()
            and p.suffix.lower() not in SELECTABLE_FONT_SUFFIXES
            and p.suffix.lower() not in {".txt", ".md"}
        )
        self.assertEqual(
            unusable,
            [],
            "선택할 수 없는 확장자의 글꼴이 번들되어 있다",
        )
