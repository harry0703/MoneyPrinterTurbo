import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.services import material


def test_partial_faststart_video_does_not_poison_download_cache(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("native FFmpeg required")
    footage = tmp_path / "source.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=128x128:rate=20:duration=2", "-c:v", "libx264", "-preset", "ultrafast", "-movflags", "+faststart", str(footage)], check=True)
    complete = footage.read_bytes()
    payloads = [complete[:len(complete) // 2], complete]
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append(self.path)
            data = payloads[min(len(requests) - 1, 1)]
            self.send_response(200)
            # This is a completed transport response containing a truncated
            # media object, not a Content-Length/socket truncation.
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cache = tmp_path / "cache"
    try:
        url = f"http://127.0.0.1:{server.server_port}/clip.mp4"
        assert material.save_video(url, str(cache)) == ""
        assert list(cache.iterdir()) == []
        saved = material.save_video(url, str(cache))
        assert saved
        assert material.save_video(url, str(cache)) == saved
        assert len(requests) == 2
        assert len(list(cache.iterdir())) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
