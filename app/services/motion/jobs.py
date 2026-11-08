"""Motion Studio background jobs and character files.

One video renders at a time (Chrome is heavy); up to MAX_PENDING jobs wait. The studio polls status.
ponytail: in-memory registry, so job status is lost when the server restarts (files stay in
storage/motion/jobs). Move to MPT's Redis task manager if multi-process serving is ever needed.
"""

import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from app.models.motion import MotionJobRequest
from app.services.motion import pipeline, writer
from app.services.motion.errors import MotionError
from app.utils import utils

ROOT = Path(utils.storage_dir("motion", create=True))
JOBS_DIR, UPLOADS_DIR, PRESETS_DIR = ROOT / "jobs", ROOT / "uploads", ROOT / "characters"
MAX_PENDING = 3
MAX_UPLOADS = 100
RENDER_TIMEOUT_S = 15 * 60
RETENTION_S = 7 * 24 * 3600  # finished jobs and uploads older than this are deleted
GLB_MAX_BYTES, IMAGE_MAX_BYTES = 50 * 1024 * 1024, 10 * 1024 * 1024
SUFFIX_KIND = {".glb": "glb", ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image"}
UNSUPPORTED_GLB = {
    "KHR_draco_mesh_compression": "Draco compression",
    "EXT_meshopt_compression": "meshopt compression",
    "KHR_texture_basisu": "Basis textures",
}
ACTIVE = ("queued", "writing", "voicing", "rendering")
# Share of the whole job each stage takes, for one overall progress bar.
STAGE_SPAN = {"queued": (0, 0), "writing": (0, 0.12), "voicing": (0.12, 0.2), "rendering": (0.2, 1), "done": (1, 1)}


class Busy(Exception):
    """Too many jobs waiting."""


class _Cancelled(Exception):
    pass


@dataclass
class Job:
    id: str
    title: str
    status: str = "queued"
    stage: str = "queued"  # last working stage, kept when the job fails or is cancelled
    progress: float = 0.0  # within the current stage, 0..1
    message: str = ""
    stage_started: float = field(default_factory=time.time)
    result: dict | None = None
    cancelled: bool = False
    timed_out: bool = False
    proc: subprocess.Popen | None = field(default=None, repr=False)
    # Holds the request (and so the API key) only until the writer takes it, then it is emptied.
    secret: list = field(default_factory=list, repr=False)

    def public(self) -> dict:
        lo, hi = STAGE_SPAN.get(self.status, (0, 0))
        eta = None
        if self.status == "rendering" and self.progress > 0.03:
            elapsed = time.time() - self.stage_started
            eta = round(elapsed / self.progress * (1 - self.progress))
        return {"id": self.id, "title": self.title, "status": self.status, "stage": self.stage, "progress": round(self.progress, 3),
                "overall": round(lo + (hi - lo) * self.progress, 3), "eta_s": eta, "message": self.message,
                "result": self.result}


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="motion-job")


def renderer_installed() -> bool:
    return importlib.util.find_spec("playwright") is not None


# ---------- characters ----------
def _kind_of(path: Path) -> str | None:
    return SUFFIX_KIND.get(path.suffix.lower())


def list_characters() -> list[dict]:
    """Saved characters: files the user put in storage/motion/characters (never shipped in the repo)."""
    if not PRESETS_DIR.is_dir():
        return []
    out = []
    for path in sorted(PRESETS_DIR.iterdir()):
        slug = re.sub(r"[^A-Za-z0-9_-]", "-", path.stem)[:60]
        if path.is_file() and _kind_of(path):
            out.append({"id": f"preset-{slug}", "name": path.stem, "kind": _kind_of(path)})
    return out


def resolve_character(character_id: str) -> Path:
    """File for a character id. Ids are matched against real files, never joined into a path."""
    if character_id.startswith("up-") and UPLOADS_DIR.is_dir():
        for path in UPLOADS_DIR.iterdir():
            if path.stem == character_id[3:] and _kind_of(path):
                return path
    if character_id.startswith("preset-") and PRESETS_DIR.is_dir():
        for path in PRESETS_DIR.iterdir():
            if f"preset-{re.sub(r'[^A-Za-z0-9_-]', '-', path.stem)[:60]}" == character_id and _kind_of(path):
                return path
    raise MotionError("That character file is gone. Upload it again.")


def _check_glb(data: bytes) -> None:
    if len(data) < 20 or data[:4] != b"glTF" or int.from_bytes(data[4:8], "little") != 2:
        raise MotionError("That isn't a binary glTF 2.0 file (.glb).")
    length, kind = int.from_bytes(data[12:16], "little"), data[16:20]
    try:
        gltf = json.loads(data[20:20 + length]) if kind == b"JSON" else None
    except ValueError:
        gltf = None
    if not isinstance(gltf, dict):
        raise MotionError("That .glb file is damaged: its scene description can't be read.")
    blocked = [UNSUPPORTED_GLB[e] for e in gltf.get("extensionsRequired", []) if e in UNSUPPORTED_GLB]
    if blocked:
        raise MotionError(f"This model uses {', '.join(blocked)}, which the renderer can't decode. "
                          "Export it again without compression.")


def save_upload(filename: str, data: bytes) -> dict:
    suffix = Path(filename).suffix.lower()
    kind = SUFFIX_KIND.get(suffix)
    if kind is None:
        raise MotionError("Use a .glb model or a PNG, JPG or WebP image.")
    limit = GLB_MAX_BYTES if kind == "glb" else IMAGE_MAX_BYTES
    if len(data) > limit:
        raise MotionError(f"That file is over {limit // (1024 * 1024)} MB.")
    if kind == "glb":
        _check_glb(data)
    elif not (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")
              or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")):
        raise MotionError("That file isn't a PNG, JPG or WebP image.")
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    sweep()
    uploads = sorted(UPLOADS_DIR.iterdir(), key=lambda p: p.stat().st_mtime)
    for old in uploads[: max(0, len(uploads) - MAX_UPLOADS + 1)]:
        old.unlink(missing_ok=True)
    uid = uuid.uuid4().hex
    (UPLOADS_DIR / f"{uid}{suffix}").write_bytes(data)
    return {"id": f"up-{uid}", "name": Path(filename).name[:80], "kind": kind}


def sweep() -> None:
    """Delete finished jobs and uploads older than RETENTION_S, and forget jobs whose folder is gone."""
    cutoff = time.time() - RETENTION_S
    for folder in (JOBS_DIR, UPLOADS_DIR):
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            job = _jobs.get(path.name)
            if (job and job.status in ACTIVE) or path.stat().st_mtime >= cutoff:
                continue
            try:
                shutil.rmtree(path) if path.is_dir() else path.unlink()
            except OSError:
                pass  # in use (e.g. a video being downloaded); try again next sweep
    with _lock:
        for job_id in [i for i, j in _jobs.items() if j.status not in ACTIVE and not (JOBS_DIR / i).exists()]:
            del _jobs[job_id]


# ---------- jobs ----------
def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def video_path(job: Job) -> Path:
    return JOBS_DIR / job.id / "video.mp4"


def submit(request: MotionJobRequest) -> Job:
    character = resolve_character(request.character_id) if request.character_id else None
    sweep()
    with _lock:
        if sum(j.status in ACTIVE for j in _jobs.values()) >= MAX_PENDING:
            raise Busy()
        job = Job(id=uuid.uuid4().hex[:16], title=request.title, secret=[request])
        _jobs[job.id] = job
    _worker.submit(_run, job, character)
    return job


def _kill_tree(proc: subprocess.Popen) -> None:
    """Stop the renderer and everything it started (Playwright driver, Chrome, ffmpeg)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        os.killpg(proc.pid, signal.SIGKILL)


def cancel(job: Job) -> None:
    job.cancelled = True
    if job.status == "queued":
        job.status = "cancelled"
        job.secret.clear()
    if job.proc is not None:
        _kill_tree(job.proc)


def _stage(job: Job, status: str) -> None:
    if job.cancelled:
        raise _Cancelled()
    job.status, job.stage, job.progress, job.stage_started = status, status, 0.0, time.time()


def _run(job: Job, character: Path | None) -> None:
    if not job.secret:  # cancelled while queued
        return
    request = job.secret.pop()  # the request holds the API key; it lives only in this frame now
    job_dir = JOBS_DIR / job.id
    voice, title = request.voice, request.title
    try:
        job_dir.mkdir(parents=True, exist_ok=True)
        _stage(job, "writing")
        storyboard = writer.write(request)
        del request
        # The creator's own title is the YouTube title; the AI writes the description and hashtags.
        storyboard.youtube.title = title
        (job_dir / "youtube.json").write_text(storyboard.youtube.model_dump_json(), encoding="utf-8")
        _stage(job, "voicing")
        speech = pipeline.prepare(job_dir, storyboard, voice, character)
        _stage(job, "rendering")
        _render(job, job_dir)
        for copy in job_dir.glob("character.*"):  # the upload itself stays in uploads/
            copy.unlink(missing_ok=True)
        job.result = {"duration": speech.duration, "youtube": storyboard.youtube.model_dump()}
        job.status, job.progress = "done", 1.0
    except _Cancelled:
        job.status, job.message = "cancelled", "Cancelled."
    except MotionError as error:
        job.status, job.message = "failed", str(error)
    except Exception as error:  # a bug, not a user problem; log the type only (no locals, no key)
        logger.error(f"motion job {job.id} failed: {type(error).__name__}: {error}")
        job.status, job.message = "failed", "Something went wrong while making the video. The server log has details."
    finally:
        job.proc = None


def _render(job: Job, job_dir: Path) -> None:
    log_path = job_dir / "render.log"
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.services.motion.renderer", str(job_dir)],
            cwd=utils.root_dir(), stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8",
            errors="replace", env={**os.environ, "PYTHONUTF8": "1"}, start_new_session=os.name != "nt",
        )
        job.proc = proc
        if job.cancelled:  # cancel arrived between the stage change and the process starting
            _kill_tree(proc)

        def time_out() -> None:
            job.timed_out = True
            _kill_tree(proc)

        timer = threading.Timer(RENDER_TIMEOUT_S, time_out)
        timer.start()
        try:
            for line in proc.stdout:
                parts = line.split()
                if len(parts) == 3 and parts[0] == "progress":
                    job.progress = int(parts[1]) / max(int(parts[2]), 1)
            proc.wait()
        finally:
            timer.cancel()
    if job.cancelled:
        raise _Cancelled()
    if job.timed_out:
        raise MotionError(f"Rendering took longer than {RENDER_TIMEOUT_S // 60} minutes and was stopped. "
                          "Try a shorter script.")
    if proc.returncode != 0:
        detail = log_path.read_text(encoding="utf-8", errors="replace")
        logger.error(f"motion render {job.id} failed:\n{detail[-3000:]}")
        if "No module named 'playwright'" in detail:
            raise MotionError("The renderer isn't installed. Run: uv pip install playwright")
        if "Executable doesn't exist" in detail or "playwright install" in detail:
            raise MotionError("No browser for rendering. Install Google Chrome, or run: playwright install chromium")
        raise MotionError(f"Rendering failed. Details are in storage/motion/jobs/{job.id}/render.log")
