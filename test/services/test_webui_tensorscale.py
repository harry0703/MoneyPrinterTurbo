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


def test_tensorscale_source_limits_duration_and_requires_confirmation():
    test_config = dict(
        config.app,
        llm_provider="openai",
        video_source="pexels",
        tensorscale_api_key="tensorscale-secret",
        tensorscale_base_url="https://api.tensorscale.io/v1",
        tensorscale_resolution="768p",
    )
    with (
        patch.object(config, "app", test_config),
        patch.object(config, "try_save_config", return_value=True),
        patch("app.services.webui_task.submit_generation") as submit_generation,
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()

        _widget_by_key(app.text_area, "video_subject").set_value("Ocean city").run()
        _widget_by_key(app.text_area, "video_script").set_value(
            "A futuristic city rises above the ocean."
        ).run()
        _widget_by_key(app.text_area, "video_terms").set_value(
            "futuristic ocean city"
        ).run()
        app.session_state["video_source_select_en"] = "tensorscale"
        app.run()

        clip_duration = _widget_by_key(app.selectbox, "video_clip_duration_select")
        assert min(map(int, clip_duration.options)) == 4
        assert max(map(int, clip_duration.options)) == 15
        assert int(clip_duration.value) == 5

        _widget_by_key(app.button, "generate_video_button").click().run()
        assert submit_generation.call_count == 0
        assert any("confirm" in str(item.value).lower() for item in app.error)

        _widget_by_key(app.checkbox, "tensorscale_confirm_charge").check().run()
        _widget_by_key(app.button, "generate_video_button").click().run()

        assert submit_generation.call_count == 1
        submitted_params = submit_generation.call_args.kwargs["params"]
        assert submitted_params.video_source == "tensorscale"
        assert "tensorscale-secret" not in submitted_params.model_dump_json()
        assert [str(item.value) for item in app.exception] == []


def test_tensorscale_material_settings_expose_key_base_url_and_resolution():
    test_config = dict(
        config.app,
        tensorscale_api_key="",
        tensorscale_base_url="https://gateway.example/v1",
        tensorscale_resolution="480p",
    )
    test_ui = dict(config.ui, language="en")
    with (
        patch.object(config, "app", test_config),
        patch.object(config, "ui", test_ui),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.session_state["settings_dialog_open"] = True
        app.session_state["settings_dialog_target_tab"] = "material"
        app.run()

        key = _widget_by_key(app.text_input, "tensorscale_api_key_input")
        base_url = _widget_by_key(app.text_input, "tensorscale_base_url_input")
        resolution = _widget_by_key(app.selectbox, "tensorscale_resolution_input")
        assert base_url.value == "https://gateway.example/v1"
        assert resolution.value == "480p"

        key.set_value("new-secret").run()
        resolution = _widget_by_key(app.selectbox, "tensorscale_resolution_input")
        resolution.set_value("768p").run()
        assert test_config["tensorscale_api_key"] == "new-secret"
        assert test_config["tensorscale_resolution"] == "768p"
        assert [str(item.value) for item in app.exception] == []
