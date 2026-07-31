import ast
import json
import os
import tempfile
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


def _webui_selectable_fonts():
    """
    WebUI 글꼴 드롭다운이 실제로 만들어 내는 목록을 그대로 얻는다.

    확장자 규칙을 테스트가 복사해 두면 앱이 규칙을 바꿔도 테스트가 따라가지 않고,
    대소문자 처리 같은 미묘한 차이도 놓친다. get_all_fonts 의 본문을 그대로 실행해
    앱이 고르는 것과 같은 집합을 쓴다.
    """
    source = (Path(__file__).parent.parent.parent / "webui" / "Main.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_all_fonts":
            body = [n for n in node.body if not isinstance(n, ast.Expr)]
            fn = ast.Module(
                body=[ast.FunctionDef(
                    name="get_all_fonts", args=node.args, body=body,
                    decorator_list=[], returns=None, type_params=[],
                )],
                type_ignores=[],
            )
            ast.fix_missing_locations(fn)
            ns = {"os": os, "font_dir": str(FONTS_DIR)}
            exec(compile(fn, "<get_all_fonts>", "exec"), ns)
            return sorted(ns["get_all_fonts"]())
    raise AssertionError("webui/Main.py 에서 get_all_fonts 를 찾지 못했다")


FONTS_DIR = Path(__file__).parent.parent.parent / "resource" / "fonts"


def _script_locales():
    """webui/Main.py 의 support_locales 를 그대로 읽는다."""
    source = (Path(__file__).parent.parent.parent / "webui" / "Main.py").read_text(
        encoding="utf-8"
    )
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "support_locales" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("webui/Main.py 에서 support_locales 를 찾지 못했다")


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
            "ko": "한글자막",
            "ja": "日本語字幕",
            "zh": "中文字幕",
            "en": "English",
            "ru": "Русский",
            "th": "คำบรรยาย",
            "vi": "Phụ đề",
            "tr": "Altyazı",
            "de": "Untertitel",
            "es": "Subtítulos",
            "fr": "Sous-titres",
        }
        # 대본 언어 목록에서 직접 유도한다. 목록에 언어를 추가하고 여기에 표본을
        # 넣지 않으면 그 사실이 드러나야 하므로, 표본 누락도 실패로 처리한다.
        declared = _script_locales()
        missing_samples = sorted(
            loc for loc in declared if loc.split("-")[0] not in samples
        )
        self.assertEqual(missing_samples, [], "표본이 없는 대본 언어가 있다")
        samples = {
            loc: samples[loc.split("-")[0]] for loc in declared
        }
        bundled = [str(self.FONTS_DIR / name) for name in _webui_selectable_fonts()]

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
        selectable = set(_webui_selectable_fonts())
        unusable = sorted(
            p.name
            for p in self.FONTS_DIR.iterdir()
            if p.is_file()
            and p.suffix.lower() not in {".txt", ".md"}
            and p.name not in selectable
        )
        self.assertEqual(
            unusable,
            [],
            "선택할 수 없는 확장자의 글꼴이 번들되어 있다",
        )


class TestSubtitleFontFallback(unittest.TestCase):
    """
    저장된 글꼴이 대본을 그리지 못할 때만 교체되는지 확인한다.

    글꼴 값은 config.toml, CLI 인자, API 파라미터 어디서든 오고 그중 다수는
    저장소가 관리하지 않는다. 기본값만 고쳐서는 이미 잘못된 값을 저장한
    사용자를 구제하지 못하므로, 생성 시점에 교정되어야 한다.
    """

    @staticmethod
    def _subtitle(tmp_dir, text):
        path = Path(tmp_dir) / "subtitle.srt"
        path.write_text(
            f"1\n00:00:00,000 --> 00:00:02,000\n{text}\n", encoding="utf-8"
        )
        return str(path)

    def test_korean_script_replaces_a_font_without_hangul(self):
        """한글을 못 그리는 저장값은 그릴 수 있는 글꼴로 교체돼야 한다."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            resolved = video.resolve_subtitle_font(
                "MicrosoftYaHeiBold.ttc", self._subtitle(tmp_dir, "한글 자막 확인")
            )

        self.assertNotEqual(resolved, "MicrosoftYaHeiBold.ttc")
        self.assertTrue(
            video.subtitle_font_supports_text(
                str(FONTS_DIR / resolved), "한글 자막 확인"
            )
        )

    def test_japanese_script_keeps_a_font_that_can_render_it(self):
        """
        일본어를 그릴 수 있는 선택은 그대로 둬야 한다. 무조건 한글 글꼴로 바꾸면
        일본어 사용자의 자막이 반대로 깨진다.

        같은 글꼴이 한국어 대본에서는 교체되는 것까지 함께 확인한다. 그러지 않으면
        resolver 가 입력을 그대로 돌려주기만 해도 이 테스트가 통과한다.
        """
        # 전제: 이 글꼴은 일본어를 그릴 수 있고 한글은 못 그린다.
        japanese_font = str(FONTS_DIR / "MicrosoftYaHeiBold.ttc")
        self.assertTrue(video.subtitle_font_supports_text(japanese_font, "日本語の字幕"))
        self.assertFalse(video.subtitle_font_supports_text(japanese_font, "한글자막"))

        with tempfile.TemporaryDirectory() as tmp_dir:
            kept = video.resolve_subtitle_font(
                "MicrosoftYaHeiBold.ttc", self._subtitle(tmp_dir, "日本語の字幕")
            )
            swapped = video.resolve_subtitle_font(
                "MicrosoftYaHeiBold.ttc", self._subtitle(tmp_dir, "한글 자막")
            )

        self.assertEqual(kept, "MicrosoftYaHeiBold.ttc")
        self.assertNotEqual(swapped, "MicrosoftYaHeiBold.ttc")

    def test_unopenable_font_is_replaced(self):
        """
        설정에 남은 이름이 지워진 파일을 가리킬 수 있다. 글꼴 검사가 실패했을 때
        '지원됨'으로 취급하면 그대로 통과해 자막이 사라진다.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            resolved = video.resolve_subtitle_font(
                "Deleted-Font.ttf", self._subtitle(tmp_dir, "한글 자막")
            )

        self.assertNotEqual(resolved, "Deleted-Font.ttf")
        self.assertTrue((FONTS_DIR / resolved).is_file())

    def test_corrupt_font_is_not_treated_as_supported(self):
        """
        파일이 존재하지만 열리지 않는 글꼴이 있다. 검사 실패를 '지원됨' 으로 답하면
        선택값이 그대로 통과해 자막이 사라지고, 손상된 후보가 대체 글꼴로 뽑힐 수도
        있다. 파일 부재는 경로 검증이 걸러 주지만 손상 파일은 여기서만 걸린다.
        """
        corrupt = FONTS_DIR / "_corrupt_probe.ttf"
        corrupt.write_bytes(b"not a font")
        try:
            self.assertIsNone(
                video._inspect_subtitle_font(str(corrupt), "한글"),
                "열 수 없는 글꼴은 판정 불가여야 한다",
            )

            with tempfile.TemporaryDirectory() as tmp_dir:
                resolved = video.resolve_subtitle_font(
                    corrupt.name, self._subtitle(tmp_dir, "한글 자막")
                )

            self.assertNotEqual(resolved, corrupt.name)
            self.assertTrue(
                video.subtitle_font_supports_text(str(FONTS_DIR / resolved), "한글 자막")
            )
        finally:
            corrupt.unlink(missing_ok=True)
            video._inspect_subtitle_font.cache_clear()

    def test_font_name_cannot_escape_the_bundle_directory(self):
        """글꼴 이름은 API 파라미터로도 들어온다. 번들 밖을 가리키면 후보에서 빠져야 한다."""
        self.assertEqual(video._font_path_within_bundle("../../etc/passwd"), "")

    def test_unreadable_subtitle_file_does_not_crash(self):
        """자막이 UTF-8 이 아니어도 생성이 죽으면 안 된다."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "subtitle.srt"
            path.write_bytes(b"\xff\xfe\x00invalid")
            resolved = video.resolve_subtitle_font("Pretendard-Bold.ttf", str(path))

        self.assertEqual(resolved, "Pretendard-Bold.ttf")

    def test_srt_metadata_does_not_crowd_out_the_dialogue(self):
        """
        자막 파일에는 순번과 타임코드가 섞여 있다. 그 숫자가 표본을 차지하면
        뒤쪽 언어의 문자를 놓쳐 잘못된 글꼴이 통과할 수 있다.
        """
        srt = "1\n00:00:00,000 --> 00:00:02,000\n한글\n"
        sample = video._subtitle_sample(srt)

        self.assertIn("한", sample)
        self.assertNotIn("0", sample)

    def test_missing_subtitle_file_keeps_the_selected_font(self):
        """자막 파일을 읽을 수 없으면 판단 근거가 없으므로 선택을 바꾸지 않는다."""
        resolved = video.resolve_subtitle_font(
            "MicrosoftYaHeiBold.ttc", "/nonexistent/subtitle.srt"
        )

        self.assertEqual(resolved, "MicrosoftYaHeiBold.ttc")

    def test_generate_video_applies_the_fallback(self):
        """
        헬퍼가 옳아도 generate_video 가 호출하지 않으면 사용자에게는 아무 효과가
        없다. 호출부가 사라지는 회귀를 잡기 위해 실제 진입점을 확인한다.
        """
        source = (
            Path(__file__).parent.parent.parent
            / "app" / "services" / "video.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)

        target = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "generate_video"
        )
        called = {
            node.func.id
            for node in ast.walk(target)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

        self.assertIn(
            "resolve_subtitle_font",
            called,
            "generate_video 가 자막 글꼴 교체를 호출하지 않는다",
        )
