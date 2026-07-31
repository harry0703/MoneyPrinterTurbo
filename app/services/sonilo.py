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
VIDEO_TO_MUSIC_SERVICE_ID = "video_to_music"


class SoniloError(RuntimeError):
    """Sonilo 요청, 응답 프로토콜, 생성 오디오 검증이 실패했음을 나타낸다."""


def get_api_key() -> str:
    """WebUI 가 저장한 설정을 우선 읽고, 설정이 없으면 환경 변수를 허용한다."""
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
    """설정 값의 범위를 제한해, 무한대나 음수 때문에 요청이 영원히 멈추거나 즉시 실패하지 않게 한다."""
    raw_timeout = config.app.get("sonilo_timeout", 600)
    try:
        read_timeout = float(raw_timeout)
    except (TypeError, ValueError):
        read_timeout = 600
    if not math.isfinite(read_timeout) or read_timeout <= 0:
        read_timeout = 600
    # Requests 는 0 초 읽기 타임아웃을 받지 않는다. 올림하면 소수 설정의 의미를 살리면서,
    # 0.1~0.9 가 int() 로 0 이 되어 Sonilo 기능 저하 경로를 타지 못한 채 ValueError 가
    # 발생하는 것도 막을 수 있다.
    return 15, max(1, math.ceil(min(read_timeout, 1800)))


def _normalize_service_id(service_id: str) -> str:
    """
    Sonilo 서비스 식별자를 프로젝트 내부에서 쓰는 밑줄 형식으로 통일한다.

    2026-07-14 기준 실제 엔드포인트는 ``video_to_music`` 을 반환하지만, 같은 날 공개 문서
    예시는 ``video-to-music`` 을 쓴다. 차이는 단어 구분자뿐이므로 외부 프로토콜 경계에서
    형식을 통일해, 제공자 문서와 운영 응답이 일시적으로 어긋날 때 UI 연결 테스트가
    실패로 오인되지 않게 한다.
    """
    return service_id.strip().lower().replace("-", "_")


def _safe_response_error(response: requests.Response) -> str:
    """짧은 응답 정보만 남긴다. 원인을 짚기 쉬우면서 오류 페이지가 로그를 더럽히지 않게 한다."""
    body = (response.text or "").strip().replace("\n", " ")[:500]
    return body or response.reason or "request failed"


def test_connection() -> dict[str, Any]:
    """
    배경음악 크레딧을 쓰지 않는 서비스 목록 엔드포인트로 API 키를 검증한다.

    원본 JSON 을 돌려줘 UI 가 사용 가능한 서비스를 보여 줄 수 있게 하되, 로그에는 키나
    요청 헤더를 절대 남기지 않는다.
    """
    api_key = get_api_key()
    if not api_key:
        raise SoniloError("Sonilo API key is required")
    try:
        response = requests.get(
            f"{_base_url()}{SERVICES_PATH}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=(15, 30),
        )
    except requests.RequestException as exc:
        raise SoniloError(f"failed to connect to Sonilo: {exc}") from exc
    if not response.ok:
        raise SoniloError(
            f"Sonilo connection failed ({response.status_code}): "
            f"{_safe_response_error(response)}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise SoniloError("Sonilo returned an invalid service response") from exc
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
    """Sonilo 중간 파일을 최대한 정리하되, 호출자가 처리 중인 원래 예외를 덮지 않는다."""
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
    오디오 트랙이 없고 긴 변이 1280 픽셀인 H.264 프록시 영상을 만든다.

    Sonilo 는 화면의 리듬과 내용만 분석하면 되므로, 원본 고화질 결과물을 올리면 대기 시간과
    트래픽만 늘고 생성 품질에는 실질적인 이득이 없다. 프록시 파일은 입력 파일과 같은
    디렉터리에 두고 작업이 끝나면 한꺼번에 정리한다.
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
        proxy_path,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
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


def _parse_event(raw_line: bytes) -> dict[str, Any]:
    """NDJSON 한 줄을 엄격하게 해석한다. 잘린 응답이나 객체가 아닌 응답을 조용히 넘기지 않는다."""
    try:
        event = json.loads(raw_line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SoniloError("Sonilo returned malformed streaming data") from exc
    if not isinstance(event, dict) or not isinstance(event.get("type"), str):
        raise SoniloError("Sonilo returned an invalid streaming event")
    return event


def _stream_audio(response: requests.Response, temp_audio_path: str) -> tuple[int, str]:
    """
    첫 번째 배경음악 스트림을 이벤트 순서대로 임시 파일에 쓰고 최대 크기를 제한한다.

    API 는 여러 후보 스트림을 동시에 반환할 수 있다. 현재 제품에는 BGM 한 개만 필요하므로
    stream_index=0 으로 고정한다. complete 이벤트를 받고 FFmpeg 로 완전히 디코딩된 뒤에만
    게시한다.
    """
    total_bytes = 0
    title = ""
    completed = False
    with open(temp_audio_path, "wb") as output:
        for raw_line in response.iter_lines():
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
    """배경음악을 요청하고, 프로토콜과 오디오 검증을 모두 통과한 뒤 원자적으로 저장한다."""
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
                response = requests.post(
                    f"{_base_url()}{VIDEO_TO_MUSIC_PATH}",
                    headers={"Authorization": f"Bearer {get_api_key()}"},
                    files={"video": (Path(video_path).name, video_file, "video/mp4")},
                    data={"prompt": prompt} if prompt else None,
                    stream=True,
                    timeout=_request_timeout(),
                )
                with response:
                    if not response.ok:
                        raise SoniloError(
                            f"Sonilo generation failed ({response.status_code}): "
                            f"{_safe_response_error(response)}"
                        )
                    total_bytes, title = _stream_audio(response, temp_audio_path)
        except requests.RequestException as exc:
            # iter_lines() 도중의 네트워크 중단도 requests 예외이므로, 연결 수립 단계만
            # 잡아서는 안 된다. 그러지 않으면 반쯤 받은 오디오 때문에 작업이 곧바로 예외로
            # 끝나고 기능 저하 경로를 타지 못한다.
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
    """이어붙인 영상 한 편에 길이가 맞는 Sonilo 배경음악을 생성한다."""
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
        # 임시 디렉터리, 프록시 파일, 마지막 원자적 교체 모두 파일 시스템 오류가 날 수 있다.
        # SoniloError 로 통일해 변환해야 작업 조율 계층이 설계대로 '배경음악 없음' 으로
        # 낮추고 결과 영상을 남길 수 있다.
        raise SoniloError(f"Sonilo local file operation failed: {exc}") from exc
    finally:
        _remove_file(proxy_path)
