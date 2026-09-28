"""Paid video submissions and polling must stop at the provider origin."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch

import pytest
import requests

from app.config import config
from app.services import metaso_minimax, ofox, volcengine_seedance


PROVIDERS = (
    (
        volcengine_seedance,
        "volcengine_seedance",
        "tasks_url",
        volcengine_seedance.VolcEngineSeedanceUnconfirmedTaskError,
    ),
    (ofox, "ofox", "videos_url", ofox.OFoxUnconfirmedTaskError),
    (
        metaso_minimax,
        "metaso_minimax",
        "base_url",
        metaso_minimax.MetasoMiniMaxUnconfirmedTaskError,
    ),
)


@contextmanager
def redirect_servers():
    redirected_requests = []

    class Destination(BaseHTTPRequestHandler):
        def do_GET(self):
            redirected_requests.append(("GET", 0))
            self.send_error(400)

        def do_POST(self):
            body_size = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(body_size)
            redirected_requests.append(("POST", body_size))
            self.send_error(400)

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


@pytest.mark.parametrize("provider,prefix,poll_url_key,error_type", PROVIDERS)
@pytest.mark.parametrize("method", ["POST", "GET"])
def test_paid_video_provider_rejects_redirect_without_replaying_request(
    provider, prefix, poll_url_key, error_type, method
):
    with redirect_servers() as (source, redirected_requests):
        base_url = f"http://127.0.0.1:{source.server_port}"
        settings = {
            f"{prefix}_api_key": "secret-key",
            f"{prefix}_base_url": base_url,
        }
        with (
            requests.Session() as session,
            patch.object(config, "app", settings),
            patch.object(config, "proxy", {}),
        ):
            session.trust_env = False
            request = session.post if method == "POST" else session.get
            with patch.object(provider.requests, method.lower(), side_effect=request):
                if method == "POST":
                    with pytest.raises(error_type):
                        provider.generate_videos("cinematic sunrise", 5)
                else:
                    poll_kwargs = {
                        "task_id": "remote-task",
                        "headers": {"Authorization": "Bearer secret-key"},
                        "api_key": "secret-key",
                        poll_url_key: base_url,
                    }
                    with pytest.raises(error_type):
                        provider._wait_for_task(**poll_kwargs)

        assert redirected_requests == []
