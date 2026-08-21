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
    assert source.value == "pexels"
    assert mode.value == "Fan-out (all selected)"
    assert providers.value == ["Pexels (API key missing)", "Pixabay (API key missing)"]


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
    assert source.value == "pixabay"
    assert providers.value == ["Pixabay (API key missing)"]


def test_modern_provider_order_drives_legacy_source_selector():
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
    assert source.value == "coverr"
    assert providers.value == [
        "Coverr (API key missing)",
        "Pexels (API key missing)",
        "Pixabay (API key missing)",
    ]
