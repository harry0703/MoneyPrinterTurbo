import hashlib
import io
import math
import re
import threading
import time
from collections.abc import Iterator
from urllib.parse import urlsplit

import requests
from loguru import logger
from PIL import Image

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect
from app.utils.request_logging import trace_http_call


_BASE_URL = "https://www.aigei.com/open/api/v1/video"
_MAX_SEARCH_PAGES = 3
_MAX_PREVIEW_BYTES = 512 * 1024
_request_lock = threading.Lock()
_next_request_start = 0.0
_ERROR_MESSAGES = {
    "key_required": "Configure the Aigei API key in material source settings.",
    "charge_changed": "The Aigei API key changed. Confirm download charges again.",
    "invalid_key": "Aigei rejected the API key. Check your material source settings.",
    "blocked": "Aigei restricted access. Check your account on aigei.com.",
    "rate_limit": "Aigei is receiving too many requests. Try again shortly.",
    "quota": "Aigei search quota is exhausted.",
    "balance": "The Aigei account has insufficient copper coins.",
    "search_failed": "Could not search Aigei video footage.",
    "no_matches": "No suitable Aigei videos found. Try different keywords or video settings.",
    "aspect_mismatch": "A downloaded Aigei video has the wrong orientation. Generation stopped before requesting more downloads.",
    "sideways_content": "A downloaded Aigei video contains sideways footage. Generation stopped before requesting more downloads.",
    "link_failed": "Could not confirm the Aigei download. Check your download history before trying again.",
    "file_failed": "Could not save the Aigei video. Check your download history before trying again.",
}
_ERROR_CODES = {
    "50101": "invalid_key",
    "50102": "invalid_key",
    "50103": "invalid_key",
    "50201": "blocked",
    "50202": "rate_limit",
    "50301": "balance",
    "50303": "quota",
}


class AigeiError(RuntimeError):
    def __init__(self, reason: str, request_id: str = ""):
        self.key = f"aigei.{reason}"
        self.request_id = request_id
        message = _ERROR_MESSAGES[reason]
        if request_id:
            message += f" (request ID: {request_id})"
        super().__init__(message)


def api_key(settings=None) -> str:
    settings = config.app if settings is None else settings
    value = settings.get("aigei_api_key")
    return value.strip() if isinstance(value, str) else ""


def key_fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _request(method, endpoint, key, **kwargs):
    global _next_request_start
    # 并行关键词和不同任务共用平台的 10 QPS 限制，只串行安排请求开始时间。
    with _request_lock:
        wait = _next_request_start - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _next_request_start = time.monotonic() + 0.11

    failure = "search_failed" if endpoint == "search" else "link_failed"
    try:
        response = trace_http_call(
            "REQUEST",
            requests.request,
            method,
            f"{_BASE_URL}/{endpoint}",
            headers={"Authorization": f"Bearer {key}"},
            proxies=config.proxy,
            timeout=(10, 60),
            allow_redirects=False,
            **kwargs,
        )
    except requests.RequestException:
        raise AigeiError(failure) from None

    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    request_id = str(body.get("requestId") or "")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", request_id):
        request_id = ""
    code = str(body.get("code"))
    data = body.get("data")
    if response.status_code == 200 and code == "10001" and isinstance(data, dict):
        return data, body.get("fund"), request_id

    reason = _ERROR_CODES.get(code)
    if not reason:
        reason = {401: "invalid_key", 403: "blocked", 429: "rate_limit"}.get(
            response.status_code, failure
        )
    logger.warning(
        f"Aigei {endpoint} failed: status={response.status_code}, "
        f"reason={reason}, request_id={request_id or '-'}"
    )
    raise AigeiError(reason, request_id)


def _video_variant(file, aspect, minimum_duration):
    if not isinstance(file, dict) or file.get("fileExtName") != "mp4":
        return None
    file_id = file.get("fileId")
    properties = file.get("videoProperties")
    fund = file.get("downloadFund")
    if not isinstance(file_id, str) or not file_id or len(file_id) > 1024:
        return None
    if not isinstance(properties, dict) or not isinstance(fund, dict):
        return None
    width = properties.get("videoWidthPx")
    height = properties.get("videoHeightPx")
    duration = properties.get("videoDurationSeconds")
    price = fund.get("fundValue")
    if any(type(value) is not int or value <= 0 for value in (width, height, duration)):
        return None
    if (
        type(price) not in (float, int)
        or (isinstance(price, float) and not math.isfinite(price))
        or price < 0
    ):
        return None
    size = file.get("fileSizeMb")
    if type(size) in (float, int) and size > 512:
        return None
    matches_aspect = {
        VideoAspect.portrait: height > width,
        VideoAspect.landscape: width > height,
        VideoAspect.square: width == height,
    }
    if duration < minimum_duration or not matches_aspect[aspect]:
        return None
    return price, width * height, file_id, width, height, duration


def search_videos(
    search_term: str, minimum_duration: int, video_aspect: VideoAspect, *, key: str,
) -> list[MaterialInfo]:
    # 搜索条件只筛选作品，返回的文件版本仍要逐项核对。每个作品只选一个
    # MP4 版本，同一作品优先选更低报价，报价相同时优先选择更高分辨率。
    aspect = VideoAspect(video_aspect)
    if not 1 <= len(search_term.strip()) <= 200:
        return []
    condition = {
        "fileCommon": {"fileExtNameIn": "mp4", "fileSizeMbMax": 512},
        "fileVideo": {
            "videoDurationSecondsMin": min(max(1, minimum_duration), 604800),
            "videoLayoutEq": aspect.value.replace(":", "_"),
        },
    }
    # 平台过滤可能造成空页，或只返回本地无法使用的文件规格。通常一页即可，
    # 仅在没有可用候选且仍有下一页时补查，避免稀疏结果耗尽查询额度。
    for page_number in range(1, _MAX_SEARCH_PAGES + 1):
        data, _, request_id = _request(
            "POST", "search", key,
            json={
                "keyword": search_term,
                "cat": "videoFootage",
                "condition": condition,
                "pageNumber": page_number,
            },
        )
        hits = data.get("itemList")
        if not isinstance(hits, list):
            raise AigeiError("search_failed", request_id)
        items = _select_videos(hits, search_term, minimum_duration, aspect)
        if items:
            return items
        page_size, item_total = data.get("pageSize"), data.get("itemTotal")
        if (
            type(page_size) is not int or page_size <= 0 or type(item_total) is not int
            or page_number * page_size >= item_total
        ):
            break
    return []


def _select_videos(hits, search_term, minimum_duration, aspect):
    items = []
    for hit in hits:
        if not isinstance(hit, dict) or not isinstance(hit.get("fileList"), list):
            continue
        variants = (
            _video_variant(file, aspect, minimum_duration) for file in hit["fileList"]
        )
        best = min(
            (variant for variant in variants if variant is not None),
            key=lambda variant: (variant[0], -variant[1]),
            default=None,
        )
        if best is None:
            continue
        _, _, file_id, width, height, duration = best
        items.append(MaterialInfo(
            provider="aigei",
            # 正式文件 ID 用于候选去重，签名链接仅在此素材被选中后才获取。
            url=file_id,
            duration=duration,
            source_info={
                "asset_id": hit.get("itemId"),
                "search_term": search_term,
                "rendition": {"width": width, "height": height},
                "preview_urls": _preview_urls(hit.get("prevImageList")) if aspect == VideoAspect.portrait else [],
            },
        ))
    return items


def _preview_urls(previews) -> list[str]:
    urls = []
    if not isinstance(previews, list):
        return urls
    for preview in previews:
        url = preview.get("prevMiniUrl") if isinstance(preview, dict) else None
        if not isinstance(url, str):
            continue
        try:
            parts = urlsplit(url)
            host = parts.hostname or ""
            if (
                parts.scheme == "https" and parts.username is None and parts.port in (None, 443)
                and (host == "aigei.com" or host.endswith(".aigei.com"))
            ):
                urls.append(url)
        except ValueError:
            continue
    urls = list(dict.fromkeys(urls))
    if len(urls) > 5:
        return [urls[round((len(urls) - 1) * i / 4)] for i in range(5)]
    return urls


def preview_frames(item: MaterialInfo) -> Iterator[Image.Image]:
    # 搜索已经返回免费小图链接，只读取选中的候选；签名链接不写入任务清单或日志。
    urls = (item.source_info or {}).get("preview_urls", [])
    if len(urls) < 3:
        return
    try:
        for url in urls:
            with requests.get(url, stream=True, timeout=(2, 4), proxies=config.proxy, allow_redirects=False) as response:
                if response.status_code != 200:
                    return
                data = response.raw.read(_MAX_PREVIEW_BYTES + 1, decode_content=True)
            if len(data) > _MAX_PREVIEW_BYTES:
                return
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > 1024 * 1024:
                    return
                yield image.convert("RGB")
    except (requests.RequestException, OSError, ValueError):
        # 预览不可用时仍可验证下载后的视频帧。
        return


def download_url(file_id: str, key: str) -> tuple[str, str]:
    data, fund, request_id = _request("GET", "download", key, params={"fileId": file_id})
    file = data.get("file")
    url = file.get("fileDownloadUrl") if isinstance(file, dict) else None
    try:
        parts = urlsplit(url) if isinstance(url, str) else None
        if not parts or parts.scheme != "https" or not parts.hostname or parts.username is not None:
            raise ValueError
    except ValueError:
        raise AigeiError("link_failed", request_id) from None

    cost = fund.get("fundValue") if isinstance(fund, dict) else None
    if type(cost) in (float, int):
        logger.info(f"Aigei download settled: copper_coins={cost}, request_id={request_id}")
    return url, request_id
