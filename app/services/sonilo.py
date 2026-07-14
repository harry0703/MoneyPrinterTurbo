import base64
import binascii
import json
import math
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import requests
from loguru import logger

from app.config import config
from app.services import bgm as bgm_service
from app.utils import utils


DEFAULT_BASE_URL = "https://api.sonilo.com"
VIDEO_TO_MUSIC_PATH = "/v1/video-to-music"
VIDEO_TO_SFX_PATH = "/v1/video-to-sfx"
TASKS_PATH = "/v1/tasks"
SERVICES_PATH = "/v1/account/services"
MAX_VIDEO_DURATION_SECONDS = 360
# 音效接口的时长上限比配乐更严：3 分钟对 6 分钟。两个上限各自独立校验，
# 成片在两者之间时配乐照常进行、音效降级跳过。
MAX_SFX_VIDEO_DURATION_SECONDS = 180
MAX_PROMPT_LENGTH = 2000
MAX_PROXY_BYTES = 300 * 1024 * 1024
MAX_GENERATED_AUDIO_BYTES = 30 * 1024 * 1024
VIDEO_TO_MUSIC_SERVICE_ID = "video_to_music"
VIDEO_TO_SFX_SERVICE_ID = "video_to_sfx"
SFX_POLL_INTERVAL_SECONDS = 5
SFX_TERMINAL_TASK_STATUSES = ("succeeded", "failed")


class SoniloError(RuntimeError):
    """表示 Sonilo 请求、响应协议或生成音频校验失败。"""


def get_api_key() -> str:
    """优先读取 WebUI 保存的配置，未配置时允许使用环境变量。"""
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
    """限制配置值范围，避免无穷大或负数让请求永久挂起或立即失败。"""
    raw_timeout = config.app.get("sonilo_timeout", 600)
    try:
        read_timeout = float(raw_timeout)
    except (TypeError, ValueError):
        read_timeout = 600
    if not math.isfinite(read_timeout) or read_timeout <= 0:
        read_timeout = 600
    # Requests 不接受 0 秒读取超时。向上取整既保留小数配置的有效含义，也能
    # 避免 0.1~0.9 被 int() 截断为 0 后抛出未进入 Sonilo 降级链路的 ValueError。
    return 15, max(1, math.ceil(min(read_timeout, 1800)))


def _normalize_service_id(service_id: str) -> str:
    """
    将 Sonilo 服务标识统一为项目内部使用的下划线格式。

    2026-07-14 实际接口返回 ``video_to_music``，但同日公开文档示例使用
    ``video-to-music``。差异仅在单词分隔符，因此在第三方协议边界统一格式，
    避免 UI 连接测试因提供方文档与生产响应暂时不一致而误报失败。
    """
    return service_id.strip().lower().replace("-", "_")


def _safe_response_error(response: requests.Response) -> str:
    """仅保留简短响应信息，既方便定位又避免异常页面污染日志。"""
    body = (response.text or "").strip().replace("\n", " ")[:500]
    return body or response.reason or "request failed"


def test_connection(
    required_service_ids: tuple[str, ...] = (VIDEO_TO_MUSIC_SERVICE_ID,),
) -> dict[str, Any]:
    """
    使用不消耗生成额度的服务列表接口验证 API Key。

    配乐与音效共用同一个 Key，但账号开通的服务可能不同；调用方按当前启用
    的功能传入必需服务列表。返回原始 JSON 便于 UI 展示可用服务，但日志中
    绝不记录 Key 或请求头。
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
    missing_services = [
        _normalize_service_id(service_id).replace("_", "-")
        for service_id in required_service_ids
        if _normalize_service_id(service_id) not in normalized_services
    ]
    if missing_services:
        raise SoniloError(
            f"Sonilo {', '.join(missing_services)} service is not available "
            "for this key"
        )
    logger.info("Sonilo connection test succeeded")
    return payload


def _remove_file(file_path: str) -> None:
    """尽力清理 Sonilo 中间文件，不覆盖调用方正在处理的原始异常。"""
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
    生成无音轨、最长边 1280 像素的 H.264 代理视频。

    Sonilo 只需分析画面节奏和内容，上传原始高清成片会增加等待时间和流量，
    对生成质量没有实际收益。代理文件放在输入文件同目录，任务结束后统一清理。
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
    """严格解析单条 NDJSON，禁止静默忽略截断或非对象响应。"""
    try:
        event = json.loads(raw_line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SoniloError("Sonilo returned malformed streaming data") from exc
    if not isinstance(event, dict) or not isinstance(event.get("type"), str):
        raise SoniloError("Sonilo returned an invalid streaming event")
    return event


def _stream_audio(response: requests.Response, temp_audio_path: str) -> tuple[int, str]:
    """
    把第一条配乐流按事件顺序写入临时文件，并限制最大体积。

    API 可能同时返回多条候选流；当前产品只需要一条 BGM，所以固定选择
    stream_index=0。只有收到 complete 事件并通过 FFmpeg 完整解码后才会发布。
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
    """请求配乐并在完整协议及音频校验通过后原子保存。"""
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
            # iter_lines() 期间的网络中断同样属于 requests 异常，不能只捕获
            # 建立连接阶段，否则半条音频可能让任务直接异常退出而无法降级。
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
    """为一条已拼接视频生成时长匹配的 Sonilo 背景音乐。"""
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
        # 临时目录、代理文件和最终原子替换都可能发生文件系统错误。统一转换为
        # SoniloError，任务编排层才能按设计降级为“无背景音乐”并保留成片。
        raise SoniloError(f"Sonilo local file operation failed: {exc}") from exc
    finally:
        _remove_file(proxy_path)


def _sfx_deadline_seconds() -> float:
    """
    音效任务从提交到终态的总等待秒数。

    与配乐共用 sonilo_timeout 配置项：配乐是流式响应的读取超时，音效是
    轮询任务的总时长上限。同样限制取值范围，避免非法配置让轮询永不结束。
    """
    raw_timeout = config.app.get("sonilo_timeout", 600)
    try:
        deadline = float(raw_timeout)
    except (TypeError, ValueError):
        deadline = 600
    if not math.isfinite(deadline) or deadline <= 0:
        deadline = 600
    return min(deadline, 1800)


def _submit_sfx_task(video_path: str, prompt: str) -> str:
    """
    提交音效任务并返回 task_id。

    与配乐接口不同，音效走异步任务管线：提交被受理即开始计费，因此和配乐
    保持同一策略——提交失败不自动重试，由任务编排层统一降级。
    """
    try:
        with open(video_path, "rb") as video_file:
            response = requests.post(
                f"{_base_url()}{VIDEO_TO_SFX_PATH}",
                headers={"Authorization": f"Bearer {get_api_key()}"},
                files={"video": (Path(video_path).name, video_file, "video/mp4")},
                data={"prompt": prompt} if prompt else None,
                timeout=_request_timeout(),
            )
    except requests.RequestException as exc:
        raise SoniloError(
            f"failed to submit Sonilo sound effects task: {exc}"
        ) from exc
    if not response.ok:
        raise SoniloError(
            f"Sonilo sound effects request failed ({response.status_code}): "
            f"{_safe_response_error(response)}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise SoniloError("Sonilo returned an invalid task response") from exc
    task_id = payload.get("task_id") if isinstance(payload, dict) else None
    if not task_id:
        raise SoniloError("Sonilo accepted the request but returned no task_id")
    return str(task_id)


def _poll_sfx_task(task_id: str) -> dict[str, Any]:
    """
    轮询任务状态直到终态（succeeded/failed）或达到总时长上限。

    404 表示 task_id 无效或不是音效任务，重试不会改变结果，必须立即失败；
    其余错误（5xx、限流、网络抖动、非法响应体）都视为暂时性——任务仍在
    服务端继续执行，留在轮询循环里等待下一轮，直到超出总时长上限。
    """
    deadline = time.monotonic() + _sfx_deadline_seconds()
    while True:
        try:
            response = requests.get(
                f"{_base_url()}{TASKS_PATH}/{task_id}",
                headers={"Authorization": f"Bearer {get_api_key()}"},
                timeout=(15, 30),
            )
        except requests.RequestException as exc:
            response = None
            logger.debug(
                f"transient Sonilo task poll failure: task_id={task_id}, "
                f"error={exc}"
            )
        if response is not None:
            if response.status_code == 404:
                raise SoniloError(
                    f"Sonilo sound effects task was not found: {task_id}"
                )
            if response.ok:
                try:
                    task_body = response.json()
                except ValueError:
                    task_body = None
                if (
                    isinstance(task_body, dict)
                    and task_body.get("status") in SFX_TERMINAL_TASK_STATUSES
                ):
                    return task_body
            else:
                logger.debug(
                    f"transient Sonilo task poll failure: task_id={task_id}, "
                    f"status={response.status_code}"
                )
        if time.monotonic() >= deadline:
            raise SoniloError(
                f"timed out waiting for Sonilo sound effects task: {task_id}"
            )
        time.sleep(SFX_POLL_INTERVAL_SECONDS)


def _download_sfx_audio(
    task_body: dict[str, Any], temp_audio_path: str, task_id: str
) -> int:
    """
    校验终态任务并把音频产物流式写入临时文件，限制最大体积。

    产物 URL 是预签名的，自带访问授权：下载请求绝不能携带 Authorization
    请求头，避免把 API Key 发送给存储域名。
    """
    if task_body.get("status") == "failed":
        error = task_body.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("code") or "unknown error")
        elif isinstance(error, str) and error:
            message = error
        else:
            message = "unknown error"
        raise SoniloError(f"Sonilo sound effects generation failed: {message}")
    audio = task_body.get("audio")
    audio_url = audio.get("url") if isinstance(audio, dict) else None
    if not isinstance(audio_url, str) or not audio_url:
        raise SoniloError(
            f"Sonilo sound effects task returned no audio artifact: {task_id}"
        )
    total_bytes = 0
    try:
        response = requests.get(audio_url, stream=True, timeout=_request_timeout())
        with response:
            if not response.ok:
                raise SoniloError(
                    f"Sonilo sound effects download failed "
                    f"({response.status_code}): {_safe_response_error(response)}"
                )
            with open(temp_audio_path, "wb") as output:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > MAX_GENERATED_AUDIO_BYTES:
                        raise SoniloError("Sonilo audio exceeds the 30 MB limit")
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
    except requests.RequestException as exc:
        raise SoniloError(
            f"failed to download Sonilo sound effects: {exc}"
        ) from exc
    if total_bytes <= 0:
        raise SoniloError("Sonilo returned no audio data")
    return total_bytes


def _request_sfx(video_path: str, output_path: str, prompt: str) -> str:
    """走完提交、轮询和下载的完整任务管线，音频校验通过后原子保存。"""
    output_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(output_dir, exist_ok=True)
    descriptor, temp_audio_path = tempfile.mkstemp(
        prefix=".sonilo-sfx-",
        suffix=Path(output_path).suffix or ".m4a",
        dir=output_dir,
    )
    os.close(descriptor)
    try:
        logger.info(
            f"requesting Sonilo sound effects: video={video_path}, "
            f"prompt_provided={bool(prompt)}"
        )
        task_id = _submit_sfx_task(video_path, prompt)
        logger.info(f"Sonilo sound effects task submitted: task_id={task_id}")
        task_body = _poll_sfx_task(task_id)
        total_bytes = _download_sfx_audio(task_body, temp_audio_path, task_id)

        try:
            bgm_service.validate_audio_file(temp_audio_path, timeout_seconds=120)
        except (bgm_service.BgmUploadError, bgm_service.BgmServiceError) as exc:
            raise SoniloError("Sonilo returned audio that FFmpeg cannot decode") from exc
        os.replace(temp_audio_path, output_path)
        temp_audio_path = ""
        logger.info(
            f"Sonilo sound effects generated: output={output_path}, "
            f"size={total_bytes} bytes, task_id={task_id}"
        )
        return output_path
    finally:
        _remove_file(temp_audio_path)


def generate_sfx(
    video_path: str,
    output_path: str,
    video_duration: float,
    prompt: str = "",
) -> str:
    """为一条已拼接视频生成贴合画面的 Sonilo 音效音轨。"""
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
    if duration > MAX_SFX_VIDEO_DURATION_SECONDS:
        # 本地先行校验可以在生成代理和上传之前直接跳过超长成片，由任务层
        # 降级为“无音效”并提示用户，而不是等服务端拒绝后才浪费一次上传。
        raise SoniloError("Sonilo sound effects support videos up to 180 seconds")
    prompt = str(prompt or "").strip()
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise SoniloError("Sonilo sound effects prompt exceeds 2000 characters")

    proxy_path = ""
    try:
        # 音效模型与配乐一样只依赖画面节奏和内容，复用同一个无音轨低码率
        # 代理，避免重复上传原始高清成片。
        proxy_path = _create_video_proxy(video_path)
        return _request_sfx(proxy_path, output_path, prompt)
    except SoniloError:
        raise
    except OSError as exc:
        # 与配乐一致：文件系统错误统一转换为 SoniloError，任务编排层才能
        # 按设计降级为“无音效”并保留成片。
        raise SoniloError(f"Sonilo local file operation failed: {exc}") from exc
    finally:
        _remove_file(proxy_path)
