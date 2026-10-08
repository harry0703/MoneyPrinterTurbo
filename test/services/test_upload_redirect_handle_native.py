import http.server
import threading
from app.services.upload_post import UploadPostService


def test_real_redirect_keeps_sent_upload_handle_without_replay(tmp_path):
    calls = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            calls.append(body)
            self.send_response(307)
            self.send_header("Location", "/another-upload")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"synthetic-upload-fixture")
    service = UploadPostService(
        {
            "upload_post_enabled": True,
            "upload_post_api_key": "synthetic-key",
            "upload_post_username": "fixture",
        }
    )
    service.API_BASE = "http://127.0.0.1:" + str(server.server_address[1])
    try:
        result = service.upload_video(str(video), "fixture", platforms=["tiktok"])
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)
    assert not result["success"]
    assert len(calls) == 1
    assert result["request_id"].encode() in calls[0]
    assert "unconfirmed" in result["error"]
