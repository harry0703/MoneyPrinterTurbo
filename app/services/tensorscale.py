"""TensorScale MiniMax H3 Fast text-to-video client.

This module owns only the TensorScale API contract: idempotent submission,
polling one paid job, and returning its short-lived direct download URL. The
material service remains responsible for downloading and composing clips.
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, quote_plus, urlsplit
from uuid import uuid4

import requests
from loguru import logger

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect

DEFAULT_BASE_URL = "https://api.tensorscale.io/v1"
DEFAULT_MODEL_ID = "MiniMax-H3-Fast"
DEFAULT_RESOLUTION = "768p"
DEFAULT_MIN_DURATION_SECONDS = 4
DEFAULT_MAX_DURATION_SECONDS = 15
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_RUN_TIMEOUT_SECONDS = 1800.0
MAX_SUBMIT_ATTEMPTS = 3
MAX_POLL_RETRIES = 5
RETRY_BASE_SECONDS = 1.0
MAX_RETRY_AFTER_SECONDS = 60.0
MAX_ERROR_TEXT_LENGTH = 500
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
ACTIVE_STATUSES = frozenset({"pending", "queued", "in_progress"})
TERMINAL_FAILURE_STATUSES = frozenset({"failed", "cancelled", "canceled", "expired"})
SUPPORTED_RESOLUTIONS = ("360p", "480p", "768p")


class TensorScaleError(RuntimeError):
    """Deterministic configuration, request, or response error."""

    def __init__(self, message: str, task_id: str = ""):
        super().__init__(message)
        self.task_id = task_id


class TensorScaleUnconfirmedTaskError(TensorScaleError):
    """A paid remote job may exist, but its final state is not known locally."""


class TensorScaleDownloadError(TensorScaleError):
    """A completed paid job could not be downloaded locally."""


def get_api_key(settings: Mapping[str, Any] | None = None) -> str:
    """Read the dedicated TensorScale key, preferring explicit config."""
    settings = config.app if settings is None else settings
    configured = str(settings.get("tensorscale_api_key", "") or "").strip()
    environment_key = os.getenv("TENSORSCALE_API_KEY", "").strip()
    return configured or environment_key


def is_enabled(settings: Mapping[str, Any] | None = None) -> bool:
    return bool(get_api_key(settings))


def _base_url() -> str:
    value = (
        str(
            config.app.get("tensorscale_base_url", DEFAULT_BASE_URL) or DEFAULT_BASE_URL
        )
        .strip()
        .rstrip("/")
    )
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise TensorScaleError("tensorscale_base_url must be an absolute HTTP(S) URL")
    return value


def _resolution() -> str:
    configured = config.app.get("tensorscale_resolution", DEFAULT_RESOLUTION)
    value = str(configured or "").strip().lower()
    if value not in SUPPORTED_RESOLUTIONS:
        raise TensorScaleError(
            f"Unsupported TensorScale resolution {value!r}; expected one of: "
            + ", ".join(SUPPORTED_RESOLUTIONS)
        )
    return value


def _tls_verify() -> bool:
    value = config.app.get("tls_verify", True)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def _bounded_float(key: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(config.app.get(key, default))
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return min(max(value, minimum), maximum)


def _status_code(response: Any) -> int:
    try:
        return int(getattr(response, "status_code", 200))
    except (TypeError, ValueError):
        return 200


def _redact_secret(value: Any, api_key: str) -> str:
    text = str(value or "")
    if api_key:
        text = text.replace(api_key, "***")
        encoded = quote_plus(api_key)
        if encoded != api_key:
            text = text.replace(encoded, "***")
    for proxy_url in config.proxy.values():
        proxy_secret = str(proxy_url or "")
        if proxy_secret:
            text = text.replace(proxy_secret, "***")
    return text[:MAX_ERROR_TEXT_LENGTH]


def _response_error(response: Any, api_key: str) -> str:
    try:
        payload = response.json()
    except (TypeError, ValueError, requests.exceptions.JSONDecodeError):
        return f"HTTP {_status_code(response)}"
    if not isinstance(payload, dict):
        return f"HTTP {_status_code(response)}"
    error = payload.get("error")
    if isinstance(error, dict):
        detail = ": ".join(
            str(item)
            for item in (error.get("code"), error.get("type"), error.get("message"))
            if item not in (None, "")
        )
    else:
        detail = str(error or payload.get("message") or "")
    return _redact_secret(detail or f"HTTP {_status_code(response)}", api_key)


def _is_retryable_error(error: Exception) -> bool:
    if isinstance(
        error,
        (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ),
    ):
        return True
    response = getattr(error, "response", None)
    return response is not None and _status_code(response) in RETRYABLE_STATUS_CODES


def _retry_after_seconds(response: Any, fallback: float) -> float:
    headers = getattr(response, "headers", None)
    raw = headers.get("Retry-After") if hasattr(headers, "get") else None
    if raw not in (None, ""):
        try:
            delay = float(raw)
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(str(raw))
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                delay = (retry_at - datetime.now(UTC)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                delay = fallback
        if math.isfinite(delay):
            return min(max(delay, 0.0), MAX_RETRY_AFTER_SECONDS)
    return min(max(fallback, 0.0), MAX_RETRY_AFTER_SECONDS)


def _normalize_duration(minimum_duration: int) -> tuple[int, int]:
    try:
        requested = int(minimum_duration)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TensorScaleError(
            "TensorScale clip duration must be a positive integer"
        ) from exc
    if requested <= 0:
        raise TensorScaleError("TensorScale clip duration must be a positive integer")
    return requested, min(
        max(requested, DEFAULT_MIN_DURATION_SECONDS),
        DEFAULT_MAX_DURATION_SECONDS,
    )


def _submit_video(
    *,
    videos_url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    api_key: str,
) -> str:
    idempotency_key = f"mpt-{uuid4().hex}"
    request_headers = {**headers, "Idempotency-Key": idempotency_key}
    last_error: Exception | None = None

    for attempt in range(MAX_SUBMIT_ATTEMPTS):
        response = None
        try:
            response = requests.post(
                videos_url,
                json=payload,
                headers=request_headers,
                proxies=config.proxy,
                verify=_tls_verify(),
                timeout=(30, 60),
            )
            status_code = _status_code(response)
            if status_code in RETRYABLE_STATUS_CODES:
                raise requests.exceptions.HTTPError(
                    f"HTTP {status_code}", response=response
                )
            if not 200 <= status_code < 300:
                raise TensorScaleError(
                    "TensorScale video generation request rejected: "
                    f"HTTP {status_code}, {_response_error(response, api_key)}"
                )
            body = response.json()
            task_id = (
                str(body.get("id") or "").strip() if isinstance(body, dict) else ""
            )
            if not task_id:
                raise TensorScaleUnconfirmedTaskError(
                    "TensorScale accepted the submission without returning a job id"
                )
            return task_id
        except TensorScaleError:
            raise
        except Exception as exc:
            if not _is_retryable_error(exc):
                raise TensorScaleUnconfirmedTaskError(
                    "TensorScale submission returned an unreadable response; a paid "
                    "job may already exist remotely: "
                    f"error={type(exc).__name__}, detail={_redact_secret(exc, api_key)}"
                ) from exc
            last_error = exc
            if attempt + 1 >= MAX_SUBMIT_ATTEMPTS:
                break
            delay = _retry_after_seconds(response, RETRY_BASE_SECONDS * (2**attempt))
            logger.warning(
                "TensorScale submission hit a transient error; retrying with the "
                f"same idempotency key: attempt={attempt + 1}/"
                f"{MAX_SUBMIT_ATTEMPTS - 1}, retry_in={delay:.1f}s"
            )
            time.sleep(delay)

    raise TensorScaleUnconfirmedTaskError(
        "TensorScale submission could not be confirmed after idempotent retries; "
        "a paid job may already exist remotely: "
        f"error={type(last_error).__name__}, "
        f"detail={_redact_secret(last_error, api_key)}"
    ) from last_error


def generate_videos(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> list[MaterialInfo]:
    """Submit one TensorScale MiniMax H3 Fast job and wait for its result URL."""
    api_key = get_api_key()
    if not api_key:
        raise TensorScaleError("TensorScale video generation requires an API key")

    term = str(search_term or "").strip()
    if not term:
        raise TensorScaleError("TensorScale search term must not be empty")

    aspect = VideoAspect(video_aspect)
    requested_duration, duration = _normalize_duration(minimum_duration)
    resolution = _resolution()
    if resolution == "360p" and aspect == VideoAspect.square:
        raise TensorScaleError(
            "TensorScale MiniMax H3 Fast does not support square video at 360p; "
            "use 480p or 768p"
        )
    if duration != requested_duration:
        logger.info(
            "TensorScale clip duration adjusted to MiniMax H3 limits: "
            f"requested={requested_duration}s, using={duration}s, "
            f"supported={DEFAULT_MIN_DURATION_SECONDS}-"
            f"{DEFAULT_MAX_DURATION_SECONDS}s"
        )

    payload = {
        "model": DEFAULT_MODEL_ID,
        "prompt": term,
        "duration": duration,
        "resolution": resolution,
        "aspect_ratio": aspect.value,
        "generate_audio": True,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    videos_url = f"{_base_url()}/videos"
    logger.info(
        "generating video with TensorScale MiniMax H3 Fast: "
        f"resolution={resolution}, aspect_ratio={aspect.value}, "
        f"duration={duration}s, prompt_length={len(term)}"
    )
    task_id = _submit_video(
        videos_url=videos_url,
        payload=payload,
        headers=headers,
        api_key=api_key,
    )
    logger.info(f"TensorScale video job created: id={task_id}")

    task = _wait_for_task(
        task_id=task_id,
        videos_url=videos_url,
        headers=headers,
        api_key=api_key,
    )
    if task is None:
        return []

    download_url = task.get("download_url")
    parsed = urlsplit(download_url) if isinstance(download_url, str) else None
    if parsed is None or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise TensorScaleError(
            "TensorScale completed the job without a direct download_url; "
            f"upgrade the TensorScale API before using this provider: id={task_id}",
            task_id=task_id,
        )

    return [
        MaterialInfo(
            provider="tensorscale",
            url=download_url,
            duration=duration,
            source_info={
                "provider": "tensorscale",
                "search_term": term,
                "asset_id": task_id,
                "rendition": {
                    "id": task_id,
                    "resolution": resolution,
                    "aspect_ratio": aspect.value,
                },
            },
        )
    ]


def _wait_for_task(
    *,
    task_id: str,
    videos_url: str,
    headers: dict[str, str],
    api_key: str,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + _bounded_float(
        "tensorscale_run_timeout",
        DEFAULT_RUN_TIMEOUT_SECONDS,
        60.0,
        7200.0,
    )
    poll_interval = _bounded_float(
        "tensorscale_poll_interval",
        DEFAULT_POLL_INTERVAL_SECONDS,
        0.5,
        60.0,
    )
    query_url = f"{videos_url}/{quote(task_id, safe='')}"
    consecutive_failures = 0

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TensorScaleUnconfirmedTaskError(
                "TensorScale job is still running after the configured local wait "
                f"timeout: id={task_id}",
                task_id=task_id,
            )

        phase_timeout = max(min(remaining / 2.0, 30.0), 0.001)
        response = None
        try:
            response = requests.get(
                query_url,
                headers=headers,
                proxies=config.proxy,
                verify=_tls_verify(),
                timeout=(phase_timeout, phase_timeout),
            )
            status_code = _status_code(response)
            if status_code in RETRYABLE_STATUS_CODES:
                raise requests.exceptions.HTTPError(
                    f"HTTP {status_code}", response=response
                )
            if not 200 <= status_code < 300:
                raise TensorScaleUnconfirmedTaskError(
                    "TensorScale job status is unknown: "
                    f"http_status={status_code}, detail={_response_error(response, api_key)}",
                    task_id=task_id,
                )
            body = response.json()
            if not isinstance(body, dict):
                raise TensorScaleUnconfirmedTaskError(
                    "TensorScale job status response is malformed", task_id=task_id
                )
        except TensorScaleUnconfirmedTaskError:
            raise
        except Exception as exc:
            if not _is_retryable_error(exc):
                raise TensorScaleUnconfirmedTaskError(
                    "TensorScale polling failed and the paid job state is unknown: "
                    f"error={type(exc).__name__}, "
                    f"detail={_redact_secret(exc, api_key)}",
                    task_id=task_id,
                ) from exc
            consecutive_failures += 1
            if consecutive_failures > MAX_POLL_RETRIES:
                raise TensorScaleUnconfirmedTaskError(
                    "TensorScale polling failed after retries; the paid job may "
                    f"still be running remotely: id={task_id}",
                    task_id=task_id,
                ) from exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TensorScaleUnconfirmedTaskError(
                    "TensorScale job is still running after the configured local "
                    f"wait timeout: id={task_id}",
                    task_id=task_id,
                ) from exc
            delay = min(
                _retry_after_seconds(
                    response, RETRY_BASE_SECONDS * consecutive_failures
                ),
                remaining,
            )
            logger.warning(
                "TensorScale polling hit a transient error; retrying the same job: "
                f"id={task_id}, attempt={consecutive_failures}/"
                f"{MAX_POLL_RETRIES}, retry_in={delay:.1f}s"
            )
            time.sleep(delay)
            continue

        consecutive_failures = 0
        status = str(body.get("status") or "").strip().lower()
        if status == "completed":
            return body
        if status in TERMINAL_FAILURE_STATUSES:
            logger.error(
                "TensorScale job did not produce a video: "
                f"id={task_id}, status={status}, "
                f"detail={_redact_secret(body.get('error'), api_key)}"
            )
            return None
        if status not in ACTIVE_STATUSES:
            raise TensorScaleUnconfirmedTaskError(
                f"TensorScale returned an unknown job status: id={task_id}, "
                f"status={status!r}",
                task_id=task_id,
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TensorScaleUnconfirmedTaskError(
                "TensorScale job is still running after the configured local wait "
                f"timeout: id={task_id}",
                task_id=task_id,
            )
        time.sleep(min(poll_interval, remaining))
