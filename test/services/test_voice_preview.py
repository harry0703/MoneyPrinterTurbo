import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import voice_preview


class TestVoicePreviewService(unittest.TestCase):
    def test_generate_preview_audio_rejects_empty_text(self):
        with self.assertRaises(ValueError):
            voice_preview.generate_preview_audio("", "zh-CN-XiaoxiaoNeural-Female", 1.0, 1.0)

    def test_generate_preview_audio_rejects_long_text(self):
        with self.assertRaises(ValueError):
            voice_preview.generate_preview_audio("x" * 501, "zh-CN-XiaoxiaoNeural-Female", 1.0, 1.0)

    def test_generate_preview_audio_returns_generated_file(self):
        def fake_tts(text, voice_name, voice_rate, voice_file, voice_volume=1.0):
            Path(voice_file).parent.mkdir(parents=True, exist_ok=True)
            Path(voice_file).write_bytes(b"preview")
            return object()

        with patch("app.services.voice_preview.voice.tts", side_effect=fake_tts):
            preview_path = voice_preview.generate_preview_audio(
                "Texto de prueba",
                "zh-CN-XiaoxiaoNeural-Female",
                1.0,
                1.0,
            )

        self.assertTrue(os.path.exists(preview_path))


if __name__ == "__main__":
    unittest.main()