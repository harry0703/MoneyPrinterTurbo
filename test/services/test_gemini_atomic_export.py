import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from pydub import AudioSegment
from app.services import voice


class TestGeminiAtomicExport(unittest.TestCase):
    def test_failed_encoder_preserves_previous_narration_and_cleans_staging(self):
        tone = AudioSegment.silent(duration=100).set_frame_rate(24000).set_channels(1).set_sample_width(2)
        response = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(inline_data=SimpleNamespace(data=tone.raw_data))]))])
        class Client:
            def __init__(self, **kwargs):
                self.models = SimpleNamespace(generate_content=lambda **kwargs: response)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        def failed_export(segment, out_f, **kwargs):
            Path(out_f).write_bytes(b"partial encoder output")
            raise OSError("encoder failed")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "narration.mp3"
            output.write_bytes(b"previous narration")
            with patch("google.genai.Client", Client), patch.dict(voice.config.app, {"gemini_api_key": "test-key"}), patch.object(AudioSegment, "export", failed_export):
                result = voice.gemini_tts("Hello.", "Zephyr", 1, str(output))
            self.assertIsNone(result)
            self.assertEqual(output.read_bytes(), b"previous narration")
            self.assertEqual(list(Path(tmp).iterdir()), [output])
