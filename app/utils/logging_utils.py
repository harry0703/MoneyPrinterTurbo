import os
import threading

from loguru import logger


PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
)
LOG_RECORD_FORMAT = (
    "<green>{time:%Y-%m-%d %H:%M:%S}</> | "
    "<level>{level}</> | "
    '"{file.path}:{line}":<blue> {function}</> '
    "- <level>{message}</>\n"
)
# Loguru's default terminal handler has ID 0 at startup. A WebUI reload can only replace this
# basic terminal output; calling logger.remove() to clear all handlers would also delete the
# temporary sink that collects WebUI logs for running tasks.
_terminal_handler_id: int | None = 0
_terminal_handler_lock = threading.RLock()


def format_log_record(record):
    """
    Format terminal and WebUI logs uniformly.

    Loguru hands each record to multiple sinks. The first sink may already have converted an
    absolute path to a project-relative one, so accept both absolute paths and already-formatted
    ``./`` paths here. The WebUI sink disables colors, but time, level, call site, and message
    stay identical to the terminal.
    """
    file_path = record["file"].path
    if os.path.isabs(file_path):
        relative_path = os.path.relpath(file_path, PROJECT_ROOT).replace(os.sep, "/")
        record["file"].path = f"./{relative_path}"

    # Log messages sometimes contain absolute paths of task files. Shortening them to project-relative paths uniformly
    # prevents the WebUI and the terminal from showing two different layouts depending on the initialization entry point.
    record["message"] = record["message"].replace(PROJECT_ROOT, ".")
    return LOG_RECORD_FORMAT


def configure_terminal_logger(sink, level: str, colorize: bool = True) -> int:
    """
    Safely replace the process-level terminal log handler while keeping task-specific handlers.

    Streamlit may re-run log initialization on hot reload or cache invalidation. Remove only the
    recorded terminal handler ID precisely, so background tasks' WebUI log writes are never
    interrupted. The lock protects the ID update when multiple browser sessions initialize at once.
    """
    global _terminal_handler_id

    with _terminal_handler_lock:
        if _terminal_handler_id is not None:
            try:
                logger.remove(_terminal_handler_id)
            except ValueError:
                # Tests or external entry points may already have removed that handler. Just create a new terminal
                # output without affecting other still-valid log sinks.
                pass

        _terminal_handler_id = logger.add(
            sink,
            level=level,
            format=format_log_record,
            colorize=colorize,
        )
        return _terminal_handler_id
