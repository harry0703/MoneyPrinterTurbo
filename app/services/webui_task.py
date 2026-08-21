import threading
from collections import deque

from loguru import logger

from app.config import config
from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.models import const
from app.models.schema import VideoParams
from app.services import state as sm
from app.services import task as tm
from app.services.loomloom import LoomLoomConfirmedVideoRequest
from app.utils.logging_utils import format_log_record


# The WebUI configuration lives in a process-level global dict. The old synchronous implementation held the
# runtime_config_lock for the whole generation, so different browser sessions effectively ran serially. Fixing the
# concurrency at 1 preserves that configuration consistency and keeps threads from waiting pointlessly outside the config lock.
_task_manager = InMemoryTaskManager(
    max_concurrent_tasks=1,
    max_queued_tasks=max(1, int(config.app.get("max_queued_tasks", 100))),
)
_task_logs: dict[str, deque[str]] = {}
_task_logs_lock = threading.RLock()
_MAX_LOG_TASKS = 20
_MAX_LOG_RECORDS_PER_TASK = 1000
# Streamlit cannot push widget updates from a background thread; only Fragment polling works. 0.5 seconds
# brings the WebUI log close to terminal real-time output without the constant browser load of high-frequency refreshes.
TASK_LOG_REFRESH_INTERVAL_SECONDS = 0.5


def _append_task_log(task_id: str, message: str) -> None:
    """Keep a bounded number of logs per task for safe polling by the Streamlit Fragment."""
    with _task_logs_lock:
        records = _task_logs.get(task_id)
        if records is None:
            # Keep logs for only the most recent tasks so a long-running WebUI does not keep growing memory.
            # dict preserves insertion order; task logs are UI diagnostics only, so evicting the oldest record never affects tasks.
            if len(_task_logs) >= _MAX_LOG_TASKS:
                oldest_task_id = next(iter(_task_logs))
                _task_logs.pop(oldest_task_id, None)
            records = deque(maxlen=_MAX_LOG_RECORDS_PER_TASK)
            _task_logs[task_id] = records
        records.append(message.rstrip())


def get_task_logs(task_id: str) -> list[str]:
    """Return a log snapshot so page rendering never holds the lock used by the background thread."""
    with _task_logs_lock:
        return list(_task_logs.get(task_id, ()))


def _run_generation(
    task_id: str,
    params: VideoParams,
    capture_logs: bool,
    voice_preview: dict | None = None,
    loomloom_video_request: LoomLoomConfirmedVideoRequest | None = None,
) -> dict:
    """
    Run the existing video pipeline in a background thread.

    Loguru sinks are process-level resources, so filtering by the current worker thread is
    mandatory — otherwise concurrently running API tasks or other pages' logs leak in. The page
    reads only a plain list snapshot and never touches Streamlit session_state from the
    background thread, eliminating stale-delta paths on refresh at the root.
    """
    log_handler_id = None
    worker_thread_id = threading.get_ident()
    try:
        if capture_logs:
            log_handler_id = logger.add(
                lambda message: _append_task_log(task_id, str(message)),
                level="DEBUG",
                format=format_log_record,
                colorize=False,
                filter=lambda record: record["thread"].id == worker_thread_id,
            )

        # Full tasks still use the original config lock so another WebUI session cannot modify process-level
        # configuration (Provider, keys, ...) mid-generation and make one video use different settings before and after.
        with config.runtime_config_lock():
            return tm.start(
                task_id=task_id,
                params=params,
                voice_preview=voice_preview,
                loomloom_video_request=loomloom_video_request,
            )
    except Exception as exc:
        # tm.start already converts pipeline exceptions into failed states; this extra guard covers the log sink
        # and config lock in the WebUI wrapper. Any background-thread exception must leave a terminal state so the
        # task manager never shows "generating" forever after the worker exits.
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
) -> None:
    """
    Register and submit the WebUI video generation task; return immediately after the call.

    Task state must be written before the thread starts, so the page script can query the task
    when it finishes this run — browser refreshes and WebSocket reconnects never depend on a
    placeholder living in the old page's memory.
    """
    task_params = params.model_copy(deep=True)
    # The preview payload contains only an immutable audio path, a parameter snapshot, and a read-only subtitle
    # timeline. Copying the outer dict prevents later page reruns from swapping cached fields under a task already queued.
    voice_preview_snapshot = dict(voice_preview) if voice_preview else None
    # The confirmed request is a frozen data object passed only within this process. The API key never enters
    # VideoParams, task state, logs, or on-disk history, and later page reruns cannot affect it.
    loomloom_request_snapshot = loomloom_video_request
    sm.state.update_task(
        task_id,
        state=const.TASK_STATE_PROCESSING,
        progress=0,
        video_subject=task_params.video_subject or task_params.video_script or task_id,
    )
    try:
        _task_manager.add_task(
            _run_generation,
            task_id=task_id,
            params=task_params,
            capture_logs=capture_logs,
            voice_preview=voice_preview_snapshot,
            loomloom_video_request=loomloom_request_snapshot,
        )
    except Exception as exc:
        # Scheduling failures must become queryable states exactly like pipeline failures so the task manager never
        # shows "generating" forever. Keeping the exception type makes queue problems quick to locate from Docker or local logs.
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
