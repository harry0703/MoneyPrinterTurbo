"""Jalapeno Cloud 视频配置；复用 Seedance 的异步任务与付费重试边界。"""

import math
import os
from collections.abc import Mapping
from urllib.parse import urlsplit

from app.config import config
from app.models.schema import VideoAspect
from app.services import volcengine_seedance as seedance


CAMPAIGN_URL = "https://www.jalapeno-cloud.ai/MoneyPrinterTurbo"
MODELS_URL = "https://www.jalapeno-cloud.ai/models"
DEFAULT_BASE_URL = "https://api.jalapeno-cloud.ai/api/v3"
DEFAULT_MODEL = "Doubao-Seedance-2-5-260628"
DEFAULT_RESOLUTION = "480p"
TASKS_PATH = "/contents/generations/tasks"
DEFAULT_TASKS_URL = DEFAULT_BASE_URL + TASKS_PATH

# 同协议错误保留远端任务 ID，由任务编排层按素材来源归属恢复信息。
JalapenoVideoError = seedance.VolcEngineSeedanceError


def get_api_key(settings: Mapping | None = None) -> str:
    values = config.app if settings is None else settings
    return (
        str(values.get("jalapeno_video_api_key", "") or "").strip()
        or os.getenv("JALAPENO_VIDEO_API_KEY", "").strip()
        or str(values.get("jalapeno_api_key", "") or "").strip()
    )


def is_enabled(settings: Mapping | None = None) -> bool:
    return bool(get_api_key(settings))


def _bounded_seconds(values, suffix, default, minimum, maximum):
    try:
        value = float(values.get(f"jalapeno_video_{suffix}", default))
    except (TypeError, ValueError):
        return default
    return min(max(value, minimum), maximum) if math.isfinite(value) else default


def endpoint(settings: Mapping | None = None) -> seedance.SeedanceEndpoint:
    """一次性校验并解析提交参数，非法地址在配音和付费提交前报错。"""
    values = config.app if settings is None else settings
    key = get_api_key(values)
    if not key:
        raise JalapenoVideoError("Jalapeno Cloud video requires an API key")
    base = (
        str(values.get("jalapeno_video_base_url", "") or DEFAULT_BASE_URL)
        .strip()
        .rstrip("/")
    )
    try:
        parts = urlsplit(base)
        # urlsplit 不会主动校验端口；这里读取一次，避免配音后才发现地址非法。
        parts.port
    except ValueError as exc:
        raise JalapenoVideoError("Jalapeno Cloud video Base URL is invalid") from exc
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise JalapenoVideoError(
            "Jalapeno Cloud video Base URL must be an HTTP(S) URL without credentials or query parameters"
        )
    # 同时接受 Base URL 和活动页示例中的完整任务地址，保证只拼接一次路径。
    tasks_url = base if parts.path.endswith(TASKS_PATH) else base + TASKS_PATH
    model = str(values.get("jalapeno_video_model", "") or DEFAULT_MODEL).strip()
    if not model or len(model) > 200:
        raise JalapenoVideoError(
            "Jalapeno Cloud video model must contain 1-200 characters"
        )
    resolution = (
        str(values.get("jalapeno_video_resolution", DEFAULT_RESOLUTION)).strip().lower()
    )
    if resolution not in seedance.SUPPORTED_RESOLUTIONS:
        raise JalapenoVideoError(
            "Jalapeno Cloud video resolution must be 480p, 720p or 1080p"
        )
    return seedance.SeedanceEndpoint(
        provider_id="jalapeno",
        display_name="Jalapeno Cloud",
        api_key=key,
        tasks_url=tasks_url,
        model=model,
        resolution=resolution,
        run_timeout=_bounded_seconds(values, "run_timeout", 1800, 60, 7200),
        poll_interval=_bounded_seconds(values, "poll_interval", 5, 0.5, 60),
    )


def generate_videos(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
    *,
    endpoint_snapshot: seedance.SeedanceEndpoint | None = None,
):
    return seedance.generate_videos(
        search_term,
        minimum_duration,
        video_aspect,
        endpoint=endpoint_snapshot if endpoint_snapshot is not None else endpoint(),
    )
