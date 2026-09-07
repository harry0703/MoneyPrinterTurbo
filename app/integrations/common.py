from __future__ import annotations

import os
import re
import time
from typing import Any, Callable, Optional

from loguru import logger

POLL_INTERVAL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 600


def sanitize_filename(value: str, default_name: str = "generated") -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or default_name


def ensure_output_dir(output_dir: Optional[str] = None) -> str:
    directory = output_dir or os.path.join("storage", "generated")
    os.makedirs(directory, exist_ok=True)
    return directory


def log_external_status(provider: str, status: str, external_id: str = "") -> None:
    logger.info(
        f"external provider={provider} status={status} id={external_id or 'n/a'}"
    )


def missing_key_result(provider: str) -> dict[str, Any]:
    return {
        "success": False,
        "provider": provider,
        "error": "Missing API key",
    }


def error_result(provider: str, error: str, external_id: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "success": False,
        "provider": provider,
        "error": error,
    }
    if external_id:
        payload["external_generation_id"] = external_id
    return payload


def success_result(
    *,
    provider: str,
    output_type: str,
    local_path: str,
    remote_url: str,
    filename: str,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "success": True,
        "provider": provider,
        "type": output_type,
        "localPath": local_path,
        "remoteUrl": remote_url,
        "filename": filename,
        "metadata": metadata or {},
    }


def poll_until_done(
    *,
    provider: str,
    external_id: str,
    get_status: Callable[[], tuple[str, dict[str, Any]]],
    timeout_seconds: int = POLL_TIMEOUT_SECONDS,
    interval_seconds: int = POLL_INTERVAL_SECONDS,
) -> tuple[bool, str, dict[str, Any]]:
    started_at = time.time()
    while True:
        status, payload = get_status()
        normalized = (status or "").strip().lower()
        log_external_status(provider, normalized or "unknown", external_id)

        if normalized in {"completed", "complete", "done", "succeeded", "success", "ready"}:
            return True, normalized, payload
        if normalized in {"failed", "error", "canceled", "cancelled", "rejected"}:
            return False, normalized, payload

        if time.time() - started_at > timeout_seconds:
            return False, "timeout", payload

        time.sleep(interval_seconds)
