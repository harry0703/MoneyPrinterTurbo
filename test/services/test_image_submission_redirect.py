import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest

from app.services import material


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_paid_image_submission_does_not_follow_redirects(status):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            requests.append(("POST", self.path))
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path == "/generation":
                self.send_response(status)
                self.send_header("Location", "/redirected")
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self.respond()

        def do_GET(self):
            requests.append(("GET", self.path))
            self.respond()

        def respond(self):
            body = json.dumps({"data": [{"b64_json": base64.b64encode(b"fixture").decode()}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with (
            patch.object(material.config, "proxy", {}),
            patch.object(material.config, "app", {"openai_image_api_keys": []}),
            pytest.raises(material.OpenAIImageUnconfirmedError, match="redirect"),
        ):
            material._request_openai_image(f"http://127.0.0.1:{server.server_port}/generation", {"prompt": "fixture"})
        assert requests == [("POST", "/generation")]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
