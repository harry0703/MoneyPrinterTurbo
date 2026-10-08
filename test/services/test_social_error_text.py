import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from app.config import config
from app.services import llm


def test_social_metadata_accepts_error_text_inside_successful_provider_json():
    metadata = {"title": "Disk recovery tutorial", "caption": "Fix Error: disk full without losing files", "hashtags": ["#tech", "#storage", "#repair"]}
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            received.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            body = json.dumps({"id": "fixture", "object": "chat.completion", "created": 1, "model": "fixture", "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(metadata)}, "finish_reason": "stop"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = {"llm_provider": "openai", "openai_api_key": "fixture-key", "openai_model_name": "fixture", "openai_base_url": f"http://127.0.0.1:{server.server_port}/v1"}
        with patch.object(config, "app", settings):
            actual = llm.generate_social_metadata(video_subject="Storage tips", platform="youtube_shorts")
        assert actual == metadata
        assert len(received) == 1
        assert received[0][0] == "/v1/chat/completions"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_provider_error_prefix_still_returns_the_fallback():
    with patch.object(llm, "_generate_response", return_value="Error: provider unavailable") as response:
        actual = llm.generate_social_metadata(video_subject="Storage tips", platform="youtube_shorts")
    assert actual["title"] == "Storage tips"
    assert response.call_count == 1
