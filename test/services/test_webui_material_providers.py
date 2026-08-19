from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config


ROOT_DIR = Path(__file__).resolve().parents[2]
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


def test_legacy_pexels_pixabay_config_migrates_to_visible_fan_out_controls():
    app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
    app.session_state["ui_language"] = "en"
    legacy_config = dict(
        config.app,
        video_source="pexels_pixabay",
        material_provider_mode="locked",
        material_providers=[],
        pexels_api_keys=[],
        pixabay_api_keys=[],
        coverr_api_keys=[],
    )
    with patch.object(config, "app", legacy_config), patch.object(
        config, "try_save_config", return_value=True
    ):
        app.run()

    assert not app.exception
    source = next(
        widget for widget in app.selectbox if "video_source_select" in str(widget.key)
    )
    mode = next(
        widget
        for widget in app.selectbox
        if "material_provider_mode_select" in str(widget.key)
    )
    providers = next(widget for widget in app.multiselect if "material_providers_select" in str(widget.key))
    assert source.value == "stock"
    assert mode.value == "fan_out"
    assert providers.value == ["pexels", "pixabay"]
    inline_key_inputs = {
        widget.key
        for widget in app.text_input
        if str(widget.key).startswith("selected_")
    }
    assert inline_key_inputs == {
        "selected_pexels_api_keys_input",
        "selected_pixabay_api_keys_input",
    }


def test_existing_single_stock_source_migrates_to_matching_locked_provider():
    app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
    app.session_state["ui_language"] = "en"
    legacy_config = dict(
        config.app,
        video_source="pixabay",
        pexels_api_keys=[],
        pixabay_api_keys=[],
        coverr_api_keys=[],
    )
    legacy_config.pop("material_provider_mode", None)
    legacy_config.pop("material_providers", None)
    with patch.object(config, "app", legacy_config), patch.object(
        config, "try_save_config", return_value=True
    ):
        app.run()

    assert not app.exception
    source = next(
        widget for widget in app.selectbox if "video_source_select" in str(widget.key)
    )
    providers = next(
        widget
        for widget in app.multiselect
        if "material_providers_select" in str(widget.key)
    )
    assert source.value == "stock"
    assert providers.value == ["pixabay"]
    inline_key_inputs = {
        widget.key
        for widget in app.text_input
        if str(widget.key).startswith("selected_")
    }
    assert inline_key_inputs == {"selected_pixabay_api_keys_input"}


def test_modern_provider_order_is_not_modified_by_compatibility_source():
    app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
    app.session_state["ui_language"] = "en"
    modern_config = dict(
        config.app,
        video_source="pexels",
        material_provider_mode="fallback",
        material_providers=["coverr", "pexels", "pixabay"],
        pexels_api_keys=[],
        pixabay_api_keys=[],
        coverr_api_keys=[],
    )
    with patch.object(config, "app", modern_config), patch.object(
        config, "try_save_config", return_value=True
    ):
        app.run()

    assert not app.exception
    source = next(
        widget for widget in app.selectbox if "video_source_select" in str(widget.key)
    )
    providers = next(
        widget
        for widget in app.multiselect
        if "material_providers_select" in str(widget.key)
    )
    assert source.value == "stock"
    assert providers.value == ["coverr", "pexels", "pixabay"]


def test_each_selected_missing_provider_gets_an_inline_api_key_card():
    app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
    app.session_state["ui_language"] = "en"
    provider_config = dict(
        config.app,
        video_source="pexels",
        material_provider_mode="locked",
        material_providers=["pexels"],
        pexels_api_keys=["configured"],
        pixabay_api_keys=[],
        coverr_api_keys=[],
    )
    with patch.object(config, "app", provider_config), patch.object(
        config, "try_save_config", return_value=True
    ):
        app.run()
        mode = next(
            widget
            for widget in app.selectbox
            if "material_provider_mode_select" in str(widget.key)
        )
        mode.set_value("fan_out").run()
        providers = next(
            widget
            for widget in app.multiselect
            if "material_providers_select" in str(widget.key)
        )
        providers.set_value(["pexels", "pixabay", "coverr"]).run()

    assert not app.exception
    providers = next(
        widget
        for widget in app.multiselect
        if "material_providers_select" in str(widget.key)
    )
    assert providers.value == ["pexels", "pixabay", "coverr"]
    inline_key_inputs = {
        widget.key: widget
        for widget in app.text_input
        if str(widget.key).startswith("selected_")
    }
    assert set(inline_key_inputs) == {
        "selected_pixabay_api_keys_input",
        "selected_coverr_api_keys_input",
    }
    assert "https://pixabay.com/api/docs/" in inline_key_inputs[
        "selected_pixabay_api_keys_input"
    ].label
    assert "https://coverr.co/developers" in inline_key_inputs[
        "selected_coverr_api_keys_input"
    ].label


def test_non_stock_source_hides_stock_provider_controls_and_key_cards():
    app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
    app.session_state["ui_language"] = "en"
    local_config = dict(config.app, video_source="local")
    with patch.object(config, "app", local_config), patch.object(
        config, "try_save_config", return_value=True
    ):
        app.run()

    assert not app.exception
    source = next(
        widget for widget in app.selectbox if "video_source_select" in str(widget.key)
    )
    assert source.value == "local"
    assert not any(
        "material_providers_select" in str(widget.key)
        for widget in app.multiselect
    )
    assert not any(
        str(widget.key).startswith("selected_") for widget in app.text_input
    )
