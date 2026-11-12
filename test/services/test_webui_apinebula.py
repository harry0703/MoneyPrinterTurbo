"""实际运行 APINEBULA 设置组件，验证配置保存、语言回退及连接测试入口。"""

from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import llm


def _widget(elements, key):
    return next(
        item for item in elements
        if str(item.key) == key or str(item.key).startswith(f"{key}_")
    )


@pytest.mark.parametrize("language", ["zh", "en", "de"])
def test_settings_defaults_overrides_and_connection_button(language):
    """默认值可直接使用，覆盖值独立保存，次要语言复用英文说明。"""
    values = {"llm_provider": "apinebula"}
    with (
        patch.object(config, "app", values),
        patch.object(config, "ui", dict(config.ui, language=language)),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(llm, "test_connection", return_value=(True, "", 0.1)) as test,
    ):
        app = AppTest.from_file(
            str(Path(__file__).parents[2] / "webui/Main.py"), default_timeout=60
        )
        app.session_state["ui_language"] = language
        app.session_state["settings_dialog_open"] = True
        app.session_state["settings_dialog_target_tab"] = "llm"
        app.run()
        assert not app.exception
        assert _widget(app.selectbox, "llm_provider_select").value == "apinebula"
        assert app.text_input(key="apinebula_model_name_input").value == "gpt-6.1-sol"
        assert (
            app.text_input(key="apinebula_base_url_custom_input").value
            == "https://apinebula.ai/v1"
        )
        key_input = app.text_input(key="apinebula_api_key_input")
        assert key_input.proto.type == key_input.proto.PASSWORD
        assert values.get("apinebula_model_name", "") == ""
        assert values.get("apinebula_base_url", "") == ""
        tips = "\n".join(item.value for item in app.info)
        assert "https://apinebula.ai/ref/luDuqJIb" in tips
        assert "https://apinebula.ai/zh/pricing" in tips
        assert "gpt-6.1-sol" in tips and "MPT" in tips
        assert "{default_" not in tips
        if language == "de":
            assert "APINEBULA Configuration" in tips

        for suffix, value in (
            ("api_key_input", "test-ui-key"),
            ("model_name_input", "custom-model"),
            ("base_url_custom_input", "https://gateway.example/v1"),
        ):
            app.text_input(key=f"apinebula_{suffix}").set_value(value).run()
        assert values["apinebula_api_key"] == "test-ui-key"
        assert values["apinebula_model_name"] == "custom-model"
        assert values["apinebula_base_url"] == "https://gateway.example/v1"
        app.button(key="test_llm_connection_button").click().run()
        test.assert_called_once()
        assert not app.exception
