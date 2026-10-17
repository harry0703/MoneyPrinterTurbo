from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config


MAIN = Path(__file__).parent.parent.parent / "webui" / "Main.py"


def _widget(elements, key):
    return next(item for item in elements if str(getattr(item, "key", "")).startswith(key))


def test_vgenv_requires_explicit_charge_confirmation_and_keeps_key_out_of_task():
    settings = dict(config.app, llm_provider="openai", video_source="pexels", vgenv_api_key="fixture-secret")
    with (
        patch.object(config, "app", settings),
        patch.object(config, "ui", dict(config.ui, voice_mode="none")),
        patch.object(config, "try_save_config", return_value=True),
        patch("app.services.webui_task.submit_generation") as submit,
    ):
        app = AppTest.from_file(str(MAIN), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()
        _widget(app.text_area, "video_subject").set_value("Space fleet").run()
        _widget(app.text_area, "video_script").set_value(
            "A fleet travels across the galaxy."
        ).run()
        _widget(app.text_area, "video_terms").set_value("cinematic space fleet").run()
        app.session_state["video_source_select_en"] = "vgenv"
        app.run()
        durations = _widget(app.selectbox, "video_clip_duration_select")
        assert min(map(int, durations.options)) == 4
        assert max(map(int, durations.options)) == 15
        _widget(app.button, "generate_video_button").click().run()
        submit.assert_not_called()
        assert any("confirm" in str(item.value).lower() for item in app.error)
        _widget(app.checkbox, "vgenv_confirm_charge").check().run()
        _widget(app.button, "generate_video_button").click().run()
        assert submit.call_count == 1
        params = submit.call_args.kwargs["params"]
        assert params.video_source == "vgenv"
        assert "fixture-secret" not in params.model_dump_json()
        assert not app.exception
