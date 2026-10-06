import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest

from app.config import config
from app.models.schema import VideoParams
from app.services import task, voice


@pytest.mark.parametrize("voice_id", ["Brand-Female-Narrator", "Brand-Male-Narrator", "BrandNarrator-Female", "BrandNarrator-V2"])
def test_custom_minimax_id_reaches_its_actual_http_adapter_unchanged(tmp_path, voice_id):
    if not shutil.which("ffmpeg"):
        pytest.skip("native FFmpeg required")
    encoded = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2", "-f", "mp3", "-"], capture_output=True, check=True).stdout
    requests_seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            requests_seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps({"base_resp": {"status_code": 0}, "data": {"status": 2, "audio": encoded.hex()}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with patch.dict(config.minimax_tts, {"api_key": "fixture-key", "base_url": f"http://127.0.0.1:{server.server_port}/t2a_v2", "audio_format": "mp3"}), patch.object(task.utils, "task_dir", return_value=str(tmp_path)), patch.object(voice, "azure_tts_v2", side_effect=AssertionError("qualified provider routed to Azure")):
            audio_file, duration, maker = task.generate_audio("fixture", VideoParams(video_subject="Coffee", voice_name=f"minimax:{voice_id}"), "Coffee")
        assert audio_file and duration > 0 and maker is not None
        assert len(requests_seen) == 1
        assert requests_seen[0]["voice_setting"]["voice_id"] == voice_id
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", audio_file, "-f", "null", "-"], check=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        assert not thread.is_alive()


@pytest.mark.parametrize("label,expected", [
    ("zh-CN-XiaoyiNeural-Female", "zh-CN-XiaoyiNeural"),
    ("zh-CN-YunxiNeural-Male", "zh-CN-YunxiNeural"),
    ("zh-CN-XiaoxiaoMultilingualNeural-V2-Female", "zh-CN-XiaoxiaoMultilingualNeural-V2"),
])
def test_legacy_azure_labels_are_still_normalized(label, expected):
    assert voice.parse_voice_name(label) == expected


def test_provider_label_handlers_still_remove_display_suffixes(tmp_path):
    cases = [
        ("siliconflow:FunAudioLLM/CosyVoice2-0.5B:alex-Male", "siliconflow_tts", 2, "FunAudioLLM/CosyVoice2-0.5B:alex"),
        ("kokoro:af_heart-Female", "kokoro_tts", 1, "af_heart"),
        ("chatterbox:default-Female", "chatterbox_tts", 1, "default"),
        ("gemini:Kore-Female", "gemini_tts", 1, "Kore"),
    ]
    for label, adapter, argument, expected in cases:
        with patch.object(voice, adapter, return_value=object()) as provider:
            voice.tts("Coffee", voice.parse_voice_name(label), 1, str(tmp_path / "audio.mp3"))
        assert provider.call_args.args[argument] == expected
