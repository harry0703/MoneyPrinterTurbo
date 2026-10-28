"""实际渲染默认值、活动入口、独立视频配置及计费确认失效。"""

from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import jalapeno_video as provider

WEBUI = Path(__file__).parents[2] / "webui/Main.py"


@pytest.mark.parametrize("language", ["zh", "en", "de"])
def test_defaults_campaign_links_and_shared_key_are_visible(language):
    values = {
        "llm_provider": "jalapeno",
        "jalapeno_api_key": "shared-key",
        "video_source": "jalapeno",
    }
    with (
        patch.object(config, "app", values),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI), default_timeout=60)
        app.session_state["ui_language"] = language
        app.session_state["settings_dialog_open"] = True
        app.session_state["settings_dialog_target_tab"] = "llm"
        app.session_state["settings_material_providers"] = {"ai_video": "jalapeno"}
        app.run()
        assert not app.exception
        assert (
            app.text_input(key="jalapeno_model_name_input").value
            == "DeepSeek-V4.1-Flash"
        )
        tips = "\n".join(item.value for item in app.info)
        assert provider.CAMPAIGN_URL in tips and provider.MODELS_URL in tips
        app.session_state["settings_dialog_target_tab"] = "video"
        app.run()
        assert not app.exception
        assert (
            app.text_input(key="jalapeno_video_model_input").value
            == provider.DEFAULT_MODEL
        )
        assert (
            app.text_input(key="jalapeno_video_base_url_input").value
            == provider.DEFAULT_TASKS_URL
        )
        assert app.text_input(key="jalapeno_video_api_key_input").value == ""
        assert provider.get_api_key(values) == "shared-key"
        assert (
            provider.CAMPAIGN_URL
            in app.text_input(key="jalapeno_video_api_key_input").label
        )
        if language == "de":
            assert any(
                "Jalapeno Cloud bills each generated clip." in item.value
                for item in app.warning
            )
        app.checkbox(key="jalapeno_confirm_charge").check().run()
        assert app.checkbox(key="jalapeno_confirm_charge").value
        app.text_input(key="jalapeno_video_model_input").set_value(
            "Doubao-Seedance-2-0-260128"
        ).run()
        assert not app.exception
        assert not app.checkbox(key="jalapeno_confirm_charge").value


@pytest.mark.parametrize("llm_provider", ["jalapeno", "openai"])
def test_video_key_override_and_endpoint_are_independent_of_llm(llm_provider):
    values = {
        "llm_provider": llm_provider,
        "jalapeno_api_key": "shared-key",
        "video_source": "jalapeno",
        "jalapeno_base_url": "https://llm.example/v1",
        "volcengine_seedance_model": "ark-own-model",
        "volcengine_seedance_api_key": "ark-key",
    }
    with (
        patch.object(config, "app", values),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.session_state["settings_dialog_open"] = True
        app.session_state["settings_dialog_target_tab"] = "video"
        app.session_state["settings_material_providers"] = {"ai_video": "jalapeno"}
        app.run()
        assert not app.exception
        app.checkbox(key="jalapeno_confirm_charge").check().run()
        app.text_input(key="jalapeno_video_api_key_input").set_value(
            "video-only-key"
        ).run()
        assert not app.exception
        assert not app.checkbox(key="jalapeno_confirm_charge").value
        assert provider.get_api_key(values) == "video-only-key"
        app.text_input(key="jalapeno_video_base_url_input").set_value(
            "https://video.example/api/v3/contents/generations/tasks"
        ).run()
        assert (
            provider.endpoint(values).tasks_url
            == "https://video.example/api/v3/contents/generations/tasks"
        )
        assert values["jalapeno_api_key"] == "shared-key"
        assert values["jalapeno_base_url"] == "https://llm.example/v1"
        assert values["volcengine_seedance_model"] == "ark-own-model"
        assert values["volcengine_seedance_api_key"] == "ark-key"
        app.text_input(key="jalapeno_video_api_key_input").set_value("").run()
        assert not app.exception
        assert provider.get_api_key(values) == "shared-key"


def test_generation_rechecks_confirmation_at_submission_and_keeps_key_private():
    """模拟另一会话在表单渲染后更新配置，提交时必须重新确认。"""
    values = {
        "llm_provider": "jalapeno",
        "jalapeno_api_key": "shared-private-key",
        "video_source": "jalapeno",
    }
    change_during_submission = False

    def save_config():
        if change_during_submission:
            values["jalapeno_video_model"] = "changed-after-render"
        return True

    with (
        patch.object(config, "app", values),
        patch.object(config, "ui", dict(config.ui, voice_mode="none")),
        patch.object(config, "try_save_config", side_effect=save_config),
        patch("app.services.webui_task.submit_generation") as submit,
    ):
        app = AppTest.from_file(str(WEBUI), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()
        for prefix, value in [
            ("video_subject", "river"),
            ("video_script", "A peaceful river."),
            ("video_terms", "river"),
        ]:
            next(
                item for item in app.text_area if str(item.key).startswith(prefix)
            ).set_value(value).run()
        app.checkbox(key="jalapeno_confirm_charge").check().run()
        assert app.checkbox(key="jalapeno_confirm_charge").value
        change_during_submission = True
        app.button(key="generate_video_button").click().run()
        assert not app.exception
        assert submit.call_count == 0
        assert any("confirm" in str(item.value).lower() for item in app.error)
        change_during_submission = False
        app.run()
        app.checkbox(key="jalapeno_confirm_charge").check().run()
        app.button(key="generate_video_button").click().run()
        assert not app.exception
        assert submit.call_count == 1
        snapshot = submit.call_args.kwargs["jalapeno_video_endpoint"]
        assert snapshot.model == "changed-after-render"
        assert snapshot.api_key == "shared-private-key"
        assert (
            "shared-private-key"
            not in submit.call_args.kwargs["params"].model_dump_json()
        )
        assert "shared-private-key" not in repr(snapshot)
