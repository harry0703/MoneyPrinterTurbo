"""GenMagic asynchronous text-to-video client.

GenMagic (https://genmagic.co) puts many text-to-video models behind one API key.
A job is created with ``POST /videos`` (HTTP 202 and an ``id``) and polled with
``GET /videos/{id}`` until it is ``completed`` (a hosted ``url``) or ``failed``.
Nothing is charged when a job is created: GenMagic bills a clip once, when it
completes, and polling the same job again never charges twice.

The provider-specific submit/poll protocol lives here so the material service
only deals with ``MaterialInfo`` and local downloads. Like the other paid video
sources, submission is never retried when the response is ambiguous, because the
remote job may already exist.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, quote_plus, urlsplit

import requests
from loguru import logger

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect
from app.services import generation_progress
from app.utils.request_logging import trace_http_call


DEFAULT_BASE_URL = "https://genmagic.co/api/v1"
# Identifies this integration to GenMagic; it is not a secret and carries no user data.
CLIENT_HEADER = "moneyprinterturbo/1.0.0"
API_KEY_URL = (
    "https://genmagic.co/get-api-key"
    "?utm_source=moneyprinterturbo&utm_medium=integration"
)
MODELS_URL = "https://genmagic.co/models?category=video"
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_RUN_TIMEOUT_SECONDS = 1800.0
MAX_POLL_RETRIES = 5
RETRY_BASE_SECONDS = 1.0
MAX_ERROR_TEXT_LENGTH = 500
# The poll that sees a finished clip downloads and hosts it before it answers
# (GenMagic allows that request up to 60 seconds), so the read timeout is wider
# than the other providers' status calls. Re-polling the same job is always safe.
POLL_READ_TIMEOUT_SECONDS = 75.0
CATALOG_CACHE_SECONDS = 600.0
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
ACTIVE_STATUSES = frozenset({"queued", "processing"})
TERMINAL_SUCCESS_STATUSES = frozenset({"completed"})
TERMINAL_FAILURE_STATUSES = frozenset({"failed"})

_catalog_lock = threading.Lock()
_catalog_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


class GenMagicError(RuntimeError):
    """Deterministic configuration, request, or response error."""

    def __init__(self, message: str, task_id: str = ""):
        super().__init__(message)
        self.task_id = task_id


class GenMagicUnconfirmedTaskError(GenMagicError):
    """The remote job may exist, but its final state cannot be confirmed."""


class GenMagicDownloadError(GenMagicError):
    """A billable job completed, but its output could not be downloaded."""


def get_api_key(settings: Mapping[str, Any] | None = None) -> str:
    """Read the dedicated GenMagic key, then the provider-specific environment key."""
    settings = config.app if settings is None else settings
    configured = str(settings.get("genmagic_api_key", "") or "").strip()
    environment_key = os.getenv("GENMAGIC_API_KEY", "").strip()
    return configured or environment_key


def is_enabled(settings: Mapping[str, Any] | None = None) -> bool:
    return bool(get_api_key(settings))


def _base_url() -> str:
    value = str(
        config.app.get("genmagic_base_url", DEFAULT_BASE_URL) or DEFAULT_BASE_URL
    ).strip().rstrip("/")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise GenMagicError(
            "genmagic_base_url must be an absolute HTTP(S) URL without "
            "credentials or query parameters"
        )
    return value


def _model() -> str:
    """The configured model id. Empty means GenMagic picks its own default."""
    return str(config.app.get("genmagic_video_model", "") or "").strip()


def _resolution() -> str:
    """The configured resolution. Empty means the model's default resolution."""
    return str(config.app.get("genmagic_resolution", "") or "").strip()


def _config_bool(key: str, default: bool) -> bool:
    value = config.app.get(key, default)
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


def _tls_verify() -> bool:
    return _config_bool("tls_verify", True)


def _status_code(response: Any) -> int:
    try:
        return int(getattr(response, "status_code", 200))
    except (TypeError, ValueError):
        return 200


def _redact_secret(value: Any, secret: str) -> str:
    text = str(value or "")
    if secret:
        text = text.replace(secret, "***")
        encoded = quote_plus(secret)
        if encoded != secret:
            text = text.replace(encoded, "***")
    for proxy_url in config.proxy.values():
        proxy_secret = str(proxy_url or "")
        if proxy_secret:
            text = text.replace(proxy_secret, "***")
    return text[:MAX_ERROR_TEXT_LENGTH]


def _response_error(response: Any, api_key: str) -> str:
    """Read GenMagic's ``{"error": {"message", "code"}}`` envelope."""
    try:
        payload = response.json()
    except Exception:
        return f"HTTP {_status_code(response)}"
    if not isinstance(payload, dict):
        return f"HTTP {_status_code(response)}"

    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        code = error.get("code")
        detail = f"{message} ({code})" if message and code else message or code
    else:
        detail = error or payload.get("message") or payload.get("detail")
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


def _request_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-GenMagic-Client": CLIENT_HEADER,
    }


def list_video_models(base_url: str | None = None) -> list[dict[str, Any]]:
    """Return GenMagic's text-to-video models from the public catalog.

    ``GET /models?category=video`` is a free lookup that needs no key, so no
    credential is sent. The result is cached briefly. Any failure returns an
    empty list: the catalog only refines a request, it never gates one.
    """
    try:
        base = base_url or _base_url()
    except GenMagicError:
        return []
    now = time.monotonic()
    with _catalog_lock:
        cached = _catalog_cache.get(base)
        if cached and now - cached[0] < CATALOG_CACHE_SECONDS:
            return cached[1]
    try:
        response = trace_http_call(
            "GET", requests.get,
            f"{base}/models",
            params={"category": "video"},
            headers={"X-GenMagic-Client": CLIENT_HEADER},
            proxies=config.proxy,
            verify=_tls_verify(),
            timeout=(10, 20),
            allow_redirects=False,
        )
        if _status_code(response) != 200:
            raise ValueError(f"HTTP {_status_code(response)}")
        body = response.json()
        rows = body.get("data") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise ValueError("unexpected catalog shape")
    except Exception as exc:
        logger.warning(
            f"could not read the GenMagic model catalog: {type(exc).__name__}, "
            f"detail={_redact_secret(exc, '')}"
        )
        return []
    models = [
        row for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("id"), str)
        and (row.get("capabilities") or {}).get("text_to_video") is True
    ]
    with _catalog_lock:
        _catalog_cache[base] = (now, models)
    return models


def model_durations(model: str, base_url: str | None = None) -> list[int]:
    """Clip lengths in seconds that ``model`` accepts, ascending. Empty if unknown."""
    for row in list_video_models(base_url):
        if row.get("id") != model:
            continue
        video = (row.get("pricing") or {}).get("video") or {}
        values = video.get("durations_seconds")
        if not isinstance(values, list):
            return []
        return sorted(
            {int(value) for value in values if isinstance(value, int) and value > 0}
        )
    return []


def _pick_duration(model: str, requested: int, base_url: str) -> int | None:
    """Choose a clip length the model accepts, or None to use the model's default.

    GenMagic only accepts a length from the model's own list, and bills by the
    second. Use the shortest listed length that covers the requested clip and fall
    back to the longest one; the editing pipeline trims any extra footage. With no
    model configured GenMagic runs its default model, whose list is not known here,
    so the length is left out and the default (usually 5 seconds) applies.
    """
    if not model:
        return None
    allowed = model_durations(model, base_url)
    if not allowed:
        return None
    for seconds in allowed:
        if seconds >= requested:
            return seconds
    return allowed[-1]


def generate_videos(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> list[MaterialInfo]:
    """Submit one GenMagic text-to-video job and wait for its downloadable output."""
    api_key = get_api_key()
    if not api_key:
        raise GenMagicError("GenMagic video generation requires a GenMagic API key")

    term = str(search_term or "").strip()
    if not term:
        raise GenMagicError("GenMagic search term must not be empty")

    try:
        aspect = VideoAspect(video_aspect)
    except (TypeError, ValueError) as exc:
        raise GenMagicError("GenMagic video aspect is invalid") from exc
    try:
        requested_duration = max(int(minimum_duration), 1)
    except (TypeError, ValueError, OverflowError) as exc:
        raise GenMagicError("GenMagic clip duration must be a positive integer") from exc

    base_url = _base_url()
    model = _model()
    duration = _pick_duration(model, requested_duration, base_url)
    if duration is not None and duration != requested_duration:
        logger.info(
            "genmagic clip duration adjusted to a length the model accepts: "
            f"model={model}, requested={requested_duration}s, using={duration}s"
        )

    # MPT discards a clip's own soundtrack and mixes the narration over it, so
    # never pay for generated sound (it can roughly double a clip's price).
    payload: dict[str, Any] = {
        "prompt": term,
        "aspect_ratio": aspect.value,
        "generate_audio": False,
    }
    if model:
        payload["model"] = model
    if duration is not None:
        payload["duration"] = duration
    resolution = _resolution()
    if resolution:
        payload["resolution"] = resolution

    headers = _request_headers(api_key)
    logger.info(
        "generating video with GenMagic: "
        f"model={model or 'default'}, term={term!r}, "
        f"duration={duration if duration is not None else 'default'}"
    )

    # A timeout or 5xx after POST may mean that GenMagic accepted the job, which
    # is billed when it completes. Retrying the submission could create a second
    # paid generation.
    generation_progress.submitting("genmagic")
    try:
        response = trace_http_call(
            "POST", requests.post,
            f"{base_url}/videos",
            json=payload,
            headers=headers,
            proxies=config.proxy,
            verify=_tls_verify(),
            timeout=(30, 90),
            allow_redirects=False,
        )
    except Exception as exc:
        raise GenMagicUnconfirmedTaskError(
            "GenMagic submission returned no response; a paid task may already "
            "exist remotely: "
            f"error={type(exc).__name__}, detail={_redact_secret(exc, api_key)}"
        ) from exc

    status_code = _status_code(response)
    if 300 <= status_code < 400:
        location = getattr(response, "headers", {}).get("Location", "")
        raise GenMagicUnconfirmedTaskError(
            "GenMagic submission returned an unexpected redirect; the paid task "
            "state is unknown: "
            f"HTTP {status_code}, location={_redact_secret(location, api_key)}"
        )
    if status_code >= 500:
        raise GenMagicUnconfirmedTaskError(
            f"GenMagic submission failed with HTTP {status_code}; a paid task may "
            "already exist remotely"
        )
    if not 200 <= status_code < 300:
        raise GenMagicError(
            "GenMagic video generation request rejected: "
            f"HTTP {status_code}, {_response_error(response, api_key)}"
        )
    try:
        body = response.json()
    except Exception as exc:
        raise GenMagicUnconfirmedTaskError(
            "GenMagic submission returned an unreadable response; a paid task may "
            f"already exist remotely: error={type(exc).__name__}"
        ) from exc
    task_id = str(body.get("id") or "").strip() if isinstance(body, dict) else ""
    if not task_id:
        raise GenMagicUnconfirmedTaskError(
            "GenMagic accepted the submission without returning a job id"
        )
    logger.info(f"GenMagic video task created: id={task_id}")

    task = _wait_for_task(
        task_id=task_id,
        base_url=base_url,
        headers=headers,
        api_key=api_key,
    )
    if task is None:
        return []

    video_url = task.get("url")
    if not (
        isinstance(video_url, str) and video_url.startswith(("http://", "https://"))
    ):
        raise GenMagicError(
            f"GenMagic task completed without a downloadable video: id={task_id}",
            task_id=task_id,
        )
    logger.info(
        f"GenMagic video task completed: id={task_id}, "
        f"model={task.get('model') or model or 'default'}, "
        f"cost_cents={task.get('cost_cents')}"
    )

    video_width, video_height = aspect.to_resolution()
    return [
        MaterialInfo(
            provider="genmagic",
            url=video_url,
            duration=duration if duration is not None else requested_duration,
            source_info={
                "provider": "genmagic",
                "search_term": term,
                "asset_id": task_id,
                "rendition": {
                    "id": task_id,
                    "width": video_width,
                    "height": video_height,
                },
            },
        )
    ]


def _wait_for_task(
    *,
    task_id: str,
    base_url: str,
    headers: dict[str, str],
    api_key: str,
) -> dict[str, Any] | None:
    """Poll one job until it completes. Returns None when GenMagic reports it failed.

    Transient errors are retried on the same job id and never resubmit. Anything
    that leaves the job's state unknown raises ``GenMagicUnconfirmedTaskError`` so
    the caller stops placing new paid jobs.
    """
    deadline = time.monotonic() + _bounded_float(
        "genmagic_run_timeout",
        DEFAULT_RUN_TIMEOUT_SECONDS,
        60.0,
        7200.0,
    )
    poll_interval = _bounded_float(
        "genmagic_poll_interval",
        DEFAULT_POLL_INTERVAL_SECONDS,
        0.5,
        60.0,
    )
    status_url = f"{base_url}/videos/{quote(task_id, safe='')}"
    generation_progress.remote("genmagic", task_id)
    consecutive_failures = 0

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise GenMagicUnconfirmedTaskError(
                "GenMagic task is still running after the configured local wait "
                f"timeout: id={task_id}",
                task_id=task_id,
            )

        try:
            response = trace_http_call(
                "GET", requests.get,
                status_url,
                headers=headers,
                proxies=config.proxy,
                verify=_tls_verify(),
                timeout=(10, max(min(remaining, POLL_READ_TIMEOUT_SECONDS), 0.001)),
                allow_redirects=False,
            )
            status_code = _status_code(response)
            if 300 <= status_code < 400:
                location = getattr(response, "headers", {}).get("Location", "")
                raise GenMagicUnconfirmedTaskError(
                    "GenMagic polling returned an unexpected redirect; the paid "
                    "task state is unknown: "
                    f"HTTP {status_code}, location={_redact_secret(location, api_key)}",
                    task_id=task_id,
                )
            if status_code in RETRYABLE_STATUS_CODES:
                raise requests.exceptions.HTTPError(
                    f"HTTP {status_code}", response=response
                )
            if not 200 <= status_code < 300:
                raise GenMagicUnconfirmedTaskError(
                    "GenMagic task status is unknown: "
                    f"http_status={status_code}, "
                    f"detail={_response_error(response, api_key)}",
                    task_id=task_id,
                )
            body = response.json()
            if not isinstance(body, dict):
                raise GenMagicUnconfirmedTaskError(
                    "GenMagic task status response is malformed", task_id=task_id
                )
        except GenMagicUnconfirmedTaskError:
            raise
        except Exception as exc:
            if not _is_retryable_error(exc):
                raise GenMagicUnconfirmedTaskError(
                    "GenMagic polling failed and the task state is unknown: "
                    f"error={type(exc).__name__}, "
                    f"detail={_redact_secret(exc, api_key)}",
                    task_id=task_id,
                ) from exc

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GenMagicUnconfirmedTaskError(
                    "GenMagic task is still running after the configured local wait "
                    f"timeout: id={task_id}",
                    task_id=task_id,
                ) from exc
            consecutive_failures += 1
            generation_progress.remote("genmagic", task_id, retrying=True)
            if consecutive_failures > MAX_POLL_RETRIES:
                raise GenMagicUnconfirmedTaskError(
                    "GenMagic polling failed after retries; the paid task may still "
                    f"be running remotely: id={task_id}",
                    task_id=task_id,
                ) from exc
            delay = min(RETRY_BASE_SECONDS * consecutive_failures, remaining)
            logger.warning(
                "GenMagic polling hit a transient error; retrying the same task: "
                f"id={task_id}, attempt={consecutive_failures}/{MAX_POLL_RETRIES}, "
                f"retry_in={delay:.1f}s"
            )
            time.sleep(delay)
            continue

        consecutive_failures = 0
        status = str(body.get("status") or "").strip().lower()
        generation_progress.remote("genmagic", task_id, status)
        if status in TERMINAL_SUCCESS_STATUSES:
            return body
        if status in TERMINAL_FAILURE_STATUSES:
            # A failed GenMagic job is never charged, so the caller may move on
            # to the next script keyword.
            logger.error(
                "GenMagic task did not produce a video: "
                f"id={task_id}, status={status}, "
                f"detail={_redact_secret(body.get('error'), api_key)}"
            )
            return None
        if status not in ACTIVE_STATUSES:
            raise GenMagicUnconfirmedTaskError(
                f"GenMagic returned an unknown task status: id={task_id}, "
                f"status={status!r}",
                task_id=task_id,
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise GenMagicUnconfirmedTaskError(
                "GenMagic task is still running after the configured local wait "
                f"timeout: id={task_id}",
                task_id=task_id,
            )
        time.sleep(min(poll_interval, remaining))
