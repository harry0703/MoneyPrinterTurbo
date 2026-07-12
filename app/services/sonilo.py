"""
Sonilo (https://sonilo.com) video-to-music integration — optional, opt-in.

Generates a background music track matched to the visuals and editing pace of
the assembled video, by calling Sonilo's `/v1/video-to-music` API.

The integration is fully opt-in and non-breaking:
  * OFF by default. It only runs when the user selects the "sonilo" BGM mode
    AND a Sonilo API key is configured (`sonilo_api_key` in config.toml, or
    the `SONILO_API_KEY` environment variable as a fallback).
  * The existing "random" / "custom" BGM code paths are untouched. This module
    only changes where the BGM audio file comes from; volume, fade-out, loop
    and mixing all reuse the existing BGM pipeline in app/services/video.py.
  * Every failure (timeout, HTTP error, broken stream, oversized video)
    degrades to "no background music" and never fails the video task.
  * User notice: in this mode the assembled (no-BGM) video is uploaded to the
    Sonilo API to generate the track. Generated music is licensed and safe for
    commercial use per Sonilo's terms (terms apply).
    生成的音乐已获授权、可商用（以条款为准）。

The API returns an NDJSON event stream: `audio_chunk` (base64 audio fragments,
grouped by stream_index), `title`, `complete` (success terminal event) and
`error` (failure terminal event). Progress events and unparseable lines are
ignored. The generated audio is AAC in an .m4a container.

Config (config.toml, [app] section):
    sonilo_api_key = "..."             # required to enable
    # sonilo_base_url = "https://api.sonilo.com"
    # sonilo_timeout_seconds = 600
    # sonilo_bgm_prompt = ""           # optional style hint for the music
"""

import base64
import binascii
import json
import os
from typing import Iterable

import requests
from loguru import logger

from app.config import config

DEFAULT_BASE_URL = "https://api.sonilo.com"
VIDEO_TO_MUSIC_PATH = "/v1/video-to-music"
# 后端生成接口的读超时约为 600 秒。生成一旦开始就会计费，客户端过早超时只会
# 浪费一次已经付费的请求，所以默认读超时与后端保持一致，并允许用户覆盖。
DEFAULT_TIMEOUT_SECONDS = 600
_CONNECT_TIMEOUT_SECONDS = 15
# 接口目前拒绝超过 6 分钟的视频；上传前先在本地校验时长，避免白传一次成片。
MAX_VIDEO_DURATION_SECONDS = 360


class SoniloError(Exception):
    """Sonilo BGM generation failed."""


def get_api_key() -> str:
    """Return the configured Sonilo API key (config.toml first, then env)."""
    api_key = config.app.get("sonilo_api_key", "") or os.getenv("SONILO_API_KEY", "")
    return str(api_key).strip()


def is_enabled() -> bool:
    """True only when a Sonilo API key is configured."""
    return bool(get_api_key())


def generate_bgm(video_path: str, save_path: str, video_duration: float = 0) -> str:
    """
    Upload the assembled (no-BGM) video to Sonilo and save the generated
    background music to `save_path` (.m4a).

    Returns the saved audio file path, or "" on any failure so the caller
    falls back to "no background music". This function never raises — a BGM
    problem must never fail the video task.
    """
    if not is_enabled():
        logger.warning(
            "sonilo bgm skipped: no api key configured, continue without bgm"
        )
        return ""

    if not video_path or not os.path.isfile(video_path):
        logger.warning(f"sonilo bgm skipped: video file not found: {video_path}")
        return ""

    if video_duration and video_duration > MAX_VIDEO_DURATION_SECONDS:
        logger.warning(
            f"sonilo bgm skipped: video duration {video_duration:.1f}s exceeds "
            f"the {MAX_VIDEO_DURATION_SECONDS}s api limit, continue without bgm"
        )
        return ""

    try:
        audio = _request_video_to_music(video_path)
    except Exception as e:
        # 任何失败（超时、HTTP 错误、流中断）都降级为“无背景音乐”，
        # 绝不让配乐问题中断成片任务。
        logger.error(f"sonilo bgm generation failed, continue without bgm: {str(e)}")
        return ""

    try:
        with open(save_path, "wb") as f:
            f.write(audio)
    except OSError as e:
        logger.error(f"failed to save sonilo bgm file, continue without bgm: {str(e)}")
        return ""

    logger.success(f"sonilo bgm generated: {save_path}")
    return save_path


def _error_detail(body: str) -> str:
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return body
    if isinstance(parsed, dict):
        detail = parsed.get("detail") or parsed.get("error") or parsed.get("message")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return body


def _http_error_message(status_code: int, body: str) -> str:
    detail = _error_detail(body)
    if status_code == 401:
        return "invalid sonilo api key, please check the configured key"
    if status_code == 402:
        return detail or "insufficient sonilo account balance"
    if status_code == 413:
        return f"video file too large: {detail}"
    if status_code == 429:
        return f"sonilo rate limit reached: {detail}"
    return f"sonilo api error ({status_code}): {detail}"


def _request_video_to_music(video_path: str) -> bytes:
    base_url = str(config.app.get("sonilo_base_url", "") or DEFAULT_BASE_URL).rstrip(
        "/"
    )
    try:
        timeout_seconds = float(
            config.app.get("sonilo_timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        )
    except (TypeError, ValueError):
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS

    prompt = str(config.app.get("sonilo_bgm_prompt", "") or "").strip()
    data = {"prompt": prompt} if prompt else None
    headers = {"Authorization": f"Bearer {get_api_key()}"}

    logger.info(
        f"generating bgm with sonilo, video: {video_path}, "
        f"read timeout: {timeout_seconds:.0f}s"
    )

    try:
        with open(video_path, "rb") as video_file:
            files = {
                "video": (os.path.basename(video_path), video_file, "video/mp4"),
            }
            # 生成接口非幂等（生成即计费），失败不做自动重试，直接降级。
            with requests.post(
                f"{base_url}{VIDEO_TO_MUSIC_PATH}",
                headers=headers,
                data=data,
                files=files,
                stream=True,
                timeout=(_CONNECT_TIMEOUT_SECONDS, timeout_seconds),
            ) as response:
                if response.status_code >= 400:
                    body = response.content.decode("utf-8", errors="replace")
                    raise SoniloError(
                        _http_error_message(response.status_code, body)
                    )
                return _consume_ndjson_stream(
                    response.iter_lines(decode_unicode=True)
                )
    except requests.exceptions.Timeout as exc:
        raise SoniloError(
            f"sonilo request timed out ({timeout_seconds:.0f}s)"
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise SoniloError(f"sonilo request failed: {str(exc)}") from exc


def _consume_ndjson_stream(lines: Iterable[str]) -> bytes:
    """
    Consume the NDJSON event stream, group base64 audio chunks by
    stream_index and return the first audio track.
    """
    streams = {}
    completed = False
    for line in lines:
        if not line or not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "audio_chunk":
            chunk = event.get("data")
            if not isinstance(chunk, str):
                continue
            try:
                index = int(event.get("stream_index", 0))
            except (TypeError, ValueError):
                continue
            if index < 0:
                continue
            try:
                decoded = base64.b64decode(chunk, validate=True)
            except (binascii.Error, ValueError):
                continue
            streams.setdefault(index, bytearray()).extend(decoded)
        elif event_type == "complete":
            completed = True
        elif event_type == "error":
            message = event.get("message") or event.get("code") or "stream error"
            raise SoniloError(f"sonilo generation failed: {message}")
        # title / stage_start 等进度事件一律忽略。

    if not completed:
        raise SoniloError("sonilo stream ended unexpectedly (no complete event)")
    if not streams:
        raise SoniloError("sonilo stream completed but returned no audio data")
    first_index = sorted(streams)[0]
    return bytes(streams[first_index])
