"""验证 OFox 展示顺序调整，不改变已保存的生成配置或触发付费请求。"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config


WEBUI = Path(__file__).resolve().parents[2] / "webui" / "Main.py"


def test_ai_video_source_order_keeps_ofox_below_metaso():
    # 视频来源的选择顺序由 app.models.video_sources 注册表声明，WebUI 只派生
    # 展示，因此这里校验注册表本身；WebUI 是否同源由
    # test_video_sources_registry.py 用 AST 校验，避免两处各写一份清单后漂移。
    from app.models import video_sources

    groups = video_sources.video_source_groups()
    assert groups["ai_video"] == (
        "metaso_minimax", "ofox", "loomloom", "volcengine_seedance", "wavespeed"
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
        app.run()
        assert not app.exception
        keys = [item.key for item in app.text_input]
        assert keys.index("metaso_minimax_api_key_input") < keys.index("ofox_api_key_input")
        assert keys.index("ofox_api_key_input") < keys.index("loomloom_api_token_input")
        # 获取密钥入口也要携带同一组跟踪参数，防止切换语言后丢失推广来源。
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
