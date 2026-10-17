from unittest.mock import patch
from pathlib import Path
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

def test_hi_in_applies_default_hindi_voice_for_azure_v1():
    test_ui_config = dict(config.ui, language="en", voice_name="", tts_server="azure-tts-v1")
    
    with (
        patch.object(config, "ui", test_ui_config),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.run()
        
        # Switch to hi-IN
        _widget_by_key(app.selectbox, "script_language_select").set_value("hi-IN")
        app.run()
        
        voice_widget = _widget_by_key(app.selectbox, "speech_synthesis_select_azure-tts-v1")
        assert voice_widget.value.lower().startswith("hi-in")

def test_hi_in_applies_default_hindi_voice_for_azure_v2():
    test_ui_config = dict(config.ui, language="en", voice_name="", tts_server="azure-tts-v2")
    
    with (
        patch.object(config, "ui", test_ui_config),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.run()
        
        # Switch to hi-IN
        _widget_by_key(app.selectbox, "script_language_select").set_value("hi-IN")
        app.run()
        
        voice_widget = _widget_by_key(app.selectbox, "speech_synthesis_select_azure-tts-v2")
        assert not voice_widget.value.lower().startswith("hi-in")
        assert voice.is_azure_v2_voice(voice_widget.value)

def test_hi_in_preserves_explicit_voice_selection():
    explicit_voice = "en-US-JennyNeural-Female"
    test_ui_config = dict(config.ui, language="en", voice_name=explicit_voice, tts_server="azure-tts-v1")
    
    with (
        patch.object(config, "ui", test_ui_config),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.run()
        
        # Switch to hi-IN
        _widget_by_key(app.selectbox, "script_language_select").set_value("hi-IN")
        app.run()
        
        voice_widget = _widget_by_key(app.selectbox, "speech_synthesis_select_azure-tts-v1")
        assert voice_widget.value == explicit_voice


def test_hi_in_restores_defaults_when_leaving():
    test_ui_config = dict(config.ui, language="en", video_language="en-US", font_name="MicrosoftYaHeiBold.ttc", voice_name="", tts_server="azure-tts-v1")
    
    with (
        patch.object(config, "ui", test_ui_config),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.run()
        
        # Capture pre-hindi voice
        voice_widget = _widget_by_key(app.selectbox, "speech_synthesis_select_azure-tts-v1")
        original_voice = voice_widget.value
        
        # Switch to hi-IN
        _widget_by_key(app.selectbox, "script_language_select").set_value("hi-IN")
        app.run()
        
        voice_widget = _widget_by_key(app.selectbox, "speech_synthesis_select_azure-tts-v1")
        assert voice_widget.value.lower().startswith("hi-in")
        font_widget = _widget_by_key(app.selectbox, "font_name_select")
        assert font_widget.value == "NotoSansDevanagari-Bold.ttf"
        
        # Switch to zh-CN
        _widget_by_key(app.selectbox, "script_language_select").set_value("zh-CN")
        app.run()
        
        # Verify restoration
        font_widget = _widget_by_key(app.selectbox, "font_name_select")
        assert font_widget.value == "MicrosoftYaHeiBold.ttc"
        voice_widget = _widget_by_key(app.selectbox, "speech_synthesis_select_azure-tts-v1")
        assert voice_widget.value == original_voice

def test_hi_in_preserves_explicit_selection_equal_to_fallback():
    # Simulate an explicit choice of the English fallback voice
    explicit_voice = "en-AU-NatashaNeural-Female"
    test_ui_config = dict(config.ui, language="en", video_language="en-US", font_name="MicrosoftYaHeiBold.ttc", voice_name=explicit_voice, tts_server="azure-tts-v1")
    
    with (
        patch.object(config, "ui", test_ui_config),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.run()
        
        # Switch to hi-IN
        _widget_by_key(app.selectbox, "script_language_select").set_value("hi-IN")
        app.run()
        
        voice_widget = _widget_by_key(app.selectbox, "speech_synthesis_select_azure-tts-v1")
        assert voice_widget.value.lower().startswith("hi-in")
        
        # Switch back to en-US
        _widget_by_key(app.selectbox, "script_language_select").set_value("en-US")
        app.run()
        
        voice_widget = _widget_by_key(app.selectbox, "speech_synthesis_select_azure-tts-v1")
        assert voice_widget.value == explicit_voice
