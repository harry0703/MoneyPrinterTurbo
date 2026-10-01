import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from app.services.loomloom import LoomLoomAPIError, LoomLoomScriptBackend, LoomLoomSettings


class TestLoomLoomRequestRedirects(unittest.TestCase):
    def test_paid_execute_never_follows_or_retries_redirects(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                requests_seen = []

                class Handler(BaseHTTPRequestHandler):
                    def log_message(self, *args):
                        pass

                    def respond(self):
                        length = int(self.headers.get("Content-Length", "0"))
                        body = self.rfile.read(length)
                        requests_seen.append((self.command, self.path, body))
                        if self.path.endswith(":execute"):
                            self.send_response(status)
                            self.send_header("Location", "/unexpected-target")
                            payload = b'{}'
                        else:
                            self.send_response(200)
                            payload = json.dumps({"runId": "unexpected-run"}).encode()
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(payload)))
                        self.end_headers()
                        self.wfile.write(payload)

                    do_POST = respond
                    do_GET = respond

                server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    with requests.Session() as session:
                        backend = LoomLoomScriptBackend(
                            LoomLoomSettings(
                                base_url=f"http://127.0.0.1:{server.server_port}",
                                api_token="fixture-only",
                                market_listing_id="fixture-listing",
                            ),
                            session=session,
                        )
                        batch = backend.prepare_script_batch(subject="fixture", candidate_count=1)
                        with self.assertRaises(LoomLoomAPIError) as raised:
                            backend.execute(
                                batch, client_request_id="fixture-request", listing_version_id="fixture-version", confirm=True
                            )
                        self.assertEqual(raised.exception.status_code, status)
                        self.assertFalse(raised.exception.retryable)
                        self.assertEqual(len(requests_seen), 1)
                        self.assertTrue(requests_seen[0][1].endswith(":execute"))
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()
