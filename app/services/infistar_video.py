"""Infistar 异步文生视频：按已验证的模型规格下单，保留付费任务恢复线索。"""

import hashlib
import math
import os
from pathlib import Path
import tempfile
import time
from collections.abc import Mapping
from urllib.parse import quote, urljoin, urlsplit

import requests
from loguru import logger

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect
from app.services import generation_progress, material_upload
from app.utils.request_logging import sanitize_payload, trace_http_call

DEFAULT_BASE_URL = "https://infistar.cc/v1"
DEFAULT_MODEL = "doubao-seedance-2-0-fast-260128"
# 使用文档示例及实测的短片规格，避免套用其它模型的时长/尺寸约束。
MODELS = {
    DEFAULT_MODEL: {"label": "Seedance 2.0 Fast", "seconds": 5, "size": "720p"},
    "MiniMax-H3": {"label": "MiniMax H3", "seconds": 6, "size": "768p"},
    "kling-v2-6": {"label": "Kling 2.6", "seconds": 5, "size": "720p"},
}
ACTIVE_STATUSES = {"pending", "queued", "in_progress", "running", "processing"}
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024


class InfistarVideoError(RuntimeError):
    def __init__(self, message, task_id=""):
        super().__init__(message)
        self.task_id = task_id


class InfistarVideoUnconfirmedError(InfistarVideoError):
    """付费提交或远端状态未确认，不能自动重新下单。"""


def get_api_key(settings: Mapping | None = None) -> str:
    values = config.app if settings is None else settings
    return (
        str(values.get("infistar_video_api_key", "") or "").strip()
        or os.getenv("INFISTAR_VIDEO_API_KEY", "").strip()
    )


def is_enabled(settings: Mapping | None = None) -> bool:
    return bool(get_api_key(settings))


def model_id(settings: Mapping | None = None) -> str:
    values = config.app if settings is None else settings
    value = str(values.get("infistar_video_model", "") or DEFAULT_MODEL).strip()
    if value not in MODELS:
        raise InfistarVideoError(f"Unsupported Infistar video model: {value}")
    return value


def _base_url() -> str:
    # 视频配置独立于 LLM；切换大模型或修改其网关时，不改变视频的凭据和地址。
    value = (
        str(config.app.get("infistar_video_base_url", "") or DEFAULT_BASE_URL)
        .strip()
        .rstrip("/")
    )
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.netloc
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise InfistarVideoError(
            "Infistar Base URL must be an HTTP(S) URL without credentials or query parameters"
        )
    return value


def _setting_seconds(key, default, minimum, maximum):
    try:
        value = float(config.app.get(key, default))
    except (ValueError, TypeError):
        return default
    return min(max(value, minimum), maximum) if math.isfinite(value) else default


def _request(method, url, **kwargs):
    verify = config.app.get("tls_verify", True)
    if isinstance(verify, str):
        verify = verify.lower().strip() not in {"false", "0", "off", "no", ""}
    return trace_http_call(
        method,
        getattr(requests, method.lower()),
        url,
        proxies=config.proxy,
        verify=bool(verify),
        allow_redirects=False,
        **kwargs,
    )


def _detail(response, secret):
    try:
        body = response.json()
        error = (body.get("error") or body) if isinstance(body, dict) else {}
        text = error.get("message", "") if isinstance(error, dict) else str(error)
    except (ValueError, TypeError):
        text = ""
    return str(sanitize_payload(str(text).replace(secret, "***")))[:500]


def _json(response, task_id=""):
    try:
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError()
        return body
    except (ValueError, TypeError) as exc:
        raise InfistarVideoUnconfirmedError(
            "Infistar returned an unreadable task response", task_id
        ) from exc


def _wait(task_id, base, headers, secret):
    deadline = time.monotonic() + _setting_seconds(
        "infistar_video_run_timeout", 1800, 60, 7200
    )
    interval = _setting_seconds("infistar_video_poll_interval", 5, 1, 60)
    generation_progress.remote("infistar", task_id)
    failures = 0
    previous = ""
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        phase = max(min(remaining / 2, 30), 0.001)
        try:
            response = _request(
                "GET",
                f"{base}/videos/{quote(task_id, safe='')}",
                headers=headers,
                timeout=(phase, phase),
            )
            if response.status_code in {429, 500, 502, 503, 504}:
                raise requests.HTTPError(f"HTTP {response.status_code}")
            if response.status_code != 200:
                raise InfistarVideoUnconfirmedError(
                    f"Infistar task status unavailable: HTTP {response.status_code}, {_detail(response, secret)}",
                    task_id,
                )
            body = _json(response, task_id)
        except (requests.RequestException, OSError) as exc:
            failures += 1
            generation_progress.remote("infistar", task_id, retrying=True)
            if failures > 5:
                raise InfistarVideoUnconfirmedError(
                    "Infistar polling failed; keep the task ID and check the console",
                    task_id,
                ) from exc
            time.sleep(min(interval, max(deadline - time.monotonic(), 0)))
            continue
        failures = 0
        status = str(body.get("status", "")).strip().lower()
        generation_progress.remote("infistar", task_id, status)
        if status != previous:
            logger.info(f"Infistar video task: id={task_id}, status={status}")
            previous = status
        if status in {"completed", "succeeded"}:
            return body
        if status in {"failed", "error", "cancelled", "canceled", "expired"}:
            detail = str(
                sanitize_payload(str(body.get("error", "")).replace(secret, "***"))
            )[:500]
            raise InfistarVideoError(f"Infistar video task failed: {detail}", task_id)
        if status not in ACTIVE_STATUSES:
            raise InfistarVideoUnconfirmedError(
                f"Infistar returned an unknown status: {status!r}", task_id
            )
        time.sleep(min(interval, max(deadline - time.monotonic(), 0)))
    raise InfistarVideoUnconfirmedError(
        "Infistar video is still running after the local wait timeout", task_id
    )


def _download(task_id, base, headers, output_dir):
    """仅向原始 content 端点发送 Key；重定向到对象存储后不携带凭据。"""
    generation_progress.downloading()
    url = f"{base}/videos/{quote(task_id, safe='')}/content"
    response = None
    staged = None
    try:
        for hop in range(6):
            response = _request(
                "GET",
                url,
                headers=headers if hop == 0 else {},
                timeout=(30, 120),
                stream=True,
            )
            if response.status_code not in {301, 302, 303, 307, 308}:
                break
            next_url = urljoin(url, response.headers.get("Location", ""))
            response.close()
            response = None
            if urlsplit(next_url).scheme != "https" or not urlsplit(next_url).hostname:
                raise ValueError("Video download redirected to an invalid URL")
            url = next_url
        else:
            raise ValueError("Too many video download redirects")
        if response.status_code != 200:
            raise ValueError(f"Video download failed: HTTP {response.status_code}")
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(task_id.encode()).hexdigest()[:24] + ".mp4"
        destination = Path(output_dir) / f"infistar-{name}"
        with tempfile.NamedTemporaryFile(
            dir=output_dir, suffix=".part", delete=False
        ) as stream:
            staged = Path(stream.name)
            count = 0
            for chunk in response.iter_content(1024 * 1024):
                count += len(chunk)
                if count > MAX_DOWNLOAD_BYTES:
                    raise ValueError("Video download exceeds 512 MiB")
                stream.write(chunk)
                generation_progress.downloading(count)
            if count == 0:
                raise ValueError("Video download is empty")
        # 复用素材验证：拒绝错误页、播放列表和仅有文件头的截断视频，
        # 完整解码成功后才将原子落盘的文件交给后续素材编排。
        generation_progress.verifying()
        material_upload._validate_video(str(staged))
        from moviepy import VideoFileClip

        with VideoFileClip(str(staged)) as clip:
            duration = float(clip.duration)
            width, height = clip.size
            if not math.isfinite(duration) or duration < 1:
                raise ValueError("Generated video is shorter than one second")
        staged.replace(destination)
        return destination, duration, width, height
    except Exception as exc:
        raise InfistarVideoError(
            f"Infistar generated a paid video but download/validation failed ({type(exc).__name__}); keep the task ID to recover it",
            task_id,
        ) from exc
    finally:
        if response is not None:
            response.close()
        if staged is not None:
            staged.unlink(missing_ok=True)


def generate_video(*, search_term, video_aspect, output_dir) -> MaterialInfo:
    secret = get_api_key()
    if not secret:
        raise InfistarVideoError("Infistar video generation requires an API key")
    model = model_id()
    profile = MODELS[model]
    aspect = VideoAspect(video_aspect)
    if aspect not in {VideoAspect.landscape, VideoAspect.portrait}:
        raise InfistarVideoError("Infistar video currently supports 16:9 and 9:16")
    term = str(search_term or "").strip()
    if not term or len(term) > 2000:
        raise InfistarVideoError("Infistar video prompt must contain 1-2000 characters")
    base = _base_url()
    headers = {"Authorization": f"Bearer {secret}"}
    size = "1280x720" if aspect == VideoAspect.landscape else "720x1280"
    if model == "MiniMax-H3":
        size = "768p"
    payload = {
        "model": model,
        "prompt": term,
        "seconds": str(profile["seconds"]),
        "size": size,
    }
    # 当前 MiniMax 线路忽略 aspect_ratio，size 只接受分辨率档位。
    # 明确生成横屏素材，竖屏成片由既有画面适配逻辑裁剪或留边；WebUI 同步提示。
    generation_progress.submitting("infistar")
    try:
        response = _request(
            "POST", f"{base}/videos", json=payload, headers=headers, timeout=(30, 90)
        )
    except requests.RequestException as exc:
        raise InfistarVideoUnconfirmedError(
            "Infistar submission returned no response; a paid task may already exist. Check the console before retrying."
        ) from exc
    if response.status_code >= 500 or 300 <= response.status_code < 400:
        raise InfistarVideoUnconfirmedError(
            f"Infistar submission unconfirmed: HTTP {response.status_code}; do not resubmit automatically"
        )
    if not 200 <= response.status_code < 300:
        raise InfistarVideoError(
            f"Infistar video request rejected: HTTP {response.status_code}, {_detail(response, secret)}"
        )
    body = _json(response)
    task_id = str(body.get("id") or body.get("task_id") or "").strip()
    if not task_id:
        raise InfistarVideoUnconfirmedError(
            "Infistar accepted the submission without a task ID; check the console"
        )
    logger.info(f"Infistar paid video task created: id={task_id}, model={model}")
    _wait(task_id, base, headers, secret)
    path, duration, width, height = _download(task_id, base, headers, output_dir)
    return MaterialInfo(
        provider="infistar",
        url=str(path),
        duration=int(duration),
        source_info={
            "provider": "infistar",
            "search_term": term,
            "asset_id": task_id,
            "rendition": {"id": model, "width": width, "height": height},
        },
    )
