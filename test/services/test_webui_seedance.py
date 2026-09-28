from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


def _widget_by_key(elements, key):
    return next(
        item
        for item in elements
        if str(getattr(item, "key", "")) == key
        or str(getattr(item, "key", "")).startswith(f"{key}_")
    )


def test_seedance_source_requires_confirmation_then_submits_without_secret_in_params():
    test_config = dict(
        config.app,
        llm_provider="openai",
        video_source="pexels",
        volcengine_seedance_api_key="ark-secret",
    )
    with (
        patch.object(config, "app", test_config),
        patch.object(config, "try_save_config", return_value=True),
        patch("app.services.webui_task.submit_generation") as submit_generation,
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()

        _widget_by_key(app.text_area, "video_subject").set_value("AI office").run()
        _widget_by_key(app.text_area, "video_script").set_value(
            "AI helps people work faster."
        ).run()
        _widget_by_key(app.text_area, "video_terms").set_value(
            "office worker, AI assistant"
        ).run()
        app.session_state["video_source_select_en"] = "volcengine_seedance"
        app.run()

        _widget_by_key(app.button, "generate_video_button").click().run()
        assert submit_generation.call_count == 0
        assert any("confirm" in str(item.value).lower() for item in app.error)

        _widget_by_key(
            app.checkbox, "volcengine_seedance_confirm_charge"
        ).check().run()
        _widget_by_key(app.button, "generate_video_button").click().run()

        assert submit_generation.call_count == 1
        submitted_params = submit_generation.call_args.kwargs["params"]
        assert submitted_params.video_source == "volcengine_seedance"
        assert "ark-secret" not in submitted_params.model_dump_json()
        assert [str(item.value) for item in app.exception] == []
