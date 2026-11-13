from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import useapi


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


def _widget_by_key(elements, key):
    return next(
        item
        for item in elements
        if str(getattr(item, "key", "")) == key
        or str(getattr(item, "key", "")).startswith(f"{key}_")
    )


def test_useapi_source_requires_confirmation_then_submits_without_secret_in_params():
    test_config = dict(
        config.app,
        llm_provider="openai",
        video_source="pexels",
        useapi_api_token="useapi-secret",
        useapi_video_model="omni-flash-1.2",
    )
    with (
        patch.object(config, "app", test_config),
        patch.object(config, "ui", dict(config.ui, voice_mode="none")),
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
        app.session_state["video_source_select_en"] = "useapi"
        app.run()

        # Omni 1.2 Flash offers its own 3-10 second clip range.
        clip_duration = _widget_by_key(app.selectbox, "video_clip_duration_select")
        assert clip_duration.options == [str(value) for value in range(3, 11)]
        assert any(
            "Gemini Omni 1.2 Flash (Google Flow)" in str(item.value)
            for item in app.warning
        )

        _widget_by_key(app.button, "generate_video_button").click().run()
        assert submit_generation.call_count == 0
        assert any("confirm" in str(item.value).lower() for item in app.error)

        _widget_by_key(app.checkbox, "useapi_confirm_charge").check().run()
        _widget_by_key(app.button, "generate_video_button").click().run()

        assert submit_generation.call_count == 1
        submitted_params = submit_generation.call_args.kwargs["params"]
        assert submitted_params.video_source == "useapi"
        assert "useapi-secret" not in submitted_params.model_dump_json()
        assert [str(item.value) for item in app.exception] == []


def test_useapi_settings_show_token_and_model_choice():
    values = {
        "llm_provider": "openai",
        "useapi_api_token": "review-only-fake-token",
        "useapi_video_model": "seedance-2.0-fast",
    }
    with (
        patch.object(config, "app", values),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()
        app.session_state["settings_dialog_open"] = True
        app.session_state["settings_dialog_target_tab"] = "video"
        app.session_state["settings_material_providers"] = {"ai_video": "useapi"}
        app.run()

        assert not app.exception
        token = app.text_input(key="useapi_api_token_input")
        assert token.value == "review-only-fake-token"
        assert "utm_source=moneyprinterturbo" in token.label
        model = app.selectbox(key="useapi_video_model_select_en")
        assert model.value == "seedance-2.0-fast"
        assert model.options == [
            useapi.model_label(model_id) for model_id in useapi.MODELS
        ]
        assert model.options[:2] == [
            "Veo 3.1 Lite (Google Flow)",
            "Veo 3.1 Lite low priority (0 credits on Ultra $199)",
        ]
        assert "Gemini Omni 1.2 Flash (Google Vids)" in model.options
        model.select("veo-3.1-lite").run()
        assert values["useapi_video_model"] == "veo-3.1-lite"
        assert values["useapi_api_token"] == "review-only-fake-token"


def test_useapi_image_settings_share_the_token_with_the_video_section():
    values = {
        "llm_provider": "openai",
        "useapi_api_token": "first-fake-token",
        "useapi_image_model": "nano-banana-pro",
    }
    with (
        patch.object(config, "app", values),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()
        app.session_state["settings_dialog_open"] = True
        app.session_state["settings_dialog_target_tab"] = "image"
        app.session_state["settings_material_providers"] = {
            "ai_video": "useapi",
            "ai_image": "useapi_image",
        }
        app.run()

        assert not app.exception
        model = app.selectbox(key="useapi_image_model_select_en")
        assert model.value == "nano-banana-pro"
        assert model.options == [
            "Nano Banana 2 Lite (Google Flow)",
            "Nano Banana 2.1 (Google Flow)",
            "Nano Banana Pro (Google Flow)",
            "Kling Kolors 3.0 (Kling)",
            "Kling Kolors 2.1 (Kling)",
            "Kling Omni Image 3.0 (Kling)",
            "Kling Omni Image O1 (Kling)",
        ]
        image_token = app.text_input(key="useapi_image_api_token_input")
        video_token = app.text_input(key="useapi_api_token_input")
        assert image_token.value == video_token.value == "first-fake-token"

        image_token.set_value(" second-fake-token ").run()
        assert values["useapi_api_token"] == "second-fake-token"
        assert app.text_input(key="useapi_api_token_input").value == "second-fake-token"
        assert values["useapi_api_token"] == "second-fake-token"

        model.select("nano-banana-2").run()
        assert values["useapi_image_model"] == "nano-banana-2"
        assert not app.exception


def _submit_image_task(image_model, confirm=False):
    test_config = dict(
        config.app,
        llm_provider="openai",
        video_source="pexels",
        useapi_api_token="useapi-secret",
        useapi_image_model=image_model,
    )
    with (
        patch.object(config, "app", test_config),
        patch.object(config, "ui", dict(config.ui, voice_mode="none")),
        patch.object(config, "try_save_config", return_value=True),
        patch("app.services.webui_task.submit_generation") as submit_generation,
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()
        _widget_by_key(app.text_area, "video_subject").set_value("Harbor").run()
        _widget_by_key(app.text_area, "video_script").set_value(
            "Boats leave the harbor at dawn."
        ).run()
        _widget_by_key(app.text_area, "video_terms").set_value("harbor, boats").run()
        app.session_state["video_source_select_en"] = "useapi_image"
        app.run()
        confirm_boxes = [
            item for item in app.checkbox
            if str(getattr(item, "key", "")).startswith("useapi_confirm_charge")
        ]
        if confirm and confirm_boxes:
            confirm_boxes[0].check().run()
        _widget_by_key(app.button, "generate_video_button").click().run()
        assert [str(item.value) for item in app.exception] == []
        return submit_generation.call_count, bool(confirm_boxes), app


def test_nano_banana_images_need_no_charge_confirmation():
    submitted, has_confirm, _ = _submit_image_task("nano-banana-2-lite")
    assert has_confirm is False
    assert submitted == 1


def test_kling_images_require_the_charge_confirmation():
    submitted, has_confirm, app = _submit_image_task("kling-kolors-v3-0")
    assert has_confirm is True
    assert submitted == 0
    assert any("confirm" in str(item.value).lower() for item in app.error)

    submitted, _, _ = _submit_image_task("kling-kolors-v3-0", confirm=True)
    assert submitted == 1


def test_useapi_model_labels_are_translated_in_chinese():
    values = {
        "llm_provider": "openai",
        "useapi_api_token": "review-only-fake-token",
        "useapi_video_model": "veo-3.1-fast",
    }
    with (
        patch.object(config, "app", values),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "zh"
        app.run()
        app.session_state["settings_dialog_open"] = True
        app.session_state["settings_dialog_target_tab"] = "video"
        app.session_state["settings_material_providers"] = {"ai_video": "useapi"}
        app.run()

        assert not app.exception
        model = app.selectbox(key="useapi_video_model_select_zh")
        assert model.value == "veo-3.1-fast"
        assert "Veo 3.1 Fast（Google Flow，12 月 5 日停用）" in model.options
        assert "Veo 3.1 Quality（Google Flow，12 月 5 日停用）" in model.options
        assert "Gemini Omni 1.1 Flash（Google Flow，12 月 5 日停用）" in model.options
        assert "Veo 3.1 Lite 低优先级（Ultra $199 套餐 0 积分）" in model.options
        assert "Veo 3.1 Lite (Google Flow)" in model.options


def _settings_app(values):
    app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
    app.session_state["ui_language"] = "en"
    app.run()
    app.session_state["settings_dialog_open"] = True
    app.session_state["settings_dialog_target_tab"] = "video"
    app.session_state["settings_material_providers"] = {"ai_video": "useapi"}
    app.run()
    return app


def _selectbox_or_none(app, key):
    return next((item for item in app.selectbox if str(item.key) == key), None)


def test_resolution_and_upscale_dropdowns_follow_the_model():
    values = {
        "llm_provider": "openai",
        "useapi_api_token": "review-only-fake-token",
        "useapi_video_model": "omni-flash-1.2",
    }
    with (
        patch.object(config, "app", values),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = _settings_app(values)
        assert not app.exception
        resolution = _selectbox_or_none(app, "useapi_resolution_select_omni-flash-1.2_en")
        upscale = _selectbox_or_none(app, "useapi_upscale_select_omni-flash-1.2_en")
        assert resolution.options == ["720p", "360p"]
        assert resolution.value == "720p"
        assert upscale.options == ["None (default)", "1080p", "4K"]
        assert upscale.value == ""

        resolution.select("360p").run()
        upscale = _selectbox_or_none(app, "useapi_upscale_select_omni-flash-1.2_en")
        assert upscale.options == ["None (default)", "720p", "1080p", "4K"]
        upscale.select("1080p").run()
        assert values["useapi_resolution"] == "360p"
        assert values["useapi_upscale"] == "1080p"

        app.selectbox(key="useapi_video_model_select_en").select("vids-omni-flash-1.2").run()
        resolution = _selectbox_or_none(app, "useapi_resolution_select_vids-omni-flash-1.2_en")
        assert resolution.options == ["1080p", "720p"]
        assert resolution.value == "1080p"
        assert values["useapi_resolution"] == "1080p"
        assert _selectbox_or_none(app, "useapi_upscale_select_vids-omni-flash-1.2_en") is None

        app.selectbox(key="useapi_video_model_select_en").select("kling-v3-0").run()
        resolution = _selectbox_or_none(app, "useapi_resolution_select_kling-v3-0_en")
        assert resolution.options == ["720p (std)", "1080p (pro)", "4K"]
        assert _selectbox_or_none(app, "useapi_upscale_select_kling-v3-0_en") is None

        app.selectbox(key="useapi_video_model_select_en").select("veo-3.1-lite").run()
        assert _selectbox_or_none(app, "useapi_resolution_select_veo-3.1-lite_en") is None
        upscale = _selectbox_or_none(app, "useapi_upscale_select_veo-3.1-lite_en")
        assert upscale.options == ["None (default)", "1080p", "4K"]
        assert not app.exception


def test_4k_upscale_still_needs_the_charge_confirmation():
    test_config = dict(
        config.app,
        llm_provider="openai",
        video_source="pexels",
        useapi_api_token="useapi-secret",
        useapi_video_model="veo-3.1-lite",
        useapi_upscale="4K",
    )
    with (
        patch.object(config, "app", test_config),
        patch.object(config, "ui", dict(config.ui, voice_mode="none")),
        patch.object(config, "try_save_config", return_value=True),
        patch("app.services.webui_task.submit_generation") as submit_generation,
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()
        _widget_by_key(app.text_area, "video_subject").set_value("Lake").run()
        _widget_by_key(app.text_area, "video_script").set_value("A quiet lake.").run()
        _widget_by_key(app.text_area, "video_terms").set_value("quiet lake").run()
        app.session_state["video_source_select_en"] = "useapi"
        app.run()
        _widget_by_key(app.button, "generate_video_button").click().run()
        assert submit_generation.call_count == 0
        _widget_by_key(app.checkbox, "useapi_confirm_charge").check().run()
        _widget_by_key(app.button, "generate_video_button").click().run()
        assert submit_generation.call_count == 1
