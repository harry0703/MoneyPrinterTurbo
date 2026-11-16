import ast
import wave
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import voice
from app.utils import utils


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
LOCALES = utils.load_locales(str(ROOT_DIR / "webui" / "i18n"))


def _sample(language):
    return LOCALES[language]["Translation"]["Voice Example"]


def _load_voice_preview_sample(ui_language):
    """Load the sample picker alone, with tr() bound to one WebUI language."""
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_get_voice_preview_sample"
    )
    module = ast.Module(body=[function], type_ignores=[])
    namespace = {
        "voice": voice,
        "locales": LOCALES,
        "tr": lambda key: LOCALES[ui_language]["Translation"][key],
    }
    exec(compile(module, str(WEBUI_MAIN), "exec"), namespace)
    return namespace["_get_voice_preview_sample"]


@pytest.mark.parametrize(
    "ui_language,voice_name,sample_language",
    [
        # Edge returns no audio for these: each voice gets the sample of the
        # WebUI language on main.
        ("zh", "en-US-JennyNeural-Female", "en"),
        ("zh", "pt-BR-AntonioNeural-Male", "pt"),
        ("zh", "de-DE-KatjaNeural-Female", "de"),
        ("ko", "en-US-JennyNeural-Female", "en"),
        ("ru", "en-US-JennyNeural-Female", "en"),
        ("en", "zh-CN-XiaoxiaoNeural-Female", "zh"),
        ("zh", "zh-TW-HsiaoChenNeural-Female", "zh"),
        ("zh", "zh-CN-XiaoxiaoMultilingualNeural-V2-Female", "zh"),
        # No WebUI language has a sample in Japanese or Arabic.
        ("zh", "ja-JP-NanamiNeural-Female", "en"),
        ("zh", "ar-SA-ZariyahNeural-Female", "en"),
        # Voices of other providers keep the sample of the WebUI language.
        ("zh", "gemini:Puck-Male", "zh"),
        ("en", "siliconflow:FunAudioLLM/CosyVoice2-0.5B:alex-Male", "en"),
    ],
)
def test_edge_voice_sample_is_in_the_language_of_the_voice(
    ui_language, voice_name, sample_language
):
    sample = _load_voice_preview_sample(ui_language)(voice_name)

    assert sample == _sample(sample_language)


def test_voice_sample_button_sends_the_english_sample_for_an_english_voice():
    """With the Chinese WebUI, an en-US voice must not get the Chinese sample."""
    test_ui = dict(
        config.ui,
        voice_mode="tts",
        tts_server="azure-tts-v1",
        voice_name="en-US-JennyNeural-Female",
    )

    def fake_tts(**kwargs):
        with wave.open(kwargs["voice_file"], "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(24000)
            audio.writeframes(bytes(4800))
        return object()

    with (
        patch.object(config, "ui", test_ui),
        patch.object(config, "save_config"),
        patch.object(voice, "tts", side_effect=fake_tts) as synthesize,
        patch.object(voice, "get_audio_duration", return_value=0.1),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "zh"
        app.run()
        next(
            button
            for button in app.button
            if str(getattr(button, "key", "")).startswith("play_voice_button")
        ).click().run()

    synthesize.assert_called_once()
    assert synthesize.call_args.kwargs["voice_name"] == "en-US-JennyNeural-Female"
    assert synthesize.call_args.kwargs["text"] == _sample("en")
    assert len(app.get("audio")) == 1
    assert [item.value for item in app.error] == []
    assert [str(item.value) for item in app.exception] == []
