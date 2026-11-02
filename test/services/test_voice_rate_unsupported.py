"""Gemini TTS, MiMo TTS and VoxCPM have no speech speed setting to send.

No provider is called: the Gemini and MiMo clients are mocked.
"""

import base64
import io
import wave
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, sentinel

import pytest

from app.services import voice

TEXT = "The ocean covers most of our planet."
# 0.2 s of 24 kHz 16-bit mono silence, the PCM format Gemini TTS returns.
PCM_SILENCE = bytes(9600)


@pytest.fixture
def logged_warnings():
    messages = []
    sink = voice.logger.add(
        lambda message: messages.append(message.record["message"]), level="WARNING"
    )
    yield messages
    voice.logger.remove(sink)


def _narrate_with_gemini(tmp_path, voice_rate):
    """Narrate TEXT through voice.tts() and return the Gemini request."""
    part = SimpleNamespace(inline_data=SimpleNamespace(data=PCM_SILENCE))
    response = SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))]
    )
    with (
        patch("google.genai.Client") as client,
        patch.dict(voice.config.app, {"gemini_api_key": "test-key"}),
    ):
        generate = client.return_value.__enter__.return_value.models.generate_content
        generate.return_value = response
        sub_maker = voice.tts(
            TEXT, "gemini:Zephyr-Bright", voice_rate, str(tmp_path / "gemini.mp3")
        )

    assert sub_maker is not None
    generate.assert_called_once()
    request = generate.call_args.kwargs
    return request["model"], request["contents"], request["config"].model_dump()


def _narrate_with_mimo(tmp_path, voice_rate):
    """Narrate TEXT through voice.tts() and return the MiMo request."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(PCM_SILENCE)
    audio = {"data": base64.b64encode(buffer.getvalue()).decode("ascii")}
    client = MagicMock()
    client.__enter__.return_value = client
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(audio=audio))]
    )
    with (
        patch.object(voice, "OpenAI", return_value=client),
        patch.dict(voice.config.app, {"mimo_api_key": "test-key"}),
    ):
        sub_maker = voice.tts(
            TEXT, "mimo:mimo_default-Female", voice_rate, str(tmp_path / "mimo.wav")
        )

    assert sub_maker is not None
    client.chat.completions.create.assert_called_once()
    return client.chat.completions.create.call_args.kwargs


def test_gemini_logs_that_a_requested_speed_is_ignored(tmp_path, logged_warnings):
    normal_request = _narrate_with_gemini(tmp_path, 1.0)
    assert logged_warnings == []

    assert _narrate_with_gemini(tmp_path, 1.5) == normal_request
    assert logged_warnings == [
        "Gemini TTS does not support numeric speed adjustment; voice_rate 1.5 is ignored"
    ]


def test_mimo_logs_that_a_requested_speed_is_ignored(tmp_path, logged_warnings):
    normal_request = _narrate_with_mimo(tmp_path, 1.0)
    assert normal_request["audio"] == {"format": "wav", "voice": "mimo_default"}
    assert logged_warnings == []

    assert _narrate_with_mimo(tmp_path, 2.0) == normal_request
    assert logged_warnings == [
        "MiMo TTS does not support numeric speed adjustment; voice_rate 2.0 is ignored"
    ]


@pytest.mark.parametrize(
    ("voice_name", "provider_function", "provider"),
    [
        ("gemini:Zephyr-Bright", "gemini_tts", "Gemini TTS"),
        ("mimo:mimo_default-Female", "mimo_tts", "MiMo TTS"),
        ("voxcpm:default", "voxcpm_tts", "VoxCPM"),
    ],
)
@pytest.mark.parametrize("voice_rate", [0.8, 1.0, None])
def test_providers_without_a_speed_setting_warn_only_for_another_speed(
    tmp_path, logged_warnings, voice_name, provider_function, provider, voice_rate
):
    with patch.object(voice, provider_function, return_value=sentinel.narration):
        result = voice.tts(TEXT, voice_name, voice_rate, str(tmp_path / "voice.mp3"))

    assert result is sentinel.narration
    warning = (
        f"{provider} does not support numeric speed adjustment; "
        "voice_rate 0.8 is ignored"
    )
    assert logged_warnings == ([warning] if voice_rate == 0.8 else [])


@pytest.mark.parametrize(
    ("voice_name", "provider_function"),
    [
        ("en-US-AriaNeural", "azure_tts_v1"),
        ("siliconflow:FunAudioLLM/CosyVoice2-0.5B:alex-Male", "siliconflow_tts"),
    ],
)
def test_providers_with_a_speed_setting_get_the_rate_without_a_warning(
    tmp_path, logged_warnings, voice_name, provider_function
):
    with patch.object(
        voice, provider_function, return_value=sentinel.narration
    ) as synthesize:
        result = voice.tts(TEXT, voice_name, 1.5, str(tmp_path / "voice.mp3"))

    assert result is sentinel.narration
    assert 1.5 in synthesize.call_args.args
    assert logged_warnings == []
