

"""useapi.net video and image client.

useapi.net is a third-party API that runs generations on accounts the user
connects to it: Veo 3.1 and Gemini Omni Flash videos and Nano Banana images
through Google Flow and Gemini Omni 1.2 Flash videos through Google Vids on the
user's own Google AI plan, Kling videos and images on the user's own Kling AI
account, and Seedance videos on the user's own Dreamina account.  A video
spends credits (or Vids allowance) on that account, so the protocol follows the
MuAPI client: a submission that may have been accepted is never retried, while
a ``429`` (every connected account is busy, nothing was started) waits and
submits again.  Videos and Kling images are submitted asynchronously and
polled; Nano Banana images come back in the same response.
"""

from __future__ import annotations

import base64
import binascii
import math
import os
import re
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, quote_plus

import requests
from loguru import logger

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect
from app.services import generation_progress
from app.utils.request_logging import trace_http_call


DEFAULT_BASE_URL = "https://api.useapi.net/v1"
# useapi.net counts integrations by User-Agent; keep it on every API request.
USER_AGENT = "MoneyPrinterTurbo-useapi/1.0"
TOKEN_URL = (
    "https://useapi.net/docs/start-here/setup-useapi"
    "?utm_source=moneyprinterturbo&utm_medium=referral"
    "&utm_campaign=mpt-integration"
)
GOOGLE_FLOW = "google-flow"
DREAMINA = "dreamina"
KLING = "kling"
GOOGLE_VIDS = "google-vids"
DEFAULT_MODEL = "veo-3.1-lite"
_GOOGLE_FLOW_ASPECTS = {
    VideoAspect.portrait: "portrait",
    VideoAspect.landscape: "landscape",
}
# Dreamina and Kling both take the ratio strings MPT uses.
_DREAMINA_ASPECTS = {
    VideoAspect.portrait: "9:16",
    VideoAspect.landscape: "16:9",
    VideoAspect.square: "1:1",
}
# Durations and ratios come from the useapi.net model tables.
#
# Veo accepts 4, 6 and 8 seconds, but 4 and 6 only on Google AI Ultra, and a Veo
# generation costs the same at every length, so 8 seconds is requested and the
# editor trims the clip.  Omni 1.2 Flash accepts 3-15 seconds, but 11-15 only on
# paid plans and at twice the per-second rate, so its range stops at 10.
# Google retires Veo 3.1 Fast, Veo 3.1 Quality and Omni 1.1 Flash in Google Flow
# on 2026-12-05; a follow-up change will drop them then.
#
# Google Vids runs Omni 1.2 Flash for 3-15 seconds, landscape or portrait, and
# each clip uses its length in seconds of the account's monthly Vids allowance.
#
# Kling and Dreamina models keep their documented lengths.  Resolutions list
# what each model accepts, default first.  For Kling they stand for its quality
# modes: 720p is "std", 1080p "pro" (on Kling 4.0 a paid Kling plan only) and
# 4K "4k" (Kling 3.0 only); 2.5 and 2.1 Master run only in pro mode.
def _model(label, service, durations, aspects, resolutions=(), **defaults):
    spec = {
        "label": label,
        "service": service,
        "durations": tuple(durations),
        "aspects": dict(aspects),
        # Resolutions the model accepts, its default first; empty means the
        # model has one fixed quality and no resolution is sent.
        "resolutions": tuple(resolutions),
    }
    if defaults:
        spec["defaults"] = defaults
    return spec


_VEO_ASPECTS = {**_GOOGLE_FLOW_ASPECTS, VideoAspect.square: "1:1"}
MODELS: dict[str, dict[str, Any]] = {
    "veo-3.1-lite": _model(
        "Veo 3.1 Lite (Google Flow)", GOOGLE_FLOW, (8,), _VEO_ASPECTS
    ),
    "veo-3.1-lite-low-priority": _model(
        "Veo 3.1 Lite low priority (0 credits on Ultra $199)",
        GOOGLE_FLOW,
        (8,),
        _VEO_ASPECTS,
    ),
    "veo-3.1-fast": _model(
        "Veo 3.1 Fast (Google Flow, retires December 5)", GOOGLE_FLOW, (8,), _VEO_ASPECTS
    ),
    "veo-3.1-quality": _model(
        "Veo 3.1 Quality (Google Flow, retires December 5)", GOOGLE_FLOW, (8,), _VEO_ASPECTS
    ),
    "omni-flash": _model(
        "Gemini Omni 1.1 Flash (Google Flow, retires December 5)",
        GOOGLE_FLOW,
        (4, 6, 8, 10),
        _GOOGLE_FLOW_ASPECTS,
        ("720p", "360p"),
    ),
    "omni-flash-1.2": _model(
        "Gemini Omni 1.2 Flash (Google Flow)",
        GOOGLE_FLOW,
        range(3, 11),
        _GOOGLE_FLOW_ASPECTS,
        ("720p", "360p"),
    ),
    "vids-omni-flash-1.2": _model(
        "Gemini Omni 1.2 Flash (Google Vids)",
        GOOGLE_VIDS,
        range(3, 16),
        _GOOGLE_FLOW_ASPECTS,
        # Google Vids charges the same for 1080p as for 720p.
        ("1080p", "720p"),
    ),
    "kling-v4-0": _model(
        "Kling 4.0 (Kling AI)", KLING, range(3, 31), _DREAMINA_ASPECTS, ("720p", "1080p")
    ),
    "kling-v4-0-flash": _model(
        "Kling 4.0 Flash (Kling AI)", KLING, range(3, 21), _DREAMINA_ASPECTS, ("720p",)
    ),
    "kling-v3-0": _model(
        "Kling 3.0 (Kling AI)",
        KLING,
        range(3, 16),
        _DREAMINA_ASPECTS,
        ("720p", "1080p", "4K"),
    ),
    "kling-v3-0-turbo": _model(
        "Kling 3.0 Turbo (Kling AI)", KLING, range(3, 16), _DREAMINA_ASPECTS, ("720p", "1080p")
    ),
    "kling-v2-6": _model(
        "Kling 2.6 (Kling AI)", KLING, (5, 10), _DREAMINA_ASPECTS, ("720p", "1080p")
    ),
    "kling-v2-5": _model(
        "Kling 2.5 (Kling AI)", KLING, (5, 10), _DREAMINA_ASPECTS, ("1080p",)
    ),
    "kling-v2-1-master": _model(
        "Kling 2.1 Master (Kling AI)", KLING, (5, 10), _DREAMINA_ASPECTS, ("1080p",)
    ),
    "kling-v1-6": _model(
        "Kling 1.6 (Kling AI)", KLING, (5, 10), _DREAMINA_ASPECTS, ("720p", "1080p")
    ),
    "kling-v1-5": _model(
        "Kling 1.5 (Kling AI)", KLING, (5, 10), _DREAMINA_ASPECTS, ("720p", "1080p")
    ),
    "seedance-2.5": _model(
        "Seedance 2.5 (Dreamina)", DREAMINA, range(4, 31), _DREAMINA_ASPECTS,
        ("480p", "720p", "1080p"),
    ),
    "seedance-2.0": _model(
        "Seedance 2.0 (Dreamina)", DREAMINA, range(4, 16), _DREAMINA_ASPECTS,
        ("720p", "1080p", "4k"),
    ),
    "seedance-2.0-fast": _model(
        "Seedance 2.0 Fast (Dreamina)", DREAMINA, range(4, 16), _DREAMINA_ASPECTS,
        ("720p", "1080p", "2k", "4k"),
    ),
    "seedance-2.0-mini": _model(
        "Seedance 2.0 Mini (Dreamina)", DREAMINA, range(4, 16), _DREAMINA_ASPECTS,
        ("720p", "1080p", "2k", "4k"),
    ),
    "seedance-1.5-pro": _model(
        "Seedance 1.5 Pro (Dreamina)", DREAMINA, (5, 10, 12), _DREAMINA_ASPECTS,
        ("720p", "1080p"),
    ),
    "seedance-1.0-pro": _model(
        "Seedance 1.0 Pro (Dreamina, CA accounts)",
        DREAMINA,
        (5, 10),
        _DREAMINA_ASPECTS,
        ("1080p",),
    ),
    "seedance-1.0-mini": _model(
        "Seedance 1.0 Mini (Dreamina, US accounts)", DREAMINA, (5, 10), _DREAMINA_ASPECTS,
        ("720p",),
    ),
    "seedance-1.0-fast": _model(
        "Seedance 1.0 Fast (Dreamina, CA accounts)", DREAMINA, (5, 10), _DREAMINA_ASPECTS,
        ("720p", "1080p"),
    ),
}
# Nano Banana images through Google Flow, in the order the useapi.net docs list
# them; 2 Lite is Google Flow's own default and Google Flow charges no credits
# for them.  Kling images (KOLORS 3.0 / 2.1 and Omni Image v3 / O1) run as Kling
# tasks and spend the user's Kling credits.  Every model takes the MPT ratios.
_IMAGE_ASPECTS = {
    VideoAspect.portrait: "9:16",
    VideoAspect.landscape: "16:9",
    VideoAspect.square: "1:1",
}
IMAGE_MODELS: dict[str, dict[str, Any]] = {
    "nano-banana-2-lite": {
        "label": "Nano Banana 2 Lite (Google Flow)",
        "service": GOOGLE_FLOW,
        "aspects": dict(_IMAGE_ASPECTS),
    },
    "nano-banana-2": {
        "label": "Nano Banana 2.1 (Google Flow)",
        "service": GOOGLE_FLOW,
        "aspects": dict(_IMAGE_ASPECTS),
    },
    "nano-banana-pro": {
        "label": "Nano Banana Pro (Google Flow)",
        "service": GOOGLE_FLOW,
        "aspects": dict(_IMAGE_ASPECTS),
    },
    "kling-kolors-v3-0": {
        "label": "Kling Kolors 3.0 (Kling)",
        "service": KLING,
        "endpoint": "kolors",
        "version": {"version": "kling-v3-0"},
        "aspects": dict(_IMAGE_ASPECTS),
    },
    "kling-kolors-v2-1": {
        "label": "Kling Kolors 2.1 (Kling)",
        "service": KLING,
        "endpoint": "kolors",
        "version": {"version": "kling-v2-1"},
        "aspects": dict(_IMAGE_ASPECTS),
    },
    "kling-omni-image-v3": {
        "label": "Kling Omni Image 3.0 (Kling)",
        "service": KLING,
        "endpoint": "omni",
        "version": {"omni_version": "v3"},
        "aspects": dict(_IMAGE_ASPECTS),
    },
    "kling-omni-image-o1": {
        "label": "Kling Omni Image O1 (Kling)",
        "service": KLING,
        "endpoint": "omni",
        "version": {"omni_version": "o1"},
        "aspects": dict(_IMAGE_ASPECTS),
    },
}
DEFAULT_IMAGE_MODEL = "nano-banana-2-lite"
IMAGE_PROMPT_REJECTED_STATUSES = frozenset({400, 500})
IMAGE_DOWNLOAD_ATTEMPTS = 3
MAX_IMAGE_BYTES = 25 * 1024 * 1024
DEFAULT_POLL_INTERVAL_SECONDS = 10.0
DEFAULT_RUN_TIMEOUT_SECONDS = 1800.0
# Google Flow answers an async submission only after its captcha is solved,
# which can take several minutes with retries.
SUBMIT_TIMEOUT = (30, 600)
MAX_SUBMIT_BUSY_RETRIES = 5
DEFAULT_BUSY_RETRY_SECONDS = 30.0
MAX_BUSY_RETRY_SECONDS = 300.0
MAX_POLL_RETRIES = 5
RETRY_BASE_SECONDS = 1.0
# A completed Google Flow job can lack its signed URL for a while; the job
# re-resolves it at most once a minute, so faster polling cannot help.
MISSING_URL_POLL_SECONDS = 60.0
MAX_ERROR_TEXT_LENGTH = 500
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
# 596 is useapi.net's own "account session needs to be re-added" answer, sent
# before any generation starts, so it is a definite rejection.
SESSION_ERROR_STATUS = 596
ACTIVE_STATUSES = frozenset({"created", "started", "queued", "pending", "processing"})
TERMINAL_SUCCESS_STATUSES = frozenset({"completed"})
TERMINAL_FAILURE_STATUSES = frozenset({"failed", "cancelled", "canceled", "expired"})
_PROGRESS_STATUS = {"created": "queued", "started": "running"}


# useapi.net job and media ids embed the connected account's email, for example
# "j1108...-u700-email:someone@gmail.com-bot:google-flow" or, URL-encoded,
# "user%3A1-someone%40gmail.com-video%3A...".  Anything logged, raised or shown
# masks the address; the raw id is used only for the API calls themselves.
_EMAIL = re.compile(
    r"[A-Za-z0-9._%+*-]+(?:@|%40)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}",
    re.IGNORECASE,
)


def mask_emails(text: Any) -> str:
    """Replace every email address in ``text`` with ``***``."""
    return _EMAIL.sub("***", str(text or ""))


def safe_job_id(job_id: Any) -> str:
    """A job or media id fit for logs, errors and the UI (email masked)."""
    return mask_emails(job_id)


class UseAPIError(RuntimeError):
    """Deterministic configuration, request, or response error.

    The message and ``task_id`` are masked here, so no exception carries an
    account email into logs, task state or the WebUI.
    """

    def __init__(self, message: str, task_id: str = ""):
        super().__init__(mask_emails(message))
        self.task_id = safe_job_id(task_id)


class UseAPIUnconfirmedTaskError(UseAPIError):
    """The remote job may exist, but its final state cannot be confirmed."""


class UseAPIDownloadError(UseAPIError):
    """A generation completed, but its output could not be downloaded."""


def get_api_key(settings: Mapping[str, Any] | None = None) -> str:
    """Read the configured useapi.net token, then ``USEAPI_TOKEN``."""
    settings = config.app if settings is None else settings
    configured = str(settings.get("useapi_api_token", "") or "").strip()
    environment_token = os.getenv("USEAPI_TOKEN", "").strip()
    return configured or environment_token


def is_enabled(settings: Mapping[str, Any] | None = None) -> bool:
    return bool(get_api_key(settings))


def model_id(settings: Mapping[str, Any] | None = None) -> str:
    settings = config.app if settings is None else settings
    value = str(settings.get("useapi_video_model", "") or DEFAULT_MODEL).strip()
    if value not in MODELS:
        raise UseAPIError(
            f"Unsupported useapi.net video model: {value}. "
            f"Supported models: {', '.join(MODELS)}"
        )
    return value


def model_label(model: str) -> str:
    return str(MODELS.get(model, {}).get("label") or model)


def supported_aspects(model: str) -> tuple[VideoAspect, ...]:
    return tuple(MODELS[model]["aspects"])


def check_aspect(model: str, video_aspect: VideoAspect | str) -> VideoAspect:
    """Reject a ratio the model cannot generate before anything is submitted."""
    try:
        aspect = VideoAspect(video_aspect)
    except (TypeError, ValueError) as exc:
        raise UseAPIError("useapi.net video aspect is invalid") from exc
    if aspect not in MODELS[model]["aspects"]:
        allowed = ", ".join(item.value for item in supported_aspects(model))
        raise UseAPIError(
            f"useapi.net model {model} supports the {allowed} video ratios, "
            f"not {aspect.value}"
        )
    return aspect


def _duration_bounds(model: str | None = None) -> tuple[int, int]:
    durations = MODELS[model or model_id()]["durations"]
    return min(durations), max(durations)


def request_duration(model: str, requested: int) -> int:
    """Return the duration sent for ``requested``: the nearest allowed value."""
    durations = MODELS[model]["durations"]
    longer = [value for value in durations if value >= requested]
    return min(longer) if longer else max(durations)


def clip_duration_options(model: str) -> list[int]:
    """Clip durations the WebUI offers for ``model``."""
    minimum, maximum = _duration_bounds(model)
    if minimum == maximum:
        # A fixed-length model is trimmed by the editor, so shorter clips work.
        return list(range(2, maximum + 1))
    return list(range(minimum, maximum + 1))


# Kling quality modes behind the resolutions offered for Kling models.
KLING_MODES = {"720p": "std", "1080p": "pro", "4K": "4k"}
_KLING_MODE_LABELS = {"720p": "720p (std)", "1080p": "1080p (pro)", "4K": "4K"}


def resolution_label(model: str, resolution: str) -> str:
    """How a resolution is shown for ``model``; Kling names its mode too."""
    if MODELS.get(model, {}).get("service") == KLING:
        return _KLING_MODE_LABELS.get(resolution, resolution)
    return resolution


def resolution_options(model: str) -> tuple[str, ...]:
    """Resolutions ``model`` accepts, its default first; empty for fixed quality."""
    return tuple(MODELS.get(model, {}).get("resolutions") or ())


def resolution_for(model: str, settings: Mapping[str, Any] | None = None) -> str:
    """The resolution sent for ``model``: the configured one if it accepts it.

    ``useapi_resolution`` is shared by every model, so a value chosen for one
    model (360p for Omni, say) falls back to the default of a model that does
    not take it, instead of being sent and rejected.
    """
    options = resolution_options(model)
    if not options:
        return ""
    settings = config.app if settings is None else settings
    configured = str(settings.get("useapi_resolution", "") or "").strip()
    for option in options:
        if option.lower() == configured.lower():
            return option
    return options[0]


def upscale_options(model: str, settings: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    """Google Flow upscale targets for ``model`` ("" = no upscale).

    Only Google Flow videos can be upscaled.  720p only makes sense for a 360p
    Omni clip; a 360p clip can also go straight to 1080p.
    """
    if MODELS.get(model, {}).get("service") != GOOGLE_FLOW:
        return ()
    options = ["", "1080p", "4K"]
    if resolution_for(model, settings) == "360p":
        options.insert(1, "720p")
    return tuple(options)


def upscale_for(model: str, settings: Mapping[str, Any] | None = None) -> str:
    """The upscale requested for ``model``, or "" when none applies."""
    settings = config.app if settings is None else settings
    configured = str(settings.get("useapi_upscale", "") or "").strip()
    for option in upscale_options(model, settings):
        if option and option.lower() == configured.lower():
            return option
    return ""


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
    # API error texts can name the account, e.g. "Account user@example.com ...".
    return mask_emails(text)[:MAX_ERROR_TEXT_LENGTH]


def _payload_error(payload: Any, status_code: int, api_token: str) -> str:
    if not isinstance(payload, dict):
        return f"HTTP {status_code}"
    error = payload.get("error")
    if isinstance(error, dict):
        detail = error.get("message") or error.get("status") or error.get("code")
    else:
        detail = error or payload.get("message")
    extra = payload.get("errorDetails")
    if isinstance(extra, str) and extra.strip():
        detail = f"{detail or ''} ({extra.strip()})".strip()
    response = payload.get("response")
    reasons = response.get("failureReasons") if isinstance(response, dict) else None
    if isinstance(reasons, list) and reasons:
        detail = f"{detail or ''} ({', '.join(str(item) for item in reasons)})".strip()
    return _redact_secret(detail or f"HTTP {status_code}", api_token)


def _response_error(response: Any, api_token: str) -> str:
    try:
        payload = response.json()
    except Exception:
        return f"HTTP {_status_code(response)}"
    return _payload_error(payload, _status_code(response), api_token)


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


def _retry_after_seconds(response: Any, default: float) -> float:
    """Read the wait a ``429``/``503`` asks for, from the header or the body."""
    headers = getattr(response, "headers", None) or {}
    value = headers.get("Retry-After") if hasattr(headers, "get") else None
    seconds = None
    if value not in (None, ""):
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(str(value))
                seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, IndexError):
                seconds = None
    if seconds is None:
        try:
            payload = response.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            if payload.get("retryAfterSec") is not None:
                try:
                    seconds = float(payload["retryAfterSec"])
                except (TypeError, ValueError):
                    seconds = None
            elif isinstance(payload.get("retryAfter") or payload.get("retryAt"), str):
                # Google Flow sends "retryAfter", Google Vids "retryAt".
                try:
                    retry_at = datetime.fromisoformat(
                        (payload.get("retryAfter") or payload["retryAt"]).replace(
                            "Z", "+00:00"
                        )
                    )
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
                except ValueError:
                    seconds = None
    if seconds is None or not math.isfinite(seconds):
        seconds = default
    # Not capped here: a wait longer than MAX_BUSY_RETRY_SECONDS (such as a used-up
    # monthly allowance) is reported at once instead of being waited out.
    return max(seconds, 1.0)


def _headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def _submission(
    model: str, term: str, aspect: VideoAspect, duration: int
) -> tuple[str, dict[str, Any]]:
    spec = MODELS[model]
    service = spec["service"]
    ratio = spec["aspects"][aspect]
    defaults = dict(spec.get("defaults") or {})
    if service == GOOGLE_FLOW:
        payload: dict[str, Any] = {
            "prompt": term,
            "model": model,
            "aspectRatio": ratio,
            "duration": duration,
            "async": True,
        }
    elif service == GOOGLE_VIDS:
        # Google Vids has a single video model, so no model field is sent.
        payload = {
            "prompt": term,
            "aspectRatio": ratio,
            "duration": duration,
            "async": True,
        }
    elif service == KLING:
        # Kling's quality is chosen by "mode", not a resolution.  The documented
        # request example sends the duration as a string.
        payload = {
            "prompt": term,
            "model_name": model,
            "aspect_ratio": ratio,
            "duration": str(duration),
            **defaults,
        }
        resolution = resolution_for(model)
        if resolution:
            payload["mode"] = KLING_MODES[resolution]
        return f"{DEFAULT_BASE_URL}/kling/videos/text2video", payload
    else:
        payload = {
            "prompt": term,
            "model": model,
            "ratio": ratio,
            "duration": duration,
        }
    payload.update(defaults)
    resolution = resolution_for(model)
    if resolution:
        payload["resolution"] = resolution
    return f"{DEFAULT_BASE_URL}/{service}/videos", payload


def _jobs_url(service: str) -> str:
    if service in {GOOGLE_FLOW, GOOGLE_VIDS}:
        return f"{DEFAULT_BASE_URL}/{service}/jobs"
    if service == KLING:
        return f"{DEFAULT_BASE_URL}/kling/tasks"
    return f"{DEFAULT_BASE_URL}/dreamina/videos"


def download_headers(url: str) -> dict[str, str] | None:
    """Headers for downloading ``url`` when it is a useapi.net media link.

    Google Vids files open only through useapi.net, so their download needs
    the API token.  Every other result is a public signed link and must never
    receive it.
    """
    if not str(url or "").startswith(f"{DEFAULT_BASE_URL}/"):
        return None
    api_token = get_api_key()
    if not api_token:
        return None
    return {"Authorization": f"Bearer {api_token}", "User-Agent": USER_AGENT}


def _valid_job_id(value: Any) -> str:
    job_id = str(value or "").strip()
    # The id becomes a URL path segment; anything that could change the path
    # or the query means the response cannot be trusted.
    if not job_id or any(char in job_id for char in "/?#\\") or any(
        char.isspace() for char in job_id
    ):
        return ""
    return job_id


def generate_videos(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> list[MaterialInfo]:
    """Submit one useapi.net text-to-video job and wait for its video URL."""
    api_token = get_api_key()
    if not api_token:
        raise UseAPIError("useapi.net video generation requires a useapi.net API token")

    term = str(search_term or "").strip()
    if not term:
        raise UseAPIError("useapi.net search term must not be empty")

    model = model_id()
    aspect = check_aspect(model, video_aspect)
    try:
        requested_duration = max(int(minimum_duration), 1)
    except (TypeError, ValueError, OverflowError) as exc:
        raise UseAPIError("useapi.net clip duration must be a positive integer") from exc
    duration = request_duration(model, requested_duration)
    if duration != requested_duration:
        minimum, maximum = _duration_bounds(model)
        logger.info(
            "useapi.net clip duration adjusted to the model's allowed lengths: "
            f"model={model}, requested={requested_duration}s, using={duration}s "
            f"(allowed {minimum}-{maximum}s)"
        )

    service = MODELS[model]["service"]
    videos_url, payload = _submission(model, term, aspect, duration)
    headers = _headers(api_token)
    logger.info(
        "generating video with useapi.net: "
        f"model={model}, term={term!r}, duration={duration}s, ratio={aspect.value}"
    )

    job_id, body = _submit(videos_url, payload, headers, api_token, service)
    logger.info(f"useapi.net video job created: id={safe_job_id(job_id)}")

    params = None
    if service == KLING:
        # With several Kling accounts, reading a task needs the email of the
        # account that ran it; the task's userId identifies that account.
        email = _kling_account_email(body, headers, api_token)
        params = {"email": email} if email else None

    job = _wait_for_task(
        task_id=job_id,
        jobs_url=_jobs_url(service),
        params=params,
        headers=headers,
        api_key=api_token,
        service=service,
    )
    if job is None:
        return []

    video_urls = _video_urls(job, service)
    if not video_urls:
        raise UseAPIError(
            f"useapi.net job completed without a downloadable video: id={safe_job_id(job_id)}",
            task_id=job_id,
        )

    upscale = upscale_for(model) if service == GOOGLE_FLOW else ""
    if upscale:
        upscaled_url = _upscale_flow_video(job, upscale, headers, api_token)
        if upscaled_url:
            # Keep the original link as a fallback for the download.
            video_urls = [upscaled_url, *video_urls]

    video_width, video_height = aspect.to_resolution()
    response = job.get("response") if isinstance(job.get("response"), dict) else {}
    if service == KLING:
        response = _kling_work(job).get("resource") or {}
    elif service == GOOGLE_VIDS:
        response = job.get("result") or {}
    if service in {DREAMINA, KLING, GOOGLE_VIDS} and isinstance(response, dict):
        width, height = response.get("width"), response.get("height")
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            video_width, video_height = width, height
    return [
        MaterialInfo(
            provider="useapi",
            url=video_urls[0],
            duration=duration,
            source_info={
                "provider": "useapi",
                "search_term": term,
                "asset_id": safe_job_id(job_id),
                "model": model,
                "rendition": {
                    "id": safe_job_id(job_id),
                    "width": video_width,
                    "height": video_height,
                },
                # Alternate hosts for the same file; the material service tries
                # them before reporting a failed download.
                "fallback_urls": video_urls[1:],
            },
        )
    ]


# Upscale targets the account's plan refused in this process.  The refusal
# comes before anything is charged and does not change on retry, so later
# clips skip the request and keep their original resolution.
_REFUSED_UPSCALES: set[str] = set()


def _flow_media_generation_id(job: dict[str, Any]) -> str:
    response = job.get("response")
    media = response.get("media") if isinstance(response, dict) else None
    for item in media if isinstance(media, list) else []:
        if not isinstance(item, dict):
            continue
        status = (
            ((item.get("mediaMetadata") or {}).get("mediaStatus") or {})
            .get("mediaGenerationStatus")
        )
        if status and status != "MEDIA_GENERATION_STATUS_SUCCESSFUL":
            continue
        media_id = item.get("mediaGenerationId")
        if isinstance(media_id, str) and media_id.strip():
            return media_id.strip()
    return ""


def _upscale_flow_video(
    job: dict[str, Any], resolution: str, headers: dict[str, str], api_token: str
) -> str:
    """Upscale a finished Google Flow clip; return the upscaled link or "".

    The original clip is already made, so every upscale problem keeps it:
    a plan that does not include the resolution (refused before anything is
    charged), a busy account, a failed upscale job, or an answer that leaves
    the upscale state unknown.  An ambiguous upscale is never submitted again.
    """
    if resolution in _REFUSED_UPSCALES:
        return ""
    media_id = _flow_media_generation_id(job)
    if not media_id:
        logger.warning("useapi.net clip has no media id to upscale; keeping it as is")
        return ""
    logger.info(f"upscaling useapi.net clip to {resolution}")
    try:
        response = _post(
            f"{DEFAULT_BASE_URL}/google-flow/videos/upscale",
            {"mediaGenerationId": media_id, "resolution": resolution, "async": True},
            headers,
            api_token,
        )
        status_code = _status_code(response)
        if status_code == 400:
            _REFUSED_UPSCALES.add(resolution)
            logger.warning(
                f"useapi.net upscale to {resolution} was refused and nothing was "
                "charged; the original clips are kept for the rest of this run "
                f"(upscaling needs a paid Google AI plan, 4K needs Ultra): "
                f"{_response_error(response, api_token)}"
            )
            return ""
        job_id, _ = _submit_response(response, api_token, "upscale")
        logger.info(f"useapi.net upscale job created: id={safe_job_id(job_id)}")
        upscaled = _wait_for_task(
            task_id=job_id,
            jobs_url=_jobs_url(GOOGLE_FLOW),
            headers=headers,
            api_key=api_token,
            service=GOOGLE_FLOW,
        )
    except UseAPIError as exc:
        logger.warning(
            f"useapi.net upscale to {resolution} did not finish; keeping the "
            f"original clip: {exc}"
        )
        return ""
    if upscaled is None:
        logger.warning(
            f"useapi.net upscale to {resolution} failed; keeping the original clip"
        )
        return ""
    urls = _video_urls(upscaled, GOOGLE_FLOW)
    return urls[0] if urls else ""


def _post(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    api_token: str,
) -> Any:
    """POST once per attempt, waiting out ``429`` answers; return the response.

    A ``429`` means every connected account is busy (or one hit a Google or
    Dreamina limit) and nothing was started, so posting again is safe.  Any
    answer that may hide a started generation raises
    :class:`UseAPIUnconfirmedTaskError` and is never posted again.
    """
    deadline = time.monotonic() + _bounded_float(
        "useapi_run_timeout", DEFAULT_RUN_TIMEOUT_SECONDS, 60.0, 7200.0
    )
    busy_attempts = 0
    while True:
        generation_progress.submitting("useapi")
        try:
            response = trace_http_call(
                "POST", requests.post,
                url,
                json=payload,
                headers=headers,
                proxies=config.proxy,
                verify=_tls_verify(),
                timeout=SUBMIT_TIMEOUT,
                allow_redirects=False,
            )
        except Exception as exc:
            # A timeout or dropped connection after the request left may mean
            # useapi.net already started the generation on the user's account.
            raise UseAPIUnconfirmedTaskError(
                "useapi.net submission returned no response; the generation may "
                "already have started on your account: "
                f"error={type(exc).__name__}, detail={_redact_secret(exc, api_token)}"
            ) from exc

        status_code = _status_code(response)
        if status_code == 429:
            busy_attempts += 1
            delay = _retry_after_seconds(response, DEFAULT_BUSY_RETRY_SECONDS)
            remaining = deadline - time.monotonic()
            if (
                busy_attempts > MAX_SUBMIT_BUSY_RETRIES
                or delay >= remaining
                or delay > MAX_BUSY_RETRY_SECONDS
            ):
                raise UseAPIError(
                    "useapi.net accounts are busy; no generation was started: "
                    f"HTTP 429, {_response_error(response, api_token)}"
                )
            logger.warning(
                "useapi.net accounts are busy; submitting again after a pause: "
                f"attempt={busy_attempts}/{MAX_SUBMIT_BUSY_RETRIES}, "
                f"retry_in={delay:.0f}s, detail={_response_error(response, api_token)}"
            )
            time.sleep(delay)
            continue
        if 300 <= status_code < 400:
            location = getattr(response, "headers", {}).get("Location", "")
            raise UseAPIUnconfirmedTaskError(
                "useapi.net submission returned an unexpected redirect; the "
                "generation state is unknown: "
                f"HTTP {status_code}, location={_redact_secret(location, api_token)}"
            )
        return response


def _unconfirmed_server_error(response: Any, api_token: str) -> UseAPIUnconfirmedTaskError:
    return UseAPIUnconfirmedTaskError(
        f"useapi.net submission failed with HTTP {_status_code(response)}; the "
        "generation may already have started on your account: "
        f"{_response_error(response, api_token)}"
    )


def _json_body(response: Any) -> Any:
    try:
        return response.json()
    except Exception as exc:
        raise UseAPIUnconfirmedTaskError(
            "useapi.net submission returned an unreadable response; the "
            "generation may already have started on your account: "
            f"error={type(exc).__name__}"
        ) from exc


def _submit(
    videos_url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    api_token: str,
    service: str = GOOGLE_FLOW,
) -> tuple[str, dict[str, Any]]:
    """Submit an async video job; return its job id and the response body."""
    response = _post(videos_url, payload, headers, api_token)
    return _submit_response(response, api_token, "video generation", service)


def _submit_response(
    response: Any, api_token: str, what: str, service: str = GOOGLE_FLOW
) -> tuple[str, dict[str, Any]]:
    """Classify a submission answer; return the job id and the response body."""
    status_code = _status_code(response)
    # Kling also answers moderation with 500, but its docs say a real server
    # error cannot be told apart from it, so it stays unconfirmed as well.
    if status_code >= 500 and status_code != SESSION_ERROR_STATUS:
        raise _unconfirmed_server_error(response, api_token)
    if not 200 <= status_code < 300:
        raise UseAPIError(
            f"useapi.net {what} request rejected: "
            f"HTTP {status_code}, {_response_error(response, api_token)}"
        )
    body = _json_body(response)
    job_id = ""
    if isinstance(body, dict):
        if service == KLING:
            task = body.get("task")
            task_id = task.get("id") if isinstance(task, dict) else None
            # Kling task ids are numbers; anything else is not a task id.
            if isinstance(task_id, int) and not isinstance(task_id, bool):
                job_id = str(task_id)
            elif isinstance(task_id, str) and task_id.strip().isdigit():
                job_id = task_id.strip()
        else:
            # Async Google Flow answers carry "jobid"; the sync shape uses "jobId".
            job_id = _valid_job_id(body.get("jobid") or body.get("jobId"))
    if not job_id:
        raise UseAPIUnconfirmedTaskError(
            "useapi.net accepted the submission without returning a job id"
        )
    return job_id, body


def _kling_account_email(
    body: dict[str, Any], headers: dict[str, str], api_token: str
) -> str:
    """Find the connected Kling account that took the task, if there are several.

    A wrong guess cannot spend credits: this only decides which account the
    status is read from.  Any failure falls back to reading without an email,
    which is what a single connected account needs.
    """
    task = body.get("task")
    user_id = task.get("userId") if isinstance(task, dict) else None
    if user_id is None:
        return ""
    try:
        response = trace_http_call(
            "GET", requests.get,
            f"{DEFAULT_BASE_URL}/kling/accounts",
            headers=headers,
            proxies=config.proxy,
            verify=_tls_verify(),
            timeout=(30, 30),
            allow_redirects=False,
        )
        accounts = response.json() if _status_code(response) == 200 else None
    except Exception as exc:
        logger.warning(
            "could not list useapi.net Kling accounts; reading the task without "
            f"an account: error={type(exc).__name__}"
        )
        return ""
    if not isinstance(accounts, dict) or len(accounts) < 2:
        return ""
    for key, account in accounts.items():
        if not isinstance(account, dict):
            continue
        session = account.get("session")
        if isinstance(session, dict) and session.get("userId") == user_id:
            return str(account.get("email") or key)
    return ""


def _kling_work(job: dict[str, Any], content_type: str = "video") -> dict[str, Any]:
    """The first finished work of ``content_type`` in a Kling task record."""
    works = job.get("works")
    for work in works if isinstance(works, list) else []:
        if not isinstance(work, dict):
            continue
        if work.get("contentType") not in (None, content_type):
            continue
        if str(work.get("status_name") or "succeed") != "succeed":
            continue
        return work
    return {}


def _job_status(body: dict[str, Any], service: str) -> str:
    """Map a job record's status onto the shared status names."""
    if service != KLING:
        return str(body.get("status") or "").strip().lower()
    # Kling's numeric "status" has many failure codes; status_name is stable.
    name = str(body.get("status_name") or "").strip().lower()
    if name == "succeed":
        return "completed"
    if name == "failed":
        return "failed"
    if name == "submitted":
        return "created"
    if name == "processing":
        return "started"
    if body.get("status_final") is True:
        return "failed"
    return name


def image_model_id(settings: Mapping[str, Any] | None = None) -> str:
    settings = config.app if settings is None else settings
    value = str(settings.get("useapi_image_model", "") or DEFAULT_IMAGE_MODEL).strip()
    if value not in IMAGE_MODELS:
        raise UseAPIError(
            f"Unsupported useapi.net image model: {value}. "
            f"Supported models: {', '.join(IMAGE_MODELS)}"
        )
    return value


def image_model_label(model: str) -> str:
    return str(IMAGE_MODELS.get(model, {}).get("label") or model)


def image_spends_credits(model: str) -> bool:
    """Kling images spend the user's Kling credits; Nano Banana images do not."""
    return IMAGE_MODELS.get(model, {}).get("service") == KLING


def image_requires_confirmation(settings: Mapping[str, Any] | None = None) -> bool:
    """Whether the configured image model needs the useapi.net charge consent."""
    try:
        return image_spends_credits(image_model_id(settings))
    except UseAPIError:
        return False


def _generate_kling_image(
    model: str, term: str, aspect: VideoAspect, api_token: str
) -> tuple[bytes | None, str]:
    """Run one Kling text-to-image task: submit, poll, download the image."""
    spec = IMAGE_MODELS[model]
    payload = {
        "prompt": f"Create one image depicting: {term}.",
        **spec["version"],
        "aspect_ratio": spec["aspects"][aspect],
        # KOLORS 3.0 makes two images by default; one material needs one.
        "imageCount": 1,
    }
    headers = _headers(api_token)
    logger.info(
        "generating image with useapi.net: "
        f"model={model}, term={term!r}, ratio={aspect.value}"
    )
    job_id, body = _submit(
        f"{DEFAULT_BASE_URL}/kling/images/{spec['endpoint']}",
        payload,
        headers,
        api_token,
        KLING,
    )
    email = _kling_account_email(body, headers, api_token)
    job = _wait_for_task(
        task_id=job_id,
        jobs_url=_jobs_url(KLING),
        params={"email": email} if email else None,
        headers=headers,
        api_key=api_token,
        service=KLING,
    )
    if job is None:
        # A failed Kling task (moderation and the like) skips this segment.
        return None, safe_job_id(job_id)
    resource = _kling_work(job, "image").get("resource")
    image_url = resource.get("resource") if isinstance(resource, dict) else None
    if not (isinstance(image_url, str) and image_url.startswith(("http://", "https://"))):
        raise UseAPIError(
            f"useapi.net Kling image task completed without an image: id={safe_job_id(job_id)}",
            task_id=job_id,
        )
    return _download_image(image_url, safe_job_id(job_id)), safe_job_id(job_id)


def generate_image(
    search_term: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> tuple[bytes | None, str]:
    """Generate one image: Nano Banana through Google Flow, or a Kling task.

    Returns ``(image bytes, job id)``, or ``(None, job id)`` when Google Flow
    refused this prompt (validation or content moderation) or the Kling task
    failed, so the caller can move on to the next script segment.  Errors that
    would repeat for every segment, or that leave the request state unknown,
    raise.
    """
    api_token = get_api_key()
    if not api_token:
        raise UseAPIError("useapi.net image generation requires a useapi.net API token")
    term = str(search_term or "").strip()
    if not term:
        raise UseAPIError("useapi.net search term must not be empty")
    model = image_model_id()
    try:
        aspect = VideoAspect(video_aspect)
    except (TypeError, ValueError) as exc:
        raise UseAPIError("useapi.net video aspect is invalid") from exc
    if aspect not in IMAGE_MODELS[model]["aspects"]:
        raise UseAPIError(
            f"useapi.net image model {model} does not support the {aspect.value} ratio"
        )
    if IMAGE_MODELS[model]["service"] == KLING:
        return _generate_kling_image(model, term, aspect, api_token)

    payload = {
        "prompt": f"Create one image depicting: {term}.",
        "model": model,
        "aspectRatio": IMAGE_MODELS[model]["aspects"][aspect],
        # The API's default is 4 images; one material needs one.
        "count": 1,
    }
    logger.info(
        "generating image with useapi.net: "
        f"model={model}, term={term!r}, ratio={aspect.value}"
    )
    response = _post(
        f"{DEFAULT_BASE_URL}/google-flow/images", payload, _headers(api_token), api_token
    )
    status_code = _status_code(response)
    if status_code in IMAGE_PROMPT_REJECTED_STATUSES:
        # 400 is a refused prompt; for images 500 is Google's moderation answer.
        logger.error(
            "useapi.net image request was refused for this segment: "
            f"term={term!r}, HTTP {status_code}, "
            f"detail={_response_error(response, api_token)}"
        )
        return None, ""
    if status_code >= 500 and status_code != SESSION_ERROR_STATUS:
        raise _unconfirmed_server_error(response, api_token)
    if not 200 <= status_code < 300:
        raise UseAPIError(
            "useapi.net image generation request rejected: "
            f"HTTP {status_code}, {_response_error(response, api_token)}"
        )
    body = _json_body(response)
    job_id = _valid_job_id(body.get("jobId") or body.get("jobid")) if isinstance(
        body, dict
    ) else ""
    image = {}
    media = body.get("media") if isinstance(body, dict) else None
    for item in media if isinstance(media, list) else []:
        image_info = item.get("image") if isinstance(item, dict) else None
        generated = image_info.get("generatedImage") if isinstance(image_info, dict) else None
        if isinstance(generated, dict):
            image = generated
            break
    encoded = image.get("encodedImage")
    if isinstance(encoded, str) and encoded:
        # Google sends the bytes inline when it could not produce a link.
        if len(encoded) > MAX_IMAGE_BYTES * 4 // 3 + 4:
            logger.error(f"useapi.net inline image is too large: id={safe_job_id(job_id)}")
            return None, safe_job_id(job_id)
        try:
            return base64.b64decode(encoded, validate=True), safe_job_id(job_id)
        except (binascii.Error, ValueError):
            logger.error(f"useapi.net inline image is not valid base64: id={safe_job_id(job_id)}")
            return None, safe_job_id(job_id)
    image_url = image.get("fifeUrl")
    if not (isinstance(image_url, str) and image_url.startswith(("http://", "https://"))):
        raise UseAPIError(
            f"useapi.net image generation returned no image: id={safe_job_id(job_id) or 'unknown'}",
            task_id=job_id,
        )
    return _download_image(image_url, safe_job_id(job_id)), safe_job_id(job_id)


def _download_image(image_url: str, job_id: str) -> bytes:
    """Download a generated image from its signed link, retrying that link."""
    failure = "no download attempt was made"
    for attempt in range(1, IMAGE_DOWNLOAD_ATTEMPTS + 1):
        response = None
        try:
            # The signed link needs no credentials; never send the API token.
            response = trace_http_call(
                "GET", requests.get,
                image_url,
                headers={"User-Agent": USER_AGENT},
                proxies=config.proxy,
                verify=_tls_verify(),
                timeout=(30, 120),
                stream=True,
            )
            status_code = _status_code(response)
            if status_code == 200:
                content = bytearray()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    if len(content) + len(chunk) > MAX_IMAGE_BYTES:
                        raise UseAPIError(
                            f"useapi.net image exceeds {MAX_IMAGE_BYTES} bytes: id={safe_job_id(job_id)}",
                            task_id=job_id,
                        )
                    content.extend(chunk)
                if content:
                    return bytes(content)
                failure = "empty download"
            else:
                failure = f"HTTP {status_code}"
        except UseAPIError:
            raise
        except Exception as exc:
            failure = f"error={type(exc).__name__}"
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
        if attempt < IMAGE_DOWNLOAD_ATTEMPTS:
            logger.warning(
                "useapi.net image download failed, retrying the same link: "
                f"id={safe_job_id(job_id)}, attempt={attempt}/{IMAGE_DOWNLOAD_ATTEMPTS}, {failure}"
            )
            time.sleep(RETRY_BASE_SECONDS * attempt)
    raise UseAPIError(
        f"useapi.net image could not be downloaded: id={safe_job_id(job_id) or 'unknown'}, {failure}",
        task_id=job_id,
    )


def _video_urls(job: dict[str, Any], service: str) -> list[str]:
    candidates: list[Any] = []
    if service == KLING:
        resource = _kling_work(job).get("resource")
        if isinstance(resource, dict):
            candidates.append(resource.get("resource"))
    response = job.get("response")
    if not isinstance(response, dict):
        response = {}
    if service == GOOGLE_VIDS:
        # Vids files open only through useapi.net (GET /media/{mediaId}); the
        # material service downloads them with the API token.
        result = job.get("result")
        media_id = result.get("mediaId") if isinstance(result, dict) else None
        if isinstance(media_id, str) and media_id.strip():
            candidates.append(
                f"{DEFAULT_BASE_URL}/google-vids/media/{quote(media_id.strip(), safe='')}"
            )
    elif service == KLING:
        pass
    elif service == GOOGLE_FLOW:
        media = response.get("media")
        for item in media if isinstance(media, list) else []:
            if not isinstance(item, dict):
                continue
            status = (
                ((item.get("mediaMetadata") or {}).get("mediaStatus") or {})
                .get("mediaGenerationStatus")
            )
            if status and status != "MEDIA_GENERATION_STATUS_SUCCESSFUL":
                continue
            candidates.append(item.get("videoUrl"))
    else:
        candidates.append(response.get("videoUrl"))
        candidates.append(response.get("videoUrlBackup"))
        backups = response.get("videoUrlBackups")
        if isinstance(backups, list):
            candidates.extend(backups)
    urls: list[str] = []
    for candidate in candidates:
        if (
            isinstance(candidate, str)
            and candidate.startswith(("http://", "https://"))
            and candidate not in urls
        ):
            urls.append(candidate)
    return urls


def _wait_for_task(
    *,
    task_id: str,
    jobs_url: str,
    headers: dict[str, str],
    api_key: str,
    service: str = GOOGLE_FLOW,
    params: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + _bounded_float(
        "useapi_run_timeout", DEFAULT_RUN_TIMEOUT_SECONDS, 60.0, 7200.0
    )
    poll_interval = _bounded_float(
        "useapi_poll_interval", DEFAULT_POLL_INTERVAL_SECONDS, 1.0, 60.0
    )
    job_url = f"{jobs_url.rstrip('/')}/{task_id}"
    # The job id can carry the account email; logs and errors show it masked.
    shown_id = safe_job_id(task_id)
    request_options = {"params": params} if params else {}
    generation_progress.remote("useapi", shown_id)
    consecutive_failures = 0

    def still_running(cause: Exception | None = None):
        error = UseAPIUnconfirmedTaskError(
            "useapi.net job is still running after the configured local wait "
            f"timeout: id={shown_id}",
            task_id=task_id,
        )
        if cause is not None:
            raise error from cause
        raise error

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            still_running()

        phase_timeout = max(min(remaining / 2.0, 30.0), 0.001)
        response = None
        try:
            response = trace_http_call(
                "GET", requests.get,
                job_url,
                headers=headers,
                proxies=config.proxy,
                verify=_tls_verify(),
                timeout=(phase_timeout, phase_timeout),
                allow_redirects=False,
                **request_options,
            )
            status_code = _status_code(response)
            if 300 <= status_code < 400:
                location = getattr(response, "headers", {}).get("Location", "")
                raise UseAPIUnconfirmedTaskError(
                    "useapi.net polling returned an unexpected redirect; the "
                    "job state is unknown: "
                    f"HTTP {status_code}, location={_redact_secret(location, api_key)}",
                    task_id=task_id,
                )
            if status_code in RETRYABLE_STATUS_CODES:
                raise requests.exceptions.HTTPError(
                    f"HTTP {status_code}", response=response
                )
            if service == KLING and status_code == 404:
                # Kling's documented 404 for a task: deleted, failed on
                # moderation, or not enough credits.  It will not succeed.
                body = {
                    "status_name": "failed",
                    "error": _response_error(response, api_key),
                }
            elif not 200 <= status_code < 300:
                raise UseAPIUnconfirmedTaskError(
                    "useapi.net job status is unknown: "
                    f"http_status={status_code}, "
                    f"detail={_response_error(response, api_key)}",
                    task_id=task_id,
                )
            else:
                body = response.json()
            if not isinstance(body, dict):
                raise UseAPIUnconfirmedTaskError(
                    "useapi.net job status response is malformed", task_id=task_id
                )
        except UseAPIUnconfirmedTaskError:
            raise
        except Exception as exc:
            if not _is_retryable_error(exc):
                raise UseAPIUnconfirmedTaskError(
                    "useapi.net polling failed and the job state is unknown: "
                    f"error={type(exc).__name__}, "
                    f"detail={_redact_secret(exc, api_key)}",
                    task_id=task_id,
                ) from exc

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                still_running(exc)
            consecutive_failures += 1
            generation_progress.remote("useapi", shown_id, retrying=True)
            if consecutive_failures > MAX_POLL_RETRIES:
                raise UseAPIUnconfirmedTaskError(
                    "useapi.net polling failed after retries; the job may still "
                    f"be running: id={shown_id}",
                    task_id=task_id,
                ) from exc
            failed_response = getattr(exc, "response", None)
            if failed_response is not None and _status_code(failed_response) == 429:
                delay = _retry_after_seconds(
                    failed_response, RETRY_BASE_SECONDS * consecutive_failures
                )
            else:
                delay = RETRY_BASE_SECONDS * consecutive_failures
            delay = min(delay, remaining, MAX_BUSY_RETRY_SECONDS)
            logger.warning(
                "useapi.net polling hit a transient error; checking the same job "
                f"again: id={shown_id}, attempt={consecutive_failures}/"
                f"{MAX_POLL_RETRIES}, retry_in={delay:.1f}s"
            )
            time.sleep(delay)
            continue

        consecutive_failures = 0
        status = _job_status(body, service)
        generation_progress.remote(
            "useapi", shown_id, _PROGRESS_STATUS.get(status, status)
        )
        wait = poll_interval
        if status in TERMINAL_SUCCESS_STATUSES:
            if _video_urls(body, service) or service != GOOGLE_FLOW:
                return body
            # A finished Google Flow video can be missing its signed URL for a
            # while; the job record fills it in on a later poll.
            logger.warning(
                "useapi.net job completed but its video link is not ready yet; "
                f"checking again: id={shown_id}"
            )
            wait = max(poll_interval, MISSING_URL_POLL_SECONDS)
        elif status in TERMINAL_FAILURE_STATUSES:
            logger.error(
                "useapi.net job did not produce a video: "
                f"id={shown_id}, status={status}, "
                f"detail={_payload_error(body, 200, api_key)}"
            )
            return None
        elif status not in ACTIVE_STATUSES:
            raise UseAPIUnconfirmedTaskError(
                f"useapi.net returned an unknown job status: id={shown_id}, "
                f"status={status!r}",
                task_id=task_id,
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if status in TERMINAL_SUCCESS_STATUSES:
                return body
            still_running()
        time.sleep(min(wait, remaining))

