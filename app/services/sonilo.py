import base64
import binascii
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import requests
from loguru import logger

from app.utils.request_logging import trace_http_call

from app.config import config
from app.services import bgm as bgm_service
from app.utils import utils


DEFAULT_BASE_URL = "https://api.sonilo.com"
VIDEO_TO_MUSIC_PATH = "/v1/video-to-music"
SERVICES_PATH = "/v1/account/services"
MAX_VIDEO_DURATION_SECONDS = 360
MAX_PROMPT_LENGTH = 2000
MAX_PROXY_BYTES = 300 * 1024 * 1024
MAX_GENERATED_AUDIO_BYTES = 30 * 1024 * 1024
MAX_ERROR_BODY_BYTES = 500
# One event can hold the full permitted audio as base64, plus JSON metadata.
MAX_STREAM_EVENT_BYTES = 4 * ((MAX_GENERATED_AUDIO_BYTES + 2) // 3) + 64 * 1024
_STREAM_READ_BYTES = 64 * 1024
VIDEO_TO_MUSIC_SERVICE_ID = "video_to_music"


class SoniloError(RuntimeError):
    """A Sonilo request, response protocol or generated audio validation failed."""


def get_api_key() -> str:
    """Prefer the config saved by the WebUI; allow the environment variable when not configured."""
    configured_key = str(config.app.get("sonilo_api_key", "") or "").strip()
    return configured_key or os.getenv("SONILO_API_KEY", "").strip()


def is_enabled() -> bool:
    return bool(get_api_key())


def _base_url() -> str:
    return str(
        config.app.get("sonilo_base_url", DEFAULT_BASE_URL) or DEFAULT_BASE_URL
    ).rstrip(
        "/"
    )


def _request_timeout() -> tuple[int, int]:
    """Clamp the config value range, so infinity or negative values can't make requests hang forever or fail immediately."""
    raw_timeout = config.app.get("sonilo_timeout", 600)
    try:
        read_timeout = float(raw_timeout)
    except (TypeError, ValueError):
        read_timeout = 600
    if not math.isfinite(read_timeout) or read_timeout <= 0:
        read_timeout = 600
    # Requests doesn't accept a 0-second read timeout. Rounding up keeps the meaning of fractional config values and also
    # prevents 0.1~0.9 from being truncated to 0 by int() and raising a ValueError that bypasses the Sonilo degradation path.
    return 15, max(1, math.ceil(min(read_timeout, 1800)))


def _normalize_service_id(service_id: str) -> str:
    """
    Normalize the Sonilo service identifier to the underscore format used inside the project.

    On 2026-07-14 the actual API returned ``video_to_music``, but the public docs example the same day used
    ``video-to-music``. The difference is only the word separator, so the format is normalized at the third-party protocol boundary,
    so the UI connection test doesn't falsely report failure while the provider's docs and production responses temporarily disagree.
    """
    return service_id.strip().lower().replace("-", "_")


def _safe_response_error(response: requests.Response) -> str:
    """Read only a limited amount of the third-party error body, so abnormal responses can't exhaust memory or pollute task logs."""
    try:
        body_bytes = next(
            response.iter_content(chunk_size=MAX_ERROR_BODY_BYTES),
            b"",
        )
    except requests.RequestException:
        body_bytes = b""
    if isinstance(body_bytes, bytes):
        try:
            body = body_bytes.decode(
                response.encoding or "utf-8",
                errors="replace",
            )
        except LookupError:
            # response.encoding comes straight from the charset declared upstream, and an unknown value (e.g.
            # charset=unknown-charset) makes codecs raise LookupError, while errors
            # only affects UnicodeDecodeError. The old response.text fell back to
            # UTF-8 internally; keep the same behavior here, so this exception doesn't bypass the caller's Sonilo degradation path.
            body = body_bytes.decode("utf-8", errors="replace")
    else:
        body = str(body_bytes)
    body = body.strip().replace("\n", " ")[:MAX_ERROR_BODY_BYTES]
    return body or response.reason or "request failed"


def test_connection() -> dict[str, Any]:
    """
    Validate the API Key using the service list endpoint, which doesn't consume music credits.

    The raw JSON is returned so the UI can show available services, but the Key or request headers are never logged.
    """
    api_key = get_api_key()
    if not api_key:
        raise SoniloError("Sonilo API key is required")
    try:
        with trace_http_call(
            "GET", requests.get,
            f"{_base_url()}{SERVICES_PATH}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=(15, 30),
            stream=True,
            allow_redirects=False,
        ) as response:
            if 300 <= response.status_code < 400:
                raise SoniloError(
                    "Sonilo connection check returned a redirect; "
                    "the API key was not forwarded"
                )
            if not response.ok:
                raise SoniloError(
                    f"Sonilo connection failed ({response.status_code}): "
                    f"{_safe_response_error(response)}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise SoniloError(
                    "Sonilo returned an invalid service response"
                ) from exc
    except requests.RequestException as exc:
        raise SoniloError(f"failed to connect to Sonilo: {exc}") from exc
    if not isinstance(payload, dict):
        raise SoniloError("Sonilo returned an unexpected service response")
    available_services = payload.get("available_services")
    if not isinstance(available_services, list) or not all(
        isinstance(service_id, str) for service_id in available_services
    ):
        raise SoniloError("Sonilo returned an invalid service list")
    normalized_services = {
        _normalize_service_id(service_id) for service_id in available_services
    }
    if VIDEO_TO_MUSIC_SERVICE_ID not in normalized_services:
        raise SoniloError("Sonilo video-to-music service is not available for this key")
    logger.info("Sonilo connection test succeeded")
    return payload


def _remove_file(file_path: str) -> None:
    """Do our best to clean up Sonilo intermediate files, without overriding the original exception the caller is handling."""
    if not file_path or not os.path.exists(file_path):
        return
    try:
        os.remove(file_path)
    except OSError as exc:
        logger.warning(
            f"failed to remove Sonilo temporary file: path={file_path}, error={exc}"
        )


def _create_video_proxy(video_path: str) -> str:
    """
    Generate a soundless H.264 proxy video with a longest side of 1280 pixels.

    Sonilo only needs to analyze the rhythm and content of the visuals; uploading the original HD video would add waiting time and traffic
    with no real benefit to generation quality. The proxy file lives in the same directory as the input file and is cleaned up after the task.
    """
    descriptor, proxy_path = tempfile.mkstemp(
        prefix=".sonilo-proxy-",
        suffix=".mp4",
        dir=os.path.dirname(os.path.abspath(video_path)),
    )
    os.close(descriptor)
    command = [
        utils.get_ffmpeg_binary(),
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-i",
        video_path,
        "-vf",
        (
            "scale=w=1280:h=1280:force_original_aspect_ratio=decrease:"
            "force_divisible_by=2"
        ),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "30",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-fs",
        str(MAX_PROXY_BYTES),
        proxy_path,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        _remove_file(proxy_path)
        raise SoniloError("Sonilo video proxy generation timed out") from exc
    except OSError as exc:
        _remove_file(proxy_path)
        raise SoniloError("failed to run FFmpeg for Sonilo video proxy") from exc
    if result.returncode != 0:
        _remove_file(proxy_path)
        detail = (result.stderr or "").strip().replace("\n", " ")[-500:]
        raise SoniloError(f"failed to generate Sonilo video proxy: {detail}")
    proxy_size = os.path.getsize(proxy_path) if os.path.isfile(proxy_path) else 0
    if proxy_size <= 0 or proxy_size > MAX_PROXY_BYTES:
        _remove_file(proxy_path)
        raise SoniloError("Sonilo video proxy is empty or exceeds the 300 MB limit")
    logger.info(
        f"Sonilo video proxy prepared: source={video_path}, size={proxy_size} bytes"
    )
    return proxy_path


def _iter_bounded_events(response: requests.Response):
    """Read NDJSON without Requests' unbounded unterminated-line buffer."""
    pending = bytearray()
    for chunk in response.iter_content(chunk_size=_STREAM_READ_BYTES):
        if not chunk:
            continue
        # Split only the bounded transport chunk; never concatenate an
        # oversized line before checking its accumulated size.
        pieces = chunk.split(b"\n")
        for index, piece in enumerate(pieces):
            if len(pending) + len(piece) > MAX_STREAM_EVENT_BYTES:
                raise SoniloError("Sonilo streaming event exceeds the size limit")
            pending.extend(piece)
            if index < len(pieces) - 1:
                if pending:
                    yield bytes(pending).rstrip(b"\r")
                pending.clear()
    if pending:
        yield bytes(pending).rstrip(b"\r")


def _parse_event(raw_line: bytes) -> dict[str, Any]:
    """Strictly parse a single NDJSON line, never silently ignoring truncated or non-object responses."""
    try:
        event = json.loads(raw_line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SoniloError("Sonilo returned malformed streaming data") from exc
    if not isinstance(event, dict) or not isinstance(event.get("type"), str):
        raise SoniloError("Sonilo returned an invalid streaming event")
    return event


def _stream_audio(response: requests.Response, temp_audio_path: str) -> tuple[int, str]:
    """
    Write the first music stream to a temp file in event order, with a maximum size.

    The API may return several candidate streams at once; the product currently only needs one BGM, so
    stream_index=0 is always chosen. It's only published after a complete event is received and FFmpeg fully decodes it.
    """
    total_bytes = 0
    title = ""
    completed = False
    with open(temp_audio_path, "wb") as output:
        for raw_line in _iter_bounded_events(response):
            if not raw_line:
                continue
            event = _parse_event(raw_line)
            event_type = event["type"]
            if event_type == "error":
                message = str(
                    event.get("message") or event.get("error") or "unknown error"
                )
                raise SoniloError(f"Sonilo generation failed: {message}")
            if event_type == "title":
                title = str(event.get("title") or event.get("data") or "")[:200]
                continue
            if event_type == "complete":
                completed = True
                break
            if event_type != "audio_chunk":
                logger.debug(f"ignoring unsupported Sonilo event: type={event_type}")
                continue

            stream_index = event.get("stream_index", 0)
            if stream_index != 0:
                continue
            encoded_chunk = event.get("data") or event.get("audio")
            if not isinstance(encoded_chunk, str) or not encoded_chunk:
                raise SoniloError("Sonilo returned an empty audio chunk")
            try:
                chunk = base64.b64decode(encoded_chunk, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise SoniloError("Sonilo returned an invalid audio chunk") from exc
            if not chunk:
                raise SoniloError("Sonilo returned an empty audio chunk")
            total_bytes += len(chunk)
            if total_bytes > MAX_GENERATED_AUDIO_BYTES:
                raise SoniloError("Sonilo audio exceeds the 30 MB limit")
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())

    if not completed:
        raise SoniloError("Sonilo stream ended before completion")
    if total_bytes <= 0:
        raise SoniloError("Sonilo returned no audio data")
    return total_bytes, title


def _request_bgm(video_path: str, output_path: str, prompt: str) -> str:
    """Request music and save it atomically once the full protocol and audio validation pass."""
    output_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(output_dir, exist_ok=True)
    descriptor, temp_audio_path = tempfile.mkstemp(
        prefix=".sonilo-audio-",
        suffix=Path(output_path).suffix or ".m4a",
        dir=output_dir,
    )
    os.close(descriptor)
    try:
        logger.info(
            f"requesting Sonilo background music: video={video_path}, "
            f"prompt_provided={bool(prompt)}"
        )
        try:
            with open(video_path, "rb") as video_file:
                response = trace_http_call(
                    "POST", requests.post,
                    f"{_base_url()}{VIDEO_TO_MUSIC_PATH}",
                    headers={"Authorization": f"Bearer {get_api_key()}"},
                    files={"video": (Path(video_path).name, video_file, "video/mp4")},
                    data={"prompt": prompt} if prompt else None,
                    stream=True,
                    timeout=_request_timeout(),
                    allow_redirects=False,
                )
                with response:
                    if 300 <= response.status_code < 400:
                        raise SoniloError(
                            "Sonilo generation returned a redirect; "
                            "the video and API key were not forwarded"
                        )
                    if not response.ok:
                        raise SoniloError(
                            f"Sonilo generation failed ({response.status_code}): "
                            f"{_safe_response_error(response)}"
                        )
                    total_bytes, title = _stream_audio(response, temp_audio_path)
        except requests.RequestException as exc:
            # A network interruption during iter_lines() is also a requests exception; catching only the
            # connection phase would let half an audio file make the task exit abnormally without degrading.
            raise SoniloError(f"failed to request Sonilo music: {exc}") from exc

        try:
            bgm_service.validate_audio_file(temp_audio_path, timeout_seconds=120)
        except (bgm_service.BgmUploadError, bgm_service.BgmServiceError) as exc:
            raise SoniloError("Sonilo returned audio that FFmpeg cannot decode") from exc
        os.replace(temp_audio_path, output_path)
        temp_audio_path = ""
        logger.info(
            f"Sonilo background music generated: output={output_path}, "
            f"size={total_bytes} bytes, title={title or '-'}"
        )
        return output_path
    finally:
        _remove_file(temp_audio_path)


def generate_bgm(
    video_path: str,
    output_path: str,
    video_duration: float,
    prompt: str = "",
) -> str:
    """Generate Sonilo background music matching the duration of one concatenated video."""
    if not get_api_key():
        raise SoniloError("Sonilo API key is required")
    if not os.path.isfile(video_path):
        raise SoniloError("Sonilo input video does not exist")
    try:
        duration = float(video_duration)
    except (TypeError, ValueError) as exc:
        raise SoniloError("Sonilo video duration is invalid") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise SoniloError("Sonilo video duration is invalid")
    if duration > MAX_VIDEO_DURATION_SECONDS:
        raise SoniloError("Sonilo supports videos up to 360 seconds")
    prompt = str(prompt or "").strip()
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise SoniloError("Sonilo music prompt exceeds 2000 characters")

    proxy_path = ""
    try:
        proxy_path = _create_video_proxy(video_path)
        return _request_bgm(proxy_path, output_path, prompt)
    except SoniloError:
        raise
    except OSError as exc:
        # The temp directory, proxy file and final atomic replace can all hit file system errors. Converting them uniformly to
        # SoniloError lets the task orchestration layer degrade to "no background music" as designed and keep the video.
        raise SoniloError(f"Sonilo local file operation failed: {exc}") from exc
    finally:
        _remove_file(proxy_path)
