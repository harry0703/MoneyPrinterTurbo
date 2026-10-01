import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from app.services.loomloom import LoomLoomAPIError, LoomLoomScriptBackend, LoomLoomSettings


class TestLoomLoomPagination(unittest.TestCase):
    def collect(self, pages):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                seen.append(self.path)
                index = len(seen) - 1
                payload = pages[index] if index < len(pages) else {"error": "fixture loop cutoff"}
                body = json.dumps(payload).encode()
                self.send_response(200 if index < len(pages) else 500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with requests.Session() as session:
                backend = LoomLoomScriptBackend(
                    LoomLoomSettings(
                        base_url=f"http://127.0.0.1:{server.server_port}",
                        api_token="fixture-only", market_listing_id="fixture-listing",
                    ), session=session,
                )
                return backend.get_script_results("fixture-run"), seen
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            self.last_requests = seen

    def test_rejects_repeated_page_token_before_requesting_it_again(self):
        with self.assertRaisesRegex(LoomLoomAPIError, "repeated.*page token"):
            self.collect([
                {"items": [], "nextPageToken": "a"},
                {"items": [], "nextPageToken": "b"},
                {"items": [], "nextPageToken": "a"},
            ])
        self.assertEqual(len(self.last_requests), 3)

    def test_null_terminal_token_does_not_request_a_literal_none_page(self):
        result, seen = self.collect([{"items": [], "nextPageToken": None}])
        self.assertEqual(result.candidates, ())
        self.assertEqual(len(seen), 1)

    def test_complete_non_repeating_pages_are_preserved(self):
        result, seen = self.collect([
            {"items": [], "nextPageToken": "a"},
            {"items": [], "nextPageToken": "b"},
            {"items": []},
        ])
        self.assertEqual(result.errors, ())
        self.assertEqual(len(seen), 3)
        self.assertIn("pageToken=a", seen[1])
        self.assertIn("pageToken=b", seen[2])
