"""Render job queue for the Cartoon Studio 2D web panel.

One heavy render at a time by default, on the CPU. The queue is persisted next
to the projects so the panel can show what happened after a reload. Jobs that
were running when the process died are marked as interrupted instead of being
reported as completed.

Cancellation is cooperative: the worker polls an event, the animation encoder
stops between frames and terminates FFmpeg, and ``video_project`` writes its
cancel marker so its FFmpeg stages stop within ~0.1 s.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from app.services import cartoon_studio
from app.services.cartoon_studio_workspace import (
    StudioError,
    StudioStore,
    _atomic_json,
)
from app.services.video_project import ProjectError, VideoProject

QUEUED = "pending"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"
TERMINAL = {COMPLETED, FAILED, CANCELLED}

_STAGE_LABELS = {
    "imagenes": "Generando imágenes",
    "narracion": "Generando narración",
    "assembly": "Ensamblando video",
    "video": "Codificando video",
    "audio": "Procesando audio",
    "subtitles": "Quemando subtítulos",
    "export": "Exportando MP4",
}


def _now() -> float:
    return time.time()


def _clean_error(value: BaseException | str) -> str:
    text = str(value).replace("\n", " ").strip()
    return text[:800] or value.__class__.__name__


class RenderJobManager:
    def __init__(
        self,
        root: str | Path | None = None,
        *,
        max_workers: int = 1,
        build: Callable[..., dict] = cartoon_studio.build,
    ):
        self.store = StudioStore(root)
        self.root = self.store.root
        self._path = self.root / ".render_jobs.json"
        self._lock = threading.RLock()
        self._events: dict[str, threading.Event] = {}
        self._build = build
        self._closed = False
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)),
            thread_name_prefix="cartoon-render",
        )
        self._jobs: dict[str, dict] = {}
        self._load()
        self._recover_interrupted()

    # -- persistence ---------------------------------------------------

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            import json

            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        records = data.get("jobs") if isinstance(data, dict) else None
        for record in records or []:
            if isinstance(record, dict) and record.get("id"):
                self._jobs[record["id"]] = record

    def _persist(self) -> None:
        with self._lock:
            _atomic_json(
                self._path,
                {
                    "schema_version": 1,
                    "jobs": sorted(
                        self._jobs.values(), key=lambda job: job["created_at"]
                    ),
                },
            )

    def _recover_interrupted(self) -> None:
        changed = False
        for job in self._jobs.values():
            if job.get("state") in {QUEUED, RUNNING}:
                job.update(
                    state=FAILED,
                    stage="interrumpido",
                    error="Render interrumpido por un reinicio del servidor",
                    recovered=True,
                    finished_at=_now(),
                )
                changed = True
                logger.warning(
                    f"cartoon render job marked interrupted: {job.get('id')}"
                )
        if changed:
            self._persist()

    # -- queue ---------------------------------------------------------

    def submit(self, project_id: str, options: dict | None = None) -> dict:
        if self._closed:
            raise StudioError("El gestor de trabajos está cerrado")
        if not self.store.exists(project_id):
            raise StudioError(f"El proyecto no existe: {project_id}")
        options = dict(options or {})
        job = {
            "id": uuid.uuid4().hex[:12],
            "project_id": project_id,
            "state": QUEUED,
            "stage": "en_cola",
            "message": "En cola",
            "error": "",
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
            "revision": "",
            "export_path": "",
            "cancel_requested": False,
            "recovered": False,
            "options": self._validate_options(options),
        }
        with self._lock:
            self._jobs[job["id"]] = job
            self._events[job["id"]] = threading.Event()
            self._persist()
        self._executor.submit(self._run, job["id"])
        return dict(job)

    @staticmethod
    def _validate_options(options: dict) -> dict:
        allowed = {
            "mode",
            "fps",
            "crf",
            "output_width",
            "output_height",
            "voice",
            "voice_rate",
            "subtitles",
            "subtitle_font_size",
            "stage_timeout",
        }
        unknown = set(options) - allowed
        if unknown:
            raise StudioError(
                f"Opciones de render desconocidas: {', '.join(sorted(unknown))}"
            )
        mode = options.get("mode", "auto")
        if mode not in {"auto", "classic", "animation"}:
            raise StudioError("El modo debe ser auto, classic o animation")
        fps = options.get("fps", 24)
        if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 60:
            raise StudioError("FPS debe ser un entero entre 1 y 60")
        crf = options.get("crf", 20)
        if isinstance(crf, bool) or not isinstance(crf, int) or not 0 <= crf <= 51:
            raise StudioError("CRF debe ser un entero entre 0 y 51")
        for key in ("output_width", "output_height"):
            value = options.get(key)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 64 <= value <= 4320
            ):
                raise StudioError(f"{key} debe estar entre 64 y 4320")
        voice = options.get("voice", "")
        if not isinstance(voice, str) or len(voice) > 200:
            raise StudioError("La voz debe ser texto de menos de 200 caracteres")
        rate = options.get("voice_rate", 1.0)
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            raise StudioError("La velocidad de voz debe ser un número")
        if not 0.5 <= float(rate) <= 2.0:
            raise StudioError("La velocidad de voz debe estar entre 0.5 y 2.0")
        subtitles = options.get("subtitles", False)
        if not isinstance(subtitles, bool):
            raise StudioError("El campo de subtítulos debe ser booleano")
        font = options.get("subtitle_font_size", 56)
        if isinstance(font, bool) or not isinstance(font, int) or not 16 <= font <= 160:
            raise StudioError("El tamaño de subtítulos debe estar entre 16 y 160")
        timeout = options.get("stage_timeout", 600)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise StudioError("El tiempo límite debe ser un número")
        if not 1 <= float(timeout) <= 7200:
            raise StudioError("El tiempo límite debe estar entre 1 y 7200 segundos")
        result = dict(options)
        result["mode"] = mode
        result["fps"] = fps
        result["crf"] = crf
        result["voice"] = voice.strip()
        result["voice_rate"] = float(rate)
        result["subtitles"] = subtitles
        result["subtitle_font_size"] = font
        result["stage_timeout"] = float(timeout)
        return result

    # -- worker --------------------------------------------------------

    def _update(self, job_id: str, **values: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.update(values)
            self._persist()

    def _run(self, job_id: str) -> None:
        event = self._events.get(job_id)
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None or event is None:
            return
        if event.is_set():
            self._update(
                job_id,
                state=CANCELLED,
                stage="cancelado",
                message="Cancelado antes de iniciar",
                finished_at=_now(),
            )
            return
        self._update(
            job_id,
            state=RUNNING,
            stage="preparando",
            message="Preparando render",
            started_at=_now(),
        )
        options = job["options"]
        project_id = job["project_id"]
        try:
            loaded = self.store.load(project_id)
            settings = loaded["settings"]
            voice = options.get("voice") or settings.get("voice", "")
            output_width = options.get("output_width")
            output_height = options.get("output_height")
            if output_width is None:
                output_width = settings.get("output_width")
            if output_height is None:
                output_height = settings.get("output_height")
            animation_settings = cartoon_studio.animation_render_settings(
                loaded["storyboard"].aspect,
                fps=options["fps"],
                crf=options["crf"],
                output_width=output_width,
                output_height=output_height,
            )

            def on_stage(stage: str, reused: bool) -> None:
                label = _STAGE_LABELS.get(stage, f"Etapa: {stage}")
                self._update(
                    job_id,
                    stage=stage,
                    message=("Reutilizado: " if reused else "") + label,
                )

            def on_revision(revision: str) -> None:
                self._update(job_id, revision=revision)
                if event.is_set():
                    self._cancel_revision(project_id, revision)

            result = self._build(
                project_dir=self.store.project_dir(project_id),
                storyboard=loaded["storyboard"],
                voice_name=voice,
                voice_rate=options["voice_rate"],
                subtitles=options["subtitles"],
                subtitle_font_size=options["subtitle_font_size"],
                mode=options["mode"],
                animation_settings=animation_settings,
                stage_timeout=options["stage_timeout"],
                cancel=event.is_set,
                on_stage=on_stage,
                on_revision=on_revision,
            )
            status = result.get("status") or {}
            export = status.get("export") or {}
            if event.is_set():
                self._update(
                    job_id,
                    state=CANCELLED,
                    stage="cancelado",
                    message="Render cancelado",
                    finished_at=_now(),
                )
                return
            self._update(
                job_id,
                state=COMPLETED,
                stage="completado",
                message="Render completado",
                revision=result.get("revision", job.get("revision", "")),
                export_path=export.get("path", ""),
                finished_at=_now(),
            )
        except cartoon_studio.RenderCancelled:
            self._update(
                job_id,
                state=CANCELLED,
                stage="cancelado",
                message="Render cancelado",
                finished_at=_now(),
            )
        except (StudioError, cartoon_studio.CartoonStudioError, ProjectError) as exc:
            self._finish_failure(job_id, event, exc)
        except Exception as exc:  # noqa: BLE001 - surfaced in the panel
            logger.exception(f"cartoon render job failed: {job_id}")
            self._finish_failure(job_id, event, exc)

    def _finish_failure(
        self, job_id: str, event: threading.Event, exc: BaseException
    ) -> None:
        if event.is_set() or "cancelled" in str(exc).lower():
            self._update(
                job_id,
                state=CANCELLED,
                stage="cancelado",
                message="Render cancelado",
                finished_at=_now(),
            )
            return
        self._update(
            job_id,
            state=FAILED,
            stage="error",
            message="El render falló",
            error=_clean_error(exc),
            finished_at=_now(),
        )

    def _cancel_revision(self, project_id: str, revision: str) -> None:
        try:
            VideoProject(self.store.project_dir(project_id)).cancel(revision)
        except (OSError, ProjectError, ValueError) as exc:
            logger.debug(f"cartoon cancel marker not written: {exc}")

    # -- public state --------------------------------------------------

    def jobs(self, project_id: str | None = None) -> list[dict]:
        with self._lock:
            values = [
                dict(job)
                for job in self._jobs.values()
                if project_id is None or job.get("project_id") == project_id
            ]
        values.sort(key=lambda job: job["created_at"], reverse=True)
        return values

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def queue_position(self, job_id: str) -> int | None:
        """1-based position among queued jobs, or ``None`` if not waiting."""
        waiting = [
            job
            for job in sorted(self.jobs(), key=lambda item: item["created_at"])
            if job["state"] == QUEUED
        ]
        for index, job in enumerate(waiting, start=1):
            if job["id"] == job_id:
                return index
        return None

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise StudioError("Trabajo de render no encontrado")
            if job["state"] in TERMINAL:
                return dict(job)
            event = self._events.get(job_id)
            if event is not None:
                event.set()
            job["cancel_requested"] = True
            if job["state"] == QUEUED:
                job.update(
                    state=CANCELLED,
                    stage="cancelado",
                    message="Cancelado antes de iniciar",
                    finished_at=_now(),
                )
            else:
                job.update(stage="cancelando", message="Cancelando…")
            revision = job.get("revision")
            self._persist()
        if job["state"] == RUNNING and revision:
            self._cancel_revision(job["project_id"], revision)
        return dict(job)

    def active_count(self) -> int:
        return len(
            [job for job in self.jobs() if job["state"] in {QUEUED, RUNNING}]
        )

    def latest_error(self, project_id: str) -> dict | None:
        for job in self.jobs(project_id):
            if job["state"] == FAILED:
                return job
        return None

    def shutdown(self, wait: bool = True) -> None:
        self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=True)


_manager: RenderJobManager | None = None
_manager_lock = threading.Lock()


def default_manager() -> RenderJobManager:
    """Process-wide queue shared by every Streamlit rerun/session."""
    global _manager
    with _manager_lock:
        if _manager is None or _manager._closed:
            _manager = RenderJobManager()
        return _manager


__all__ = [
    "CANCELLED",
    "COMPLETED",
    "FAILED",
    "QUEUED",
    "RUNNING",
    "RenderJobManager",
    "default_manager",
]
