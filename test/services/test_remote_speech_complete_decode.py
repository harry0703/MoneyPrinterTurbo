import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest
import requests
from moviepy.audio.io.AudioFileClip import AudioFileClip

from app.config import config
from app.services import voice


@pytest.mark.parametrize("provider", ["siliconflow", "minimax", "elevenlabs", "openai", "fish"])
@pytest.mark.parametrize("corrupt", [True, False])
def test_accepted_audio_requires_full_decode_and_preserves_previous_export(tmp_path, provider, corrupt):
    if not shutil.which("ffmpeg"):
        pytest.skip("native FFmpeg required")
    complete = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-f", "mp3", "-"], capture_output=True, check=True).stdout
    damaged = complete[:len(complete)*2//5] + bytes(len(complete)//5) + complete[len(complete)*3//5:]
    payload = damaged if corrupt else complete
    probe = tmp_path / "probe.mp3"
    probe.write_bytes(payload)
    with AudioFileClip(str(probe)) as clip:
        assert clip.duration > 0
    decoded = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(probe), "-f", "null", "-"], capture_output=True)
    assert (decoded.returncode != 0) == corrupt
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            data = json.dumps({"base_resp": {"status_code": 0}, "data": {"status": 2, "audio": payload.hex()}}).encode() if provider == "minimax" else payload
            self.send_response(200)
            self.send_header("Content-Type", "application/json" if provider == "minimax" else "audio/mpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    real_post = requests.post

    def post_to_fixture(url, **kwargs):
        assert url.startswith("https://")
        return real_post(f"http://127.0.0.1:{server.server_port}/speech", **kwargs)

    output = tmp_path / "narration.mp3"
    output.write_bytes(complete)
    try:
        with patch.dict(config.siliconflow, {"api_key": "fixture"}), patch.dict(config.minimax_tts, {"api_key": "fixture"}), patch.dict(config.elevenlabs, {"api_key": "fixture"}), patch.object(voice, "get_fish_audio_api_key", return_value="fixture"), patch.object(voice.requests, "post", side_effect=post_to_fixture):
            calls = {
                "siliconflow": lambda: voice.siliconflow_tts("hello", "model", "voice", 1.0, str(output)),
                "minimax": lambda: voice.minimax_tts("hello", "voice", 1.0, str(output)),
                "elevenlabs": lambda: voice.elevenlabs_tts("hello", "voice", str(output)),
                "openai": lambda: voice._openai_compatible_tts("fixture", "https://fixture.invalid/v1", "fixture", "model", "voice", "hello", 1.0, str(output)),
                "fish": lambda: voice.fish_audio_tts("hello", str(output)),
            }
            result = calls[provider]()
        assert len(seen) == 1, "accepted audio must not trigger another speech POST"
        if corrupt:
            assert result is None
            assert output.read_bytes() == complete
        else:
            assert result is not None
            assert output.read_bytes() == complete
        assert sorted(path.name for path in tmp_path.iterdir()) == ["narration.mp3", "probe.mp3"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        assert not thread.is_alive()
