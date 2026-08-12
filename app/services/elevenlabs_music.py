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


DEFAULT_BASE_URL = "https://api.elevenlabs.io"
VIDEO_TO_MUSIC_PATH = "/v1/music/video-to-music"
SUBSCRIPTION_PATH = "/v1/user/subscription"
DEFAULT_MODEL_ID = "music_v2"
SUPPORTED_MODEL_IDS = frozenset({"music_v1", "music_v2"})
MAX_VIDEO_DURATION_SECONDS = 600
MAX_PROMPT_LENGTH = 1000
MAX_PROXY_BYTES = 200 * 1024 * 1024
MAX_GENERATED_AUDIO_BYTES = 50 * 1024 * 1024
MAX_ERROR_BODY_BYTES = 500


class ElevenLabsMusicError(RuntimeError):
    """表示 ElevenLabs 配乐请求、代理生成或返回音频校验失败。"""


class ElevenLabsPaidPlanRequiredError(ElevenLabsMusicError):
    """表示 Key 有效，但当前账号套餐不包含 ElevenLabs Music API。"""


class ElevenLabsAuthenticationError(ElevenLabsMusicError):
    """表示 ElevenLabs API Key 缺失或已被服务端拒绝。"""


def get_api_key() -> str:
    """
    读取 ElevenLabs 共用 API Key。

    配乐与现有 ElevenLabs TTS 使用同一个账号配置，避免用户在 WebUI 重复维护
    两份 Key；环境变量仅作为本机配置未填写时的后备来源。
    """
    configured_key = str(config.elevenlabs.get("api_key", "") or "").strip()
    return configured_key or os.getenv("ELEVENLABS_API_KEY", "").strip()


def is_enabled() -> bool:
    return bool(get_api_key())


def _base_url() -> str:
    return str(
        config.elevenlabs.get("music_base_url", DEFAULT_BASE_URL)
        or DEFAULT_BASE_URL
    ).rstrip("/")


def _model_id() -> str:
    """只允许官方 Video-to-Music 当前公开的模型，错误配置时安全回退。"""
    model_id = str(
        config.elevenlabs.get("music_model_id", DEFAULT_MODEL_ID)
        or DEFAULT_MODEL_ID
    ).strip()
    return model_id if model_id in SUPPORTED_MODEL_IDS else DEFAULT_MODEL_ID


def _request_timeout() -> tuple[int, int]:
    """限制配乐读取超时，兼顾长视频生成耗时与错误配置的可恢复性。"""
    raw_timeout = config.elevenlabs.get("music_timeout", 600)
    try:
        read_timeout = float(raw_timeout)
    except (TypeError, ValueError):
        read_timeout = 600
    if not math.isfinite(read_timeout) or read_timeout <= 0:
        read_timeout = 600
    return 15, max(1, math.ceil(min(read_timeout, 1800)))


def _safe_response_error(response: requests.Response) -> str:
    """只读取有限的第三方错误正文，避免异常响应耗尽内存或污染任务日志。"""
    try:
        body_bytes = next(
            response.iter_content(chunk_size=MAX_ERROR_BODY_BYTES),
            b"",
        )
    except requests.RequestException:
        body_bytes = b""
    if isinstance(body_bytes, bytes):
        body = body_bytes.decode(
            response.encoding or "utf-8",
            errors="replace",
        )
    else:
        body = str(body_bytes)
    body = body.strip().replace("\n", " ")[:MAX_ERROR_BODY_BYTES]
    return body or response.reason or "request failed"


def test_connection() -> dict[str, Any]:
    """
    使用不消耗音乐生成额度的订阅接口检查 API Key 和账号套餐。

    该接口只能确认 Key 可访问订阅信息以及账号不是免费套餐，不能证明当前 Key
    一定拥有 Music endpoint 权限。ElevenLabs 允许按 endpoint、额度和 IP 限制
    Key，因此 UI 成功提示必须保留这一边界，实际权限仍由生成请求最终确认。
    响应中的账单和用量详情不会写入日志，避免记录账号隐私。
    """
    api_key = get_api_key()
    if not api_key:
        raise ElevenLabsAuthenticationError("ElevenLabs API key is required")
    try:
        with requests.get(
            f"{_base_url()}{SUBSCRIPTION_PATH}",
            headers={"xi-api-key": api_key},
            timeout=(15, 30),
            stream=True,
        ) as response:
            if response.status_code == 401:
                raise ElevenLabsAuthenticationError(
                    "ElevenLabs API key was rejected (401): "
                    f"{_safe_response_error(response)}"
                )
            if not response.ok:
                raise ElevenLabsMusicError(
                    "ElevenLabs account check failed "
                    f"({response.status_code}): "
                    f"{_safe_response_error(response)}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise ElevenLabsMusicError(
                    "ElevenLabs returned an invalid subscription response"
                ) from exc
    except requests.RequestException as exc:
        raise ElevenLabsMusicError(
            f"failed to connect to ElevenLabs: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ElevenLabsMusicError(
            "ElevenLabs returned an unexpected subscription response"
        )
    tier = str(payload.get("tier") or "").strip().lower()
    if not tier:
        raise ElevenLabsMusicError(
            "ElevenLabs subscription response does not include an account tier"
        )
    if tier == "free":
        raise ElevenLabsPaidPlanRequiredError(
            "ElevenLabs Music API requires a paid plan; "
            "the current account is on the free tier"
        )
    logger.info(f"ElevenLabs account and plan check succeeded: tier={tier}")
    return payload


def validate_generation_access() -> None:
    """
    在昂贵的视频流水线开始前排除确定无法生成配乐的账号。

    免费套餐和无效 Key 都是确定性错误，必须立即终止，避免先消耗 LLM、TTS
    和素材服务额度。订阅接口也可能因 Music-only endpoint scope、IP 限制或
    临时网络问题不可访问；这些结果不能证明 Music API 不可用，因此只记录警告，
    继续让真正的生成请求决定结果，避免把受限但可用的 Key 错误拦截。
    """
    try:
        test_connection()
    except (ElevenLabsPaidPlanRequiredError, ElevenLabsAuthenticationError):
        raise
    except ElevenLabsMusicError as exc:
        logger.warning(
            "ElevenLabs account preflight was inconclusive; "
            f"generation will verify Music API access: error={exc}"
        )


def _remove_file(file_path: str) -> None:
    """尽力清理 ElevenLabs 中间文件，不覆盖调用方正在处理的原始异常。"""
    if not file_path or not os.path.exists(file_path):
        return
    try:
        os.remove(file_path)
    except OSError as exc:
        logger.warning(
            "failed to remove ElevenLabs temporary file: "
            f"path={file_path}, error={exc}"
        )


def _create_video_proxy(video_path: str) -> str:
    """
    生成无音轨、最长边 1280 像素的 H.264 代理视频。

    Video-to-Music 只分析画面，上传原始高清成片既不会改善配乐，又会增加流量
    和等待时间。代理严格限制在官方 200 MB 上限内，并在请求结束后删除。
    """
    descriptor, proxy_path = tempfile.mkstemp(
        prefix=".elevenlabs-music-proxy-",
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
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        _remove_file(proxy_path)
        raise ElevenLabsMusicError(
            "ElevenLabs video proxy generation timed out"
        ) from exc
    except OSError as exc:
        _remove_file(proxy_path)
        raise ElevenLabsMusicError(
            "failed to run FFmpeg for ElevenLabs video proxy"
        ) from exc
    if result.returncode != 0:
        _remove_file(proxy_path)
        detail = (result.stderr or "").strip().replace("\n", " ")[-500:]
        raise ElevenLabsMusicError(
            f"failed to generate ElevenLabs video proxy: {detail}"
        )
    proxy_size = os.path.getsize(proxy_path) if os.path.isfile(proxy_path) else 0
    if proxy_size <= 0 or proxy_size > MAX_PROXY_BYTES:
        _remove_file(proxy_path)
        raise ElevenLabsMusicError(
            "ElevenLabs video proxy is empty or exceeds the 200 MB limit"
        )
    logger.info(
        "ElevenLabs video proxy prepared: "
        f"source={video_path}, size={proxy_size} bytes"
    )
    return proxy_path


def _stream_audio(response: requests.Response, temp_audio_path: str) -> int:
    """分块保存音频并限制最大体积，防止异常响应耗尽本机磁盘。"""
    total_bytes = 0
    with open(temp_audio_path, "wb") as output:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            total_bytes += len(chunk)
            if total_bytes > MAX_GENERATED_AUDIO_BYTES:
                raise ElevenLabsMusicError(
                    "ElevenLabs audio exceeds the 50 MB limit"
                )
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    if total_bytes <= 0:
        raise ElevenLabsMusicError("ElevenLabs returned no audio data")
    return total_bytes


def _request_bgm(video_path: str, output_path: str, prompt: str) -> str:
    """请求 ElevenLabs 配乐，完整下载并通过 FFmpeg 校验后再原子发布。"""
    output_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(output_dir, exist_ok=True)
    descriptor, temp_audio_path = tempfile.mkstemp(
        prefix=".elevenlabs-music-",
        suffix=Path(output_path).suffix or ".mp3",
        dir=output_dir,
    )
    os.close(descriptor)
    try:
        model_id = _model_id()
        logger.info(
            "requesting ElevenLabs background music: "
            f"video={video_path}, model={model_id}, "
            f"prompt_provided={bool(prompt)}"
        )
        request_data = {"model_id": model_id}
        if prompt:
            request_data["description"] = prompt
        try:
            with open(video_path, "rb") as video_file:
                response = requests.post(
                    f"{_base_url()}{VIDEO_TO_MUSIC_PATH}",
                    headers={"xi-api-key": get_api_key()},
                    params={"output_format": "mp3_44100_128"},
                    files=[
                        (
                            # 官方文档把表单数组展示为 ``videos[]``，但 2026-07-18
                            # 生产接口会对该字段返回 422，实际 Starlette 参数名为
                            # ``videos``。重复上传时 requests 可继续添加同名字段。
                            "videos",
                            (Path(video_path).name, video_file, "video/mp4"),
                        )
                    ],
                    data=request_data,
                    stream=True,
                    timeout=_request_timeout(),
                )
                with response:
                    if not response.ok:
                        raise ElevenLabsMusicError(
                            "ElevenLabs generation failed "
                            f"({response.status_code}): "
                            f"{_safe_response_error(response)}"
                        )
                    total_bytes = _stream_audio(response, temp_audio_path)
        except requests.RequestException as exc:
            # 下载阶段断线也属于请求失败，必须进入任务降级逻辑，不能留下半条
            # 音频或让已经生成的视频因为第三方网络波动整体失败。
            raise ElevenLabsMusicError(
                f"failed to request ElevenLabs music: {exc}"
            ) from exc

        try:
            bgm_service.validate_audio_file(temp_audio_path, timeout_seconds=120)
        except (bgm_service.BgmUploadError, bgm_service.BgmServiceError) as exc:
            raise ElevenLabsMusicError(
                "ElevenLabs returned audio that FFmpeg cannot decode"
            ) from exc
        os.replace(temp_audio_path, output_path)
        temp_audio_path = ""
        logger.info(
            "ElevenLabs background music generated: "
            f"output={output_path}, size={total_bytes} bytes"
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
    """为一条已拼接视频生成时长和画面匹配的 ElevenLabs 背景音乐。"""
    if not get_api_key():
        raise ElevenLabsMusicError("ElevenLabs API key is required")
    if not os.path.isfile(video_path):
        raise ElevenLabsMusicError("ElevenLabs input video does not exist")
    try:
        duration = float(video_duration)
    except (TypeError, ValueError) as exc:
        raise ElevenLabsMusicError(
            "ElevenLabs video duration is invalid"
        ) from exc
    if not math.isfinite(duration) or duration <= 0:
        raise ElevenLabsMusicError("ElevenLabs video duration is invalid")
    if duration > MAX_VIDEO_DURATION_SECONDS:
        raise ElevenLabsMusicError(
            "ElevenLabs supports videos up to 600 seconds"
        )
    prompt = str(prompt or "").strip()
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise ElevenLabsMusicError(
            "ElevenLabs music prompt exceeds 1000 characters"
        )

    proxy_path = ""
    try:
        proxy_path = _create_video_proxy(video_path)
        return _request_bgm(proxy_path, output_path, prompt)
    except ElevenLabsMusicError:
        raise
    except OSError as exc:
        raise ElevenLabsMusicError(
            f"ElevenLabs local file operation failed: {exc}"
        ) from exc
    finally:
        _remove_file(proxy_path)
