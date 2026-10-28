"""Offline Gemini response diagnostics; no provider calls or narration logging."""

from unittest.mock import patch

import pytest
from google.genai import types
from pydub import AudioSegment

from app.services import voice


@pytest.mark.parametrize(
    "payload, finish_reason, block_reason",
    [
        ({"prompt_feedback": {"block_reason": "SAFETY"}}, "None", "SAFETY"),
        ({"candidates": []}, "None", "None"),
        ({"candidates": [{"finish_reason": "SAFETY"}]}, "SAFETY", "None"),
        (
            {"candidates": [{"finish_reason": "MAX_TOKENS", "content": {}}]},
            "MAX_TOKENS",
            "None",
        ),
        (
            {"candidates": [{"finish_reason": "STOP", "content": {"parts": []}}]},
            "STOP",
            "None",
        ),
        (
            {
                "candidates": [
                    {
                        "finish_reason": "STOP",
                        "content": {
                            "parts": [{"text": "private provider response"}],
                        },
                    }
                ]
            },
            "STOP",
            "None",
        ),
        (
            {
                "candidates": [
                    {
                        "finish_reason": "OTHER",
                        "content": {
                            "parts": [
                                {"inline_data": {"mime_type": "audio/pcm", "data": b""}}
                            ],
                        },
                    }
                ]
            },
            "OTHER",
            "None",
        ),
    ],
)
def test_empty_audio_reports_provider_reason_without_overwriting_narration(
    tmp_path,
    payload,
    finish_reason,
    block_reason,
):
    response = types.GenerateContentResponse(**payload)
    output = tmp_path / "narration.mp3"
    output.write_bytes(b"previous narration")
    messages = []
    sink = voice.logger.add(lambda message: messages.append(message.record["message"]))
    try:
        with (
            patch("google.genai.Client") as client,
            patch.dict(voice.config.app, {"gemini_api_key": "private-test-key"}),
            patch.object(AudioSegment, "from_file") as decode,
        ):
            generate = (
                client.return_value.__enter__.return_value.models.generate_content
            )
            generate.return_value = response
            result = voice.gemini_tts("private narration", "Achird", 1, str(output))
            generate.assert_called_once()
            decode.assert_not_called()
    finally:
        voice.logger.remove(sink)

    assert result is None
    assert output.read_bytes() == b"previous narration"
    assert list(tmp_path.iterdir()) == [output]
    diagnostic = next(
        (message for message in messages if "finish_reason=" in message), ""
    )
    assert finish_reason in diagnostic.split("prompt_block_reason=")[0]
    assert block_reason in diagnostic.split("prompt_block_reason=")[-1]
    logs = "\n".join(messages)
    assert "private narration" not in logs
    assert "private provider response" not in logs
    assert "private-test-key" not in logs
    assert "Gemini TTS failed" not in logs
