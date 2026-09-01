"""MiniMax TTS provider."""

import math
import os
import tempfile
from typing import Union
from urllib.parse import urlparse

import requests
from edge_tts import SubMaker
from loguru import logger
from moviepy.audio.io.AudioFileClip import AudioFileClip

from app.config import config
from app.services.voice_common import (
    ensure_file_path_exists,
    ensure_legacy_submaker_fields,
    populate_legacy_submaker_with_full_text,
)

MINIMAX_TTS_GLOBAL_URL = "https://api.minimax.io/v1/t2a_v2"
MINIMAX_TTS_CN_URL = "https://api.minimaxi.com/v1/t2a_v2"
MINIMAX_TTS_DEFAULT_MODEL = "speech-2.8-hd"
MINIMAX_TTS_DEFAULT_VOICE = "English_expressive_narrator"
MINIMAX_TTS_MODELS = (
    "speech-2.8-hd", "speech-2.8-turbo", "speech-2.6-hd", "speech-2.6-turbo",
    "speech-02-hd", "speech-02-turbo", "speech-01-hd", "speech-01-turbo",
)
_MINIMAX_TTS_MAX_AUDIO_HEX_CHARS = 100 * 1024 * 1024


def get_minimax_voices(voice_id: str | None = None) -> list[str]:
    """返回当前配置的 MiniMax 音色，供统一的 TTS 调度格式使用。"""
    voice_id = str(
        voice_id
        or config.minimax_tts.get("voice_id", MINIMAX_TTS_DEFAULT_VOICE)
        or MINIMAX_TTS_DEFAULT_VOICE
    ).strip()
    return [f"minimax:{voice_id}"]


def is_minimax_voice(voice_name: str | None) -> bool:
    return (voice_name or "").startswith("minimax:")


def get_minimax_tts_api_key() -> str:
    """返回 MiniMax TTS 的有效密钥，专用配置优先于 LLM 共享配置。"""
    return str(
        config.minimax_tts.get("api_key", "")
        or config.app.get("minimax_api_key", "")
        or os.getenv("MINIMAX_API_KEY", "")
        or ""
    ).strip()


def _resolve_minimax_tts_url(configured_url: str) -> str:
    configured_url = (configured_url or "").strip().rstrip("/")
    if not configured_url:
        return MINIMAX_TTS_GLOBAL_URL
    if configured_url in {MINIMAX_TTS_GLOBAL_URL, MINIMAX_TTS_CN_URL}:
        return configured_url
    if configured_url.endswith("/v1"):
        return f"{configured_url}/t2a_v2"
    return configured_url


def _infer_minimax_tts_url(base_url: str) -> str:
    """根据 MiniMax LLM 地址推断同区域的 TTS 地址，无法识别时返回空值。"""
    normalized_url = str(base_url or "").strip()
    if not normalized_url:
        return ""

    parse_target = normalized_url if "://" in normalized_url else f"//{normalized_url}"
    host = (urlparse(parse_target).hostname or "").lower()
    if host == "minimaxi.com" or host.endswith(".minimaxi.com"):
        return MINIMAX_TTS_CN_URL
    if host == "minimax.io" or host.endswith(".minimax.io"):
        return MINIMAX_TTS_GLOBAL_URL
    return ""


def get_minimax_tts_endpoint() -> str:
    """
    返回与当前有效密钥匹配的 MiniMax TTS 地址。

    独立配置 TTS Key 时尊重用户选择的 TTS 地址；复用 MiniMax LLM Key 时，
    优先跟随 LLM Base URL 的区域，避免中国站 Key 被发送到国际站而返回 401。
    """
    dedicated_key = str(config.minimax_tts.get("api_key", "") or "").strip()
    if not dedicated_key:
        inferred_url = _infer_minimax_tts_url(config.app.get("minimax_base_url", ""))
        if inferred_url:
            return inferred_url
    return _resolve_minimax_tts_url(config.minimax_tts.get("base_url", ""))


def get_minimax_voice_catalog(
    api_key: str = "",
    endpoint: str = "",
    voice_type: str = "all",
) -> list[dict[str, str]]:
    """
    查询当前 MiniMax 账号可用的系统、克隆和生成音色。

    返回值统一为 voice_id、voice_name、voice_type 三个字段，调用方无需了解
    MiniMax 按音色来源拆分数组的响应结构。查询失败时抛出异常，让 WebUI、
    API 或 CLI 可以按各自交互方式展示明确错误，而不是静默返回空列表。
    """
    if voice_type not in {"system", "voice_cloning", "voice_generation", "all"}:
        raise ValueError(f"Unsupported MiniMax voice type: {voice_type}")

    effective_api_key = str(api_key or get_minimax_tts_api_key()).strip()
    if not effective_api_key:
        raise ValueError("MiniMax TTS API key is not set")

    tts_endpoint = (
        _resolve_minimax_tts_url(endpoint)
        if endpoint
        else get_minimax_tts_endpoint()
    )
    voice_endpoint = (
        f"{tts_endpoint[:-len('/t2a_v2')]}/get_voice"
        if tts_endpoint.endswith("/t2a_v2")
        else f"{tts_endpoint.rstrip('/')}/get_voice"
    )
    response = requests.post(
        voice_endpoint,
        json={"voice_type": voice_type},
        headers={
            "Authorization": f"Bearer {effective_api_key}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"MiniMax get_voice failed with status {response.status_code}: "
            f"{response.text[:200]}"
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise RuntimeError("MiniMax get_voice returned invalid JSON") from exc

    base_resp = body.get("base_resp") or {}
    if base_resp.get("status_code") not in {0, "0"}:
        status_message = str(base_resp.get("status_msg") or "unknown error")
        raise RuntimeError(f"MiniMax get_voice failed: {status_message}")

    catalog = []
    seen_voice_ids = set()
    response_groups = (
        ("system", "system_voice"),
        ("voice_cloning", "voice_cloning"),
        ("voice_generation", "voice_generation"),
    )
    for normalized_type, response_key in response_groups:
        for item in body.get(response_key) or []:
            voice_id = str(item.get("voice_id") or "").strip()
            if not voice_id or voice_id in seen_voice_ids:
                continue
            seen_voice_ids.add(voice_id)
            catalog.append(
                {
                    "voice_id": voice_id,
                    "voice_name": str(item.get("voice_name") or voice_id).strip(),
                    "voice_type": normalized_type,
                }
            )

    logger.info(f"loaded MiniMax voices: count={len(catalog)}, type={voice_type}")
    return catalog


def _write_validated_minimax_audio(audio_bytes: bytes, voice_file: str) -> float:
    """
    将 MiniMax 音频原子写入目标路径，并返回时长。

    远端返回成功状态不代表音频一定完整。先在同目录临时文件中验证，再使用
    os.replace 原子替换，可以避免解码失败或 MoviePy 无法读取时留下半成品。
    """
    ensure_file_path_exists(voice_file)
    output_dir = os.path.dirname(os.path.abspath(voice_file))
    output_suffix = os.path.splitext(voice_file)[1] or ".mp3"
    temp_fd, temp_path = tempfile.mkstemp(
        prefix=".minimax-tts-", suffix=output_suffix, dir=output_dir
    )
    os.close(temp_fd)

    try:
        with open(temp_path, "wb") as output:
            output.write(audio_bytes)

        audio_clip = AudioFileClip(temp_path)
        try:
            audio_duration = float(audio_clip.duration)
        finally:
            audio_clip.close()

        if not math.isfinite(audio_duration) or audio_duration <= 0:
            raise ValueError("MiniMax TTS returned audio with an invalid duration")

        os.replace(temp_path, voice_file)
        return audio_duration
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def minimax_tts(text: str, voice_id: str, voice_rate: float, voice_file: str, voice_volume: float = 1.0) -> Union[SubMaker, None]:
    """Generate speech with the synchronous MiniMax T2A HTTP API."""
    text, voice_id = (text or "").strip(), (voice_id or "").strip()
    if not text or not voice_id:
        logger.error("MiniMax TTS requires text and a voice ID")
        return None
    settings = config.minimax_tts
    api_key = get_minimax_tts_api_key()
    if not api_key:
        logger.error("MiniMax TTS API key is not set")
        return None
    url = get_minimax_tts_endpoint()
    model = str(settings.get("model_id", MINIMAX_TTS_DEFAULT_MODEL) or MINIMAX_TTS_DEFAULT_MODEL).strip()
    if model not in MINIMAX_TTS_MODELS:
        logger.error(f"Unsupported MiniMax TTS model: {model}")
        return None
    try:
        speed = max(0.5, min(2.0, float(voice_rate or 1.0)))
        volume = max(0.0, min(10.0, float(voice_volume or 1.0)))
        pitch = max(-12, min(12, int(settings.get("pitch", 0) or 0)))
        sample_rate = int(settings.get("sample_rate", 32000) or 32000)
        bitrate = int(settings.get("bitrate", 128000) or 128000)
        channel = int(settings.get("channel", 1) or 1)
    except (TypeError, ValueError) as exc:
        logger.error(f"Invalid MiniMax TTS audio setting: {str(exc)}")
        return None
    audio_format = str(settings.get("audio_format", "mp3") or "mp3").strip()
    if audio_format not in {"mp3", "wav", "flac", "pcm"}:
        logger.error(f"Unsupported MiniMax TTS audio format: {audio_format}")
        return None
    payload = {
        "model": model, "text": text, "stream": False, "language_boost": "auto", "output_format": "hex",
        "voice_setting": {"voice_id": voice_id, "speed": speed, "vol": volume, "pitch": pitch},
        "audio_setting": {"sample_rate": sample_rate, "bitrate": bitrate, "format": audio_format, "channel": channel},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for attempt in range(3):
        try:
            logger.info(f"start MiniMax TTS, model: {model}, voice: {voice_id}, try: {attempt + 1}")
            response = requests.post(url, json=payload, headers=headers, timeout=120)
            if response.status_code != 200:
                logger.error(f"MiniMax TTS failed with status {response.status_code}: {response.text[:200]}")
                continue
            body = response.json()
            data = body.get("data") or {}
            base_resp = body.get("base_resp") or {}
            if base_resp.get("status_code") != 0 or data.get("status") != 2:
                logger.error(f"MiniMax TTS returned an unsuccessful response: status_code={base_resp.get('status_code')}, audio_status={data.get('status')}")
                continue
            audio_hex = data.get("audio")
            if not isinstance(audio_hex, str) or not audio_hex:
                logger.error("MiniMax TTS returned empty audio data")
                continue
            if len(audio_hex) > _MINIMAX_TTS_MAX_AUDIO_HEX_CHARS:
                logger.error("MiniMax TTS returned audio data exceeding the supported size")
                continue
            audio_duration = _write_validated_minimax_audio(bytes.fromhex(audio_hex), voice_file)
            logger.success(f"MiniMax TTS succeeded: {voice_file}")
            return populate_legacy_submaker_with_full_text(
                ensure_legacy_submaker_fields(SubMaker()), text, audio_duration
            )
        except (OSError, ValueError, requests.RequestException) as exc:
            logger.error(f"MiniMax TTS failed: {str(exc)}")
    return None
