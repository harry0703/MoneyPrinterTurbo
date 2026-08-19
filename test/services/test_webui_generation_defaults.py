from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import voice


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


def _widget_by_key(elements, key):
    return next(
        item
        for item in elements
        if str(getattr(item, "key", "")) == key
        or str(getattr(item, "key", "")).startswith(f"{key}_")
    )


def _new_app():
    # A cold Python 3.11 environment can spend over 30 seconds importing the
    # full Streamlit entrypoint and optional media stack. Keep the assertion
    # timeout above that one-time startup cost so targeted runs do not flake.
    app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
    app.session_state["ui_language"] = "en"
    app.run()
    assert [str(item.value) for item in app.exception] == []
    return app


def test_reusable_generation_settings_survive_a_new_webui_session():
    """Reusable controls should persist while per-video content stays session-only."""
    test_app_config = dict(
        config.app,
        video_source="pexels",
        match_materials_to_script=False,
    )
    test_ui_config = dict(
        config.ui,
        language="en",
        voice_mode="tts",
        tts_server="azure-tts-v1",
        voice_name="en-US-JennyNeural-Female",
    )

    with (
        patch.object(config, "app", test_app_config),
        patch.object(config, "ui", test_ui_config),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(
            voice,
            "get_all_azure_voices",
            return_value=["en-US-JennyNeural-Female"],
        ),
    ):
        first_session = _new_app()
        _widget_by_key(first_session.text_area, "video_subject").set_value(
            "One-off subject"
        )
        _widget_by_key(first_session.text_area, "video_script").set_value(
            "One-off script"
        )
        _widget_by_key(first_session.text_area, "video_terms").set_value(
            "one-off, keywords"
        )
        _widget_by_key(first_session.selectbox, "script_language_select").set_value(
            "en-US"
        )
        _widget_by_key(first_session.slider, "paragraph_number_input").set_value(3)
        _widget_by_key(first_session.text_area, "video_script_prompt").set_value(
            "Keep the hook concise."
        )
        _widget_by_key(first_session.text_area, "custom_system_prompt").set_value(
            "Write a factual short-video script."
        )
        _widget_by_key(first_session.selectbox, "video_concat_mode_select").set_value(
            "sequential"
        )
        _widget_by_key(
            first_session.selectbox, "video_transition_mode_select"
        ).set_value("FadeIn")
        _widget_by_key(first_session.selectbox, "video_aspect_for_pexels").set_value(
            "16:9"
        )
        _widget_by_key(first_session.selectbox, "video_clip_duration_select").set_value(
            7
        )
        _widget_by_key(first_session.slider, "video_clip_speed_slider").set_value(1.5)
        _widget_by_key(first_session.selectbox, "video_count_select").set_value(3)
        _widget_by_key(first_session.selectbox, "voice_volume_select").set_value(1.5)
        _widget_by_key(first_session.selectbox, "voice_rate_select").set_value(1.2)
        _widget_by_key(first_session.selectbox, "bgm_type_select").set_value("custom")
        _widget_by_key(first_session.checkbox, "subtitle_enabled_checkbox").set_value(
            True
        )
        _widget_by_key(first_session.color_picker, "stroke_color_picker").set_value(
            "#123456"
        )
        _widget_by_key(first_session.slider, "stroke_width_slider").set_value(2.5)
        first_session.run()

        # Aspect is a per-source preference: Coverr's common landscape default
        # must not replace an explicit portrait choice or the Pexels preference.
        _widget_by_key(first_session.selectbox, "video_source_select").set_value(
            "coverr"
        ).run()
        _widget_by_key(first_session.selectbox, "video_aspect_for_coverr").set_value(
            "9:16"
        ).run()
        _widget_by_key(first_session.selectbox, "video_source_select").set_value(
            "pexels"
        ).run()

        _widget_by_key(first_session.selectbox, "bgm_volume_select").set_value(0.4)
        _widget_by_key(first_session.text_input, "custom_bgm_file_input").set_value(
            "example.mp3"
        )
        first_session.run()
        _widget_by_key(first_session.selectbox, "bgm_type_select").set_value(
            "sonilo"
        ).run()
        _widget_by_key(
            first_session.text_input, "sonilo_bgm_prompt_input"
        ).set_value("Bright acoustic underscore").run()
        _widget_by_key(first_session.selectbox, "bgm_type_select").set_value(
            "elevenlabs"
        ).run()
        _widget_by_key(
            first_session.text_input, "elevenlabs_music_prompt_input"
        ).set_value("Calm cinematic underscore").run()
        _widget_by_key(first_session.selectbox, "bgm_type_select").set_value(
            "custom"
        ).run()
        assert [str(item.value) for item in first_session.exception] == []

        expected_defaults = {
            "video_language": "en-US",
            "paragraph_number": 3,
            "video_script_prompt": "Keep the hook concise.",
            "custom_system_prompt": "Write a factual short-video script.",
            "video_concat_mode": "sequential",
            "video_transition_mode": "FadeIn",
            "video_aspect_pexels": "16:9",
            "video_aspect_coverr": "9:16",
            "video_clip_duration": 7,
            "video_clip_speed": 1.5,
            "video_count": 3,
            "voice_volume": 1.5,
            "voice_rate": 1.2,
            "bgm_type": "custom",
            "bgm_volume": 0.4,
            "custom_bgm_file": "example.mp3",
            "sonilo_bgm_prompt": "Bright acoustic underscore",
            "elevenlabs_music_prompt": "Calm cinematic underscore",
            "subtitle_enabled": True,
            "stroke_color": "#123456",
            "stroke_width": 2.5,
        }
        assert {key: test_ui_config.get(key) for key in expected_defaults} == (
            expected_defaults
        )
        assert "video_subject" not in test_ui_config
        assert "video_script" not in test_ui_config
        assert "video_terms" not in test_ui_config
        assert "video_subject" not in test_app_config
        assert "video_script" not in test_app_config
        assert "video_terms" not in test_app_config

        second_session = _new_app()
        assert _widget_by_key(
            second_session.selectbox, "script_language_select"
        ).value == "en-US"
        assert _widget_by_key(
            second_session.slider, "paragraph_number_input"
        ).value == 3
        assert _widget_by_key(
            second_session.text_area, "video_script_prompt"
        ).value == "Keep the hook concise."
        assert _widget_by_key(
            second_session.text_area, "custom_system_prompt"
        ).value == "Write a factual short-video script."
        assert _widget_by_key(
            second_session.selectbox, "video_concat_mode_select"
        ).value == "sequential"
        assert _widget_by_key(
            second_session.selectbox, "video_transition_mode_select"
        ).value == "FadeIn"
        assert _widget_by_key(
            second_session.selectbox, "video_aspect_for_pexels"
        ).value == "16:9"
        _widget_by_key(second_session.selectbox, "video_source_select").set_value(
            "coverr"
        ).run()
        assert _widget_by_key(
            second_session.selectbox, "video_aspect_for_coverr"
        ).value == "9:16"
        _widget_by_key(second_session.selectbox, "video_source_select").set_value(
            "pexels"
        ).run()
        assert _widget_by_key(
            second_session.selectbox, "video_clip_duration_select"
        ).value == 7
        assert _widget_by_key(
            second_session.slider, "video_clip_speed_slider"
        ).value == 1.5
        assert _widget_by_key(second_session.selectbox, "video_count_select").value == 3
        assert _widget_by_key(
            second_session.selectbox, "voice_volume_select"
        ).value == 1.5
        assert _widget_by_key(
            second_session.selectbox, "voice_rate_select"
        ).value == 1.2
        assert _widget_by_key(second_session.selectbox, "bgm_type_select").value == (
            "custom"
        )
        assert _widget_by_key(second_session.selectbox, "bgm_volume_select").value == (
            0.4
        )
        assert _widget_by_key(
            second_session.text_input, "custom_bgm_file_input"
        ).value == "example.mp3"
        _widget_by_key(second_session.selectbox, "bgm_type_select").set_value(
            "sonilo"
        ).run()
        assert _widget_by_key(
            second_session.text_input, "sonilo_bgm_prompt_input"
        ).value == "Bright acoustic underscore"
        _widget_by_key(second_session.selectbox, "bgm_type_select").set_value(
            "elevenlabs"
        ).run()
        assert _widget_by_key(
            second_session.text_input, "elevenlabs_music_prompt_input"
        ).value == "Calm cinematic underscore"
        assert _widget_by_key(
            second_session.checkbox, "subtitle_enabled_checkbox"
        ).value is True
        assert _widget_by_key(
            second_session.color_picker, "stroke_color_picker"
        ).value == "#123456"
        assert _widget_by_key(second_session.slider, "stroke_width_slider").value == 2.5

        # Per-video content must not leak into a new session.
        assert second_session.session_state["video_subject"] == ""
        assert second_session.session_state["video_script"] == ""
        assert second_session.session_state["video_terms"] == ""

        _widget_by_key(
            second_session.button, "restore_default_system_prompt"
        ).click().run()
        assert test_ui_config["custom_system_prompt"] == ""

        _widget_by_key(
            second_session.button, "restore_default_subtitle_settings"
        ).click().run()
        assert {
            key: test_ui_config[key]
            for key in ("subtitle_enabled", "stroke_color", "stroke_width")
        } == {
            "subtitle_enabled": True,
            "stroke_color": "#000000",
            "stroke_width": 1.5,
        }


def test_invalid_saved_generation_settings_fall_back_without_breaking_webui():
    """Stale or manually edited TOML values must not poison Streamlit widgets."""
    test_app_config = dict(
        config.app,
        video_source="pexels",
        match_materials_to_script=False,
    )
    test_ui_config = dict(
        config.ui,
        language="en",
        voice_mode="tts",
        tts_server="azure-tts-v1",
        voice_name="en-US-JennyNeural-Female",
        video_language="not-a-language",
        paragraph_number=999,
        video_concat_mode="not-a-mode",
        video_transition_mode="not-a-transition",
        video_aspect_pexels="4:3",
        video_clip_duration=999,
        video_clip_speed="nan",
        video_count=True,
        voice_volume=999,
        voice_rate=-1,
        bgm_type="not-a-source",
        bgm_volume=999,
        subtitle_enabled="false",
        stroke_color="not-a-color",
        stroke_width="inf",
        loomloom_candidate_count=0,
        loomloom_script_duration_seconds=9999,
        loomloom_video_scene_count="nan",
    )

    with (
        patch.object(config, "app", test_app_config),
        patch.object(config, "ui", test_ui_config),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(
            voice,
            "get_all_azure_voices",
            return_value=["en-US-JennyNeural-Female"],
        ),
    ):
        app = _new_app()

    assert _widget_by_key(app.selectbox, "script_language_select").value == ""
    assert _widget_by_key(app.slider, "paragraph_number_input").value == 10
    assert _widget_by_key(app.selectbox, "video_concat_mode_select").value == "random"
    assert _widget_by_key(app.selectbox, "video_transition_mode_select").value == (
        "None"
    )
    assert _widget_by_key(app.selectbox, "video_aspect_for_pexels").value == "9:16"
    assert _widget_by_key(app.selectbox, "video_clip_duration_select").value == 3
    assert _widget_by_key(app.slider, "video_clip_speed_slider").value == 1.0
    assert _widget_by_key(app.selectbox, "video_count_select").value == 1
    assert isinstance(test_ui_config["video_count"], int)
    assert not isinstance(test_ui_config["video_count"], bool)
    assert _widget_by_key(app.selectbox, "voice_volume_select").value == 1.0
    assert _widget_by_key(app.selectbox, "voice_rate_select").value == 1.0
    assert _widget_by_key(app.selectbox, "bgm_type_select").value == "random"
    assert _widget_by_key(app.selectbox, "bgm_volume_select").value == 0.2
    assert _widget_by_key(app.checkbox, "subtitle_enabled_checkbox").value is False
    assert _widget_by_key(app.color_picker, "stroke_color_picker").value == "#000000"
    assert _widget_by_key(app.slider, "stroke_width_slider").value == 1.5
    assert app.session_state["loomloom_candidate_count"] == 1
    assert app.session_state["loomloom_script_duration_seconds"] == 600
    assert app.session_state["loomloom_video_scene_count"] == 1


def test_loomloom_tuning_survives_restart_without_persisting_payment_state():
    """Paid-provider tuning is reusable; quotes and confirmations are not."""
    test_app_config = dict(
        config.app,
        video_source="loomloom",
        script_generation_backend="loomloom",
        loomloom_api_token="",
        match_materials_to_script=False,
    )
    test_ui_config = dict(
        config.ui,
        language="en",
        voice_mode="tts",
        tts_server="azure-tts-v1",
        voice_name="en-US-JennyNeural-Female",
    )

    with (
        patch.object(config, "app", test_app_config),
        patch.object(config, "ui", test_ui_config),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(
            voice,
            "get_all_azure_voices",
            return_value=["en-US-JennyNeural-Female"],
        ),
    ):
        first_session = _new_app()
        _widget_by_key(
            first_session.number_input, "loomloom_candidate_count"
        ).set_value(4)
        _widget_by_key(
            first_session.number_input, "loomloom_script_duration_seconds"
        ).set_value(120)
        _widget_by_key(
            first_session.number_input, "loomloom_video_scene_count"
        ).set_value(3)
        first_session.run()

        assert {
            key: test_ui_config.get(key)
            for key in (
                "loomloom_candidate_count",
                "loomloom_script_duration_seconds",
                "loomloom_video_scene_count",
            )
        } == {
            "loomloom_candidate_count": 4,
            "loomloom_script_duration_seconds": 120,
            "loomloom_video_scene_count": 3,
        }
        assert "loomloom_confirm_charge" not in test_ui_config
        assert "loomloom_video_confirm_charge" not in test_ui_config

        second_session = _new_app()
        assert _widget_by_key(
            second_session.number_input, "loomloom_candidate_count"
        ).value == 4
        assert _widget_by_key(
            second_session.number_input, "loomloom_script_duration_seconds"
        ).value == 120
        assert _widget_by_key(
            second_session.number_input, "loomloom_video_scene_count"
        ).value == 3
        assert second_session.session_state["loomloom_video_confirm_charge"] is False


def test_script_order_constraint_does_not_replace_saved_concat_preference():
    """A derived sequential mode must not become the user's reusable default."""
    test_app_config = dict(
        config.app,
        video_source="pexels",
        match_materials_to_script=True,
    )
    test_ui_config = dict(
        config.ui,
        language="en",
        video_concat_mode="random",
        voice_mode="tts",
        tts_server="azure-tts-v1",
        voice_name="en-US-JennyNeural-Female",
    )

    with (
        patch.object(config, "app", test_app_config),
        patch.object(config, "ui", test_ui_config),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(
            voice,
            "get_all_azure_voices",
            return_value=["en-US-JennyNeural-Female"],
        ),
    ):
        constrained_session = _new_app()
        constrained_concat = _widget_by_key(
            constrained_session.selectbox, "video_concat_mode_select"
        )
        assert constrained_concat.value == "sequential"
        assert constrained_concat.disabled is True
        assert test_ui_config["video_concat_mode"] == "random"

        # A later session without the constraint should recover the user's actual
        # preference, not the derived value shown while script-order matching ran.
        test_app_config["match_materials_to_script"] = False
        unconstrained_session = _new_app()
        assert _widget_by_key(
            unconstrained_session.selectbox, "video_concat_mode_select"
        ).value == "random"
