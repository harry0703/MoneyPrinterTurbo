"""
Direct YouTube publishing through the official YouTube Data API v3.

发布使用官方 ``google-api-python-client``，凭据来自配置中的 OAuth2
client id / client secret / refresh token。刷新令牌可以在服务端离线续期，
因此容器和无桌面环境也不需要在应用内打开浏览器授权页。
"""

import json
import os
import time
from types import SimpleNamespace
from typing import Any, Iterable

from loguru import logger

from app.config import config


PLATFORM = "youtube"
TOKEN_URI = "https://oauth2.googleapis.com/token"
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
WATCH_URL_TEMPLATE = "https://www.youtube.com/watch?v={video_id}"
PRIVACY_STATUSES = ("public", "unlisted", "private")
DEFAULT_PRIVACY_STATUS = "public"
# 22 = People & Blogs，是短视频最通用且在所有地区都可用的分类。
DEFAULT_CATEGORY_ID = "22"
DEFAULT_TITLE = "Untitled video"
# YouTube 对元数据的硬性限制；超出时接口直接返回 400，因此在本地先裁剪。
MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 5000
MAX_TAGS_TOTAL_LENGTH = 500
# 标题和简介不接受尖括号，YouTube 会以 invalidVideoMetadata 拒绝整次上传。
INVALID_METADATA_CHARS = ("<", ">")
UPLOAD_CHUNK_SIZE = 4 * 1024 * 1024
# 断点续传只对 5xx 和限流重试；4xx 属于请求本身的问题，重试只会浪费配额。
RETRIABLE_STATUS_CODES = frozenset({500, 502, 503, 504})
MAX_RETRIABLE_ATTEMPTS = 5
MAX_RETRY_BACKOFF_SECONDS = 32
# 这些原因每天都会遇到，但排查方向完全不同。把处理建议直接写进任务状态，
# 调用方不必再去翻 YouTube 的错误码文档。
ERROR_HINTS = {
    "youtubeSignupRequired": (
        "the authorized Google account has no YouTube channel; create one at "
        "youtube.com, or re-authorize with the account that owns the channel"
    ),
    "quotaExceeded": (
        "the daily API quota is exhausted; each upload costs 1600 units of the "
        "default 10000 per day"
    ),
    "forbidden": (
        "the account is not allowed to upload; check that the channel is in "
        "good standing and that uploads are not restricted"
    ),
    "uploadLimitExceeded": (
        "the channel reached its daily upload limit; retry after 24 hours"
    ),
    "invalidVideoMetadata": (
        "the title, description or tags were rejected; check for unsupported "
        "characters or length limits"
    ),
}
MISSING_DEPENDENCY_ERROR = (
    "YouTube publishing requires the official Google API client. "
    "Install it with `uv sync --extra youtube` or "
    "`pip install google-api-python-client google-auth`."
)


class YouTubeUploadError(RuntimeError):
    """表示 YouTube 发布的配置、凭据或接口调用失败。"""


def _load_google_modules() -> SimpleNamespace:
    """延迟导入官方 SDK，未安装可选依赖时也不影响其它功能启动。"""
    try:
        from google.auth.exceptions import GoogleAuthError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise YouTubeUploadError(MISSING_DEPENDENCY_ERROR) from exc

    return SimpleNamespace(
        GoogleAuthError=GoogleAuthError,
        Request=Request,
        Credentials=Credentials,
        build=build,
        HttpError=HttpError,
        MediaFileUpload=MediaFileUpload,
    )


def normalize_privacy_status(value: Any) -> str:
    """把配置或调用方传入的隐私状态收敛到接口接受的三个取值。"""
    candidate = str(value or "").strip().lower()
    if candidate in PRIVACY_STATUSES:
        return candidate
    return DEFAULT_PRIVACY_STATUS


def _clean_metadata_text(value: Any) -> str:
    text = str(value or "")
    for char in INVALID_METADATA_CHARS:
        text = text.replace(char, "")
    return text.strip()


def normalize_title(title: Any, fallback: Any = "") -> str:
    """标题为空会被接口拒绝，因此始终回落到可发布的非空文本。"""
    text = _clean_metadata_text(title) or _clean_metadata_text(fallback) or DEFAULT_TITLE
    # 换行在标题里会被 YouTube 拒绝，只保留第一行仍然是可读的标题。
    text = " ".join(text.split())
    return text[:MAX_TITLE_LENGTH]


def normalize_description(description: Any) -> str:
    return _clean_metadata_text(description)[:MAX_DESCRIPTION_LENGTH]


def normalize_tags(tags: Iterable[Any] | None) -> list[str]:
    """去掉话题符号并按 YouTube 的 500 字符总额度截断，保留原有顺序。"""
    if not tags:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    used_length = 0
    for raw_tag in tags:
        tag = str(raw_tag or "").lstrip("#").strip()
        if not tag:
            continue
        lowered = tag.casefold()
        if lowered in seen:
            continue
        # 含空格的标签在计费时按带引号的形式计算长度。
        cost = len(tag) + (2 if " " in tag else 0)
        if used_length:
            cost += 1
        if used_length + cost > MAX_TAGS_TOTAL_LENGTH:
            continue
        used_length += cost
        seen.add(lowered)
        normalized.append(tag)
    return normalized


def _http_error_status(error: Exception) -> int | None:
    return getattr(getattr(error, "resp", None), "status", None)


def _http_error_reasons(error: Exception) -> tuple[list[str], str]:
    """
    从响应体中取出 API 自己的错误原因。

    ``HttpError.reason`` 只给出 HTTP 状态短语，例如 401 会显示 Unauthorized，
    真正可定位的信息在响应体的 ``error.errors[].reason`` 里。缺少频道时返回
    ``youtubeSignupRequired``，配额耗尽时返回 ``quotaExceeded``，两者的处理
    方式完全不同，因此必须原样保留给调用方。
    """
    content = getattr(error, "content", None)
    if isinstance(content, (bytes, bytearray)):
        content = content.decode("utf-8", "replace")
    if not isinstance(content, str) or not content.strip():
        return [], ""

    try:
        payload = json.loads(content)
    except ValueError:
        return [], ""
    if not isinstance(payload, dict):
        return [], ""

    error_payload = payload.get("error")
    if not isinstance(error_payload, dict):
        return [], ""

    reasons = []
    for item in error_payload.get("errors") or []:
        if isinstance(item, dict):
            reason = str(item.get("reason") or "").strip()
            if reason and reason not in reasons:
                reasons.append(reason)

    message = str(error_payload.get("message") or "").strip()
    return reasons, message


def _describe_http_error(error: Exception) -> str:
    """优先使用 API 返回的原因，让配额或权限问题不必翻服务端日志就能定位。"""
    status = _http_error_status(error)
    reasons, message = _http_error_reasons(error)

    detail = ", ".join(reasons)
    if message and message != detail:
        detail = f"{detail} ({message})" if detail else message
    if not detail:
        reason = getattr(error, "reason", None)
        detail = reason.strip() if isinstance(reason, str) and reason.strip() else str(error)

    hint = ERROR_HINTS.get(reasons[0]) if reasons else None
    if hint:
        detail = f"{detail}. {hint}"

    if status:
        return f"YouTube API error {status}: {detail}"
    return f"YouTube API error: {detail}"


class YouTubeUploadService:
    """使用 YouTube Data API v3 直接发布成片。"""

    @property
    def client_id(self) -> str:
        return str(config.app.get("youtube_client_id", "") or "").strip()

    @property
    def client_secret(self) -> str:
        return str(config.app.get("youtube_client_secret", "") or "").strip()

    @property
    def refresh_token(self) -> str:
        return str(config.app.get("youtube_refresh_token", "") or "").strip()

    @property
    def enabled(self) -> bool:
        return bool(config.app.get("youtube_enabled", False))

    @property
    def auto_upload(self) -> bool:
        return bool(config.app.get("youtube_auto_upload", False))

    @property
    def privacy_status(self) -> str:
        # 旧版本的 YouTube 发布走 Upload-Post，隐私状态保存在它的配置项里。
        # 升级到官方接口后继续沿用该值，用户不需要重新设置一次。
        value = config.app.get("youtube_privacy_status")
        if value is None:
            value = config.app.get("upload_post_youtube_privacy_status")
        return normalize_privacy_status(value)

    @property
    def category_id(self) -> str:
        value = str(config.app.get("youtube_category_id", "") or "").strip()
        return value or DEFAULT_CATEGORY_ID

    @property
    def made_for_kids(self) -> bool:
        return bool(config.app.get("youtube_made_for_kids", False))

    @property
    def contains_synthetic_media(self) -> bool:
        # 成片由 TTS 和素材合成，默认按 YouTube 的合成内容披露要求申报。
        return bool(config.app.get("youtube_contains_synthetic_media", True))

    def is_configured(self) -> bool:
        return bool(
            self.enabled
            and self.client_id
            and self.client_secret
            and self.refresh_token
        )

    def _build_client(self, modules: SimpleNamespace):
        credentials = modules.Credentials(
            token=None,
            refresh_token=self.refresh_token,
            client_id=self.client_id,
            client_secret=self.client_secret,
            token_uri=TOKEN_URI,
            scopes=[UPLOAD_SCOPE],
        )
        try:
            # 先换取访问令牌，凭据失效时可以在打开视频文件之前就明确报错。
            credentials.refresh(modules.Request())
        except modules.GoogleAuthError as exc:
            raise YouTubeUploadError(
                f"failed to refresh the YouTube OAuth credentials: {exc}"
            ) from exc

        # 发现文档缓存需要可写目录，容器只读挂载时会直接抛出异常。
        return modules.build(
            "youtube", "v3", credentials=credentials, cache_discovery=False
        )

    def _execute_resumable_upload(self, request, modules: SimpleNamespace) -> dict:
        response = None
        attempt = 0
        while response is None:
            try:
                _, response = request.next_chunk()
            except modules.HttpError as exc:
                status = _http_error_status(exc)
                if status not in RETRIABLE_STATUS_CODES:
                    raise
                attempt += 1
                if attempt > MAX_RETRIABLE_ATTEMPTS:
                    raise
                backoff = min(2**attempt, MAX_RETRY_BACKOFF_SECONDS)
                logger.warning(
                    f"retriable YouTube upload error {status}, "
                    f"attempt: {attempt}/{MAX_RETRIABLE_ATTEMPTS}, "
                    f"retrying in {backoff}s"
                )
                time.sleep(backoff)
        if not isinstance(response, dict):
            raise YouTubeUploadError("YouTube returned an invalid upload response")
        return response

    def upload_video(
        self,
        video_path: str,
        title: str,
        description: str = "",
        tags: Iterable[Any] | None = None,
        privacy_status: str | None = None,
        category_id: str | None = None,
        made_for_kids: bool | None = None,
        contains_synthetic_media: bool | None = None,
    ) -> dict:
        """
        发布单个成片，并始终返回稳定结构而不抛出异常。

        返回 ``{"success": bool, "platform": "youtube", ...}``，成功时附带
        ``video_id`` 和 ``url``，失败时附带可直接展示给用户的 ``error``。
        """
        if not self.is_configured():
            logger.warning("YouTube publishing is not configured. Skipping upload.")
            return {
                "success": False,
                "platform": PLATFORM,
                "error": "YouTube publishing is not configured",
            }

        if not video_path or not os.path.exists(video_path):
            logger.error(f"Video file not found: {video_path}")
            return {
                "success": False,
                "platform": PLATFORM,
                "error": f"Video file not found: {video_path}",
            }

        resolved_privacy = normalize_privacy_status(
            privacy_status if privacy_status is not None else self.privacy_status
        )
        body = {
            "snippet": {
                "title": normalize_title(title),
                "description": normalize_description(description),
                "tags": normalize_tags(tags),
                "categoryId": str(
                    category_id if category_id is not None else self.category_id
                ),
            },
            "status": {
                "privacyStatus": resolved_privacy,
                "selfDeclaredMadeForKids": bool(
                    self.made_for_kids if made_for_kids is None else made_for_kids
                ),
                "containsSyntheticMedia": bool(
                    self.contains_synthetic_media
                    if contains_synthetic_media is None
                    else contains_synthetic_media
                ),
            },
        }

        logger.info(
            f"uploading video to YouTube: {video_path}, privacy: {resolved_privacy}"
        )

        media = None
        try:
            modules = _load_google_modules()
            client = self._build_client(modules)
            media = modules.MediaFileUpload(
                video_path,
                chunksize=UPLOAD_CHUNK_SIZE,
                resumable=True,
                mimetype="video/*",
            )
            request = client.videos().insert(
                part="snippet,status", body=body, media_body=media
            )
            response = self._execute_resumable_upload(request, modules)
        except YouTubeUploadError as exc:
            logger.error(f"failed to publish to YouTube: {exc}")
            return {"success": False, "platform": PLATFORM, "error": str(exc)}
        except Exception as exc:
            # 官方客户端会抛出 HttpError、socket 超时等多种异常。发布失败不能
            # 反向影响已经生成的成片，因此统一转换成可查询的失败结果。
            if _http_error_status(exc) is not None:
                message = _describe_http_error(exc)
            else:
                message = f"{type(exc).__name__}: {exc}"
            logger.error(f"failed to publish to YouTube: {message}")
            return {"success": False, "platform": PLATFORM, "error": message}
        finally:
            # MediaFileUpload 会一直持有文件句柄，任务目录清理前必须释放。
            stream = getattr(media, "stream", None)
            if callable(stream):
                try:
                    stream().close()
                except Exception:
                    pass

        video_id = str(response.get("id") or "")
        if not video_id:
            logger.error("YouTube upload response did not contain a video id")
            return {
                "success": False,
                "platform": PLATFORM,
                "error": "YouTube upload response did not contain a video id",
            }

        url = WATCH_URL_TEMPLATE.format(video_id=video_id)
        logger.success(f"✅ Video published to YouTube: {url}")
        return {
            "success": True,
            "platform": PLATFORM,
            "video_id": video_id,
            "url": url,
            "privacy_status": str(
                (response.get("status") or {}).get("privacyStatus") or resolved_privacy
            ),
        }


# Singleton instance
youtube_upload_service = YouTubeUploadService()


def publish_video(
    video_path: str,
    title: str,
    description: str = "",
    tags: Iterable[Any] | None = None,
    privacy_status: str | None = None,
) -> dict:
    return youtube_upload_service.upload_video(
        video_path=video_path,
        title=title,
        description=description,
        tags=tags,
        privacy_status=privacy_status,
    )
