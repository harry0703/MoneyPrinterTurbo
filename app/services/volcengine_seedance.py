import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import quote_plus

import requests
from loguru import logger

from app.utils.request_logging import trace_http_call

from app.config import config
from app.services import generation_progress
from app.models.schema import MaterialInfo, VideoAspect


DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL_ID = "doubao-seedance-1-0-pro-250528"
DEFAULT_RESOLUTION = "1080p"
DEFAULT_MIN_DURATION_SECONDS = 2
DEFAULT_MAX_DURATION_SECONDS = 12
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_RUN_TIMEOUT_SECONDS = 1800.0
MAX_POLL_RETRIES = 5
RETRY_BASE_SECONDS = 1.0
MAX_ERROR_TEXT_LENGTH = 500
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
TERMINAL_FAILURE_STATUSES = frozenset(
    {"failed", "cancelled", "canceled", "expired"}
)
ACTIVE_STATUSES = frozenset({"queued", "running"})
SUPPORTED_RESOLUTIONS = frozenset({"480p", "720p", "1080p"})


@dataclass(frozen=True)
class SeedanceEndpoint:
    """Submission snapshot for an endpoint of the same protocol, so different providers don't rewrite each other's global config."""

    provider_id: str
    display_name: str
    api_key: str = field(repr=False)
    tasks_url: str
    model: str
    resolution: str
    min_duration: int = 2
    max_duration: int = 30
    watermark: bool = False
    generate_audio: bool = False
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS
    run_timeout: float = DEFAULT_RUN_TIMEOUT_SECONDS


class VolcEngineSeedanceError(RuntimeError):
    """A deterministic config, request or response error."""

    def __init__(self, message: str, task_id: str = ""):
        super().__init__(message)
        # As soon as a remote task exists, every error type carries the task ID. The upper layer doesn't need
        # to maintain recovery logic per exception subclass, and the WebUI/API can reliably show troubleshooting info.
        self.task_id = task_id


class VolcEngineSeedanceUnconfirmedTaskError(VolcEngineSeedanceError):
    """The remote may have created a paid task, but this machine can't confirm its final state."""

    def __init__(self, message: str, task_id: str = ""):
        super().__init__(message, task_id=task_id)


class VolcEngineSeedanceDownloadError(VolcEngineSeedanceError):
    """The remote paid task succeeded, but the generated video couldn't be downloaded to this machine."""

    def __init__(self, message: str, task_id: str):
        super().__init__(message, task_id=task_id)


def get_api_key(settings: Mapping[str, Any] | None = None) -> str:
    """
    Read Ark credentials by a clear and unique priority.

    The Seedance-specific config has the highest priority; the only supported runtime environment variable is the clearly named
    ``VOLCENGINE_ARK_API_KEY``. The legacy ``volcengine_api_key`` is only a shared config
    fallback, so users already using Ark LLMs don't have to enter the same Key again after upgrading.
    """
    settings = config.app if settings is None else settings
    configured = str(settings.get("volcengine_seedance_api_key", "") or "").strip()
    environment_key = os.getenv("VOLCENGINE_ARK_API_KEY", "").strip()
    shared_ark_key = str(settings.get("volcengine_api_key", "") or "").strip()
    return configured or environment_key or shared_ark_key


def is_enabled(settings: Mapping[str, Any] | None = None) -> bool:
    return bool(get_api_key(settings))


def _base_url() -> str:
    return str(
        config.app.get("volcengine_seedance_base_url", DEFAULT_BASE_URL)
        or DEFAULT_BASE_URL
    ).rstrip("/")


def _model_id() -> str:
    return str(
        config.app.get("volcengine_seedance_model", DEFAULT_MODEL_ID)
        or DEFAULT_MODEL_ID
    ).strip()


def _resolution() -> str:
    configured = config.app.get("volcengine_seedance_resolution", DEFAULT_RESOLUTION)
    value = str(configured).strip().lower()
    if value not in SUPPORTED_RESOLUTIONS:
        # Resolution directly affects the spec of the paid task. Invalid values must not silently fall back to the highest default
        # resolution. When the config item is missing, get uses the default; once the user explicitly writes an empty value,
        # None, 0 or another invalid value, it must raise, otherwise it could still incur unexpected costs.
        supported = ", ".join(sorted(SUPPORTED_RESOLUTIONS))
        raise VolcEngineSeedanceError(
            f"Unsupported Seedance resolution {value!r}; expected one of: {supported}"
        )
    return value


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
        except (TypeError, ValueError, OverflowError):
            # TOML accepts `inf`; int(inf) raises OverflowError, which is not
            # a provider error and would abort the task with a traceback.
            return default
        return value if value >= 1 else default

    minimum = read(
        "volcengine_seedance_min_duration", DEFAULT_MIN_DURATION_SECONDS
    )
    maximum = read(
        "volcengine_seedance_max_duration", DEFAULT_MAX_DURATION_SECONDS
    )
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
        code = error.get("code") or payload.get("code")
        message = error.get("message") or payload.get("message")
    else:
        code = payload.get("code")
        message = payload.get("message") or error
    detail = ": ".join(str(item) for item in (code, message) if item not in (None, ""))
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


def _rendition_size(aspect: VideoAspect, resolution: str) -> tuple[int, int]:
    # For Ark's 480p video the long side is actually output as 864 due to encoder alignment, not the mathematically derived
    # 854; 720p and 1080p output 1280 and 1920 per the official ratios. Real local calls have
    # verified that 480p portrait output is 480x864. Source records must describe the real output, otherwise later
    # audits or material diagnostics would see dimensions inconsistent with the file.
    short_edge = {"480p": 480, "720p": 720, "1080p": 1080}[resolution]
    long_edge = {"480p": 864, "720p": 1280, "1080p": 1920}[resolution]
    if aspect == VideoAspect.portrait:
        return short_edge, long_edge
    if aspect == VideoAspect.square:
        return short_edge, short_edge
    return long_edge, short_edge


def generate_videos(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
    *,
    endpoint: SeedanceEndpoint | None = None,
) -> list[MaterialInfo]:
    """Submit a Seedance text-to-video task; the original Ark config is still used by default."""
    api_key = endpoint.api_key if endpoint else get_api_key()
    provider_id = endpoint.provider_id if endpoint else "volcengine_seedance"
    display_name = endpoint.display_name if endpoint else "Volcano Engine Seedance"
    if not api_key:
        raise VolcEngineSeedanceError(
            f"{display_name} requires an API key"
            if endpoint
            else "Volcano Engine Seedance requires an Ark API key"
        )

    term = str(search_term or "").strip()
    if not term:
        # An empty prompt may come from an upstream script-splitting error. A paid generation source must not submit it to the remote,
        # because even if the API accepted the request, it would only yield an unusable video that was already billed.
        raise VolcEngineSeedanceError("Seedance search term must not be empty")

    aspect = VideoAspect(video_aspect)
    try:
        requested_duration = max(int(minimum_duration), 1)
    except (TypeError, ValueError, OverflowError) as exc:
        raise VolcEngineSeedanceError(
            "Seedance clip duration must be a positive integer"
        ) from exc
    minimum, maximum = (
        (endpoint.min_duration, endpoint.max_duration) if endpoint else _duration_bounds()
    )
    duration = min(max(requested_duration, minimum), maximum)
    if duration != requested_duration:
        # Generating longer than requested doesn't affect the final video: editing still trims to the clip duration; generating shorter
        # than requested only happens when the request exceeds the model's maximum, in which case it can only be clamped to the maximum. Other paid video sources
        # all explain this clamping, otherwise users couldn't tell why clips in the final video are shorter than configured.
        logger.info(
            "Seedance clip duration clamped to the configured model range: "
            f"requested={requested_duration}s, using={duration}s "
            f"(configured {minimum}-{maximum}s)"
        )
    resolution = endpoint.resolution if endpoint else _resolution()
    payload = {
        "model": endpoint.model if endpoint else _model_id(),
        "content": [{"type": "text", "text": term}],
        "ratio": aspect.value,
        "duration": duration,
        "resolution": resolution,
        "watermark": endpoint.watermark
        if endpoint else _config_bool("volcengine_seedance_watermark", False),
    }
    if endpoint:
        # The new endpoint explicitly turns off the material's original audio; the final video is still handled by the project's own voice-over and music flow.
        payload["generate_audio"] = endpoint.generate_audio
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    tasks_url = (
        endpoint.tasks_url if endpoint
        else f"{_base_url()}/contents/generations/tasks"
    )
    logger.info(
        f"generating video with {display_name}: "
        f"model={payload['model']}, term={term!r}, duration={duration}s"
    )

    # The submit endpoint isn't retried automatically: a timeout or 5xx may happen after the paid task was already created,
    # and blind retries would cause duplicate charges. Only an explicit rejection response is treated as a deterministic failure.
    generation_progress.submitting(provider_id)
    try:
        response = trace_http_call(
            "POST", requests.post,
            tasks_url,
            json=payload,
            headers=headers,
            proxies=config.proxy,
            verify=_tls_verify(),
            timeout=(30, 60),
            allow_redirects=False,
        )
    except Exception as exc:
        raise VolcEngineSeedanceUnconfirmedTaskError(
            "Seedance submission returned no response; a paid task may already "
            "exist remotely: "
            f"error={type(exc).__name__}, detail={_redact_secret(exc, api_key)}"
        ) from exc

    status_code = _status_code(response)
    if 300 <= status_code < 400:
        raise VolcEngineSeedanceUnconfirmedTaskError(
            "Seedance submission returned a redirect; the paid task state is "
            "unknown and the request was not replayed"
        )
    if status_code >= 500:
        raise VolcEngineSeedanceUnconfirmedTaskError(
            f"Seedance submission failed with HTTP {status_code}; a paid task may "
            "already exist remotely"
        )
    if not 200 <= status_code < 300:
        raise VolcEngineSeedanceError(
            "Seedance video generation request rejected: "
            f"HTTP {status_code}, {_response_error(response, api_key)}"
        )
    try:
        body = response.json()
    except Exception as exc:
        raise VolcEngineSeedanceUnconfirmedTaskError(
            "Seedance submission returned an unreadable response; a paid task may "
            f"already exist remotely: error={type(exc).__name__}"
        ) from exc
    task_id = str(body.get("id") or "").strip() if isinstance(body, dict) else ""
    if not task_id:
        raise VolcEngineSeedanceUnconfirmedTaskError(
            "Seedance accepted the submission without returning a task id"
        )
    logger.info(f"{display_name} task created: id={task_id}")

    poll_options = (
        {"run_timeout": endpoint.run_timeout, "poll_interval": endpoint.poll_interval}
        if endpoint else {}
    )
    task = _wait_for_task(
        task_id=task_id,
        tasks_url=tasks_url,
        headers=headers,
        api_key=api_key,
        **poll_options,
    )
    if task is None:
        return []
    content = task.get("content")
    video_url = content.get("video_url") if isinstance(content, dict) else None
    if not isinstance(video_url, str) or not video_url.startswith(("http://", "https://")):
        raise VolcEngineSeedanceError(
            f"Seedance task succeeded without a downloadable video: id={task_id}",
            task_id=task_id,
        )

    rendition = {"id": task_id}
    if endpoint is None:
        width, height = _rendition_size(aspect, resolution)
        rendition.update(width=width, height=height)
    return [
        MaterialInfo(
            provider=provider_id,
            url=video_url,
            duration=duration,
            source_info={
                "provider": provider_id,
                "search_term": term,
                "asset_id": task_id,
                "rendition": rendition,
            },
        )
    ]


def _wait_for_task(
    *,
    task_id: str,
    tasks_url: str,
    headers: dict[str, str],
    api_key: str,
    run_timeout: float | None = None,
    poll_interval: float | None = None,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + (
        run_timeout if run_timeout is not None else _bounded_float(
            "volcengine_seedance_run_timeout",
            DEFAULT_RUN_TIMEOUT_SECONDS,
            60.0,
            7200.0,
        )
    )
    poll_interval = (
        poll_interval if poll_interval is not None else _bounded_float(
            "volcengine_seedance_poll_interval",
            DEFAULT_POLL_INTERVAL_SECONDS,
            0.5,
            60.0,
        )
    )
    generation_progress.remote('', task_id)
    consecutive_failures = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise VolcEngineSeedanceUnconfirmedTaskError(
                "Seedance task is still running after the configured local wait "
                f"timeout: id={task_id}",
                task_id=task_id,
            )

        # requests times connect and read timeouts separately, so each uses half of the remaining total time.
        # Even if both connect and read hit their limits, a single round of requests won't deliberately exceed the overall deadline;
        # the network library may still have tiny scheduling errors, and the next deadline check prevents another retry.
        phase_timeout = max(min(remaining / 2.0, 30.0), 0.001)
        try:
            response = trace_http_call(
                "GET", requests.get,
                f"{tasks_url}/{task_id}",
                headers=headers,
                proxies=config.proxy,
                verify=_tls_verify(),
                timeout=(phase_timeout, phase_timeout),
                allow_redirects=False,
            )
            status_code = _status_code(response)
            if status_code in RETRYABLE_STATUS_CODES:
                raise requests.exceptions.HTTPError(
                    f"HTTP {status_code}", response=response
                )
            if not 200 <= status_code < 300:
                raise VolcEngineSeedanceUnconfirmedTaskError(
                    "Seedance task status is unknown: "
                    f"http_status={status_code}, detail={_response_error(response, api_key)}",
                    task_id=task_id,
                )
            body = response.json()
            if not isinstance(body, dict):
                raise VolcEngineSeedanceUnconfirmedTaskError(
                    "Seedance task status response is malformed", task_id=task_id
                )
        except VolcEngineSeedanceUnconfirmedTaskError:
            raise
        except Exception as exc:
            if not _is_retryable_error(exc):
                raise VolcEngineSeedanceUnconfirmedTaskError(
                    "Seedance polling failed and the paid task state is unknown: "
                    f"error={type(exc).__name__}, detail={_redact_secret(exc, api_key)}",
                    task_id=task_id,
                ) from exc

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VolcEngineSeedanceUnconfirmedTaskError(
                    "Seedance task is still running after the configured local wait "
                    f"timeout: id={task_id}",
                    task_id=task_id,
                ) from exc
            consecutive_failures += 1
            generation_progress.remote('', task_id, retrying=True)
            if consecutive_failures > MAX_POLL_RETRIES:
                raise VolcEngineSeedanceUnconfirmedTaskError(
                    "Seedance polling failed after retries; the paid task may still "
                    f"be running remotely: id={task_id}",
                    task_id=task_id,
                ) from exc
            delay = min(RETRY_BASE_SECONDS * consecutive_failures, remaining)
            logger.warning(
                "Seedance polling hit a transient error; retrying the same task: "
                f"id={task_id}, attempt={consecutive_failures}/{MAX_POLL_RETRIES}, "
                f"retry_in={delay:.1f}s"
            )
            time.sleep(delay)
            continue

        consecutive_failures = 0
        status = str(body.get("status") or "").strip().lower()
        generation_progress.remote('', task_id, status)
        if status == "succeeded":
            return body
        if status in TERMINAL_FAILURE_STATUSES:
            raise VolcEngineSeedanceError(
                "Seedance task did not produce a video: "
                f"id={task_id}, status={status}, "
                f"detail={_redact_secret(body.get('error'), api_key)}",
                task_id=task_id,
            )
        if status not in ACTIVE_STATUSES:
            raise VolcEngineSeedanceUnconfirmedTaskError(
                f"Seedance returned an unknown task status: id={task_id}, status={status!r}",
                task_id=task_id,
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise VolcEngineSeedanceUnconfirmedTaskError(
                "Seedance task is still running after the configured local wait "
                f"timeout: id={task_id}",
                task_id=task_id,
            )
        time.sleep(min(poll_interval, remaining))
