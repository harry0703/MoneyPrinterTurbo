import http.server
import json
import threading
import pytest
from app.services.loomloom import (
    LoomLoomScriptBackend,
    LoomLoomSettings,
    LoomLoomRunError,
)


def test_native_poll_does_not_issue_request_after_wait_deadline():
    calls = []
    now = [0.0]

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            body = json.dumps(
                {
                    "run": {
                        "runId": "retained-run",
                        "status": "running" if len(calls) == 1 else "completed",
                        "totalTasks": 1,
                        "completedTasks": 0,
                        "failedTasks": 0,
                        "cancelledTasks": 0,
                    }
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    backend = LoomLoomScriptBackend(
        LoomLoomSettings(
            base_url=f"http://127.0.0.1:{server.server_port}",
            api_token="synthetic",
            market_listing_id="fixture",
            run_timeout_seconds=0.02,
            poll_interval_seconds=0.2,
        ),
        clock=lambda: now[0],
        sleep=lambda delay: now.__setitem__(0, now[0] + delay),
    )
    try:
        with pytest.raises(LoomLoomRunError, match="retained-run"):
            backend.wait_for_run("retained-run")
        assert len(calls) == 1
    finally:
        backend._session.close()
        server.shutdown()
        server.server_close()
        worker.join(2)
