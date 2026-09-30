import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import requests
from app.services import voice


class TestMinimaxAcceptedResponseRetry(unittest.TestCase):
    def test_successful_paid_response_is_never_resubmitted_for_invalid_audio(self):
        for audio, error in [("not-hex", None), ("01", ValueError("decode failed")), ("01", OSError("disk full")), ("", None)]:
            with self.subTest(audio=audio, error=error), tempfile.TemporaryDirectory() as tmp:
                response = Mock(status_code=200)
                response.json.return_value = {"base_resp": {"status_code": 0}, "data": {"status": 2, "audio": audio}}
                output = Path(tmp) / "narration.mp3"
                output.write_bytes(b"previous narration")
                with patch.dict(voice.config.minimax_tts, {"api_key": "test-key"}), patch.object(voice.requests, "post", return_value=response) as post, patch.object(voice, "_write_validated_minimax_audio", side_effect=error, return_value=1):
                    result = voice.minimax_tts("Hello.", "voice-id", 1, str(output))
                self.assertIsNone(result)
                self.assertEqual(post.call_count, 1, "paid synthesis was resubmitted")
                self.assertEqual(output.read_bytes(), b"previous narration")

    def test_connect_timeout_before_acceptance_can_retry(self):
        response = Mock(status_code=200)
        response.json.return_value = {"base_resp": {"status_code": 0}, "data": {"status": 2, "audio": "01"}}
        with patch.dict(voice.config.minimax_tts, {"api_key": "test-key"}), patch.object(voice.requests, "post", side_effect=[requests.ConnectTimeout("not connected"), response]) as post, patch.object(voice, "_write_validated_minimax_audio", return_value=1):
            result = voice.minimax_tts("Hello.", "voice-id", 1, "unused.mp3")
        self.assertIsNotNone(result)
        self.assertEqual(post.call_count, 2)

    def test_unreadable_or_incomplete_success_body_is_not_resubmitted(self):
        for body in (None, [], {}, {"base_resp": {}}, {"data": {"status": 2, "audio": "01"}}, {"base_resp": {"status_code": 0}, "data": {"status": 1}}):
            with self.subTest(body=body):
                response = Mock(status_code=200)
                if body is None:
                    response.json.side_effect = ValueError("invalid JSON")
                else:
                    response.json.return_value = body
                with patch.dict(voice.config.minimax_tts, {"api_key": "test-key"}), patch.object(voice.requests, "post", return_value=response) as post:
                    result = voice.minimax_tts("Hello.", "voice-id", 1, "unused.mp3")
                self.assertIsNone(result)
                post.assert_called_once()
