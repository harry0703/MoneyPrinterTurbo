import hashlib
import json
import os
import random
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, List
from urllib.parse import quote_plus, urlencode, urlsplit, urlunsplit

import requests
from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoConcatMode
from app.services import material_cache
from app.utils import utils

# Thread-safe counter for API key rotation
_api_key_counter = 0
_api_key_lock = threading.Lock()


class ProvenanceWriteError(RuntimeError):
    """The material result cannot be returned without its provenance sidecar."""


def _get_provenance(item: MaterialInfo) -> dict[str, Any]:
    value = getattr(item, "_provider_provenance", None)
    return value if isinstance(value, dict) else {}


def _set_provenance(item: MaterialInfo, value: dict[str, Any]) -> None:
    setattr(item, "_provider_provenance", value)


def _canonical_json_sha256(value: Any) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _safe_public_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _creator(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str) and value.strip():
        return {"id": None, "name": value.strip(), "profile_page": None}
    if not isinstance(value, dict):
        return None
    creator_id = value.get("id")
    name = value.get("name") or value.get("username")
    profile_page = _safe_public_url(
        value.get("url") or value.get("profile_url") or value.get("profile_page")
    )
    if creator_id is None and not name and profile_page is None:
        return None
    return {
        "id": str(creator_id) if creator_id is not None else None,
        "name": str(name) if name else None,
        "profile_page": profile_page,
    }


def _material_identity(item: MaterialInfo) -> tuple[Any, ...]:
    provenance = _get_provenance(item)
    rendition = provenance.get("rendition")
    rendition_id = rendition.get("id") if isinstance(rendition, dict) else None
    asset_id = provenance.get("asset_id")
    if asset_id is not None and rendition_id is not None:
        return item.provider, str(asset_id), str(rendition_id)
    return item.provider, _safe_public_url(item.url)


def _safe_attempt(item: MaterialInfo, status: str, error_code: str | None = None) -> dict[str, Any]:
    provenance = _get_provenance(item)
    rendition = provenance.get("rendition")
    result = {
        "status": status,
        "provider": item.provider,
        "asset_id": provenance.get("asset_id"),
        "rendition_id": rendition.get("id") if isinstance(rendition, dict) else None,
        "search_term": provenance.get("search_term"),
        "rendition_url": _safe_public_url(item.url),
    }
    if error_code is not None:
        result["error_code"] = error_code
    return result


def _local_artifact(path_value: str) -> dict[str, Any]:
    path = Path(path_value).expanduser().absolute()
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            raise ProvenanceWriteError("material provenance local artifact is missing")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return {
            "path": str(path),
            "sha256": digest.hexdigest(),
            "bytes": path.stat().st_size,
        }
    except ProvenanceWriteError:
        raise
    except OSError as error:
        raise ProvenanceWriteError(
            "material provenance local artifact could not be hashed"
        ) from error


def _material_record(
    item: MaterialInfo,
    path: str,
    selection_index: int,
    max_clip_duration: int,
) -> dict[str, Any]:
    source = _get_provenance(item)
    creator = source.get("creator")
    safe_creator = None
    if isinstance(creator, dict):
        safe_creator = {
            "id": creator.get("id"),
            "name": creator.get("name"),
            "profile_page": _safe_public_url(creator.get("profile_page")),
        }
    rendition = source.get("rendition")
    safe_rendition: dict[str, Any] = {}
    if isinstance(rendition, dict):
        allowed_rendition_fields = (
            "id",
            "kind",
            "quality",
            "mime_type",
            "width",
            "height",
            "fps",
            "declared_bytes",
            "aspect_ratio",
        )
        safe_rendition = {
            field: rendition.get(field) for field in allowed_rendition_fields
        }
        safe_rendition["url"] = _safe_public_url(rendition.get("url") or item.url)
    rights = source.get("rights")
    safe_rights: dict[str, Any] = {}
    if isinstance(rights, dict):
        for field in (
            "license_status",
            "attribution_status",
            "commercial_use",
            "api_attribution_logo_required",
        ):
            if field in rights:
                safe_rights[field] = rights[field]
        if "reference" in rights:
            safe_rights["reference"] = _safe_public_url(rights.get("reference"))
    warnings = []
    if item.provider == "coverr":
        warnings.append(
            "Coverr API and content-license attribution terms require separate review."
        )
    elif not source.get("asset_id"):
        warnings.append("Provider identity was unavailable from the search result.")
    return {
        "selection_index": selection_index,
        "search_term": source.get("search_term"),
        "provider": item.provider,
        "asset_id": source.get("asset_id"),
        "canonical_page": _safe_public_url(source.get("canonical_page")),
        "creator": safe_creator,
        "provider_response_sha256": source.get("provider_response_sha256"),
        "provider_result_index": source.get("provider_result_index"),
        "provider_duration_sec": source.get("provider_duration_sec"),
        "rendition": safe_rendition,
        "rights": safe_rights,
        "warnings": warnings,
        "effective_clip_duration_sec": min(max_clip_duration, item.duration),
        "local": _local_artifact(path),
    }


def _provenance_status(materials: list[dict[str, Any]]) -> str:
    if not materials:
        return "FAIL"
    required = ("provider", "asset_id", "search_term", "provider_response_sha256", "rendition")
    def complete(item: dict[str, Any]) -> bool:
        response_hash = item.get("provider_response_sha256")
        local = item.get("local")
        local_path = local.get("path") if isinstance(local, dict) else None
        local_sha256 = local.get("sha256") if isinstance(local, dict) else None
        local_bytes = local.get("bytes") if isinstance(local, dict) else None
        return (
            all(item.get(field) not in (None, "") for field in required)
            and isinstance(local_path, str)
            and Path(local_path).is_absolute()
            and isinstance(local_sha256, str)
            and len(local_sha256) == 64
            and all(character in "0123456789abcdef" for character in local_sha256)
            and isinstance(local_bytes, int)
            and not isinstance(local_bytes, bool)
            and local_bytes > 0
            and isinstance(item.get("rendition"), dict)
            and item["rendition"].get("id") not in (None, "")
            and isinstance(response_hash, str)
            and len(response_hash) == 64
            and all(character in "0123456789abcdef" for character in response_hash)
        )

    return (
        "PASS"
        if all(complete(item) for item in materials)
        else "INCONCLUSIVE"
    )


def _fsync_parent_directory(path: Path, platform: str | None = None) -> None:
    if (platform or os.name) == "nt":
        return
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _write_provenance_sidecar(task_id: str, receipt: dict[str, Any]) -> None:
    target = Path(utils.task_dir(task_id)) / "materials-provenance.json"
    rendered = (
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    temp_path: Path | None = None
    published = False
    try:
        if target.exists() or target.is_symlink():
            if not target.is_symlink() and target.is_file() and target.read_bytes() == rendered:
                return
            raise ProvenanceWriteError("material provenance sidecar collision")
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            delete=False,
        ) as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.link(temp_path, target)
        published = True
        temp_path.unlink()
        temp_path = None
        _fsync_parent_directory(target.parent)
    except ProvenanceWriteError:
        raise
    except OSError as error:
        if published:
            try:
                target.unlink()
            except OSError:
                pass
        raise ProvenanceWriteError("material provenance sidecar write failed") from error
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _publish_download_provenance(
    *,
    task_id: str,
    source: str,
    search_terms: List[str],
    video_aspect: VideoAspect,
    video_concat_mode: VideoConcatMode,
    match_script_order: bool,
    audio_duration: float,
    max_clip_duration: int,
    materials: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
) -> None:
    aspect_value = getattr(video_aspect, "value", video_aspect)
    concat_value = getattr(video_concat_mode, "value", video_concat_mode)
    receipt = {
        "schema_version": 1,
        "scope": "material_provider_provenance",
        "status": _provenance_status(materials),
        "task_id": task_id,
        "provider": source,
        "request": {
            "search_terms": list(search_terms),
            "video_aspect": aspect_value,
            "video_concat_mode": concat_value,
            "match_script_order": match_script_order,
            "audio_duration_sec": audio_duration,
            "max_clip_duration_sec": max_clip_duration,
        },
        "materials": materials,
        "attempts": attempts,
        "approval_scope": "provider_identity_and_local_byte_binding_only",
    }
    _write_provenance_sidecar(task_id, receipt)


def _get_tls_verify() -> bool:
    # 默认开启 TLS 证书校验，防止素材搜索和下载过程被中间人篡改。
    # 仅在企业代理、自签证书等明确需要的场景下，允许用户通过
    # `config.toml` 显式设置 `tls_verify = false` 临时关闭。
    tls_verify = config.app.get("tls_verify", True)
    if isinstance(tls_verify, str):
        tls_verify = tls_verify.strip().lower() not in ("0", "false", "no", "off")

    if not tls_verify:
        logger.warning(
            "TLS certificate verification is disabled by config.app.tls_verify=false. "
            "Only use this in trusted proxy environments."
        )

    return bool(tls_verify)


def get_api_key(cfg_key: str):
    api_keys = config.app.get(cfg_key)
    if not api_keys:
        raise ValueError(
            f"\n\n##### {cfg_key} is not set #####\n\nPlease set it in the config.toml file: {config.config_file}\n\n"
        )

    # if only one key is provided, return it
    if isinstance(api_keys, str):
        return api_keys

    global _api_key_counter
    with _api_key_lock:
        _api_key_counter += 1
        return api_keys[_api_key_counter % len(api_keys)]


def _redact_secret(message: str, secret: str) -> str:
    """
    对即将写入日志的异常文本做最小范围脱敏。

    requests 的连接异常可能包含完整请求 URL，而 Pixabay API Key 通过查询
    参数传递。这里同时替换原始值和 URL 编码值，既保留网络错误信息用于排查，
    又避免密钥进入日志文件。
    """
    safe_message = str(message)
    if not secret:
        return safe_message

    safe_message = safe_message.replace(secret, "***")
    encoded_secret = quote_plus(secret)
    if encoded_secret != secret:
        safe_message = safe_message.replace(encoded_secret, "***")
    return safe_message


def _is_cloudflare_challenge(response: requests.Response) -> bool:
    """
    识别 Cloudflare 返回的 HTML Challenge，而不是把它当成 Pixabay JSON。

    Cloudflare 通常会设置 `cf-mitigated: challenge`；部分部署只返回带有
    "Just a moment" 或 challenge-platform 的 HTML，因此保留内容特征兜底。
    响应正文仅在内存中判断，不写入日志，避免记录无价值的大段 HTML。
    """
    headers = getattr(response, "headers", {}) or {}
    if str(headers.get("cf-mitigated", "")).lower() == "challenge":
        return True

    content_type = str(headers.get("content-type", "")).lower()
    if "text/html" not in content_type:
        return False

    body = str(getattr(response, "text", "")).lower()
    return "just a moment" in body or "/cdn-cgi/challenge-platform/" in body


def search_videos_pexels(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)
    video_orientation = aspect.name
    video_width, video_height = aspect.to_resolution()
    api_key = get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    }
    # Build URL
    params = {"query": search_term, "per_page": 20, "orientation": video_orientation}
    query_url = f"https://api.pexels.com/videos/search?{urlencode(params)}"
    logger.info(f"searching videos on pexels: term={search_term!r}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        response = r.json()
        response_sha256 = _canonical_json_sha256(response)
        video_items = []
        if "videos" not in response:
            logger.error("pexels video search returned an unsupported response")
            return video_items
        videos = response["videos"]
        # loop through each video in the result
        for result_index, v in enumerate(videos):
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["video_files"]
            # loop through each url to determine the best quality
            for video in video_files:
                w = int(video["width"])
                h = int(video["height"])
                if w == video_width and h == video_height:
                    item = MaterialInfo()
                    item.provider = "pexels"
                    item.url = video["link"]
                    item.duration = duration
                    user = v.get("user")
                    _set_provenance(item, {
                        "search_term": search_term,
                        "provider": "pexels",
                        "asset_id": str(v.get("id")) if v.get("id") is not None else None,
                        "canonical_page": _safe_public_url(v.get("url")),
                        "creator": _creator(user),
                        "provider_response_sha256": response_sha256,
                        "provider_result_index": result_index,
                        "provider_duration_sec": duration,
                        "rendition": {
                            "id": str(video.get("id")) if video.get("id") is not None else None,
                            "kind": "video_file",
                            "quality": video.get("quality"),
                            "mime_type": video.get("file_type"),
                            "width": w,
                            "height": h,
                            "fps": video.get("fps"),
                            "declared_bytes": video.get("file_size") or video.get("size"),
                            "url": _safe_public_url(video.get("link")),
                        },
                        "rights": {
                            "license_status": "not_evaluated",
                            "attribution_status": "not_evaluated",
                        },
                        "warnings": [],
                    })
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(f"pexels video search failed: {type(e).__name__}")

    return []


def search_videos_pixabay(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)

    video_width, video_height = aspect.to_resolution()

    api_key = get_api_key("pixabay_api_keys")
    # Build URL
    params = {
        "q": search_term,
        "video_type": "all",  # Accepted values: "all", "film", "animation"
        "per_page": 50,
        "key": api_key,
    }
    query_url = f"https://pixabay.com/api/videos/?{urlencode(params)}"
    logger.info(
        f"searching videos on pixabay: term={search_term!r}, "
        f"proxy_enabled={bool(config.proxy)}"
    )

    try:
        r = requests.get(
            query_url, proxies=config.proxy, verify=_get_tls_verify(), timeout=(30, 60)
        )
        status_code = int(getattr(r, "status_code", 200))
        headers = getattr(r, "headers", {}) or {}
        content_type = str(headers.get("content-type", ""))
        retry_after = headers.get("retry-after")
        cf_ray = headers.get("cf-ray")

        if _is_cloudflare_challenge(r):
            logger.error(
                "pixabay search was blocked by a Cloudflare challenge: "
                f"status={status_code}, cf_ray={cf_ray or 'unknown'}. "
                "Check the server network or proxy, or use Pexels/Coverr instead."
            )
            return []

        if status_code == 429:
            logger.error(
                "pixabay API rate limit exceeded: "
                f"status=429, retry_after={retry_after or 'unknown'}"
            )
            return []

        if status_code >= 400:
            logger.error(
                "pixabay search request failed: "
                f"status={status_code}, content_type={content_type or 'unknown'}"
            )
            return []

        try:
            response = r.json()
        except ValueError:
            logger.error(
                "pixabay returned an unexpected non-JSON response: "
                f"status={status_code}, content_type={content_type or 'unknown'}"
            )
            return []
        response_sha256 = _canonical_json_sha256(response)
        video_items = []
        if "hits" not in response:
            logger.error("pixabay video search returned an unsupported response")
            return video_items
        videos = response["hits"]
        # loop through each video in the result
        for result_index, v in enumerate(videos):
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["videos"]
            # loop through each url to determine the best quality
            for video_type, video in video_files.items():
                w = int(video["width"])
                # h = int(video["height"])
                if w >= video_width:
                    item = MaterialInfo()
                    item.provider = "pixabay"
                    item.url = video["url"]
                    item.duration = duration
                    _set_provenance(item, {
                        "search_term": search_term,
                        "provider": "pixabay",
                        "asset_id": str(v.get("id")) if v.get("id") is not None else None,
                        "canonical_page": _safe_public_url(v.get("pageURL")),
                        "creator": {
                            "id": str(v.get("user_id")) if v.get("user_id") is not None else None,
                            "name": v.get("user"),
                            "profile_page": None,
                        },
                        "provider_response_sha256": response_sha256,
                        "provider_result_index": result_index,
                        "provider_duration_sec": duration,
                        "rendition": {
                            "id": video_type,
                            "kind": "video_variant",
                            "width": w,
                            "height": video.get("height"),
                            "declared_bytes": video.get("size"),
                            "url": _safe_public_url(video.get("url")),
                        },
                        "rights": {
                            "license_status": "not_evaluated",
                            "attribution_status": "not_evaluated",
                        },
                        "warnings": [],
                    })
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        error_message = _redact_secret(str(e), api_key)
        # ProxyError 等异常可能回显完整代理 URL，其中可能包含用户名和密码。
        # 仅替换用户实际配置的代理值，不对普通错误文本做宽泛正则处理，
        # 避免误删 DNS、超时、证书等真正有助于排查的信息。
        for proxy_url in config.proxy.values():
            error_message = _redact_secret(error_message, str(proxy_url))
        logger.error(
            "pixabay search request failed: "
            f"error={type(e).__name__}, detail={error_message}"
        )

    return []


def search_videos_coverr(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    """
    Coverr (https://coverr.co) - free HD/4K stock videos,
    subject to Coverr license terms (https://coverr.co/license).

    Coverr API notes (based on official docs at api.coverr.co/docs/):
      - 鉴权: Authorization: Bearer <api_key>
      - 搜索端点: GET /videos?query=...,响应结构 {"hits": [...], ...}
      - 加 ?urls=true 在搜索响应里直接返回 mp4 直链
      - URL 是 signed JWT(绑定 API key,无过期时间)
      - Coverr 库以 16:9 横屏为主,9:16 portrait 占比极低(约 1%)
        因此本函数不做 aspect_ratio 过滤,由下游 video.py 的
        resize + letterbox 逻辑统一处理
      - duration 字段同时存在 number 和 string 两种形态,本函数都接受

    本函数使用 urls.mp4_download 字段作为下载地址 —— 按 Coverr 官方文档
    (https://api.coverr.co/docs/videos/#download-a-video) 的说法,
    GET 这个 URL 本身就被 Coverr 当作一次合法的 download 事件计入统计,
    无需再调用 PATCH /videos/:id/stats/downloads。
    """
    api_key = get_api_key("coverr_api_keys")
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {
        "query": search_term,
        "page_size": 20,
        "urls": "true",
        "sort": "popular",
    }
    query_url = f"https://api.coverr.co/videos?{urlencode(params)}"
    logger.info(f"searching videos on coverr: term={search_term!r}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        response = r.json()
        response_sha256 = _canonical_json_sha256(response)
        video_items: List[MaterialInfo] = []

        if not isinstance(response, dict) or "hits" not in response:
            logger.error("coverr video search returned an unsupported response")
            return video_items

        for result_index, v in enumerate(response["hits"]):
            # duration 在不同响应里可能是 number(11.625) 或 string("10.500000")
            try:
                duration = int(float(v.get("duration") or 0))
            except (TypeError, ValueError):
                continue
            if duration < minimum_duration:
                continue

            video_id = v.get("id")
            mp4_download_url = (v.get("urls") or {}).get("mp4_download")
            if not video_id or not mp4_download_url:
                continue

            item = MaterialInfo()
            item.provider = "coverr"
            item.url = mp4_download_url
            item.duration = duration
            _set_provenance(item, {
                "search_term": search_term,
                "provider": "coverr",
                "asset_id": str(video_id),
                "canonical_page": _safe_public_url(
                    v.get("canonical_url") or v.get("url")
                ),
                "creator": _creator(v.get("creator") or v.get("author")),
                "provider_response_sha256": response_sha256,
                "provider_result_index": result_index,
                "provider_duration_sec": float(v.get("duration") or 0),
                "rendition": {
                    "id": "mp4_download",
                    "kind": "mp4_download",
                    "width": v.get("max_width"),
                    "height": v.get("max_height"),
                    "aspect_ratio": v.get("aspect_ratio"),
                    "url": _safe_public_url(mp4_download_url),
                },
                "rights": {
                    "license_status": "ambiguous",
                    "attribution_status": "ambiguous",
                    "commercial_use": "ambiguous",
                    "api_attribution_logo_required": True,
                    "reference": "https://coverr.co/license",
                },
                "warnings": [
                    "Coverr API and content-license attribution terms require separate review."
                ],
            })
            video_items.append(item)
        return video_items
    except Exception as e:
        logger.error(f"coverr video search failed: {type(e).__name__}")

    return []


def save_video(video_url: str, save_dir: str = "") -> str:
    if not save_dir:
        save_dir = utils.storage_dir("cache_videos")

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    url_without_query = video_url.split("?")[0]
    url_hash = utils.md5(url_without_query)
    video_id = f"vid-{url_hash}"
    video_path = f"{save_dir}/{video_id}.mp4"

    # if video already exists, return the path
    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        logger.info(f"video already exists: {video_path}")
        return video_path

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }

    # if video does not exist, download it
    with open(video_path, "wb") as f:
        f.write(
            requests.get(
                video_url,
                headers=headers,
                proxies=config.proxy,
                verify=_get_tls_verify(),
                timeout=(60, 240),
            ).content
        )

    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        clip = None
        try:
            clip = VideoFileClip(video_path)
            duration = clip.duration
            fps = clip.fps
            if duration > 0 and fps > 0:
                return video_path
        except Exception as e:
            logger.warning(f"invalid video file: {video_path} => {str(e)}")
            try:
                os.remove(video_path)
            except Exception as remove_error:
                logger.warning(
                    f"failed to remove invalid video file: {video_path}, error: {str(remove_error)}"
                )
        finally:
            if clip is not None:
                try:
                    clip.close()
                except Exception as close_error:
                    logger.warning(
                        f"failed to close video clip: {video_path}, error: {str(close_error)}"
                    )
    return ""


def _search_videos_with_cache(
    provider: str,
    search_videos: Callable[..., List[MaterialInfo]],
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect,
) -> List[MaterialInfo]:
    """
    统一处理三个在线素材源的 24 小时搜索缓存。

    缓存只包裹搜索 API，不改变后续视频下载与去重逻辑。远端返回空列表时不写
    缓存，因为现有 provider 接口使用空列表同时表示“没有结果”和“请求失败”；
    在两者尚未拆分为明确结果类型前，宁可下次重试，也不能把临时故障缓存一天。
    """
    cache_args = {
        "provider": provider,
        "search_term": search_term,
        "minimum_duration": minimum_duration,
        "video_aspect": video_aspect,
    }

    def load_cache_safely() -> List[MaterialInfo] | None:
        try:
            return material_cache.load_material_search_cache(**cache_args)
        except Exception as exc:
            # 缓存是可选优化，任何缓存实现异常都必须按未命中处理，不能阻断
            # Pexels、Pixabay 或 Coverr 的正常远端搜索。
            logger.warning(
                "material search cache read failed, continue with remote search: "
                f"provider={provider}, error={type(exc).__name__}, detail={exc}"
            )
            return None

    cached_items = load_cache_safely()
    if cached_items is not None:
        return cached_items

    cache_lock = material_cache.get_material_search_cache_lock(**cache_args)
    with cache_lock:
        # 等待相同搜索条件的线程完成后再次读取，避免多个 API 任务在首次缓存
        # 未命中时同时请求远端，降低第三方接口限流和风控触发概率。
        cached_items = load_cache_safely()
        if cached_items is not None:
            return cached_items

        items = search_videos(
            search_term=search_term,
            minimum_duration=minimum_duration,
            video_aspect=video_aspect,
        )
        if items:
            try:
                material_cache.save_material_search_cache(
                    **cache_args,
                    items=items,
                )
            except Exception as exc:
                logger.warning(
                    "material search cache write failed, use remote results: "
                    f"provider={provider}, error={type(exc).__name__}, detail={exc}"
                )
        return items


def download_videos(
    task_id: str,
    search_terms: List[str],
    source: str = "pexels",
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    audio_duration: float = 0.0,
    max_clip_duration: int = 5,
    match_script_order: bool = False,
) -> List[str]:
    providers = {
        "pexels": search_videos_pexels,
        "pixabay": search_videos_pixabay,
        "coverr": search_videos_coverr,
    }
    if source not in providers:
        raise ValueError(f"unsupported online material source: {source}")
    remote_search_videos = providers[source]

    def search_videos(
        search_term: str,
        minimum_duration: int,
        video_aspect: VideoAspect,
    ) -> List[MaterialInfo]:
        return _search_videos_with_cache(
            provider=source,
            search_videos=remote_search_videos,
            search_term=search_term,
            minimum_duration=minimum_duration,
            video_aspect=video_aspect,
        )

    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    if match_script_order:
        return _download_videos_by_script_order(
            task_id=task_id,
            search_terms=search_terms,
            source=source,
            search_videos=search_videos,
            video_aspect=video_aspect,
            video_concat_mode=video_concat_mode,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            material_directory=material_directory,
        )

    valid_video_items = []
    valid_video_identities = set()
    attempts: list[dict[str, Any]] = []
    found_duration = 0.0
    for search_term in search_terms:
        video_items = search_videos(
            search_term=search_term,
            minimum_duration=max_clip_duration,
            video_aspect=video_aspect,
        )
        logger.info(f"found {len(video_items)} videos for '{search_term}'")

        for item in video_items:
            if not _get_provenance(item):
                _set_provenance(item, {
                    "search_term": search_term,
                    "provider": item.provider,
                    "asset_id": None,
                    "canonical_page": None,
                    "creator": None,
                    "provider_response_sha256": None,
                    "provider_result_index": None,
                    "rendition": {
                        "id": None,
                        "kind": "download_url",
                        "url": _safe_public_url(item.url),
                    },
                    "rights": {
                        "license_status": "not_evaluated",
                        "attribution_status": "not_evaluated",
                    },
                    "warnings": ["Provider identity was unavailable from the search result."],
                })
            identity = _material_identity(item)
            if identity in valid_video_identities:
                attempts.append(_safe_attempt(item, "DUPLICATE_SKIPPED"))
                continue
            valid_video_items.append(item)
            valid_video_identities.add(identity)
            found_duration += item.duration

    logger.info(
        f"found total videos: {len(valid_video_items)}, required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )
    video_paths: list[str] = []
    material_records: list[dict[str, Any]] = []

    concat_mode_value = getattr(video_concat_mode, "value", video_concat_mode)
    if concat_mode_value == VideoConcatMode.random.value:
        random.shuffle(valid_video_items)

    total_duration = 0.0
    for item in valid_video_items:
        try:
            provenance = _get_provenance(item)
            logger.info(
                f"downloading {item.provider} video asset={provenance.get('asset_id')!r}"
            )
            saved_video_path = save_video(
                video_url=item.url, save_dir=material_directory
            )
            if saved_video_path:
                logger.info(f"video saved: {saved_video_path}")
                record = _material_record(
                    item,
                    saved_video_path,
                    len(material_records),
                    max_clip_duration,
                )
                video_paths.append(saved_video_path)
                material_records.append(record)
                seconds = min(max_clip_duration, item.duration)
                total_duration += seconds
                if total_duration > audio_duration:
                    logger.info(
                        f"total duration of downloaded videos: {total_duration} seconds, skip downloading more"
                    )
                    break
            else:
                attempts.append(
                    _safe_attempt(item, "DOWNLOAD_FAILED", "E_EMPTY_DOWNLOAD")
                )
        except ProvenanceWriteError:
            raise
        except Exception as e:
            attempts.append(
                _safe_attempt(
                    item,
                    "DOWNLOAD_FAILED",
                    f"E_{type(e).__name__.upper()}",
                )
            )
            logger.error(
                f"failed to download {item.provider} material: {type(e).__name__}"
            )
    logger.success(f"downloaded {len(video_paths)} videos")
    _publish_download_provenance(
        task_id=task_id,
        source=source,
        search_terms=search_terms,
        video_aspect=video_aspect,
        video_concat_mode=video_concat_mode,
        match_script_order=False,
        audio_duration=audio_duration,
        max_clip_duration=max_clip_duration,
        materials=material_records,
        attempts=attempts,
    )
    return video_paths


def _download_videos_by_script_order(
    task_id: str,
    search_terms: List[str],
    source: str,
    search_videos,
    video_aspect: VideoAspect,
    video_concat_mode: VideoConcatMode,
    audio_duration: float,
    max_clip_duration: int,
    material_directory: str,
) -> List[str]:
    """
    按脚本文案顺序下载素材。

    默认下载逻辑会把所有关键词的候选素材合并成一个大列表；如果第一个
    关键词返回很多结果，最终下载时可能一直消耗这个关键词的素材，后续
    脚本主题就排不上时间线。这里按关键词分组后轮询下载：
    第 1 轮取每个关键词的第 1 个候选，第 2 轮取每个关键词的第 2 个候选。
    这样在不重写视频合成引擎的前提下，尽量保证素材顺序贴近文案顺序。
    """
    logger.info("downloading videos with script-order material matching")
    candidate_groups = []
    valid_video_identities = set()
    attempts: list[dict[str, Any]] = []
    found_duration = 0.0

    for search_term in search_terms:
        video_items = search_videos(
            search_term=search_term,
            minimum_duration=max_clip_duration,
            video_aspect=video_aspect,
        )
        logger.info(f"found {len(video_items)} videos for '{search_term}'")

        term_items = []
        for item in video_items:
            if not _get_provenance(item):
                _set_provenance(item, {
                    "search_term": search_term,
                    "provider": item.provider,
                    "asset_id": None,
                    "canonical_page": None,
                    "creator": None,
                    "provider_response_sha256": None,
                    "provider_result_index": None,
                    "rendition": {
                        "id": None,
                        "kind": "download_url",
                        "url": _safe_public_url(item.url),
                    },
                    "rights": {
                        "license_status": "not_evaluated",
                        "attribution_status": "not_evaluated",
                    },
                    "warnings": ["Provider identity was unavailable from the search result."],
                })
            identity = _material_identity(item)
            if identity in valid_video_identities:
                attempts.append(_safe_attempt(item, "DUPLICATE_SKIPPED"))
                continue
            term_items.append(item)
            valid_video_identities.add(identity)
            found_duration += item.duration

        if term_items:
            candidate_groups.append((search_term, term_items))

    logger.info(
        f"found total ordered video candidates: {sum(len(items) for _, items in candidate_groups)}, "
        f"required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )

    video_paths: list[str] = []
    material_records: list[dict[str, Any]] = []
    total_duration = 0.0
    candidate_index = 0
    while candidate_groups and total_duration <= audio_duration:
        has_candidate = False
        for search_term, term_items in candidate_groups:
            if candidate_index >= len(term_items):
                continue

            has_candidate = True
            item = term_items[candidate_index]
            try:
                provenance = _get_provenance(item)
                logger.info(
                    f"downloading ordered {item.provider} video for {search_term!r}, "
                    f"asset={provenance.get('asset_id')!r}"
                )
                saved_video_path = save_video(
                    video_url=item.url, save_dir=material_directory
                )
                if saved_video_path:
                    logger.info(f"video saved: {saved_video_path}")
                    record = _material_record(
                        item,
                        saved_video_path,
                        len(material_records),
                        max_clip_duration,
                    )
                    video_paths.append(saved_video_path)
                    material_records.append(record)
                    total_duration += min(max_clip_duration, item.duration)
                    if total_duration > audio_duration:
                        logger.info(
                            f"total duration of downloaded videos: {total_duration} seconds, skip downloading more"
                        )
                        break
                else:
                    attempts.append(
                        _safe_attempt(item, "DOWNLOAD_FAILED", "E_EMPTY_DOWNLOAD")
                    )
            except ProvenanceWriteError:
                raise
            except Exception as e:
                attempts.append(
                    _safe_attempt(
                        item,
                        "DOWNLOAD_FAILED",
                        f"E_{type(e).__name__.upper()}",
                    )
                )
                logger.error(
                    f"failed to download ordered {item.provider} material: {type(e).__name__}"
                )

        if not has_candidate:
            break
        candidate_index += 1

    logger.success(f"downloaded {len(video_paths)} ordered videos")
    _publish_download_provenance(
        task_id=task_id,
        source=source,
        search_terms=search_terms,
        video_aspect=video_aspect,
        video_concat_mode=video_concat_mode,
        match_script_order=True,
        audio_duration=audio_duration,
        max_clip_duration=max_clip_duration,
        materials=material_records,
        attempts=attempts,
    )
    return video_paths


if __name__ == "__main__":
    download_videos(
        "test123", ["Money Exchange Medium"], audio_duration=100, source="pixabay"
    )
