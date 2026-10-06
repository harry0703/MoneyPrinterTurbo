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


@pytest.mark.parametrize("rate,expected", [(0.8, 0.8), (1.2, 1.2), (0.5, 0.7), (2.0, 1.2), (1.0, None), (None, None)])
def test_selected_rate_reaches_real_elevenlabs_http_transport(tmp_path, rate, expected):
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
        with patch.dict(config.elevenlabs, {"api_key": "fixture-key"}), patch.object(task.utils, "task_dir", return_value=str(tmp_path)), patch.object(voice.requests, "post", side_effect=loopback_post):
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
