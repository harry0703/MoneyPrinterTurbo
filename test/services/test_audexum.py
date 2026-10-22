"""Tests for the Audexum TTS provider (OpenAI-compatible /audio/speech)."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import voice as vs


class _FakeClip:
    duration = 3.0

    def close(self):
        pass


class _FakeResponse:
    status_code = 200
    content = b"\xff" * 200
    text = ""


class TestAudexum(unittest.TestCase):
    def test_voice_helpers(self):
        self.assertTrue(vs.is_audexum_voice("audexum:Nova"))
        self.assertFalse(vs.is_audexum_voice("kokoro:af_heart"))
        self.assertFalse(vs.is_audexum_voice(None))
        voices = vs.get_audexum_voices()
        self.assertIn("audexum:Nova", voices)
        self.assertTrue(all(vs.is_audexum_voice(v) for v in voices))
        self.assertFalse(vs.is_azure_v1_voice("audexum:Nova"))

    def test_dispatch_strips_prefix(self):
        with patch.object(vs, "audexum_tts", return_value="ok") as tts:
            result = vs.tts("Hi.", "audexum:Atlas", 1.0, "out.mp3", 1.0)
        self.assertEqual(result, "ok")
        self.assertEqual(tts.call_args.args[1], "Atlas")

    def test_missing_api_key_returns_none(self):
        with patch.object(vs.config, "audexum", {}), patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(vs.audexum_tts("Hi.", "Nova", "out.mp3"))

    @patch("app.services.voice._validate_remote_tts_audio", new=lambda _path: None)
    def test_request_shape_and_success(self):
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None, allow_redirects=True):
            captured.update(url=url, json=json, headers=headers)
            return _FakeResponse()

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(vs.config, "audexum", {"api_key": "sk_live_test"}), \
             patch.object(vs.requests, "post", side_effect=fake_post), \
             patch.object(vs, "AudioFileClip", return_value=_FakeClip()):
            result = vs.audexum_tts("Hi.", "Nova", str(Path(tmp) / "a.mp3"), voice_rate=1.2)

        self.assertIsNotNone(result)
        self.assertEqual(captured["url"], "https://audexum.com/v1/audio/speech")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer sk_live_test")
        self.assertEqual(captured["json"]["voice"], "Nova")
        self.assertAlmostEqual(captured["json"]["speed"], 1.2)


if __name__ == "__main__":
    unittest.main()
