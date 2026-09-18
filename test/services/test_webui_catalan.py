from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import state as sm
from app.services import version_checker, voice


WEBUI_MAIN = Path(__file__).resolve().parents[2] / "webui" / "Main.py"


def _selectbox(app, key):
    """语言切换会重建带 locale 后缀的控件，按稳定键查找。"""
    return next(
        item for item in app.selectbox
        if item.key == key or str(item.key).startswith(f"{key}_")
    )


@pytest.fixture
def catalan_app():
    # 使用无凭据的配置、空任务列表和禁止写盘的保存函数，避免界面测试读取
    # 用户任务或修改真实配置。保留内置音色目录，检查实际的加泰罗尼亚语音色。
    with (
        patch.object(config, "app", {"llm_provider": "openai", "video_source": "pexels"}),
        patch.object(config, "ui", {
            "language": "ca", "voice_mode": "tts", "tts_server": "azure-tts-v1",
            "voice_name": "ca-ES-JoanaNeural-Female", "video_language": "ca-ES",
        }),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(sm.state, "get_all_tasks", return_value=([], 0)),
        # 固定为已完成且无更新，避免启动真实 GitHub 请求和后台刷新，
        # 也不读写进程级版本检查缓存，让语言切换与弹窗测试保持确定性。
        patch.object(
            version_checker,
            "poll_available_update",
            return_value=version_checker.UpdateCheckSnapshot(complete=True),
        ),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "ca"
        app.run()
        assert not app.exception
        yield app


def test_catalan_language_switch_preserves_script_and_script_language(catalan_app):
    """真实执行 Streamlit 重跑：一次切换即生效，正文和生成语言不随 UI 丢失。"""
    app = catalan_app
    assert "Català" in _selectbox(app, "top_language_code_selector").options
    assert _selectbox(app, "script_language_select").label == "Idioma del guió"
    assert _selectbox(app, "script_language_select").value == "ca-ES"
    contents = {
        "video_subject": "L'Àlex aprèn amb intel·ligència artificial",
        "video_script": "La intel·ligència artificial ens ajuda a aprendre. L'àudio també és útil.",
        "video_terms": "escola, estudiants, tecnologia",
    }
    for key, value in contents.items():
        next(item for item in app.text_area if item.key == key).set_value(value).run()
    for language, label in (("en", "Script Language"), ("ca", "Idioma del guió")):
        _selectbox(app, "top_language_code_selector").set_value(language).run()
        assert not app.exception
        assert app.session_state["ui_language"] == language
        assert _selectbox(app, "script_language_select").label == label
        assert _selectbox(app, "script_language_select").value == "ca-ES"
        for key, value in contents.items():
            assert next(item for item in app.text_area if item.key == key).value == value


def test_catalan_builtin_voices_and_settings_dialog(catalan_app):
    """两种内置音色可供选择；设置弹窗可使用新语言正常打开。"""
    assert set(voice.get_all_azure_voices(["ca-ES"])) >= {
        "ca-ES-EnricNeural-Male", "ca-ES-JoanaNeural-Female",
    }
    app = catalan_app
    assert any("Joana" in option for item in app.selectbox for option in item.options)
    next(item for item in app.button if item.key == "open_settings_dialog_button").click().run()
    assert not app.exception
    assert any(tab.label == "Model de llenguatge" for tab in app.tabs)
    assert any(tab.label == "Orígens del material" for tab in app.tabs)
