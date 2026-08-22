"""Tests for Fish Audio TTS integration.

Covers dispatch/model selection, config and environment API keys, request
payloads (prosody, reference_id), 401/402/429 handling, invalid audio
responses, voice helpers, and task restoration via _infer_tts_server_from_voice.
"""

import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import voice as vs


class _FakeClip:
    duration = 4.2

    def close(self):
        pass


class _FakeResponse:
    def __init__(self, status_code=200, content=b"\xff" * 200, text=""):
        self.status_code = status_code
        self.content = content
        self.text = text


class TestFishAudioVoiceHelpers(unittest.TestCase):
    """is_fish_audio_voice / get_fish_audio_voices basics."""

    def test_is_fish_audio_voice_recognizes_prefix(self):
        self.assertTrue(vs.is_fish_audio_voice("fish_audio:default:Default Voice"))
        self.assertTrue(vs.is_fish_audio_voice("fish_audio:abc123:My Voice"))
        self.assertFalse(vs.is_fish_audio_voice("elevenlabs:abc:Rachel"))
        self.assertFalse(vs.is_fish_audio_voice(""))
        self.assertFalse(vs.is_fish_audio_voice(None))

    def test_get_fish_audio_voices_default(self):
        """With no voices configured, returns preset female, male, and default entries."""
        with patch.object(vs.config, "fish_audio", {"voices": []}):
            voices = vs.get_fish_audio_voices()
        self.assertEqual(
            voices,
            [
                "fish_audio:2324c907b9a94c64ab4afb941e5b3408:Clear Female-Female",
                "fish_audio:7b6131ba75ba47c98a46c847db729ab6:Clear Male-Male",
                "fish_audio:default:Default Voice",
            ],
        )

    def test_get_fish_audio_voices_with_configured_entries(self):
        """User-configured voices are appended after the defaults."""
        with patch.object(
            vs.config,
            "fish_audio",
            {"voices": ["abc123:My Narrator", "def456"]},
        ):
            voices = vs.get_fish_audio_voices()
        self.assertEqual(
            voices,
            [
                "fish_audio:2324c907b9a94c64ab4afb941e5b3408:Clear Female-Female",
                "fish_audio:7b6131ba75ba47c98a46c847db729ab6:Clear Male-Male",
                "fish_audio:default:Default Voice",
                "fish_audio:abc123:My Narrator",
                "fish_audio:def456:def456",
            ],
        )

    def test_get_fish_audio_voices_comma_separated_string(self):
        """TOML-friendly comma-separated string is accepted."""
        with patch.object(
            vs.config, "fish_audio", {"voices": "abc123:Voice A, def456:Voice B,"}
        ):
            voices = vs.get_fish_audio_voices()
        self.assertIn("fish_audio:abc123:Voice A", voices)
        self.assertIn("fish_audio:def456:Voice B", voices)

    def test_get_fish_audio_voices_already_prefixed(self):
        """Entries already prefixed with fish_audio: are kept as-is."""
        with patch.object(
            vs.config,
            "fish_audio",
            {"voices": ["fish_audio:abc:Custom"]},
        ):
            voices = vs.get_fish_audio_voices()
        self.assertIn("fish_audio:abc:Custom", voices)


class TestFishAudioAPIKey(unittest.TestCase):
    """get_fish_audio_api_key reads from config and env."""

    def test_api_key_from_config(self):
        with patch.object(
            vs.config, "fish_audio", {"api_key": "config-key-123"}
        ):
            self.assertEqual(vs.get_fish_audio_api_key(), "config-key-123")

    def test_api_key_from_env_fallback(self):
        with patch.object(vs.config, "fish_audio", {"api_key": ""}), \
             patch.dict(os.environ, {"FISH_API_KEY": "env-key-456"}):
            self.assertEqual(vs.get_fish_audio_api_key(), "env-key-456")

    def test_api_key_config_takes_precedence(self):
        with patch.object(
            vs.config, "fish_audio", {"api_key": "config-key"}
        ), patch.dict(os.environ, {"FISH_API_KEY": "env-key"}):
            self.assertEqual(vs.get_fish_audio_api_key(), "config-key")


class TestFishAudioDispatch(unittest.TestCase):
    """tts() correctly dispatches to fish_audio_tts."""

    def test_dispatch_default_voice(self):
        sentinel = object()
        with patch.object(vs, "fish_audio_tts", return_value=sentinel) as mock:
            result = vs.tts("hello", "fish_audio:default:Default Voice", 1.0, "out.mp3", 1.0)
        self.assertIs(result, sentinel)
        mock.assert_called_once_with(
            "hello", "out.mp3", 1.0, 1.0, reference_id=None
        )

    def test_dispatch_custom_reference_id(self):
        sentinel = object()
        with patch.object(vs, "fish_audio_tts", return_value=sentinel) as mock:
            result = vs.tts("hello", "fish_audio:abc123:My Voice", 1.2, "out.mp3", 0.8)
        self.assertIs(result, sentinel)
        mock.assert_called_once_with(
            "hello", "out.mp3", 1.2, 0.8, reference_id="abc123"
        )


class TestFishAudioTTSRequest(unittest.TestCase):
    """fish_audio_tts sends correct request payloads."""

    def _call_with_capture(self, voice_rate=1.0, voice_volume=1.0,
                           reference_id=None, model="s2.1-pro-free",
                           response=None):
        """Helper: call fish_audio_tts and capture the outgoing request."""
        captured = {}

        def _fake_post(url, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return response or _FakeResponse()

        with tempfile.TemporaryDirectory() as tmp_dir, \
             patch.object(vs.config, "fish_audio", {"api_key": "test-key", "model": model}), \
             patch.object(vs.requests, "post", side_effect=_fake_post), \
             patch.object(vs, "AudioFileClip", return_value=_FakeClip()):
            voice_file = str(Path(tmp_dir) / "fish.mp3")
            result = vs.fish_audio_tts(
                "Test sentence.",
                voice_file,
                voice_rate=voice_rate,
                voice_volume=voice_volume,
                reference_id=reference_id,
            )
        return result, captured

    def test_model_from_config(self):
        """Model is read from config, not from voice name."""
        _, captured = self._call_with_capture(model="s2.1-pro")
        self.assertEqual(captured["headers"]["model"], "s2.1-pro")

    def test_default_model_fallback(self):
        """Unknown model falls back to s2.1-pro-free."""
        _, captured = self._call_with_capture(model="nonexistent-model")
        self.assertEqual(captured["headers"]["model"], "s2.1-pro-free")

    def test_prosody_speed_sent(self):
        """voice_rate is mapped to prosody.speed."""
        _, captured = self._call_with_capture(voice_rate=1.5)
        self.assertAlmostEqual(captured["json"]["prosody"]["speed"], 1.5)

    def test_prosody_speed_clamped(self):
        """voice_rate is clamped to 0.5–2.0."""
        _, cap_low = self._call_with_capture(voice_rate=0.1)
        self.assertAlmostEqual(cap_low["json"]["prosody"]["speed"], 0.5)
        _, cap_high = self._call_with_capture(voice_rate=5.0)
        self.assertAlmostEqual(cap_high["json"]["prosody"]["speed"], 2.0)

    def test_prosody_volume_conversion(self):
        """voice_volume linear multiplier is converted to dB."""
        # 1.0 → 0 dB
        _, cap = self._call_with_capture(voice_volume=1.0)
        self.assertAlmostEqual(cap["json"]["prosody"]["volume"], 0.0, places=1)
        # 2.0 → ~6 dB
        _, cap2 = self._call_with_capture(voice_volume=2.0)
        self.assertAlmostEqual(
            cap2["json"]["prosody"]["volume"],
            20.0 * math.log10(2.0),
            places=1,
        )

    def test_reference_id_included_when_set(self):
        _, captured = self._call_with_capture(reference_id="abc123")
        self.assertEqual(captured["json"]["reference_id"], "abc123")

    def test_reference_id_absent_when_none(self):
        _, captured = self._call_with_capture(reference_id=None)
        self.assertNotIn("reference_id", captured["json"])

    def test_auth_header(self):
        _, captured = self._call_with_capture()
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")

    def test_success_returns_submaker(self):
        result, _ = self._call_with_capture()
        self.assertIsNotNone(result)


class TestFishAudioErrorHandling(unittest.TestCase):
    """Error responses are handled gracefully."""

    def _call_with_status(self, status_code, text="error"):
        resp = _FakeResponse(status_code=status_code, content=b"", text=text)

        with tempfile.TemporaryDirectory() as tmp_dir, \
             patch.object(vs.config, "fish_audio", {"api_key": "test-key", "model": "s2.1-pro-free"}), \
             patch.object(vs.requests, "post", return_value=resp), \
             patch.object(vs, "AudioFileClip", return_value=_FakeClip()):
            voice_file = str(Path(tmp_dir) / "fish.mp3")
            result = vs.fish_audio_tts("Test.", voice_file)
        return result

    def test_401_returns_none(self):
        self.assertIsNone(self._call_with_status(401))

    def test_402_returns_none(self):
        self.assertIsNone(self._call_with_status(402))

    def test_429_returns_none_after_retries(self):
        """429 triggers retry; after 3 attempts returns None."""
        self.assertIsNone(self._call_with_status(429))

    def test_500_returns_none_after_retries(self):
        self.assertIsNone(self._call_with_status(500))

    def test_empty_audio_returns_none(self):
        """Response with too-small content is rejected."""
        resp = _FakeResponse(status_code=200, content=b"tiny")
        with tempfile.TemporaryDirectory() as tmp_dir, \
             patch.object(vs.config, "fish_audio", {"api_key": "test-key", "model": "s2.1-pro-free"}), \
             patch.object(vs.requests, "post", return_value=resp):
            voice_file = str(Path(tmp_dir) / "fish.mp3")
            result = vs.fish_audio_tts("Test.", voice_file)
        self.assertIsNone(result)

    def test_missing_api_key_returns_none(self):
        with patch.object(vs.config, "fish_audio", {"api_key": ""}), \
             patch.dict(os.environ, {"FISH_API_KEY": ""}, clear=False):
            result = vs.fish_audio_tts("Test.", "/tmp/fish.mp3")
        self.assertIsNone(result)

    def test_empty_text_returns_none(self):
        result = vs.fish_audio_tts("", "/tmp/fish.mp3")
        self.assertIsNone(result)


class TestFishAudioTaskRestore(unittest.TestCase):
    """Verify that fish_audio voices are detectable for task restoration.

    _infer_tts_server_from_voice (in webui/Main.py) delegates to
    voice.is_fish_audio_voice(), so we test that the detection function
    correctly identifies fish_audio voice strings — which is the root
    cause of the task restore bug the maintainer reported.
    """

    def test_is_fish_audio_voice_matches_default(self):
        self.assertTrue(vs.is_fish_audio_voice("fish_audio:default:Default Voice"))

    def test_is_fish_audio_voice_matches_custom_ref(self):
        self.assertTrue(vs.is_fish_audio_voice("fish_audio:abc123:Custom"))

    def test_is_fish_audio_voice_rejects_other_providers(self):
        self.assertFalse(vs.is_fish_audio_voice("elevenlabs:abc:Rachel"))
        self.assertFalse(vs.is_fish_audio_voice("chatterbox:default-Female"))
        self.assertFalse(vs.is_fish_audio_voice("minimax:narrator"))
        # Azure voices don't have a prefix
        self.assertFalse(vs.is_fish_audio_voice("en-US-JennyNeural-Female"))


if __name__ == "__main__":
    unittest.main()
