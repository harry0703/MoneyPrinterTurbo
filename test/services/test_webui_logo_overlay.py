from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


def _widget_by_key(elements, key: str):
    """Streamlit 控件标签会翻译，使用稳定业务 key 定位真实控件。"""
    return next(
        item
        for item in elements
        if str(getattr(item, "key", "")) == key
        or str(getattr(item, "key", "")).startswith(f"{key}_")
    )


def test_logo_overlay_controls_render_disabled_by_default_and_toggle_correctly():
    test_ui = dict(config.ui, voice_mode="tts")

    with (
        patch.object(config, "ui", test_ui),
        patch.object(config, "save_config"),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "en"
        app.run()

        enable_checkbox = _widget_by_key(app.checkbox, "logo_overlay_enabled_checkbox")
        assert enable_checkbox.value is False

        position_select = _widget_by_key(app.selectbox, "logo_position_select")
        size_slider = _widget_by_key(app.slider, "logo_size_percent_slider")
        assert position_select.disabled is True
        assert size_slider.disabled is True

        enable_checkbox.set_value(True).run()

        position_select = _widget_by_key(app.selectbox, "logo_position_select")
        size_slider = _widget_by_key(app.slider, "logo_size_percent_slider")
        assert position_select.disabled is False
        assert size_slider.disabled is False
        assert position_select.value == "top-right"
        assert size_slider.value == 15

    assert [str(item.value) for item in app.exception] == []
