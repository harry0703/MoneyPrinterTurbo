"""WebUI 쇼츠 템플릿 설정."""

import json
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

WEBUI_MAIN = str(Path("webui") / "Main.py")


def _app():
    app = AppTest.from_file(WEBUI_MAIN, default_timeout=60)
    app.session_state["ui_language"] = "ko"
    app.run()
    return app


def _widget(app, kind, key):
    return next(w for w in getattr(app, kind) if w.key == key)


class TestLayoutControlsExist(unittest.TestCase):
    """카드 레이아웃을 화면에서 고를 수 없으면 WebUI 로는 그 영상을 못 만든다."""

    def test_an_upgrading_user_keeps_the_fullscreen_layout(self):
        """
        설정을 저장한 적 없는 사용자가 새 버전을 열기만 해도 카드로 바뀌면, 화면
        구성이 달라지고 헤드라인 생성 때문에 LLM 호출까지 한 번 더 나간다. 카드는
        직접 골라야 켜지는 것이어야 한다.
        """
        from app.config import config

        saved = config.ui.pop("layout", None)
        try:
            app = _app()
            self.assertEqual(
                _widget(app, "selectbox", "layout_select_ko").value, "fullscreen"
            )
        finally:
            if saved is not None:
                config.ui["layout"] = saved

    def test_the_card_layout_can_be_chosen_on_screen(self):
        """
        레이아웃은 스키마에만 있었다. 화면에 없으면 WebUI 로 만든 영상은 전부
        전체화면으로 나와, CLI 로 만든 결과와 달라진다.
        """
        app = _app()
        _widget(app, "selectbox", "layout_select_ko").select("card").run()
        self.assertEqual(_widget(app, "selectbox", "layout_select_ko").value, "card")

    def test_the_headline_can_be_left_empty_for_the_llm(self):
        """헤드라인을 직접 넣을 수도, 비워서 AI 에 맡길 수도 있어야 한다."""
        app = _app()
        headline = _widget(app, "text_area", "headline_input")
        self.assertEqual(headline.value, "")

    def test_a_hand_written_headline_can_choose_where_it_breaks(self):
        """
        두 줄로 얹히는 문구다. 한 줄짜리 입력칸이면 어디서 끊길지 자동 줄바꿈에
        맡겨야 하고, 직접 쓴 헤드라인의 의미 단위가 엉뚱한 곳에서 갈린다.
        """
        app = _app()
        _widget(app, "text_area", "headline_input").set_value("첫 줄\n둘째 줄").run()

        self.assertEqual(
            _widget(app, "text_area", "headline_input").value, "첫 줄\n둘째 줄"
        )

    def test_the_template_widgets_are_disabled_outside_the_card_layout(self):
        """
        전체화면에서는 이 값들이 화면에 아무 영향을 주지 않는다. 조작할 수 있게
        두면 바꿔도 아무 일이 없어 고장으로 보인다.
        """
        app = _app()
        _widget(app, "selectbox", "layout_select_ko").select("fullscreen").run()

        self.assertTrue(_widget(app, "text_area", "headline_input").disabled)
        self.assertTrue(
            _widget(app, "checkbox", "subtitle_below_video_checkbox").disabled
        )

    def test_choosing_the_card_layout_enables_them_again(self):
        """카드로 되돌리면 다시 조작할 수 있어야 한다."""
        app = _app()
        selector = _widget(app, "selectbox", "layout_select_ko")
        selector.select("fullscreen").run()
        _widget(app, "selectbox", "layout_select_ko").select("card").run()

        self.assertFalse(_widget(app, "text_area", "headline_input").disabled)


class TestLayoutLabels(unittest.TestCase):
    def test_every_locale_has_the_template_labels(self):
        """라벨이 없으면 선택지에 영어 키가 그대로 노출된다."""
        keys = [
            "Shorts Template Settings",
            "Layout",
            "Layout fullscreen",
            "Layout card",
            "Headline",
            "Headline Color",
            "Headline Font Size",
            "Layout Video Height Ratio",
            "Layout Corner Radius",
            "Layout Background Color",
            "Subtitle Below Video",
            "Subtitle Below Color",
            "Restore Default Layout Settings",
        ]
        for path in sorted(Path("webui/i18n").glob("*.json")):
            translation = json.loads(path.read_text(encoding="utf-8"))["Translation"]
            for key in keys:
                with self.subTest(locale=path.stem, key=key):
                    self.assertIn(key, translation)


class TestLayoutRestore(unittest.TestCase):
    def test_task_restore_repopulates_every_template_field(self):
        """
        '설정 불러오기' 가 템플릿을 빠뜨리면, 지난 작업을 불러와도 화면 구성만
        기본값으로 돌아가 같은 영상이 나오지 않는다.
        """
        import ast

        source = Path("webui/Main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        restore = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_apply_pending_task_restore"
        )
        restored = {
            node.value
            for node in ast.walk(restore)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }

        for field in (
            "layout_background_color",
            "layout_video_height_ratio",
            "layout_corner_radius",
            "headline_color",
            "headline_font_size",
            "subtitle_below_video",
            "subtitle_below_color",
        ):
            with self.subTest(field=field):
                self.assertIn(field, restored)


if __name__ == "__main__":
    unittest.main()
