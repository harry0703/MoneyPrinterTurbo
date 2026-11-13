"""验证 OFox 展示顺序调整，不改变已保存的生成配置或触发付费请求。"""

import ast
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config


WEBUI = Path(__file__).resolve().parents[2] / "webui" / "Main.py"


def test_ai_video_source_order_keeps_ofox_below_metaso():
    # 常量控制视频来源选择器，设置弹窗则通过下面的真实控件测试验证。
    tree = ast.parse(WEBUI.read_text(encoding="utf-8"))
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "VIDEO_SOURCE_GROUPS"
                for target in node.targets)
    )
    groups = ast.literal_eval(assignment.value)
    assert groups["ai_video"] == (
        "metaso_minimax", "ofox", "loomloom", "volcengine_seedance", "infistar", "jalapeno", "wavespeed", "muapi"
    )
    assert groups["stock_video"] == ("pexels", "pixabay", "coverr")


@pytest.mark.parametrize("language", sorted(file.stem for file in (WEBUI.parent / "i18n").glob("*.json")))
def test_ofox_settings_order_and_saved_values(language):
    # 使用虚构配置并禁止保存，打开设置不得覆盖本机凭据或改写既有 OFox 选择。
    values = {
        "llm_provider": "openai",
        "ofox_api_key": "review-only-fake-key",
        "ofox_text_to_video_model": "custom-model",
        "ofox_base_url": "https://example.invalid/v1",
        "ofox_provider": "volcengine",
    }
    expected = dict(values)
    with (
        patch.object(config, "app", values),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI), default_timeout=60)
        app.session_state["ui_language"] = language
        app.run()
        app.session_state["settings_dialog_open"] = True
        app.session_state["settings_dialog_target_tab"] = "video"
        app.session_state["settings_material_providers"] = {"ai_video": "ofox"}
        app.run()
        assert not app.exception
        messages = json.loads((WEBUI.parent / "i18n" / f"{language}.json").read_text(encoding="utf-8"))["Translation"]
        english = json.loads((WEBUI.parent / "i18n" / "en.json").read_text(encoding="utf-8"))["Translation"]
        providers = app.selectbox(key=f"settings_material_provider_ai_video_select_{language}")
        assert providers.options == [messages.get(key, english.get(key, key)) for key in (
            "Metaso MiniMax H3", "OFox AI Video", "Shengsuan Cloud AI Video",
            "Volcano Engine Seedance", "Infistar AI Video", "Jalapeno Cloud AI Video",
            "WaveSpeed AI Video", "MuAPI AI Video",
        )]
        assert providers.value == "ofox"
        assert not any(item.key in {
            "metaso_minimax_api_key_input", "loomloom_api_token_input"
        } for item in app.text_input)
        api_key_input = next(item for item in app.text_input if item.key == "ofox_api_key_input")
        assert "https://ofox.ai/?utm_source=github&utm_medium=sponsorship&utm_content=moneyprinterturbo" in api_key_input.label
        assert any(item.value == "**OfoxAI**" for item in app.markdown)
        # 每种语言均实际渲染，仅品牌名保留推广链接，官方上游说明使用普通文字。
        messages = json.loads((WEBUI.parent / "i18n" / f"{language}.json").read_text(encoding="utf-8"))
        help_text = messages["Translation"]["OFox AI Video Help"]
        assert "http" not in help_text
        assert any(
            "[OfoxAI](https://ofox.ai/?utm_source=github&utm_medium=sponsorship&utm_content=moneyprinterturbo)" in item.value
            and help_text in item.value
            for item in app.caption
        )
        app.run()
        assert not app.exception
        for key, value in expected.items():
            assert values[key] == value
