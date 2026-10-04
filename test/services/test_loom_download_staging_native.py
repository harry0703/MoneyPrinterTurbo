import http.server
import threading
import requests
from app.services.loomloom import LoomLoomVideoBackend, LoomLoomSettings


def test_native_concurrent_downloads_use_distinct_staging_files(tmp_path):
    first_chunk = threading.Event()
    release = threading.Event()
    size = 1024 * 1024
    payloads = {
        "/first": b"A" * size + b"FIRST-END",
        "/second": b"B" * size + b"SECOND-END",
    }

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = payloads[self.path]
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body[:size])
            self.wfile.flush()
            if self.path == "/first":
                first_chunk.set()
                assert release.wait(5)
            self.wfile.write(body[size:])
            self.wfile.flush()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    destination = tmp_path / "shared.mp4"
    outcomes = []

    def download(path):
        try:
            with requests.Session() as session:
                backend = LoomLoomVideoBackend(
                    LoomLoomSettings(
                        base_url="http://127.0.0.1",
                        api_token="synthetic",
                        market_listing_id="fixture",
                    ),
                    session=session,
                )
                backend._download_video_artifact(
                    f"http://127.0.0.1:{server.server_port}{path}", str(destination)
                )
            outcomes.append("complete")
        except Exception as exc:
            outcomes.append(type(exc).__name__)

    first = threading.Thread(target=download, args=("/first",))
    second = threading.Thread(target=download, args=("/second",))
    try:
        first.start()
        assert first_chunk.wait(5)
        # The first request has already opened its real staging file by the
        # time it waits for the final response chunk.
        import time

        deadline = time.monotonic() + 5
        while not any(tmp_path.glob("*.part")) and time.monotonic() < deadline:
            time.sleep(0.001)
        assert any(tmp_path.glob("*.part"))
        second.start()
        second.join(5)
        assert not second.is_alive()
        release.set()
        first.join(5)
        assert not first.is_alive()
        assert outcomes == ["complete", "complete"]
        assert destination.read_bytes() in payloads.values()
        assert not list(tmp_path.glob("*.part"))
    finally:
        release.set()
        first.join(5)
        if second.ident:
            second.join(5)
        server.shutdown()
        server.server_close()
        worker.join(2)
