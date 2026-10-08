import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest
import requests

from app.config import config
from app.models.schema import VideoParams
from app.services import task, voice


@pytest.mark.parametrize("model,rate,expected", [("eleven_multilingual_v2", 0.7, 0.7), ("eleven_multilingual_v2", 0.8, 0.8), ("eleven_multilingual_v2", 1.2, 1.2), ("eleven_multilingual_v2", 1.0, None), ("eleven_multilingual_v2", None, None), ("eleven_v3", 0.25, 0.25), ("eleven_v3", 1.5, 1.5), ("eleven_v3", 2.0, 2.0), ("eleven_v3", 4.0, 4.0)])
def test_selected_rate_reaches_real_elevenlabs_http_transport(tmp_path, model, rate, expected):
    if not shutil.which("ffmpeg"):
        pytest.skip("native FFmpeg required")
    encoded = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2", "-f", "mp3", "-"], capture_output=True, check=True).stdout
    requests_seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            requests_seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    real_post = requests.post

    def loopback_post(url, **kwargs):
        assert url == "https://api.elevenlabs.io/v1/text-to-speech/fixture"
        return real_post(f"http://127.0.0.1:{server.server_port}/v1/text-to-speech/fixture", **kwargs)

    try:
        with patch.dict(config.elevenlabs, {"api_key": "fixture-key", "model_id": model}), patch.object(task.utils, "task_dir", return_value=str(tmp_path)), patch.object(voice.requests, "post", side_effect=loopback_post):
            output, duration, maker = task.generate_audio("speed", VideoParams(video_subject="Coffee", voice_name="elevenlabs:fixture:Fixture", voice_rate=rate), "Coffee")
        assert output and duration > 0 and maker is not None
        assert len(requests_seen) == 1
        assert requests_seen[0]["voice_settings"].get("speed") == expected
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", output, "-f", "null", "-"], check=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        assert not thread.is_alive()


@pytest.mark.parametrize("rate", [0.24, 4.01, 0.0, -1.0, float("nan"), float("inf"), "invalid"])
def test_unsupported_rate_is_reported_without_a_paid_request(tmp_path, rate):
    with patch.dict(config.elevenlabs, {"api_key": "fixture-key", "model_id": "eleven_v3"}), patch.object(voice.requests, "post") as post, patch.object(voice.logger, "error") as error:
        assert voice.elevenlabs_tts("Coffee", "fixture", str(tmp_path / "voice.mp3"), voice_rate=rate) is None
    post.assert_not_called()
    assert "0.25" in str(error.call_args)
    assert "4.0" in str(error.call_args)


@pytest.mark.parametrize("model", ["eleven_v4", "eleven_v4_turbo"])
def test_v4_nonunity_speed_is_reported_without_a_paid_request(tmp_path, model):
    with patch.dict(config.elevenlabs, {"api_key": "fixture-key", "model_id": model}), patch.object(voice.requests, "post") as post, patch.object(voice.logger, "error") as error:
        assert voice.elevenlabs_tts("Coffee", "fixture", str(tmp_path / "voice.mp3"), voice_rate=1.5) is None
    post.assert_not_called()
    assert "does not support" in str(error.call_args)
    assert model in str(error.call_args)


@pytest.mark.parametrize("rate", [0.25, 0.5, 0.69, 1.21, 1.5, 2.0, 4.0])
def test_v2_unsupported_speed_fails_before_synthesis(tmp_path, rate):
    with patch.dict(config.elevenlabs, {"api_key": "fixture-key", "model_id": "eleven_multilingual_v2"}), patch.object(voice.requests, "post") as post, patch.object(voice.logger, "error") as error:
        assert voice.elevenlabs_tts("Coffee", "fixture", str(tmp_path / "voice.mp3"), voice_rate=rate) is None
    post.assert_not_called()
    assert "eleven_multilingual_v2" in str(error.call_args)
    assert "0.7" in str(error.call_args) and "1.2" in str(error.call_args)


def test_invalid_voice_settings_http_response_is_not_retried(tmp_path):
    requests_seen = []
    payload = json.dumps({"detail": {"status": "invalid_voice_settings", "message": "speed must be between 0.7 and 1.2"}}).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            requests_seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(400)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    real_post = requests.post
    output = tmp_path / "voice.mp3"
    output.write_bytes(b"existing narration")

    def loopback_post(_url, **kwargs):
        return real_post(f"http://127.0.0.1:{server.server_port}/speech", **kwargs)

    try:
        with patch.dict(config.elevenlabs, {"api_key": "fixture-key", "model_id": "eleven_v3"}), patch.object(voice.requests, "post", side_effect=loopback_post), patch.object(voice.logger, "error") as error:
            assert voice.elevenlabs_tts("Coffee", "fixture", str(output), voice_rate=1.5) is None
        assert len(requests_seen) == 1
        assert output.read_bytes() == b"existing narration"
        assert "invalid_voice_settings" in str(error.call_args_list)
        assert "speed must be between" in str(error.call_args_list)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        assert not thread.is_alive()
