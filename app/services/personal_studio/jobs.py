"""Cola de trabajos secuencial del estudio personal.

Igual que el render de Cartoon Studio, se procesa un trabajo pesado a la vez en
CPU. La cola se persiste en ``storage/personal_studio/jobs.json`` para que el
panel muestre el resultado tras recargar. Los trabajos que estaban corriendo
cuando murió el proceso se marcan como interrumpidos, nunca como completados.

La cancelación es cooperativa: el render la consulta entre fotogramas y el
trabajador de voz termina su proceso hijo.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from loguru import logger

from app.services.personal_studio import studio
from app.services.personal_studio.security import StudioError, atomic_json, read_json
from app.services.personal_studio.studio import ProjectStore

PENDING = "pending"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"
TERMINAL = {COMPLETED, FAILED, CANCELLED}

STAGE_LABELS = {
    "en_cola": "En cola",
    "narracion": "Generando narración",
    "animacion": "Animando avatar",
    "composicion": "Componiendo video",
    "portada": "Creando portada",
    "audio": "Exportando audio",
    "listo": "Listo",
}

MAX_JOBS = 200
_DEFAULT: "StudioJobManager | None" = None
_DEFAULT_LOCK = threading.Lock()


def default_manager() -> "StudioJobManager":
    """Una sola cola por proceso, compartida por todas las pestañas."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = StudioJobManager()
        return _DEFAULT


def _clean_error(value: BaseException | str) -> str:
    text = str(value).replace("\n", " ").strip()
    return text[:500] or value.__class__.__name__


class StudioJobManager:
    def __init__(
        self,
        root: str | Path | None = None,
        *,
        build: Callable[..., dict] | None = None,
        max_workers: int = 1,
    ):
        self.store = ProjectStore(root)
        self.root = self.store.root
        self._path = self.root / "jobs.json"
        self._lock = threading.RLock()
        self._events: dict[str, threading.Event] = {}
        self._jobs: dict[str, dict] = {}
        self._build = build or studio.build_project
        self._closed = False
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)), thread_name_prefix="bynnex-studio"
        )
        self._load()
        self._recover()

    # -- persistencia --------------------------------------------------
    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            data = read_json(self._path)
        except StudioError:
            return
        for record in data.get("jobs") or []:
            if isinstance(record, dict) and record.get("id"):
                self._jobs[record["id"]] = record

    def _persist(self) -> None:
        with self._lock:
            records = sorted(
                self._jobs.values(), key=lambda job: job.get("created_at") or 0
            )[-MAX_JOBS:]
            atomic_json(self._path, {"schema_version": 1, "jobs": records})

    def _recover(self) -> None:
        changed = False
        for job in self._jobs.values():
            if job.get("state") in {PENDING, RUNNING}:
                job.update(
                    state=FAILED,
                    stage="interrumpido",
                    error="El trabajo se interrumpió al reiniciar el servidor",
                    recovered=True,
                    finished_at=time.time(),
                )
                changed = True
        if changed:
            self._persist()

    # -- API -----------------------------------------------------------
    def submit(self, project_id: str) -> dict:
        project = self.store.get(project_id)
        with self._lock:
            active = [
                job
                for job in self._jobs.values()
                if job.get("project_id") == project_id and job.get("state") in {PENDING, RUNNING}
            ]
            if active:
                return dict(active[0])
            job = {
                "id": f"j_{uuid.uuid4().hex[:10]}",
                "project_id": project_id,
                "project_name": project.get("name"),
                "state": PENDING,
                "stage": "en_cola",
                "progress": 0.0,
                "error": None,
                "warnings": [],
                "created_at": time.time(),
                "started_at": None,
                "finished_at": None,
                "recovered": False,
            }
            self._jobs[job["id"]] = job
            event = threading.Event()
            self._events[job["id"]] = event
            self._persist()
        self._executor.submit(self._run, job["id"], event)
        return dict(job)

    def _run(self, job_id: str, event: threading.Event) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or self._closed:
                return
            job.update(state=RUNNING, stage="iniciando", started_at=time.time())
            self._persist()
            project_id = job["project_id"]

        def progress(stage: str, value: float) -> None:
            with self._lock:
                job.update(stage=stage, progress=round(max(0.0, min(1.0, value)), 3))
                self._persist()

        try:
            result = self._build(
                project_id,
                store=self.store,
                progress=progress,
                cancel=event.is_set,
            )
            with self._lock:
                job.update(
                    state=COMPLETED,
                    stage="listo",
                    progress=1.0,
                    finished_at=time.time(),
                    warnings=result.get("warnings") or [],
                )
        except StudioError as exc:
            cancelled = event.is_set()
            with self._lock:
                job.update(
                    state=CANCELLED if cancelled else FAILED,
                    stage="cancelado" if cancelled else "error",
                    error=_clean_error(exc),
                    finished_at=time.time(),
                )
        except Exception as exc:  # noqa: BLE001 - la cola no debe morir
            logger.exception("BYNEX studio job failed")
            with self._lock:
                job.update(
                    state=FAILED,
                    stage="error",
                    error=_clean_error(exc),
                    finished_at=time.time(),
                )
        finally:
            self._events.pop(job_id, None)
            self._persist()

    def list(self) -> list[dict]:
        with self._lock:
            jobs = [dict(job) for job in self._jobs.values()]
        jobs.sort(key=lambda job: job.get("created_at") or 0, reverse=True)
        return jobs

    def get(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise StudioError(f"El trabajo no existe: {job_id}")
            return dict(job)

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise StudioError(f"El trabajo no existe: {job_id}")
            if job.get("state") in TERMINAL:
                return dict(job)
            event = self._events.get(job_id)
            if event is not None:
                event.set()
            job["stage"] = "cancelando"
            self._persist()
            return dict(job)

    def wait(self, job_id: str, timeout: float = 1800.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.get(job_id)
            if job.get("state") in TERMINAL:
                return job
            time.sleep(0.2)
        raise StudioError("El trabajo no terminó en el tiempo esperado")

    def shutdown(self, wait: bool = False) -> None:
        with self._lock:
            self._closed = True
            for event in self._events.values():
                event.set()
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def stage_label(self, stage: str) -> str:
        return STAGE_LABELS.get(stage, stage)
