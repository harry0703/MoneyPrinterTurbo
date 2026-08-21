"""Safe reading and writing of persisted files inside the task directory."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from loguru import logger

from app.utils import utils


def _script_file(task_id: str) -> Path:
    """Return the task script-manifest path, reusing the unified task-directory creation logic."""
    return Path(utils.task_dir(task_id)) / "script.json"


def _write_json_atomic(target: Path, payload: Mapping[str, Any]) -> None:
    """
    Atomically write JSON inside the target directory so an interrupted process never leaves half a file.

    The temporary file and the target must share a directory for ``os.replace`` to stay atomic
    on common local filesystems and Docker mounts. The existing file is untouched until the
    write succeeds; on failure only the temporary file created here is cleaned up, and the error
    is left to the caller to decide whether the main flow is affected.
    """
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(
                payload,
                temp_file,
                ensure_ascii=False,
                indent=4,
                default=lambda value: value.__dict__,
            )
            temp_file.write("\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())

        os.replace(temp_path, target)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def write_script_data(task_id: str, payload: Mapping[str, Any]) -> None:
    """Create or fully replace a task's ``script.json`` manifest."""
    _write_json_atomic(_script_file(task_id), payload)


def patch_script_data(task_id: str, **updates: Any) -> bool:
    """
    Supplement the task manifest while preserving existing fields; return ``False`` on failure.

    Footage provenance is auxiliary diagnostics and must not block video generation over file
    permissions, transient disk errors, or corrupt history. This entry logs the full exception
    and degrades; first-time manifest creation still uses ``write_script_data`` so the main flow
    decides how a base-data write failure is handled.
    """
    try:
        target = _script_file(task_id)
        with target.open("r", encoding="utf-8") as script_file:
            payload = json.load(script_file)
        if not isinstance(payload, dict):
            raise ValueError("task script data must be a JSON object")

        payload.update(updates)
        _write_json_atomic(target, payload)
        return True
    except FileNotFoundError:
        # ``download_videos`` may also be called standalone by tests, scripts, or third-party code; having no
        # task manifest is normal there and must not produce warnings or a broken file just for auxiliary records.
        logger.debug(
            f"skip task script update because script.json does not exist: "
            f"task_id={task_id}"
        )
        return False
    except Exception as exc:
        logger.warning(
            "failed to update task script data: "
            f"task_id={task_id}, fields={sorted(updates)}, "
            f"error={type(exc).__name__}, detail={exc}"
        )
        return False
