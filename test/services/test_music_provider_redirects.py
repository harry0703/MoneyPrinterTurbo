"""Credentialed music requests must not follow provider-controlled redirects."""

import tempfile
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

import pytest
import requests

from app.services import elevenlabs_music, sonilo


@contextmanager
def redirect_servers():
    redirected_requests = []

    class Destination(BaseHTTPRequestHandler):
        def do_GET(self):
            redirected_requests.append(("GET", bool(self.headers.get("xi-api-key")), 0))
            self.send_error(503)

        def do_POST(self):
            body_size = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(body_size)
            redirected_requests.append(
                ("POST", bool(self.headers.get("xi-api-key")), body_size)
            )
            self.send_error(503)

        def log_message(self, *_args):
            pass

    destination = ThreadingHTTPServer(("127.0.0.1", 0), Destination)
    destination_thread = Thread(target=destination.serve_forever, daemon=True)
    destination_thread.start()

    class Source(BaseHTTPRequestHandler):
        def do_GET(self):
            self._redirect()

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self._redirect()

        def _redirect(self):
            self.send_response(307)
            self.send_header(
                "Location", f"http://127.0.0.1:{destination.server_port}/other"
            )
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_args):
            pass

    source = ThreadingHTTPServer(("127.0.0.1", 0), Source)
    source_thread = Thread(target=source.serve_forever, daemon=True)
    source_thread.start()
    try:
        yield source, redirected_requests
    finally:
        source.shutdown()
        source.server_close()
        source_thread.join(timeout=5)
        destination.shutdown()
        destination.server_close()
        destination_thread.join(timeout=5)


@pytest.mark.parametrize("provider", [elevenlabs_music, sonilo])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_music_provider_rejects_redirect_without_replaying_credentials_or_video(
    provider, method
):
    with redirect_servers() as (source, redirected_requests):
        base_url = f"http://127.0.0.1:{source.server_port}"
        if provider is elevenlabs_music:
            config_patch = patch.object(
                provider.config,
                "elevenlabs",
                {"api_key": "secret-key", "music_base_url": base_url},
            )
            error_type = provider.ElevenLabsMusicError
        else:
            config_patch = patch.object(
                provider.config,
                "app",
                {"sonilo_api_key": "secret-key", "sonilo_base_url": base_url},
            )
            error_type = provider.SoniloError

        with requests.Session() as session, config_patch:
            session.trust_env = False
            request = session.get if method == "GET" else session.post
            with patch.object(provider.requests, method.lower(), side_effect=request):
                with pytest.raises(error_type) as error:
                    if method == "GET":
                        provider.test_connection()
                    else:
                        with tempfile.TemporaryDirectory() as temp_dir:
                            video_path = Path(temp_dir) / "proxy.mp4"
                            video_path.write_bytes(b"video")
                            provider._request_bgm(
                                str(video_path), str(Path(temp_dir) / "music.mp3"), ""
                            )

        assert redirected_requests == []
        assert "redirect" in str(error.value)
