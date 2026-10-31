"""真实渲染新视频源及独立凭据，切换模型不得沿用上一模型的付费确认。"""

from pathlib import Path
import json
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
import pytest

from app.config import config

WEBUI = Path(__file__).parents[2] / "webui/Main.py"


@pytest.mark.parametrize("language", ["zh", "en", "de"])
def test_infistar_video_models_specs_and_billing_confirmation(language):
    values = {
        "llm_provider": "infistar",
        "infistar_api_key": "fake-llm-key",
        "infistar_video_api_key": "fake-video-key",
        "video_source": "infistar",
    }
    with (
        patch.object(config, "app", values),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI), default_timeout=60)
        app.session_state["ui_language"] = language
        app.run()
        assert not app.exception
        if language == "de":
            assert any(
                "Each generated clip is billed by Infistar." in warning.value
                for warning in app.warning
            )
        selector = app.selectbox(key=f"infistar_video_model_select_{language}")
        assert selector.options == ["Seedance 2.0 Fast", "MiniMax H3", "Kling 2.6"]
        assert app.selectbox(key=f"video_clip_duration_select_{language}").value == 5
        app.checkbox(key="infistar_confirm_charge").check().run()
        assert app.checkbox(key="infistar_confirm_charge").value
        app.selectbox(key=f"infistar_video_model_select_{language}").select(
            "MiniMax-H3"
        ).run()
        assert not app.exception
        assert not app.checkbox(key="infistar_confirm_charge").value
        assert app.selectbox(key=f"video_clip_duration_select_{language}").value == 6
        app.selectbox(key=f"infistar_video_model_select_{language}").select(
            "kling-v2-6"
        ).run()
        assert not app.exception
        assert app.selectbox(key=f"video_clip_duration_select_{language}").value == 5
        app.session_state["settings_dialog_open"] = True
        app.session_state["settings_dialog_target_tab"] = "video"
        app.session_state["settings_material_providers"] = {"ai_video": "infistar"}
        app.run()
        assert not app.exception
        assert (
            app.text_input(key="infistar_video_api_key_input").value == "fake-video-key"
        )
        assert values["infistar_api_key"] == "fake-llm-key"
        messages = json.loads((WEBUI.parent / "i18n" / f"{language}.json").read_text(encoding="utf-8"))["Translation"]
        english = json.loads((WEBUI.parent / "i18n" / "en.json").read_text(encoding="utf-8"))["Translation"]
        providers = app.selectbox(key=f"settings_material_provider_ai_video_select_{language}")
        assert providers.options == [messages.get(key, english.get(key, key)) for key in (
            "Metaso MiniMax H3", "OFox AI Video", "Shengsuan Cloud AI Video",
            "Volcano Engine Seedance", "Infistar AI Video", "Jalapeno Cloud AI Video",
            "WaveSpeed AI Video", "MuAPI AI Video",
        )]
        assert providers.value == "infistar"
        assert not any(item.key in {
            "volcengine_seedance_base_url_input", "wavespeed_api_keys_input"
        } for item in app.text_input)


@pytest.mark.parametrize("llm_provider", ["infistar", "openai"])
def test_video_credentials_are_editable_with_any_llm(llm_provider):
    values = {
        "llm_provider": llm_provider,
        "infistar_api_key": "old-llm-key",
        "infistar_base_url": "https://llm.example/v1",
        "infistar_video_api_key": "old-video-key",
        "infistar_video_base_url": "https://video.example/v1",
        "video_source": "infistar",
    }
    with (
        patch.object(config, "app", values),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.session_state["settings_dialog_open"] = True
        app.session_state["settings_dialog_target_tab"] = "video"
        app.session_state["settings_material_providers"] = {"ai_video": "infistar"}
        app.run()
        assert not app.exception
        app.text_input(key="infistar_video_api_key_input").set_value(
            "new-video-key"
        ).run()
        app.text_input(key="infistar_video_base_url_input").set_value(
            "https://new-video.example/v1"
        ).run()
        assert not app.exception
        assert values["infistar_video_api_key"] == "new-video-key"
        assert values["infistar_video_base_url"] == "https://new-video.example/v1"
        assert values["infistar_api_key"] == "old-llm-key"
        assert values["infistar_base_url"] == "https://llm.example/v1"
        if llm_provider == "infistar":
            app.session_state["settings_dialog_target_tab"] = "llm"
            app.run()
            assert not app.exception
            app.text_input(key="infistar_api_key_input").set_value("new-llm-key").run()
            assert not app.exception
            assert values["infistar_api_key"] == "new-llm-key"
            assert values["infistar_video_api_key"] == "new-video-key"
            assert values["infistar_video_base_url"] == "https://new-video.example/v1"
