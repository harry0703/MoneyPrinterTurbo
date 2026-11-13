"""Motion Studio renderer: plays the engine page in headless Chrome and pipes every frame into ffmpeg.

Runs as a subprocess so a stuck browser can be killed (jobs.py cancels or times it out):

    python -m app.services.motion.renderer <job_dir>

The job folder must hold storyboard.json (engine format), words.json, env.json and audio.m4a.
Prints "progress <done> <total>" lines and writes <job_dir>/video.mp4.
"""

import functools
import http.server
import json
import math
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import unquote, urlsplit

from imageio_ffmpeg import get_ffmpeg_exe

from app.utils import utils

FPS = 30
SIZE = {"width": 1080, "height": 1920}
ENGINE_DIR = Path(utils.resource_dir("motion"))
CHROME_ARGS = ["--enable-unsafe-swiftshader"]  # WebGL in headless Chrome without a GPU
MIME = {".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".html": "text/html",
        ".glb": "model/gltf-binary", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".ttf": "font/ttf", ".m4a": "audio/mp4"}


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Serves only /engine/* (the engine folder) and /job/* (this job's folder), nothing else."""

    extensions_map = MIME

    def __init__(self, *args, roots: dict[str, Path], **kwargs):
        self.roots = roots
        super().__init__(*args, **kwargs)

    def translate_path(self, path: str) -> str:
        path = unquote(urlsplit(path).path)
        for prefix, root in self.roots.items():
            if path.startswith(prefix):
                target = (root / path[len(prefix):]).resolve()
                if target.is_relative_to(root):
                    return str(target)
        return str(ENGINE_DIR / "__missing__")  # outside the allowed roots: 404

    def log_message(self, *args: object) -> None:
        pass


def _serve(job_dir: Path) -> http.server.ThreadingHTTPServer:
    handler = functools.partial(_Handler, roots={"/engine/": ENGINE_DIR.resolve(), "/job/": job_dir.resolve()})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _launch(playwright):
    try:
        return playwright.chromium.launch(channel="chrome", args=CHROME_ARGS)
    except Exception:  # no system Chrome: fall back to Playwright's own Chromium
        return playwright.chromium.launch(args=CHROME_ARGS)


def render(job_dir: Path, report=lambda done, total: None) -> Path:
    from playwright.sync_api import sync_playwright  # optional dependency, imported on use

    words = json.loads((job_dir / "words.json").read_text(encoding="utf-8"))
    env = json.loads((job_dir / "env.json").read_text(encoding="utf-8"))
    duration = json.loads((job_dir / "storyboard.json").read_text(encoding="utf-8"))["duration"]
    total = math.ceil(duration * FPS)
    out = job_dir / "video.mp4"
    server = _serve(job_dir)
    errors: list[str] = []
    ffmpeg = subprocess.Popen(
        [get_ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg",
         "-i", "pipe:0", "-i", str(job_dir / "audio.m4a"), "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE,
    )
    try:
        with sync_playwright() as p:
            browser = _launch(p)
            page = browser.new_page(viewport=SIZE)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{server.server_port}/engine/auto.html?job=/job")
            page.evaluate("async () => { await document.fonts.ready; await window.ready; }")
            if errors:
                raise RuntimeError(f"scene failed to load: {errors[0]}")
            page.evaluate("([w, e]) => window.init(w, e)", [words, env])
            for i in range(total):
                page.evaluate(f"window.render({i / FPS:.4f})")
                ffmpeg.stdin.write(page.screenshot(type="jpeg", quality=90))
                if i % 15 == 0 or i == total - 1:
                    report(i + 1, total)
            browser.close()
        ffmpeg.stdin.close()
        if ffmpeg.wait() != 0:
            raise RuntimeError("ffmpeg failed to encode the video")
    finally:
        if ffmpeg.poll() is None:
            ffmpeg.kill()
        server.shutdown()
    return out


def main() -> None:
    render(Path(sys.argv[1]), lambda done, total: print(f"progress {done} {total}", flush=True))


if __name__ == "__main__":
    main()
