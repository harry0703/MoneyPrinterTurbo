"""秘塔 MiniMax H3 文生视频客户端。

该模块只负责秘塔代理的 MiniMax V2 协议：提交付费任务、轮询同一个任务、
解析生成结果。素材按需生成、文件下载和成片拼接仍由 ``material`` 服务负责，
避免供应商协议与本地视频工作流相互耦合。
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, quote_plus, urlsplit

import requests
from loguru import logger

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect


DEFAULT_BASE_URL = "https://metaso.cn/api/minimax"
DEFAULT_MODEL_ID = "MiniMax-H3"
DEFAULT_RESOLUTION = "2K"
DEFAULT_MIN_DURATION_SECONDS = 4
DEFAULT_MAX_DURATION_SECONDS = 15
DEFAULT_POLL_INTERVAL_SECONDS = 10.0
DEFAULT_RUN_TIMEOUT_SECONDS = 1800.0
MAX_PROMPT_LENGTH = 7000
MAX_POLL_RETRIES = 5
RETRY_BASE_SECONDS = 1.0
MAX_ERROR_TEXT_LENGTH = 500
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
ACTIVE_STATUSES = frozenset({"queued", "running"})
TERMINAL_FAILURE_STATUSES = frozenset({"failed", "cancelled", "canceled"})
SUPPORTED_RESOLUTIONS = frozenset({"768P", "2K"})


class MetasoMiniMaxError(RuntimeError):
    """秘塔 MiniMax 的确定性配置、请求或响应错误。"""

    def __init__(self, message: str, task_id: str = ""):
        super().__init__(message)
        # 远端任务一旦创建，所有后续异常都携带同一个 ID。任务服务可以统一
        # 保存恢复线索，不需要了解轮询、结果解析或下载分别在哪一步失败。
        self.task_id = task_id


class MetasoMiniMaxUnconfirmedTaskError(MetasoMiniMaxError):
    """远端可能已创建付费任务，但本机无法确认其最终状态。"""


class MetasoMiniMaxDownloadError(MetasoMiniMaxError):
    """远端付费任务已成功，但成片未能下载到本机。"""


def get_api_key(settings: Mapping[str, Any] | None = None) -> str:
    """
    按固定优先级读取秘塔凭据。

    秘塔 ``mk-`` Key 与 MiniMax 官方 Key 属于不同账户体系，因此不能复用
    项目已有的 ``minimax_api_key``。独立配置和独立环境变量也能防止用户在
    切换 LLM Provider 时意外改变视频生成凭据。
    """
    settings = config.app if settings is None else settings
    configured = str(settings.get("metaso_minimax_api_key", "") or "").strip()
    environment_key = os.getenv("METASO_MINIMAX_API_KEY", "").strip()
    return configured or environment_key


def is_enabled(settings: Mapping[str, Any] | None = None) -> bool:
    """返回当前配置是否具备调用秘塔视频接口的凭据。"""
    return bool(get_api_key(settings))


def _base_url() -> str:
    value = (
        str(
            config.app.get("metaso_minimax_base_url", DEFAULT_BASE_URL)
            or DEFAULT_BASE_URL
        )
        .strip()
        .rstrip("/")
    )
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MetasoMiniMaxError(
            "metaso_minimax_base_url must be an absolute HTTP(S) URL"
        )
    return value


def _resolution() -> str:
    configured = config.app.get("metaso_minimax_resolution", DEFAULT_RESOLUTION)
    value = str(configured).strip().upper()
    if value not in SUPPORTED_RESOLUTIONS:
        supported = ", ".join(sorted(SUPPORTED_RESOLUTIONS))
        # 分辨率直接影响生成费用，用户显式写错时不能静默退回 2K。只有配置项
        # 完全缺失时才使用默认值，避免无意间创建比预期更贵的任务。
        raise MetasoMiniMaxError(
            f"Unsupported Metaso MiniMax resolution {value!r}; "
            f"expected one of: {supported}"
        )
    return value


def _tls_verify() -> bool:
    value = config.app.get("tls_verify", True)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def _bounded_float(key: str, default: float, minimum: float, maximum: float) -> float:
    """读取有限浮点配置，并限制在不会压垮远端或本机的安全范围内。"""
    try:
        value = float(config.app.get(key, default))
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return min(max(value, minimum), maximum)


def _status_code(response: Any) -> int:
    try:
        return int(getattr(response, "status_code", 200))
    except (TypeError, ValueError):
        return 200


def _redact_secret(value: Any, api_key: str) -> str:
    """保留可排障文本，同时移除 API Key、URL 编码 Key 和代理凭据。"""
    text = str(value or "")
    if api_key:
        text = text.replace(api_key, "***")
        encoded = quote_plus(api_key)
        if encoded != api_key:
            text = text.replace(encoded, "***")
    for proxy_url in config.proxy.values():
        proxy_secret = str(proxy_url or "")
        if proxy_secret:
            text = text.replace(proxy_secret, "***")
    return text[:MAX_ERROR_TEXT_LENGTH]


def _response_error(response: Any, api_key: str) -> str:
    """兼容 MiniMax V2 的嵌套错误结构，并限制日志中的响应长度。"""
    try:
        payload = response.json()
    except Exception:
        return f"HTTP {_status_code(response)}"
    if not isinstance(payload, dict):
        return f"HTTP {_status_code(response)}"

    error = payload.get("error")
    if isinstance(error, dict):
        error_type = error.get("type")
        message = error.get("message")
        http_code = error.get("http_code")
    else:
        error_type = None
        message = payload.get("message") or error
        http_code = payload.get("code")
    detail = ": ".join(
        str(item) for item in (error_type, http_code, message) if item not in (None, "")
    )
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


def _normalize_duration(minimum_duration: int) -> tuple[int, int]:
    """返回“用户请求时长、实际提交时长”，用于日志解释最短 4 秒约束。"""
    try:
        requested = int(minimum_duration)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MetasoMiniMaxError(
            "Metaso MiniMax clip duration must be a positive integer"
        ) from exc
    if requested <= 0:
        raise MetasoMiniMaxError(
            "Metaso MiniMax clip duration must be a positive integer"
        )
    duration = min(
        max(requested, DEFAULT_MIN_DURATION_SECONDS),
        DEFAULT_MAX_DURATION_SECONDS,
    )
    return requested, duration


def generate_videos(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> list[MaterialInfo]:
    """提交一个秘塔 MiniMax H3 文生视频任务并等待可下载的结果。"""
    api_key = get_api_key()
    if not api_key:
        raise MetasoMiniMaxError("Metaso MiniMax requires an API key")

    term = str(search_term or "").strip()
    if not term:
        # 空提示词通常表示上游脚本拆分失败。付费接口不能用无效输入试探，
        # 否则即使远端接受也只会产生无法使用的计费素材。
        raise MetasoMiniMaxError("Metaso MiniMax search term must not be empty")
    if len(term) > MAX_PROMPT_LENGTH:
        raise MetasoMiniMaxError(
            f"Metaso MiniMax search term exceeds {MAX_PROMPT_LENGTH} characters"
        )

    aspect = VideoAspect(video_aspect)
    requested_duration, duration = _normalize_duration(minimum_duration)
    if duration != requested_duration:
        logger.info(
            "Metaso MiniMax clip duration adjusted to H3 limits: "
            f"requested={requested_duration}s, using={duration}s, "
            f"supported={DEFAULT_MIN_DURATION_SECONDS}-{DEFAULT_MAX_DURATION_SECONDS}s"
        )
    resolution = _resolution()
    payload = {
        "model": DEFAULT_MODEL_ID,
        "content": [{"type": "text", "text": term}],
        "resolution": resolution,
        "duration": duration,
        "ratio": aspect.value,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    base_url = _base_url()
    create_url = f"{base_url}/v2/video_generation"
    logger.info(
        "generating video with Metaso MiniMax H3: "
        f"resolution={resolution}, ratio={aspect.value}, duration={duration}s, "
        f"prompt_length={len(term)}"
    )

    # POST 超时或 5xx 发生时，远端可能已经创建并计费。接口没有提供客户端
    # 幂等键，因此这里绝不自动重发；上层会停止后续关键词，避免重复扣费。
    try:
        response = requests.post(
            create_url,
            json=payload,
            headers=headers,
            proxies=config.proxy,
            verify=_tls_verify(),
            timeout=(30, 60),
        )
    except Exception as exc:
        raise MetasoMiniMaxUnconfirmedTaskError(
            "Metaso MiniMax submission returned no response; a paid task may "
            "already exist remotely: "
            f"error={type(exc).__name__}, detail={_redact_secret(exc, api_key)}"
        ) from exc

    status_code = _status_code(response)
    if status_code >= 500:
        raise MetasoMiniMaxUnconfirmedTaskError(
            f"Metaso MiniMax submission failed with HTTP {status_code}; a paid "
            "task may already exist remotely"
        )
    if not 200 <= status_code < 300:
        raise MetasoMiniMaxError(
            "Metaso MiniMax video generation request rejected: "
            f"HTTP {status_code}, {_response_error(response, api_key)}"
        )
    try:
        body = response.json()
    except Exception as exc:
        raise MetasoMiniMaxUnconfirmedTaskError(
            "Metaso MiniMax submission returned an unreadable response; a paid "
            f"task may already exist remotely: error={type(exc).__name__}"
        ) from exc

    task_id = str(body.get("task_id") or "").strip() if isinstance(body, dict) else ""
    if not task_id:
        raise MetasoMiniMaxUnconfirmedTaskError(
            "Metaso MiniMax accepted the submission without returning a task id"
        )
    logger.info(f"Metaso MiniMax paid task created: id={task_id}")

    task = _wait_for_task(
        task_id=task_id,
        base_url=base_url,
        headers=headers,
        api_key=api_key,
    )
    content = task.get("content")
    video_url = content.get("url") if isinstance(content, dict) else None
    if not isinstance(video_url, str) or not video_url.startswith(
        ("http://", "https://")
    ):
        raise MetasoMiniMaxError(
            f"Metaso MiniMax task succeeded without a downloadable video: id={task_id}",
            task_id=task_id,
        )

    actual_duration = task.get("duration", duration)
    try:
        actual_duration = int(actual_duration)
    except (TypeError, ValueError, OverflowError):
        actual_duration = duration
    if actual_duration <= 0:
        actual_duration = duration

    return [
        MaterialInfo(
            provider="metaso_minimax",
            url=video_url,
            duration=actual_duration,
            source_info={
                "provider": "metaso_minimax",
                "search_term": term,
                "asset_id": task_id,
                # MiniMax 的 2K/768P 是规格名称，接口没有承诺固定像素尺寸。
                # 不猜测 width/height，后续若需要精确尺寸应以下载文件探测值为准。
                "rendition": {"id": task_id},
            },
        )
    ]


def _wait_for_task(
    *,
    task_id: str,
    base_url: str,
    headers: dict[str, str],
    api_key: str,
) -> dict[str, Any]:
    """轮询同一个付费任务，直到成功、明确失败或本地无法确认状态。"""
    deadline = time.monotonic() + _bounded_float(
        "metaso_minimax_run_timeout",
        DEFAULT_RUN_TIMEOUT_SECONDS,
        60.0,
        7200.0,
    )
    poll_interval = _bounded_float(
        "metaso_minimax_poll_interval",
        DEFAULT_POLL_INTERVAL_SECONDS,
        1.0,
        60.0,
    )
    query_url = f"{base_url}/v2/query/video_generation/{quote(task_id, safe='')}"
    consecutive_failures = 0

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MetasoMiniMaxUnconfirmedTaskError(
                "Metaso MiniMax task is still running after the configured local "
                f"wait timeout: id={task_id}",
                task_id=task_id,
            )

        # connect/read timeout 分别计时，均使用剩余时间的一半，保证一次 GET
        # 不会有意越过任务总截止时间。到期后不会再发起下一次轮询。
        phase_timeout = max(min(remaining / 2.0, 30.0), 0.001)
        try:
            response = requests.get(
                query_url,
                headers=headers,
                proxies=config.proxy,
                verify=_tls_verify(),
                timeout=(phase_timeout, phase_timeout),
            )
            status_code = _status_code(response)
            if status_code in RETRYABLE_STATUS_CODES:
                raise requests.exceptions.HTTPError(
                    f"HTTP {status_code}", response=response
                )
            if not 200 <= status_code < 300:
                raise MetasoMiniMaxUnconfirmedTaskError(
                    "Metaso MiniMax task status is unknown: "
                    f"http_status={status_code}, "
                    f"detail={_response_error(response, api_key)}",
                    task_id=task_id,
                )
            body = response.json()
            task = body.get("task") if isinstance(body, dict) else None
            if not isinstance(task, dict):
                raise MetasoMiniMaxUnconfirmedTaskError(
                    "Metaso MiniMax task status response is malformed",
                    task_id=task_id,
                )
        except MetasoMiniMaxUnconfirmedTaskError:
            raise
        except Exception as exc:
            if not _is_retryable_error(exc):
                raise MetasoMiniMaxUnconfirmedTaskError(
                    "Metaso MiniMax polling failed and the paid task state is "
                    f"unknown: error={type(exc).__name__}, "
                    f"detail={_redact_secret(exc, api_key)}",
                    task_id=task_id,
                ) from exc

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MetasoMiniMaxUnconfirmedTaskError(
                    "Metaso MiniMax task is still running after the configured "
                    f"local wait timeout: id={task_id}",
                    task_id=task_id,
                ) from exc
            consecutive_failures += 1
            if consecutive_failures > MAX_POLL_RETRIES:
                raise MetasoMiniMaxUnconfirmedTaskError(
                    "Metaso MiniMax polling failed after retries; the paid task "
                    f"may still be running remotely: id={task_id}",
                    task_id=task_id,
                ) from exc
            delay = min(RETRY_BASE_SECONDS * consecutive_failures, remaining)
            logger.warning(
                "Metaso MiniMax polling hit a transient error; retrying the same "
                f"task: id={task_id}, attempt={consecutive_failures}/"
                f"{MAX_POLL_RETRIES}, retry_in={delay:.1f}s"
            )
            time.sleep(delay)
            continue

        consecutive_failures = 0
        status = str(task.get("status") or "").strip().lower()
        logger.info(f"Metaso MiniMax task status: id={task_id}, status={status}")
        if status == "succeeded":
            return task
        if status in TERMINAL_FAILURE_STATUSES:
            raise MetasoMiniMaxError(
                "Metaso MiniMax task did not produce a video: "
                f"id={task_id}, status={status}, "
                f"detail={_redact_secret(task.get('error'), api_key)}",
                task_id=task_id,
            )
        if status not in ACTIVE_STATUSES:
            raise MetasoMiniMaxUnconfirmedTaskError(
                "Metaso MiniMax returned an unknown task status: "
                f"id={task_id}, status={status!r}",
                task_id=task_id,
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MetasoMiniMaxUnconfirmedTaskError(
                "Metaso MiniMax task is still running after the configured local "
                f"wait timeout: id={task_id}",
                task_id=task_id,
            )
        time.sleep(min(poll_interval, remaining))
