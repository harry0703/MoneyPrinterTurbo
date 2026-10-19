from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import creative_studio, voice


WEBUI_MAIN = Path(__file__).parents[2] / "webui" / "Main.py"


def _by_key(elements, key):
    return next(item for item in elements if str(getattr(item, "key", "")) == key)


def test_selected_creative_variant_populates_normal_video_script():
    app_config = dict(config.app, video_source="pexels")
    ui_config = dict(
        config.ui,
        language="en",
        voice_mode="tts",
        tts_server="azure-tts-v1",
        voice_name="en-US-JennyNeural-Female",
    )

    def fake_script(**kwargs):
        prompt = kwargs["video_script_prompt"]
        angle = next(name for name, _ in creative_studio.HOOKS if name in prompt)
        return f"{angle} hook. Show the problem. Explain the answer. Invite action."

    with (
        patch.object(config, "app", app_config),
        patch.object(config, "ui", ui_config),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(
            voice, "get_all_azure_voices", return_value=["en-US-JennyNeural-Female"]
        ),
        patch.object(creative_studio.llm, "generate_script", side_effect=fake_script),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()
        _by_key(app.text_area, "video_subject").set_value("City gardening").run()
        _by_key(app.text_input, "creative_goal").set_value("Teach beginners").run()
        _by_key(app.text_input, "creative_audience").set_value(
            "Apartment residents"
        ).run()
        _by_key(app.text_area, "creative_source_notes").set_value(
            "Herbs need drainage and adequate light."
        ).run()
        _by_key(app.button, "creative_generate").click().run()
        assert not app.exception
        assert len(app.session_state["creative_experiment"]["variants"]) == 3

        _by_key(app.selectbox, "creative_variant_choice").set_value("surprise").run()
        _by_key(app.button, "creative_use_variant").click().run()
        assert app.session_state["video_script"].startswith("surprise hook")
        assert _by_key(app.text_area, "video_script").value.startswith("surprise hook")
        _by_key(app.text_input, "creative_goal").set_value("A different goal").run()
        assert any("brief changed" in str(item.value).lower() for item in app.info)
        assert not app.exception
