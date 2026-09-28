"""MuAPI asynchronous text-to-video client.

The provider-specific submit/poll protocol lives here so the material service
only needs to deal with ``MaterialInfo`` and local downloads.  MuAPI jobs are
billable once accepted, so submission is deliberately never retried when the
response is ambiguous.
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote_plus, urlsplit

import requests
from loguru import logger

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect


DEFAULT_BASE_URL = "https://api.muapi.ai/api/v1"
# The budget Seedance Lite route supports the three MoneyPrinterTurbo aspect
# ratios, 3-12 second clips, and 480p/720p/1080p output.
DEFAULT_ENDPOINT = "seedance-lite-t2v"
DEFAULT_RESOLUTION = "480p"
DEFAULT_MIN_DURATION_SECONDS = 3
DEFAULT_MAX_DURATION_SECONDS = 12
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_RUN_TIMEOUT_SECONDS = 1800.0
MAX_POLL_RETRIES = 5
RETRY_BASE_SECONDS = 1.0
MAX_ERROR_TEXT_LENGTH = 500
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
ACTIVE_STATUSES = frozenset({"queued", "pending", "processing"})
TERMINAL_SUCCESS_STATUSES = frozenset({"completed"})
TERMINAL_FAILURE_STATUSES = frozenset(
    {"failed", "cancelled", "canceled", "expired"}
)


class MuAPIError(RuntimeError):
    """Deterministic configuration, request, or response error."""

    def __init__(self, message: str, task_id: str = ""):
        super().__init__(message)
        self.task_id = task_id


class MuAPIUnconfirmedTaskError(MuAPIError):
    """The remote job may exist, but its final state cannot be confirmed."""


class MuAPIDownloadError(MuAPIError):
    """A billable job completed, but its output could not be downloaded."""


def get_api_key(settings: Mapping[str, Any] | None = None) -> str:
    """Read the dedicated MuAPI key, then the provider-specific environment key."""
    settings = config.app if settings is None else settings
    configured = str(settings.get("muapi_api_key", "") or "").strip()
    environment_key = os.getenv("MUAPI_API_KEY", "").strip()
    return configured or environment_key


def is_enabled(settings: Mapping[str, Any] | None = None) -> bool:
    return bool(get_api_key(settings))


def _base_url() -> str:
    value = str(
        config.app.get("muapi_base_url", DEFAULT_BASE_URL) or DEFAULT_BASE_URL
    ).strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MuAPIError("muapi_base_url must be an absolute HTTP(S) URL")
    return value


def _endpoint() -> str:
    value = str(
        config.app.get("muapi_video_endpoint", DEFAULT_ENDPOINT) or DEFAULT_ENDPOINT
    ).strip().strip("/")
    # The setting is a path below /api/v1, never an arbitrary URL.  This keeps
    # credentials in the configured MuAPI host and makes the generated request
    # straightforward to audit.
    if not value or "://" in value or "?" in value or "#" in value:
        raise MuAPIError(
            "muapi_video_endpoint must be a non-empty relative endpoint path"
        )
    return value


def _resolution() -> str:
    value = str(
        config.app.get("muapi_resolution", DEFAULT_RESOLUTION) or ""
    ).strip()
    return value or DEFAULT_RESOLUTION


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


def _duration_bounds() -> tuple[int, int]:
    def read(key: str, default: int) -> int:
        try:
            value = int(config.app.get(key, default))
        except (TypeError, ValueError):
            return default
        return value if value >= 1 else default

    minimum = read("muapi_min_duration", DEFAULT_MIN_DURATION_SECONDS)
    maximum = read("muapi_max_duration", DEFAULT_MAX_DURATION_SECONDS)
    return minimum, max(minimum, maximum)


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
    try:
        payload = response.json()
    except Exception:
        return f"HTTP {_status_code(response)}"
    if not isinstance(payload, dict):
        return f"HTTP {_status_code(response)}"

    error = payload.get("error")
    if isinstance(error, dict):
        detail = error.get("message") or error.get("detail") or error.get("code")
    else:
        detail = payload.get("detail") or payload.get("message") or error
    if isinstance(detail, list):
        detail = "; ".join(str(item) for item in detail)
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


def generate_videos(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> list[MaterialInfo]:
    """Submit one MuAPI text-to-video job and wait for its downloadable output."""
    api_key = get_api_key()
    if not api_key:
        raise MuAPIError("MuAPI video generation requires a MuAPI API key")

    term = str(search_term or "").strip()
    if not term:
        raise MuAPIError("MuAPI search term must not be empty")

    try:
        aspect = VideoAspect(video_aspect)
    except (TypeError, ValueError) as exc:
        raise MuAPIError("MuAPI video aspect is invalid") from exc
    try:
        requested_duration = max(int(minimum_duration), 1)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MuAPIError("MuAPI clip duration must be a positive integer") from exc
    minimum, maximum = _duration_bounds()
    duration = min(max(requested_duration, minimum), maximum)
    if duration != requested_duration:
        logger.info(
            "muapi clip duration clamped to the configured endpoint range: "
            f"requested={requested_duration}s, using={duration}s "
            f"(configured {minimum}-{maximum}s)"
        )

    base_url = _base_url()
    endpoint = _endpoint()
    videos_url = f"{base_url}/{endpoint}"
    payload = {
        "prompt": term,
        "aspect_ratio": aspect.value,
        "resolution": _resolution(),
        "duration": duration,
    }
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    logger.info(
        "generating video with MuAPI: "
        f"endpoint={endpoint}, term={term!r}, duration={duration}s"
    )

    # A timeout or 5xx after POST may mean that MuAPI accepted and billed the
    # job.  Retrying the submission could create a second paid generation.
    try:
        response = requests.post(
            videos_url,
            json=payload,
            headers=headers,
            proxies=config.proxy,
            verify=_tls_verify(),
            timeout=(30, 60),
            allow_redirects=False,
        )
    except Exception as exc:
        raise MuAPIUnconfirmedTaskError(
            "MuAPI submission returned no response; a paid task may already "
            "exist remotely: "
            f"error={type(exc).__name__}, detail={_redact_secret(exc, api_key)}"
        ) from exc

    status_code = _status_code(response)
    if 300 <= status_code < 400:
        location = getattr(response, "headers", {}).get("Location", "")
        raise MuAPIUnconfirmedTaskError(
            "MuAPI submission returned an unexpected redirect; the paid task "
            "state is unknown: "
            f"HTTP {status_code}, location={_redact_secret(location, api_key)}"
        )
    if status_code >= 500:
        raise MuAPIUnconfirmedTaskError(
            f"MuAPI submission failed with HTTP {status_code}; a paid task may "
            "already exist remotely"
        )
    if not 200 <= status_code < 300:
        raise MuAPIError(
            "MuAPI video generation request rejected: "
            f"HTTP {status_code}, {_response_error(response, api_key)}"
        )
    try:
        body = response.json()
    except Exception as exc:
        raise MuAPIUnconfirmedTaskError(
            "MuAPI submission returned an unreadable response; a paid task may "
            f"already exist remotely: error={type(exc).__name__}"
        ) from exc
    task_id = str(
        body.get("request_id") or body.get("id") or ""
    ).strip() if isinstance(body, dict) else ""
    if not task_id:
        raise MuAPIUnconfirmedTaskError(
            "MuAPI accepted the submission without returning a request id"
        )
    logger.info(f"MuAPI video task created: id={task_id}")

    task = _wait_for_task(
        task_id=task_id,
        base_url=base_url,
        headers=headers,
        api_key=api_key,
    )
    if task is None:
        return []

    outputs = task.get("outputs")
    candidates = [outputs] if isinstance(outputs, str) else outputs
    video_url = ""
    for candidate in candidates if isinstance(candidates, list) else []:
        if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
            video_url = candidate
            break
    if not video_url:
        raise MuAPIError(
            f"MuAPI task completed without a downloadable video: id={task_id}",
            task_id=task_id,
        )

    video_width, video_height = aspect.to_resolution()
    return [
        MaterialInfo(
            provider="muapi",
            url=video_url,
            duration=duration,
            source_info={
                "provider": "muapi",
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
    deadline = time.monotonic() + _bounded_float(
        "muapi_run_timeout",
        DEFAULT_RUN_TIMEOUT_SECONDS,
        60.0,
        7200.0,
    )
    poll_interval = _bounded_float(
        "muapi_poll_interval",
        DEFAULT_POLL_INTERVAL_SECONDS,
        0.5,
        60.0,
    )
    result_url = f"{base_url}/predictions/{task_id}/result"
    consecutive_failures = 0

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MuAPIUnconfirmedTaskError(
                "MuAPI task is still running after the configured local wait "
                f"timeout: id={task_id}",
                task_id=task_id,
            )

        phase_timeout = max(min(remaining / 2.0, 30.0), 0.001)
        try:
            response = requests.get(
                result_url,
                headers=headers,
                proxies=config.proxy,
                verify=_tls_verify(),
                timeout=(phase_timeout, phase_timeout),
                allow_redirects=False,
            )
            status_code = _status_code(response)
            if 300 <= status_code < 400:
                location = getattr(response, "headers", {}).get("Location", "")
                raise MuAPIUnconfirmedTaskError(
                    "MuAPI polling returned an unexpected redirect; the paid "
                    "task state is unknown: "
                    f"HTTP {status_code}, location={_redact_secret(location, api_key)}",
                    task_id=task_id,
                )
            if status_code in RETRYABLE_STATUS_CODES:
                raise requests.exceptions.HTTPError(
                    f"HTTP {status_code}", response=response
                )
            if not 200 <= status_code < 300:
                raise MuAPIUnconfirmedTaskError(
                    "MuAPI task status is unknown: "
                    f"http_status={status_code}, "
                    f"detail={_response_error(response, api_key)}",
                    task_id=task_id,
                )
            body = response.json()
            if not isinstance(body, dict):
                raise MuAPIUnconfirmedTaskError(
                    "MuAPI task status response is malformed", task_id=task_id
                )
        except MuAPIUnconfirmedTaskError:
            raise
        except Exception as exc:
            if not _is_retryable_error(exc):
                raise MuAPIUnconfirmedTaskError(
                    "MuAPI polling failed and the task state is unknown: "
                    f"error={type(exc).__name__}, "
                    f"detail={_redact_secret(exc, api_key)}",
                    task_id=task_id,
                ) from exc

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MuAPIUnconfirmedTaskError(
                    "MuAPI task is still running after the configured local wait "
                    f"timeout: id={task_id}",
                    task_id=task_id,
                ) from exc
            consecutive_failures += 1
            if consecutive_failures > MAX_POLL_RETRIES:
                raise MuAPIUnconfirmedTaskError(
                    "MuAPI polling failed after retries; the paid task may still "
                    f"be running remotely: id={task_id}",
                    task_id=task_id,
                ) from exc
            delay = min(RETRY_BASE_SECONDS * consecutive_failures, remaining)
            logger.warning(
                "MuAPI polling hit a transient error; retrying the same task: "
                f"id={task_id}, attempt={consecutive_failures}/{MAX_POLL_RETRIES}, "
                f"retry_in={delay:.1f}s"
            )
            time.sleep(delay)
            continue

        consecutive_failures = 0
        status = str(body.get("status") or "").strip().lower()
        if status in TERMINAL_SUCCESS_STATUSES:
            return body
        if status in TERMINAL_FAILURE_STATUSES:
            logger.error(
                "MuAPI task did not produce a video: "
                f"id={task_id}, status={status}, "
                f"detail={_redact_secret(body.get('error'), api_key)}"
            )
            return None
        if status not in ACTIVE_STATUSES:
            raise MuAPIUnconfirmedTaskError(
                f"MuAPI returned an unknown task status: id={task_id}, "
                f"status={status!r}",
                task_id=task_id,
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MuAPIUnconfirmedTaskError(
                "MuAPI task is still running after the configured local wait "
                f"timeout: id={task_id}",
                task_id=task_id,
            )
        time.sleep(min(poll_interval, remaining))
