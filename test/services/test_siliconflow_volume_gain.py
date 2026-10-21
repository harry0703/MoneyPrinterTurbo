import math
from unittest.mock import patch

import pytest

from app.services import voice


class _RejectedResponse:
    status_code = 400
    text = "rejected"
    content = b""


@pytest.mark.parametrize(
    "voice_volume, expected_gain",
    [
        (1.0, 0.0),
        (2.0, 20 * math.log10(2.0)),
        (0.6, 20 * math.log10(0.6)),
        (5.0, 10.0),
        (0.1, -10.0),
    ],
)
def test_siliconflow_gain_is_decibels_for_linear_volume(
    voice_volume, expected_gain, tmp_path
):
    # SiliconFlow's gain is in dB. The WebUI preview passes the same linear
    # multiplier that the final mix applies, so the preview must match it.
    payloads = []

    def fake_post(url, json=None, **kwargs):
        payloads.append(json)
        return _RejectedResponse()

    with (
        patch.dict(voice.config.siliconflow, {"api_key": "test-key"}),
        patch.object(voice.requests, "post", side_effect=fake_post),
    ):
        voice.siliconflow_tts(
            "hello",
            "FunAudioLLM/CosyVoice2-0.5B",
            "FunAudioLLM/CosyVoice2-0.5B:alex",
            1.0,
            str(tmp_path / "voice.mp3"),
            voice_volume,
        )

    assert payloads
    assert payloads[0]["gain"] == pytest.approx(expected_gain)
