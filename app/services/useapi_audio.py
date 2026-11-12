"""useapi.net voice-over client: Kling text-to-speech and Google Vids voices.

useapi.net is a third-party API that runs requests on accounts the user
connects to it.  Kling text-to-speech runs on the user's Kling account and is
free and unlimited on every Kling plan, including the free one.  Google Vids
speech runs on the user's Google account and uses one of the plan's monthly
speech uses per request.  The same token also drives the Google Flow Music
background music source (``useapi_flowmusic``).

The protocol follows the useapi.net video source: a ``429`` (every connected
account is busy, nothing was started) waits and submits again, while a
request that may already have been accepted is never submitted twice.
"""

from __future__ import annotations

import math
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, quote_plus

import requests
from loguru import logger

from app.config import config
from app.utils.request_logging import trace_http_call


DEFAULT_BASE_URL = "https://api.useapi.net/v1"
# useapi.net counts integrations by User-Agent; keep it on every API request.
USER_AGENT = "MoneyPrinterTurbo-useapi/1.0"
TOKEN_URL = (
    "https://useapi.net/docs/start-here/setup-useapi"
    "?utm_source=moneyprinterturbo&utm_medium=referral"
    "&utm_campaign=mpt-integration"
)
KLING_TTS_URL = f"{DEFAULT_BASE_URL}/kling/tts/create"
KLING_VOICES_URL = f"{DEFAULT_BASE_URL}/kling/tts/voices"
VIDS_SPEECH_URL = f"{DEFAULT_BASE_URL}/google-vids/speech"
VIDS_JOBS_URL = f"{DEFAULT_BASE_URL}/google-vids/jobs"
VIDS_MEDIA_URL = f"{DEFAULT_BASE_URL}/google-vids/media"

# Kling reads up to 5 minutes of speech per request.  Scripts are split at
# sentence boundaries so each request's estimated speech stays well below it.
KLING_TTS_MAX_SPEECH_SECONDS = 300
KLING_TTS_CHUNK_SECONDS = 240
KLING_TTS_MIN_SPEED = 0.8
KLING_TTS_MAX_SPEED = 2.0
# Google Vids reads 1 to 2500 characters per request; each request uses one
# monthly speech use, so chunks are packed as full as the limit allows.
VIDS_SPEECH_MAX_CHARS = 2500
# The 30 Gemini voices Google Vids offers, in the order the Google Vids editor shows
# them: (Google Vids name, Google voice id, Google's style label).  GET /voices
# returns this fixed list; it needs no token.
VIDS_VOICES = (
    ("Nyla", "Achernar", "Soft"),
    ("Holt", "Charon", "Informative"),
    ("Knox", "Algieba", "Smooth"),
    ("Tyra", "Erinome", "Clear"),
    ("Paz", "Enceladus", "Breathy"),
    ("Umi", "Sadaltager", "Knowledgeable"),
    ("Jett", "Algenib", "Gravelly"),
    ("Elio", "Achird", "Friendly"),
    ("Lani", "Callirrhoe", "Easy-going"),
    ("Zeno", "Alnilam", "Firm"),
    ("Kaci", "Autonoe", "Bright"),
    ("Tova", "Aoede", "Breezy"),
    ("Lora", "Despina", "Smooth"),
    ("Fola", "Sulafat", "Warm"),
    ("Yori", "Zubenelgenubi", "Casual"),
    ("Iro", "Rasalgethi", "Informative"),
    ("Fira", "Leda", "Youthful"),
    ("Nyx", "Iapetus", "Clear"),
    ("Neo", "Puck", "Upbeat"),
    ("Baya", "Umbriel", "Easy-going"),
    ("Peli", "Laomedeia", "Upbeat"),
    ("Jacy", "Schedar", "Even"),
    ("Cale", "Orus", "Firm"),
    ("Orla", "Vindemiatrix", "Gentle"),
    ("Dori", "Sadachbia", "Lively"),
    ("Sani", "Zephyr", "Bright"),
    ("Kero", "Fenrir", "Excitable"),
    ("Saro", "Gacrux", "Mature"),
    ("Lito", "Kore", "Firm"),
    ("Vira", "Pulcherrima", "Forward"),
)
DEFAULT_VIDS_VOICE = "Holt"

MAX_AUDIO_BYTES = 50 * 1024 * 1024
DOWNLOAD_ATTEMPTS = 3
DEFAULT_POLL_INTERVAL_SECONDS = 10.0
DEFAULT_RUN_TIMEOUT_SECONDS = 1800.0
# Kling answers a whole script in one response; Google Vids answers a sync
# request within about 100 seconds (202 after that).
SUBMIT_TIMEOUT = (30, 600)
READ_TIMEOUT = (30, 60)
MAX_SUBMIT_BUSY_RETRIES = 5
DEFAULT_BUSY_RETRY_SECONDS = 30.0
MAX_BUSY_RETRY_SECONDS = 300.0
MAX_POLL_RETRIES = 5
RETRY_BASE_SECONDS = 1.0
MAX_ERROR_TEXT_LENGTH = 500
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
# 596 is useapi.net's own "account needs to be re-added" answer, sent before
# anything starts, so it is a definite rejection.
SESSION_ERROR_STATUS = 596
ACTIVE_STATUSES = frozenset({"created", "started", "queued", "pending", "processing"})
FAILURE_STATUSES = frozenset({"failed", "cancelled", "canceled", "expired"})

_SENTENCE_END = re.compile(r"[.!?;。！？；…]+[\"'”’」』)\]]*\s*|\n+")
_CLAUSE_END = re.compile(r"[,，、:：]\s*|\s+")
# useapi.net job, media and clip ids embed the connected account's email, for
# example "j1-u12345-email:user@example.com-bot:google-vids", also URL-encoded
# ("%40") inside request paths.  It is masked everywhere it could be shown.
_EMAIL_ADDRESS = re.compile(
    r"[A-Za-z0-9._%+-]+(?:@|%40)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}",
    re.IGNORECASE,
)


def safe_text(value: Any) -> str:
    """``value`` as text with every email address replaced by ``***``."""
    return _EMAIL_ADDRESS.sub("***", str(value or ""))


def safe_job_id(job_id: Any) -> str:
    """A job, media or clip id fit for logs and messages (email masked).

    The raw id is used only in requests to useapi.net.
    """
    return safe_text(job_id)


class UseAPIAudioError(RuntimeError):
    """Deterministic configuration, request, or response error.

    The message and job id are masked, so an account email in a job id or an
    API error never reaches logs, task state or the WebUI.
    """

    def __init__(self, message: str, job_id: str = "", status_code: int = 0):
        super().__init__(safe_text(message))
        self.job_id = safe_job_id(job_id)
        self.status_code = status_code


class UseAPIAudioUnconfirmedError(UseAPIAudioError):
    """The request may have been accepted, but its result cannot be confirmed."""


def get_api_key(settings: Mapping[str, Any] | None = None) -> str:
    """Read the configured useapi.net token, then ``USEAPI_TOKEN``."""
    settings = config.app if settings is None else settings
    configured = str(settings.get("useapi_api_token", "") or "").strip()
    return configured or os.getenv("USEAPI_TOKEN", "").strip()


def is_enabled(settings: Mapping[str, Any] | None = None) -> bool:
    return bool(get_api_key(settings))


def _bounded_float(key: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(config.app.get(key, default))
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return min(max(value, minimum), maximum)


def _tls_verify() -> bool:
    value = config.app.get("tls_verify", True)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


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
    return safe_text(text)[:MAX_ERROR_TEXT_LENGTH]


def payload_error(payload: Any, status_code: int, api_token: str) -> str:
    """The readable error of a useapi.net answer or failed job record."""
    if not isinstance(payload, dict):
        return f"HTTP {status_code}"
    error = payload.get("error")
    if isinstance(error, dict):
        detail = error.get("message") or error.get("code")
    else:
        detail = error or payload.get("message")
    return _redact_secret(detail or f"HTTP {status_code}", api_token)


def response_error(response: Any, api_token: str) -> str:
    try:
        payload = response.json()
    except Exception:
        return f"HTTP {_status_code(response)}"
    return payload_error(payload, _status_code(response), api_token)


def _retry_after_seconds(response: Any, default: float) -> float:
    """Read the wait a ``429`` asks for, from the header or the body."""
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
        if isinstance(payload, dict) and payload.get("retryAfterSec") is not None:
            try:
                seconds = float(payload["retryAfterSec"])
            except (TypeError, ValueError):
                seconds = None
    if seconds is None or not math.isfinite(seconds):
        seconds = default
    return min(max(seconds, 1.0), MAX_BUSY_RETRY_SECONDS)


def headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def require_api_key() -> str:
    api_token = get_api_key()
    if not api_token:
        raise UseAPIAudioError(
            "useapi.net requires an API token; create one at " + TOKEN_URL
        )
    return api_token


def path_segment(value: str) -> str:
    """URL-encode a job or media id for one path segment (ids hold ``:`` and ``@``)."""
    return quote(str(value or ""), safe="")


def post(url: str, payload: dict[str, Any], api_token: str, timeout=SUBMIT_TIMEOUT) -> Any:
    """POST once per attempt, waiting out ``429`` answers; return the response.

    A ``429`` means every connected account is busy and nothing was started,
    so posting again is safe.  An answer that may hide an accepted request
    raises :class:`UseAPIAudioUnconfirmedError` and is never posted again.
    """
    deadline = time.monotonic() + _bounded_float(
        "useapi_run_timeout", DEFAULT_RUN_TIMEOUT_SECONDS, 60.0, 7200.0
    )
    busy_attempts = 0
    while True:
        try:
            response = trace_http_call(
                "POST", requests.post,
                url,
                json=payload,
                headers=headers(api_token),
                proxies=config.proxy,
                verify=_tls_verify(),
                timeout=timeout,
                allow_redirects=False,
            )
        except Exception as exc:
            # A timeout or dropped connection after the request left may mean
            # useapi.net already accepted it.
            raise UseAPIAudioUnconfirmedError(
                "useapi.net request returned no response; it may already have "
                "been accepted: "
                f"error={type(exc).__name__}, detail={_redact_secret(exc, api_token)}"
            ) from exc

        status_code = _status_code(response)
        if status_code == 429:
            busy_attempts += 1
            delay = _retry_after_seconds(response, DEFAULT_BUSY_RETRY_SECONDS)
            remaining = deadline - time.monotonic()
            if busy_attempts > MAX_SUBMIT_BUSY_RETRIES or delay >= remaining:
                raise UseAPIAudioError(
                    "useapi.net accounts are busy; nothing was started: "
                    f"HTTP 429, {response_error(response, api_token)}"
                )
            logger.warning(
                "useapi.net accounts are busy; submitting again after a pause: "
                f"attempt={busy_attempts}/{MAX_SUBMIT_BUSY_RETRIES}, "
                f"retry_in={delay:.0f}s, detail={response_error(response, api_token)}"
            )
            time.sleep(delay)
            continue
        if 300 <= status_code < 400:
            raise UseAPIAudioUnconfirmedError(
                "useapi.net returned an unexpected redirect; the request state "
                f"is unknown: HTTP {status_code}"
            )
        return response


def check_submission(response: Any, api_token: str, what: str) -> dict[str, Any]:
    """Return the JSON body of an accepted submission, or raise."""
    status_code = _status_code(response)
    if status_code >= 500 and status_code != SESSION_ERROR_STATUS:
        # Kling also answers moderation with 500; its docs say a real server
        # error cannot be told apart from it, so the state stays unknown.
        raise UseAPIAudioUnconfirmedError(
            f"useapi.net {what} failed with HTTP {status_code}; it may already "
            f"have been accepted: {response_error(response, api_token)}"
        )
    if not 200 <= status_code < 300:
        raise UseAPIAudioError(
            f"useapi.net {what} request rejected: HTTP {status_code}, "
            f"{response_error(response, api_token)}",
            status_code=status_code,
        )
    try:
        body = response.json()
    except Exception as exc:
        raise UseAPIAudioUnconfirmedError(
            f"useapi.net {what} returned an unreadable response: "
            f"error={type(exc).__name__}"
        ) from exc
    if not isinstance(body, dict):
        raise UseAPIAudioUnconfirmedError(
            f"useapi.net {what} returned an unexpected response"
        )
    return body


def get_json(url: str, api_token: str, params: dict[str, str] | None = None) -> Any:
    """GET a read-only useapi.net resource, retrying transient failures."""
    last_error = ""
    for attempt in range(1, MAX_POLL_RETRIES + 1):
        response = None
        try:
            response = trace_http_call(
                "GET", requests.get,
                url,
                params=params,
                headers=headers(api_token),
                proxies=config.proxy,
                verify=_tls_verify(),
                timeout=READ_TIMEOUT,
                allow_redirects=False,
            )
            status_code = _status_code(response)
            if 200 <= status_code < 300:
                return response.json()
            last_error = f"HTTP {status_code}, {response_error(response, api_token)}"
            if status_code not in RETRYABLE_STATUS_CODES:
                raise UseAPIAudioError(
                    f"useapi.net request rejected: {last_error}",
                    status_code=status_code,
                )
            delay = (
                _retry_after_seconds(response, RETRY_BASE_SECONDS * attempt)
                if status_code == 429
                else RETRY_BASE_SECONDS * attempt
            )
        except UseAPIAudioError:
            raise
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_error = f"error={type(exc).__name__}"
            delay = RETRY_BASE_SECONDS * attempt
        except ValueError as exc:
            raise UseAPIAudioError(
                "useapi.net returned an unreadable response"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise UseAPIAudioError(
                f"useapi.net request failed: error={type(exc).__name__}, "
                f"detail={_redact_secret(exc, api_token)}"
            ) from exc
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
        if attempt < MAX_POLL_RETRIES:
            time.sleep(delay)
    raise UseAPIAudioError(f"useapi.net request failed after retries: {last_error}")


def wait_for_job(job_url: str, api_token: str, job_id: str) -> dict[str, Any] | None:
    """Poll a job record until it completes (returned) or fails (``None``)."""
    deadline = time.monotonic() + _bounded_float(
        "useapi_run_timeout", DEFAULT_RUN_TIMEOUT_SECONDS, 60.0, 7200.0
    )
    poll_interval = _bounded_float(
        "useapi_poll_interval", DEFAULT_POLL_INTERVAL_SECONDS, 1.0, 60.0
    )
    consecutive_failures = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise UseAPIAudioUnconfirmedError(
                "useapi.net job is still running after the configured local wait "
                f"timeout: id={safe_job_id(job_id)}",
                job_id=job_id,
            )
        phase_timeout = max(min(remaining / 2.0, 30.0), 0.001)
        response = None
        try:
            response = trace_http_call(
                "GET", requests.get,
                job_url,
                headers=headers(api_token),
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
                raise UseAPIAudioUnconfirmedError(
                    "useapi.net job status is unknown: "
                    f"HTTP {status_code}, {response_error(response, api_token)}",
                    job_id=job_id,
                )
            body = response.json()
            if not isinstance(body, dict):
                raise UseAPIAudioUnconfirmedError(
                    "useapi.net job status response is malformed", job_id=job_id
                )
        except UseAPIAudioUnconfirmedError:
            raise
        except Exception as exc:
            retryable = isinstance(
                exc,
                (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.HTTPError,
                ),
            )
            consecutive_failures += 1
            if not retryable or consecutive_failures > MAX_POLL_RETRIES:
                raise UseAPIAudioUnconfirmedError(
                    "useapi.net polling failed and the job state is unknown: "
                    f"id={safe_job_id(job_id)}, error={type(exc).__name__}",
                    job_id=job_id,
                ) from exc
            failed_response = getattr(exc, "response", None)
            if failed_response is not None and _status_code(failed_response) == 429:
                delay = _retry_after_seconds(
                    failed_response, RETRY_BASE_SECONDS * consecutive_failures
                )
            else:
                delay = RETRY_BASE_SECONDS * consecutive_failures
            logger.warning(
                "useapi.net polling hit a transient error; checking the same job "
                f"again: id={safe_job_id(job_id)}, attempt={consecutive_failures}/{MAX_POLL_RETRIES}"
            )
            time.sleep(min(delay, max(deadline - time.monotonic(), 0)))
            continue
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

        consecutive_failures = 0
        status = str(body.get("status") or "").strip().lower()
        if status == "completed":
            return body
        if status in FAILURE_STATUSES:
            logger.error(
                "useapi.net job did not produce audio: "
                f"id={safe_job_id(job_id)}, status={status}, "
                f"detail={payload_error(body, 200, api_token)}"
            )
            return None
        if status not in ACTIVE_STATUSES:
            raise UseAPIAudioUnconfirmedError(
                f"useapi.net returned an unknown job status: id={safe_job_id(job_id)}, "
                f"status={status!r}",
                job_id=job_id,
            )
        time.sleep(min(poll_interval, max(deadline - time.monotonic(), 0)))


def download(url: str, output_path: str, api_token: str = "", job_id: str = "") -> int:
    """Download a finished file to ``output_path``, retrying the same link.

    The token is sent only to useapi.net itself; signed provider links never
    see it.  The file is written beside the destination and moved into place
    only when complete.
    """
    request_headers = {"User-Agent": USER_AGENT}
    if url.startswith(DEFAULT_BASE_URL + "/"):
        if not api_token:
            raise UseAPIAudioError("useapi.net download requires an API token")
        request_headers["Authorization"] = f"Bearer {api_token}"
    output_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(output_dir, exist_ok=True)
    failure = "no download attempt was made"
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        response = None
        descriptor, temp_path = tempfile.mkstemp(
            prefix=".useapi-audio-",
            suffix=os.path.splitext(output_path)[1],
            dir=output_dir,
        )
        os.close(descriptor)
        try:
            response = trace_http_call(
                "GET", requests.get,
                url,
                headers=request_headers,
                proxies=config.proxy,
                verify=_tls_verify(),
                timeout=(30, 120),
                stream=True,
                allow_redirects=False,
            )
            status_code = _status_code(response)
            if status_code == 200:
                size = 0
                with open(temp_path, "wb") as output:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > MAX_AUDIO_BYTES:
                            raise UseAPIAudioError(
                                f"useapi.net audio exceeds {MAX_AUDIO_BYTES} bytes: "
                                f"id={safe_job_id(job_id) or 'unknown'}",
                                job_id=job_id,
                            )
                        output.write(chunk)
                if size:
                    os.replace(temp_path, output_path)
                    return size
                failure = "empty download"
            else:
                failure = f"HTTP {status_code}"
        except UseAPIAudioError:
            raise
        except Exception as exc:
            failure = f"error={type(exc).__name__}"
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
        if attempt < DOWNLOAD_ATTEMPTS:
            logger.warning(
                "useapi.net audio download failed, retrying the same link: "
                f"id={safe_job_id(job_id) or 'unknown'}, attempt={attempt}/{DOWNLOAD_ATTEMPTS}, "
                f"{failure}"
            )
            time.sleep(RETRY_BASE_SECONDS * attempt)
    raise UseAPIAudioError(
        f"useapi.net audio could not be downloaded: id={safe_job_id(job_id) or 'unknown'}, {failure}",
        job_id=job_id,
    )


def _pieces(text: str, boundary: re.Pattern) -> list[str]:
    """Split ``text`` after each boundary match, keeping every character."""
    pieces = []
    start = 0
    for match in boundary.finditer(text):
        if match.end() > start:
            pieces.append(text[start:match.end()])
            start = match.end()
    if start < len(text):
        pieces.append(text[start:])
    return pieces


def split_script(text: str, fits: Callable[[str], bool]) -> list[str]:
    """Split ``text`` into as few chunks as possible that each satisfy ``fits``.

    Chunks end at sentence boundaries; a sentence too long on its own is split
    at clause boundaries or spaces, and as a last resort between characters.
    The chunks keep the script order and, joined, read as the whole script.
    """
    text = str(text or "").strip()
    if not text:
        return []
    if fits(text):
        return [text]

    units: list[str] = []
    for sentence in _pieces(text, _SENTENCE_END):
        if fits(sentence.strip()):
            units.append(sentence)
            continue
        for clause in _pieces(sentence, _CLAUSE_END):
            if fits(clause.strip()):
                units.append(clause)
                continue
            piece = ""
            for char in clause:
                if piece and not fits((piece + char).strip()):
                    units.append(piece)
                    piece = ""
                piece += char
            if piece:
                units.append(piece)

    chunks: list[str] = []
    current = ""
    for unit in units:
        if current and not fits((current + unit).strip()):
            chunks.append(current.strip())
            current = ""
        current += unit
    if current.strip():
        chunks.append(current.strip())
    return [chunk for chunk in chunks if chunk]


def kling_voices(api_token: str | None = None) -> list[dict[str, Any]]:
    """List Kling's text-to-speech voices: speaker id, name and emotions."""
    api_token = api_token or require_api_key()
    body = get_json(KLING_VOICES_URL, api_token)
    entries = body.get("ttsList") if isinstance(body, dict) else None
    if not isinstance(entries, list):
        raise UseAPIAudioError("useapi.net returned no Kling voice list")
    voices = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        speaker_id = str(entry.get("speakerId") or "").strip()
        if not speaker_id or speaker_id in seen or ":" in speaker_id:
            continue
        seen.add(speaker_id)
        emotions = [
            str(item.get("key")).strip()
            for item in entry.get("emotions") or []
            if isinstance(item, dict) and item.get("enable") and item.get("key")
        ]
        voices.append(
            {
                "speaker_id": speaker_id,
                "name": str(entry.get("name") or speaker_id).strip(),
                "emotions": emotions,
            }
        )
    return voices


def kling_speed(voice_rate: Any) -> float:
    """Clamp MPT's speed to the 0.8-2.0 range Kling accepts."""
    try:
        speed = float(voice_rate)
    except (TypeError, ValueError, OverflowError):
        return 1.0
    if not math.isfinite(speed) or speed <= 0:
        return 1.0
    return round(min(max(speed, KLING_TTS_MIN_SPEED), KLING_TTS_MAX_SPEED), 2)


def kling_tts(
    text: str,
    speaker_id: str,
    output_path: str,
    speed: float = 1.0,
    emotion: str = "",
) -> None:
    """Read ``text`` with a Kling voice and save the MP3 to ``output_path``."""
    api_token = require_api_key()
    text = str(text or "").strip()
    speaker_id = str(speaker_id or "").strip()
    if not text or not speaker_id:
        raise UseAPIAudioError("Kling text-to-speech needs text and a voice")
    payload: dict[str, Any] = {
        "speakerId": speaker_id,
        "text": text,
        "speed": kling_speed(speed),
    }
    emotion = str(emotion or "").strip()
    if emotion:
        payload["emotion"] = emotion
    logger.info(
        "start useapi.net Kling text-to-speech: "
        f"voice={speaker_id}, speed={payload['speed']}, characters={len(text)}"
    )
    response = post(KLING_TTS_URL, payload, api_token)
    body = check_submission(response, api_token, "Kling text-to-speech")
    status = str(body.get("status_name") or "").strip().lower()
    audio_url = body.get("resource")
    if status == "failed" or body.get("error"):
        raise UseAPIAudioError(
            "useapi.net Kling text-to-speech failed: "
            f"{payload_error(body, 200, api_token)}"
        )
    if not (isinstance(audio_url, str) and audio_url.startswith(("http://", "https://"))):
        raise UseAPIAudioUnconfirmedError(
            "useapi.net Kling text-to-speech returned no audio link"
        )
    download(audio_url, output_path)


def vids_voice_name(voice: str) -> str:
    """The Google Vids name for a Google Vids name or Google voice id, case-insensitive."""
    wanted = str(voice or "").strip().lower()
    for name, voice_id, _style in VIDS_VOICES:
        if wanted in {name.lower(), voice_id.lower()}:
            return name
    return ""


def vids_speech(text: str, voice: str, output_path: str) -> None:
    """Read ``text`` with a Google Vids voice and save the WAV to ``output_path``."""
    api_token = require_api_key()
    text = str(text or "").strip()
    if not text:
        raise UseAPIAudioError("Google Vids speech needs text")
    if len(text) > VIDS_SPEECH_MAX_CHARS:
        raise UseAPIAudioError(
            f"Google Vids speech reads up to {VIDS_SPEECH_MAX_CHARS} characters "
            "per request"
        )
    name = vids_voice_name(voice)
    if not name:
        raise UseAPIAudioError(f"Unknown Google Vids voice: {voice}")
    logger.info(
        "start useapi.net Google Vids speech: "
        f"voice={name}, characters={len(text)}"
    )
    response = post(VIDS_SPEECH_URL, {"script": text, "voice": name}, api_token)
    body = check_submission(response, api_token, "Google Vids speech")
    job_id = str(body.get("jobid") or "").strip()
    status = str(body.get("status") or "").strip().lower()
    if status != "completed":
        if status in FAILURE_STATUSES:
            raise UseAPIAudioError(
                "useapi.net Google Vids speech failed: "
                f"{payload_error(body, 200, api_token)}",
                job_id=job_id,
            )
        if not job_id:
            raise UseAPIAudioUnconfirmedError(
                "useapi.net accepted the speech request without a job id"
            )
        # A sync request still running after about 100 seconds answers 202.
        body = wait_for_job(f"{VIDS_JOBS_URL}/{path_segment(job_id)}", api_token, job_id)
        if body is None:
            raise UseAPIAudioError(
                f"useapi.net Google Vids speech job failed: id={safe_job_id(job_id)}",
                job_id=job_id,
            )
    result = body.get("result") if isinstance(body.get("result"), dict) else {}
    media_id = str(result.get("mediaId") or "").strip()
    if not media_id:
        raise UseAPIAudioUnconfirmedError(
            f"useapi.net Google Vids speech completed without audio: id={safe_job_id(job_id)}",
            job_id=job_id,
        )
    # Google Vids files are temporary at Google, so download right away.
    download(
        f"{VIDS_MEDIA_URL}/{path_segment(media_id)}",
        output_path,
        api_token=api_token,
        job_id=job_id,
    )
