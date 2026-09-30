import io
import unittest
import wave
from unittest.mock import Mock, patch
from app.services import voice


def reference_wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 160)
    return output.getvalue()


class TestVoxcpmTruncatedReference(unittest.TestCase):
    def test_truncated_reference_and_prompt_rejected_before_provider_request(self):
        valid = reference_wav()
        for field in ("reference", "prompt"):
            for cut in (44, len(valid) - 2):
                with self.subTest(field=field, cut=cut), patch.dict(voice.config.voxcpm, {"api_key": "test-key", "model_id": "test-model"}), patch.object(voice.requests, "post", return_value=Mock(status_code=400, text="rejected invalid reference")) as post:
                    kwargs = {f"{field}_audio": valid[:cut]}
                    if field == "prompt":
                        kwargs["prompt_text"] = "Reference transcript"
                    result = voice.voxcpm_tts("Hello.", "default", "unused.mp3", **kwargs)
                    self.assertIsNone(result)
                    post.assert_not_called()

    def test_complete_pcm_reference_is_encoded(self):
        encoded = voice._encode_voxcpm_audio_data_uri(reference_wav(), "reference")
        self.assertTrue(encoded.startswith("data:audio/wav;base64,"))
