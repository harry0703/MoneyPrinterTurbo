"""WebUI wiring for useapi.net voices and Google Flow Music background music."""

import json
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import useapi_audio, useapi_flowmusic


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
I18N_DIR = ROOT_DIR / "webui" / "i18n"
CATALOG = [
    {"speaker_id": "voice_1", "name": "Narrator", "emotions": ["happy", "sad"]},
    {"speaker_id": "voice_2", "name": "Storyteller", "emotions": []},
]


def _translation(locale, key):
    data = json.loads((I18N_DIR / f"{locale}.json").read_text(encoding="utf-8"))
    return data["Translation"][key]


def _widgets(elements, key):
    return [
        item
        for item in elements
        if str(getattr(item, "key", "")) == key
        or str(getattr(item, "key", "")).startswith(f"{key}_")
    ]


def _widget(elements, key):
    found = _widgets(elements, key)
    assert found, f"widget not found: {key}"
    return found[0]


def _app(app_settings, locale="en"):
    app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
    app.session_state["ui_language"] = locale
    return app


def _run(token="", ui=None):
    app_settings = dict(config.app, useapi_api_token=token, useapi_kling_tts_emotion="")
    # A positive volume: earlier tests may leave a saved volume of 0, which
    # disables background music and hides its notices.
    ui_settings = {**config.ui, "voice_mode": "tts", "bgm_volume": 0.2, **(ui or {})}
    patches = (
        patch.object(config, "app", app_settings),
        patch.object(config, "ui", ui_settings),
        patch.object(config, "save_config"),
        patch.object(useapi_audio, "kling_voices", return_value=CATALOG),
    )
    return app_settings, patches


def test_vids_voices_show_the_token_input_and_all_30_voices():
    app_settings, patches = _run(token="tok-A")
    with patches[0], patches[1], patches[2], patches[3] as kling_voices:
        app = _app(app_settings)
        app.run()
        _widget(app.selectbox, "tts_server_select").set_value("useapi-vids").run()

        token_input = _widget(app.text_input, "useapi_tts_api_token_input")
        assert token_input.value == "tok-A"
        assert token_input.label == _translation("en", "useapi.net Audio API Token")
        voice_select = _widget(app.selectbox, "speech_synthesis_select_useapi-vids")
        assert len(voice_select.options) == 30
        assert "Holt (Informative)" in voice_select.options
        # Google Vids has no speed setting.
        assert _widget(app.selectbox, "voice_rate_select").disabled
        kling_voices.assert_not_called()
    assert [str(item.value) for item in app.exception] == []


def test_kling_voices_load_with_the_token_and_offer_the_voice_emotions():
    app_settings, patches = _run(token="tok-A")
    with patches[0], patches[1], patches[2], patches[3] as kling_voices:
        app = _app(app_settings)
        app.run()
        _widget(app.selectbox, "tts_server_select").set_value("useapi-kling").run()

        kling_voices.assert_called_once_with("tok-A")
        voice_select = _widget(app.selectbox, "speech_synthesis_select_useapi-kling")
        assert voice_select.options == ["Narrator", "Storyteller"]
        assert not _widget(app.selectbox, "voice_rate_select").disabled

        emotion = _widget(app.selectbox, "useapi_kling_emotion_select_voice_1")
        assert emotion.options == ["Default", "happy", "sad"]
        emotion.set_value("happy").run()
        assert app_settings["useapi_kling_tts_emotion"] == "happy"

        # A voice without emotions clears a saved emotion it cannot use.
        _widget(app.selectbox, "speech_synthesis_select_useapi-kling").set_value(
            "useapi-kling:voice_2:Storyteller"
        ).run()
        assert not _widgets(app.selectbox, "useapi_kling_emotion_select_voice_2")
        assert app_settings["useapi_kling_tts_emotion"] == ""
        # The catalog is cached for the session, not reloaded on every rerun.
        kling_voices.assert_called_once()
    assert [str(item.value) for item in app.exception] == []


def test_kling_without_a_token_makes_no_request():
    app_settings, patches = _run(token="")
    with (
        patches[0], patches[1], patches[2], patches[3] as kling_voices,
        patch.dict("os.environ", {"USEAPI_TOKEN": ""}),
    ):
        app = _app(app_settings)
        app.run()
        _widget(app.selectbox, "tts_server_select").set_value("useapi-kling").run()
        assert _widget(app.text_input, "useapi_tts_api_token_input").value == ""
        kling_voices.assert_not_called()
    assert [str(item.value) for item in app.exception] == []


def test_kling_voice_load_failure_is_shown():
    app_settings, patches = _run(token="tok-A")
    with patches[0], patches[1], patches[2], patch.object(
        useapi_audio,
        "kling_voices",
        side_effect=useapi_audio.UseAPIAudioError("HTTP 401, Unauthorized"),
    ):
        app = _app(app_settings)
        app.run()
        _widget(app.selectbox, "tts_server_select").set_value("useapi-kling").run()
        errors = [item.value for item in app.error]
        assert any("HTTP 401, Unauthorized" in str(error) for error in errors)
    assert [str(item.value) for item in app.exception] == []


def test_editing_the_token_saves_it():
    app_settings, patches = _run(token="tok-A")
    with patches[0], patches[1], patches[2], patches[3]:
        app = _app(app_settings)
        app.run()
        _widget(app.selectbox, "tts_server_select").set_value("useapi-vids").run()
        _widget(app.text_input, "useapi_tts_api_token_input").set_value(" tok-B ").run()
        assert app_settings["useapi_api_token"] == "tok-B"
        assert _widget(app.text_input, "useapi_tts_api_token_input").value == "tok-B"


def test_flow_music_source_shows_token_prompt_model_and_credit_notice():
    for locale in ("en", "zh"):
        app_settings, patches = _run(token="tok-A", ui={"voice_mode": "none"})
        with patches[0], patches[1], patches[2], patches[3]:
            app = _app(app_settings, locale=locale)
            app.run()
            _widget(app.selectbox, "bgm_type_select").set_value("flowmusic").run()

            token_input = _widget(app.text_input, "useapi_music_api_token_input")
            assert token_input.value == "tok-A"
            prompt = _widget(app.text_input, "flowmusic_prompt_input")
            assert prompt.label == _translation(locale, "Flow Music Prompt")
            model = _widget(app.selectbox, "flowmusic_model_select")
            assert model.options == ["Lyria 3.5", "Lyria 3 Pro"]
            infos = [str(item.value) for item in app.info]
            assert _translation(locale, "Flow Music Credits Notice") in infos
            model.set_value("lyria-3-pro").run()
            assert app_settings["useapi_flowmusic_model"] == "lyria-3-pro"
        assert [str(item.value) for item in app.exception] == []


def test_voice_and_music_share_one_token_input():
    app_settings, patches = _run(token="tok-A")
    with patches[0], patches[1], patches[2], patches[3]:
        app = _app(app_settings)
        app.run()
        _widget(app.selectbox, "tts_server_select").set_value("useapi-vids").run()
        _widget(app.selectbox, "bgm_type_select").set_value("flowmusic").run()
        assert len(_widgets(app.text_input, "useapi_tts_api_token_input")) == 1
        assert not _widgets(app.text_input, "useapi_music_api_token_input")
        captions = [str(item.value) for item in app.caption]
        assert _translation("en", "useapi.net Audio API Token Shared") in captions
    assert [str(item.value) for item in app.exception] == []


def test_flow_music_connection_button_reports_the_account_count():
    app_settings, patches = _run(token="tok-A", ui={"voice_mode": "none"})
    with (
        patches[0], patches[1], patches[2], patches[3],
        patch.object(useapi_flowmusic, "test_connection", return_value=2),
    ):
        app = _app(app_settings)
        app.run()
        _widget(app.selectbox, "bgm_type_select").set_value("flowmusic").run()
        _widget(app.button, "test_flowmusic_connection_button").click().run()
        successes = [str(item.value) for item in app.success]
        assert (
            _translation("en", "Flow Music Connection Test Succeeded").format(count=2)
            in successes
        )


def test_flow_music_without_a_token_warns():
    app_settings, patches = _run(token="", ui={"voice_mode": "none"})
    with (
        patches[0], patches[1], patches[2], patches[3],
        patch.dict("os.environ", {"USEAPI_TOKEN": ""}),
    ):
        app = _app(app_settings)
        app.run()
        _widget(app.selectbox, "bgm_type_select").set_value("flowmusic").run()
        warnings = [str(item.value) for item in app.warning]
        assert _translation("en", "Flow Music Token Required") in warnings


def test_provider_tips_link_to_useapi_with_tracking_and_say_third_party():
    for locale in ("en", "zh"):
        for provider in ("useapi-kling", "useapi-vids"):
            tip = _translation(locale, f"tts_provider_tips.{provider}")
            assert "utm_source=moneyprinterturbo" in tip
            assert "useapi.net" in tip
            assert "unofficial" not in tip.lower()
        label = _translation(locale, "useapi.net Audio API Token")
        assert "useapi.net/docs/start-here/setup-useapi?utm_source=moneyprinterturbo" in label
    assert "third-party" in _translation("en", "tts_provider_tips.useapi-kling")
