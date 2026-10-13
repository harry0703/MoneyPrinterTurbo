"""vgenv's independent MiniMax H3 text-to-video API client.

Submission, polling and cancellation use one isolated request context per clip.
The caller owns local file publication and the decision to create another clip.
"""

from __future__ import annotations

import ipaddress
import math
import os
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import uuid4

import requests

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect


DEFAULT_BASE_URL = "https://api.vgenv.com"
DEFAULT_MIN_DURATION_SECONDS = 4
DEFAULT_MAX_DURATION_SECONDS = 15
DEFAULT_RESOLUTION = "768p"
DEFAULT_TIER = "fast"
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_RUN_TIMEOUT_SECONDS = 1800.0
_RETRYABLE = {429, 500, 502, 503, 504}


class VgenvError(RuntimeError):
    def __init__(self, message: str, task_id: str = ""):
        super().__init__(message)
        self.task_id = task_id


class VgenvUnconfirmedTaskError(VgenvError):
    """The remote task may have incurred a charge; do not create a replacement."""


class VgenvDownloadError(VgenvError):
    """The remote task succeeded but its output was not saved locally."""


def get_api_key(settings: Mapping[str, Any] | None = None) -> str:
    settings = config.app if settings is None else settings
    return str(settings.get("vgenv_api_key", "") or "").strip() or os.getenv(
        "VGENV_API_KEY", ""
    ).strip()


def is_enabled(settings: Mapping[str, Any] | None = None) -> bool:
    return bool(get_api_key(settings))


def _number(name: str, default: float, low: float, high: float) -> float:
    try:
        number = float(config.app.get(name, default))
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) and low <= number <= high else default


def _settings() -> tuple[str, str, str]:
    base = str(config.app.get("vgenv_base_url", DEFAULT_BASE_URL) or "").rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise VgenvError("vgenv_base_url must be an HTTPS API origin without credentials")
    resolution = str(config.app.get("vgenv_resolution", DEFAULT_RESOLUTION))
    tier = str(config.app.get("vgenv_tier", DEFAULT_TIER))
    if resolution not in {"480p", "768p"} or tier not in {"fast", "standard", "enhanced", "quality"}:
        raise VgenvError("unsupported vgenv resolution or tier")
    return base, resolution, tier


def _response(response: Any, task_id: str = "") -> dict[str, Any]:
    # Do not include response text: upstream errors can echo credentials or URLs.
    if not 200 <= response.status_code < 300:
        raise VgenvError(f"vgenv returned HTTP {response.status_code}", task_id)
    try:
        body = response.json()
    except Exception as exc:
        raise VgenvUnconfirmedTaskError("vgenv returned unreadable JSON", task_id) from exc
    if not isinstance(body, dict):
        raise VgenvUnconfirmedTaskError("vgenv returned an invalid response", task_id)
    return body


def _safe_output_url(value: Any) -> str:
    if not isinstance(value, str):
        raise VgenvError("vgenv succeeded without an output URL")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise VgenvError("vgenv output URL must be HTTPS without embedded credentials")
    try:
        if not ipaddress.ip_address(parsed.hostname).is_global:
            raise VgenvError("vgenv output URL must not target a private address")
    except ValueError:
        if parsed.hostname == "localhost" or parsed.hostname.endswith(".localhost"):
            raise VgenvError("vgenv output URL must not target localhost")
    return value


def _cancel(base: str, task_id: str, headers: dict[str, str]) -> None:
    try:
        requests.delete(
            f"{base}/v3/videos/{quote(task_id, safe='')}", headers=headers,
            timeout=(5, 10), allow_redirects=False, proxies=config.proxy,
        )
    except requests.RequestException:
        pass  # Preserve the original failure; cancellation is best effort.


def generate_videos(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> list[MaterialInfo]:
    key = get_api_key()
    if not key:
        raise VgenvError("vgenv requires VGENV_API_KEY or vgenv_api_key")
    term = str(search_term or "").strip()
    if not 5 <= len(term) <= 30000:
        raise VgenvError("vgenv prompt must contain 5-30000 characters")
    try:
        requested = int(minimum_duration)
    except (TypeError, ValueError, OverflowError) as exc:
        raise VgenvError("vgenv clip duration must be a positive integer") from exc
    if requested <= 0:
        raise VgenvError("vgenv clip duration must be a positive integer")
    duration = min(max(requested, DEFAULT_MIN_DURATION_SECONDS), DEFAULT_MAX_DURATION_SECONDS)
    try:
        aspect = VideoAspect(video_aspect).value
    except ValueError as exc:
        raise VgenvError("unsupported vgenv aspect ratio") from exc
    base, resolution, tier = _settings()
    headers = {"Authorization": f"Bearer {key}"}
    create_headers = {
        **headers, "Content-Type": "application/json", "Idempotency-Key": uuid4().hex
    }
    payload = {
        "model": "base", "tier": tier, "prompt": term, "duration": duration,
        "resolution": resolution, "aspect_ratio": aspect,
        "prompt_optimization": {"mode": "raw"},
    }
    try:
        # Retry a lost create response only with the same idempotency key.
        for attempt in range(2):
            try:
                created = requests.post(
                    f"{base}/v3/videos", json=payload, headers=create_headers,
                    timeout=(10, 30), allow_redirects=False, proxies=config.proxy,
                )
                if created.status_code in _RETRYABLE and attempt == 0:
                    continue
                break
            except (requests.Timeout, requests.ConnectionError):
                if attempt:
                    raise
        if created.status_code in _RETRYABLE or 300 <= created.status_code < 400:
            raise VgenvUnconfirmedTaskError(
                f"vgenv submission state unknown: HTTP {created.status_code}"
            )
        body = _response(created)
    except requests.RequestException as exc:
        raise VgenvUnconfirmedTaskError(
            f"vgenv submission state unknown: {type(exc).__name__}"
        ) from exc
    task_id = str(body.get("id") or "").strip()
    if not task_id:
        raise VgenvUnconfirmedTaskError("vgenv accepted a task without an id")

    deadline = time.monotonic() + _number(
        "vgenv_run_timeout", DEFAULT_RUN_TIMEOUT_SECONDS, 60, 7200
    )
    interval = _number("vgenv_poll_interval", DEFAULT_POLL_INTERVAL_SECONDS, 1, 60)
    failures = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _cancel(base, task_id, headers)
            raise VgenvUnconfirmedTaskError("vgenv polling timed out", task_id)
        try:
            result = requests.get(
                f"{base}/v3/videos/{quote(task_id, safe='')}", headers=headers,
                timeout=(min(10, remaining / 2), min(30, remaining / 2)),
                allow_redirects=False, proxies=config.proxy,
            )
            if result.status_code in _RETRYABLE:
                raise requests.HTTPError(response=result)
            body = _response(result, task_id)
            failures = 0
        except (requests.RequestException, VgenvUnconfirmedTaskError) as exc:
            failures += 1
            if failures > 5:
                _cancel(base, task_id, headers)
                raise VgenvUnconfirmedTaskError(
                    f"vgenv polling state unknown: {type(exc).__name__}", task_id
                ) from exc
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
            continue
        if body.get("id") not in (None, task_id):
            raise VgenvUnconfirmedTaskError(
                "vgenv returned a different task id", task_id
            )
        status = body.get("status")
        if status == "succeeded":
            output = body.get("output")
            try:
                url = _safe_output_url(
                    output.get("url") if isinstance(output, dict) else None
                )
            except VgenvError as exc:
                raise VgenvError(str(exc), task_id) from exc
            return [MaterialInfo(
                provider="vgenv", url=url, duration=duration,
                source_info={"provider": "vgenv", "search_term": term,
                             "asset_id": task_id, "rendition": {"id": task_id}},
            )]
        if status in {"failed", "cancelled"}:
            raise VgenvError(f"vgenv task {status}: id={task_id}", task_id)
        if status not in {"preparing", "queued", "running"}:
            raise VgenvUnconfirmedTaskError("vgenv returned an unknown task status", task_id)
        time.sleep(min(interval, max(0, deadline - time.monotonic())))
