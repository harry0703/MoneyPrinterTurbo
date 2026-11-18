import copy
import hashlib
import json
import threading
import time
from collections import deque
from dataclasses import asdict

from loguru import logger

from app.config import config
from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.models import const
from app.models.schema import VideoParams
from app.services import state as sm
from app.services import task as tm
from app.services import codex_image, jalapeno_video, volcengine_seedance
from app.services.loomloom import LoomLoomConfirmedVideoRequest
from app.utils.logging_utils import (
    format_log_record,
    log_scope_thread_id,
    runtime_log_filter,
)


# The WebUI's config is kept in a process-level global dict. The old synchronous implementation held
# runtime_config_lock for the whole generation, so different browser sessions actually ran serially. Concurrency is fixed
# at 1 here, keeping the original config consistency and avoiding multiple threads pointlessly waiting outside the config lock.
_task_manager = InMemoryTaskManager(
    max_concurrent_tasks=1,
    max_queued_tasks=max(1, int(config.app.get("max_queued_tasks", 100))),
)
_task_logs: dict[str, deque[str]] = {}
_task_logs_lock = threading.RLock()
_MAX_LOG_TASKS = 20
_MAX_LOG_RECORDS_PER_TASK = 1000
_submission_lock = threading.RLock()
_active_submissions: dict[str, str] = {}
# Streamlit can't push component updates directly from a background thread, only via Fragment polling. 0.5 seconds
# is enough to keep WebUI logs close to real-time terminal output without constantly using browser resources like high-frequency refreshes would.
TASK_LOG_REFRESH_INTERVAL_SECONDS = 0.5


def is_generation_active(task_id: str) -> bool:
    """Use the background reserved slots as the source of truth, covering the window between enqueue and state publication."""
    with _submission_lock:
        return task_id in _active_submissions.values()


def _submission_signature(
    params, references, request, endpoint, preview, codex_image_context=None
):
    # Only a digest is kept, no credentials or uploaded content. Different Keys/models/inputs are different requests,
    # and identical content may be generated again after completion; only duplicate submissions still queued or running are merged.
    request_inputs = asdict(request) if request is not None else None
    if request_inputs is not None:
        # Two tabs generate their own idempotency ID for the same quote input; that isn't a content difference.
        # Keep the account, model, input rows and quote version, and continue with the first confirmed request.
        request_inputs.pop("client_request_id", None)
    payload = {
        "params": params.model_dump(mode="json", warnings=False),
        "settings": {
            name: config.snapshot_config_with_pending(getattr(config, name))
            for name in ("app", "azure", "elevenlabs", "siliconflow", "chatterbox")
        },
        "references": [hashlib.sha256(value or b"").hexdigest() for value in references],
        "request": request_inputs,
        "endpoint": asdict(endpoint) if endpoint is not None else None,
        # The voice-over source changes the actual output; the staging path changes with the local task ID and isn't an input difference.
        "voice_preview": {
            key: preview[key]
            for key in ("script", "voice_name", "voice_rate", "voice_volume", "duration", "params", "audio_digest")
            if key in preview
        } if preview else None,
    }
    if codex_image_context is not None:
        payload["codex_image"] = asdict(codex_image_context)
    if preview and not preview.get("audio_digest"):
        # When an old caller has no content digest, two files can't be inferred to be identical from the same duration alone.
        # Arbitrary paths aren't read before validation; better to keep separate requests for different files.
        payload["voice_preview"]["audio_file"] = preview.get("audio_file")
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def _append_task_log(task_id: str, message: str) -> None:
    """Keep a limited number of logs per task for Streamlit Fragments to poll safely."""
    with _task_logs_lock:
        records = _task_logs.get(task_id)
        if records is None:
            # Only keep logs for recent tasks, so the WebUI service doesn't keep using memory after running for a long time.
            # dict keeps insertion order; task logs are only for UI diagnosis, so evicting the oldest records doesn't affect tasks.
            if len(_task_logs) >= _MAX_LOG_TASKS:
                oldest_task_id = next(iter(_task_logs))
                _task_logs.pop(oldest_task_id, None)
            records = deque(maxlen=_MAX_LOG_RECORDS_PER_TASK)
            _task_logs[task_id] = records
        records.append(message.rstrip())


def get_task_logs(task_id: str) -> list[str]:
    """Return a log snapshot, so page rendering doesn't hold the lock used by the background thread."""
    with _task_logs_lock:
        return list(_task_logs.get(task_id, ()))


def _run_generation(
    task_id: str,
    params: VideoParams,
    capture_logs: bool,
    voice_preview: dict | None = None,
    loomloom_video_request: LoomLoomConfirmedVideoRequest | None = None,
    voxcpm_reference_audio: bytes | None = None,
    voxcpm_prompt_audio: bytes | None = None,
    voxcpm_prompt_text: str = "",
    jalapeno_video_endpoint: volcengine_seedance.SeedanceEndpoint | None = None,
    codex_image_context: codex_image.CodexImageContext | None = None,
) -> dict:
    """
    Run the existing video pipeline in a background thread.

    Loguru sinks are process-level resources, so they must be filtered by the current worker thread. Otherwise concurrently running
    API tasks or other pages' logs would mix into the current task. Helper threads the task starts for downloads, clip encoding and heartbeats
    are attributed to the worker thread via bind_log_scope, and their logs must be collected too, otherwise
    these slow stages produce no output in the WebUI. The page only reads a plain list snapshot and never accesses Streamlit session_state
    from the background thread, eliminating mixed-up delta paths on refresh at the root.
    """
    log_handler_id = None
    worker_thread_id = threading.get_ident()
    try:
        if capture_logs:
            log_handler_id = logger.add(
                lambda message: _append_task_log(task_id, str(message)),
                level=0,
                format=format_log_record,
                colorize=False,
                filter=lambda record: (
                    log_scope_thread_id(record["thread"].id) == worker_thread_id
                    and runtime_log_filter(record)
                ),
            )

        # The full task still uses the original config lock, preventing another WebUI session from changing process-level config
        # such as Provider and keys midway, which would make the same video use different settings at different points.
        with config.runtime_config_lock():
            return tm.start(
                task_id=task_id,
                params=params,
                voice_preview=voice_preview,
                loomloom_video_request=loomloom_video_request,
                voxcpm_reference_audio=voxcpm_reference_audio,
                voxcpm_prompt_audio=voxcpm_prompt_audio,
                voxcpm_prompt_text=voxcpm_prompt_text,
                **({"codex_image_context": codex_image_context}
                   if codex_image_context is not None else {}),
                **({"jalapeno_video_endpoint": jalapeno_video_endpoint}
                   if jalapeno_video_endpoint is not None else {}),
            )
    except Exception as exc:
        # tm.start already converts pipeline exceptions into a failure state; this additionally protects the WebUI wrapper layer, such as the log sink
        # and config lock. Any background thread exception must leave a final state, so the task
        # manager never shows "generating" forever after the worker thread exits.
        error = f"{type(exc).__name__}: {exc}"
        failure = {
            "task_id": task_id,
            "state": const.TASK_STATE_FAILED,
            "progress": 0,
            "failed_stage": "webui_worker",
            "error": error,
        }
        sm.state.update_task(
            task_id,
            state=failure["state"],
            progress=failure["progress"],
            failed_stage=failure["failed_stage"],
            error=failure["error"],
        )
        logger.exception(
            f"unexpected WebUI generation worker failure, "
            f"task_id={task_id}, error={exc}"
        )
        return failure
    finally:
        with _submission_lock:
            for signature, active_id in list(_active_submissions.items()):
                if active_id == task_id:
                    del _active_submissions[signature]
        if log_handler_id is not None:
            try:
                logger.remove(log_handler_id)
            except ValueError:
                logger.debug(
                    f"WebUI task log handler already removed: task_id={task_id}"
                )


def submit_generation(
    task_id: str,
    params: VideoParams,
    capture_logs: bool = True,
    voice_preview: dict | None = None,
    loomloom_video_request: LoomLoomConfirmedVideoRequest | None = None,
    voxcpm_reference_audio: bytes | None = None,
    voxcpm_prompt_audio: bytes | None = None,
    voxcpm_prompt_text: str = "",
    jalapeno_video_endpoint: volcengine_seedance.SeedanceEndpoint | None = None,
) -> str:
    """
    Register and submit a WebUI video generation task, returning immediately after the call.

    The task state must be written before the thread starts. That way the task can be queried as soon as this page script run ends,
    and browser refreshes or WebSocket reconnects don't depend on a placeholder in the old page's memory.
    """
    task_params = params.model_copy(deep=True)
    # The subtitle timeline and nested preview parameters remain mutable in
    # Streamlit session state. Snapshot them before this job enters the queue.
    voice_preview_snapshot = copy.deepcopy(voice_preview) if voice_preview else None
    # Reference audio belongs only to this queued request. It is deliberately
    # separate from VideoParams so it cannot reach task history, presets, state
    # persistence, or logs. ``bytes`` is immutable; make an explicit snapshot
    # before the background worker starts so later WebUI reruns cannot share
    # mutable upload state with this task.
    voxcpm_reference_audio_snapshot = (
        bytes(voxcpm_reference_audio) if voxcpm_reference_audio else None
    )
    voxcpm_prompt_audio_snapshot = (
        bytes(voxcpm_prompt_audio) if voxcpm_prompt_audio else None
    )
    voxcpm_prompt_text_snapshot = str(voxcpm_prompt_text or "")
    # A confirmed request is a frozen data object passed only within the current process. The API Key never enters
    # VideoParams, task state, logs or saved history, and isn't affected by later page reruns.
    loomloom_request_snapshot = loomloom_video_request
    # Preparing the next item is allowed while queued, but confirmed paid config must not change with the global form.
    # The snapshot's key doesn't take part in repr; it's only passed with in-process task parameters and never written into VideoParams.
    if task_params.video_source == "jalapeno" and jalapeno_video_endpoint is None:
        jalapeno_video_endpoint = jalapeno_video.endpoint(
            config.snapshot_config_with_pending(config.app)
        )
    codex_image_context = (
        codex_image.capture_context(config.snapshot_config_with_pending(config.app))
        if task_params.video_source == "codex_image"
        else None
    )
    signature = _submission_signature(
        task_params,
        (
            voxcpm_reference_audio_snapshot,
            voxcpm_prompt_audio_snapshot,
            voxcpm_prompt_text_snapshot.encode(),
        ),
        loomloom_request_snapshot,
        jalapeno_video_endpoint,
        voice_preview_snapshot,
        codex_image_context,
    )
    # Deduplicate and reserve within the same lock, so even simultaneous clicks in two tabs only enqueue once.
    with _submission_lock:
        existing = _active_submissions.get(signature)
        if existing:
            return existing
        if task_id in _active_submissions.values():
            return task_id
        _active_submissions[signature] = task_id
    try:
        _enqueue_generation(
            task_id,
            task_params,
            capture_logs,
            voice_preview_snapshot,
            loomloom_request_snapshot,
            voxcpm_reference_audio_snapshot,
            voxcpm_prompt_audio_snapshot,
            voxcpm_prompt_text_snapshot,
            jalapeno_video_endpoint,
            codex_image_context,
        )
    except Exception:
        with _submission_lock:
            if _active_submissions.get(signature) == task_id:
                del _active_submissions[signature]
        raise
    return task_id


def _enqueue_generation(
    task_id,
    task_params,
    capture_logs,
    voice_preview_snapshot,
    loomloom_request_snapshot,
    voxcpm_reference_audio_snapshot,
    voxcpm_prompt_audio_snapshot,
    voxcpm_prompt_text_snapshot,
    jalapeno_video_endpoint,
    codex_image_context=None,
):
    submitted_at = time.time()
    sm.state.update_task(
        task_id,
        state=const.TASK_STATE_PROCESSING,
        progress=0,
        video_subject=task_params.video_subject or task_params.video_script or task_id,
        generation_submitted_at=submitted_at,
        generation_activity={"phase": "queued", "started_at": submitted_at,
                             "updated_at": submitted_at},
    )
    try:
        _task_manager.add_task(
            _run_generation,
            task_id=task_id,
            params=task_params,
            capture_logs=capture_logs,
            voice_preview=voice_preview_snapshot,
            loomloom_video_request=loomloom_request_snapshot,
            voxcpm_reference_audio=voxcpm_reference_audio_snapshot,
            voxcpm_prompt_audio=voxcpm_prompt_audio_snapshot,
            voxcpm_prompt_text=voxcpm_prompt_text_snapshot,
            **({"codex_image_context": codex_image_context}
               if codex_image_context is not None else {}),
            **({"jalapeno_video_endpoint": jalapeno_video_endpoint}
               if jalapeno_video_endpoint is not None else {}),
        )
    except Exception as exc:
        # A scheduling failure, like a pipeline failure, must become a queryable state, so the task manager doesn't show
        # "generating" forever. The exception type is kept to quickly locate queue problems from Docker or local logs.
        error = f"{type(exc).__name__}: {exc}"
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_FAILED,
            progress=0,
            failed_stage="scheduling",
            error=error,
        )
        logger.exception(
            f"failed to submit WebUI generation task, task_id={task_id}, error={exc}"
        )
        raise
