from datetime import timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import azure.cognitiveservices.speech as sdk
from app.services import voice


class TestAzureBoundaryDuration(unittest.TestCase):
    def test_sdk_timedeltas_preserve_exact_seconds_and_submillisecond_ticks(self):
        for duration, ticks in [(timedelta(0), 0), (timedelta(seconds=1), 10000000), (timedelta(microseconds=123456), 1234560)]:
            with self.subTest(duration=duration):
                captured = {}
                synthesizer = Mock()
                synthesizer.synthesis_word_boundary.connect.side_effect = lambda callback: captured.update(callback=callback)
                def speak(ssml):
                    captured["callback"](SimpleNamespace(duration=duration, audio_offset=123, text="word"))
                    return SimpleNamespace(get=lambda: SimpleNamespace(reason=sdk.ResultReason.SynthesizingAudioCompleted))
                synthesizer.speak_ssml_async.side_effect = speak
                with patch.dict(voice.config.azure, {"speech_key": "test-key", "speech_region": "test-region"}), patch.object(sdk.audio, "AudioOutputConfig"), patch.object(sdk, "SpeechConfig"), patch.object(sdk, "SpeechSynthesizer", return_value=synthesizer):
                    result = voice.azure_tts_v2("Word.", "en-US-AriaNeural-V2-Female", "unused.mp3")
                self.assertIsNotNone(result)
                self.assertEqual(result.offset, [(123, 123 + ticks)])
