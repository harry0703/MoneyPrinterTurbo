import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import minimax_music


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class TestMiniMaxMusic(unittest.TestCase):
    def test_generation_uses_regional_endpoint_and_decodes_audio(self):
        captured = {}

        def request(url, **kwargs):
            captured.update(url=url, **kwargs)
            return _Response(
                {
                    "data": {"audio": b"generated-audio".hex(), "status": 2},
                    "base_resp": {"status_code": 0},
                }
            )

        settings = {
            "api_key": "test-key",
            "base_url": minimax_music.CN_MUSIC_URL,
            "model_id": "music-2.6",
            "lyrics": "[Verse]\nA quiet road",
            "is_instrumental": False,
            "sample_rate": 32000,
            "bitrate": 128000,
            "audio_format": "mp3",
            "aigc_watermark": True,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "video.mp4"
            output = Path(temp_dir) / "music.mp3"
            video.write_bytes(b"video")
            with (
                patch.object(minimax_music.config, "minimax_music", settings),
                patch.object(minimax_music.requests, "post", side_effect=request),
                patch.object(minimax_music.bgm_service, "validate_audio_file"),
            ):
                result = minimax_music.generate_bgm(
                    str(video), str(output), 10, "Calm cinematic music"
                )

            self.assertEqual(result, str(output))
            self.assertEqual(output.read_bytes(), b"generated-audio")

        self.assertEqual(captured["url"], minimax_music.CN_MUSIC_URL)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(captured["json"]["model"], "music-2.6")
        self.assertEqual(captured["json"]["prompt"], "Calm cinematic music")
        self.assertEqual(captured["json"]["lyrics"], "[Verse]\nA quiet road")
        self.assertEqual(
            captured["json"]["audio_setting"],
            {"sample_rate": 32000, "bitrate": 128000, "format": "mp3"},
        )
        self.assertTrue(captured["json"]["aigc_watermark"])

    def test_payload_falls_back_to_supported_generation_settings(self):
        settings = {
            "model_id": "music-cover",
            "sample_rate": 123,
            "bitrate": 456,
            "audio_format": "flac",
        }
        with patch.object(minimax_music.config, "minimax_music", settings):
            payload = minimax_music._payload("Instrumental music")

        self.assertEqual(payload["model"], minimax_music.DEFAULT_MODEL)
        self.assertEqual(
            payload["audio_setting"],
            {"sample_rate": 44100, "bitrate": 256000, "format": "mp3"},
        )
        self.assertEqual(minimax_music.output_suffix(), ".mp3")

    def test_rejects_incomplete_and_invalid_audio_responses(self):
        invalid_payloads = [
            {"data": {"audio": "00", "status": 1}, "base_resp": {"status_code": 0}},
            {"data": {"audio": "not-hex", "status": 2}, "base_resp": {"status_code": 0}},
            {"data": {"audio": "", "status": 2}, "base_resp": {"status_code": 0}},
            {"data": {"status": 2}, "base_resp": {"status_code": 1001, "status_msg": "invalid"}},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(
                minimax_music.MiniMaxMusicError
            ):
                minimax_music._decode_audio(_Response(payload))


if __name__ == "__main__":
    unittest.main()
