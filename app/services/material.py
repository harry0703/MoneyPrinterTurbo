import os
import random
import threading
from typing import List
from urllib.parse import urlencode

import requests
from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoConcatMode
from app.utils import utils

# Thread-safe counter for API key rotation
_api_key_counter = 0
_api_key_lock = threading.Lock()


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
            f"{utils.to_json(config.app)}"
        )

    # if only one key is provided, return it
    if isinstance(api_keys, str):
        return api_keys

    global _api_key_counter
    with _api_key_lock:
        _api_key_counter += 1
        return api_keys[_api_key_counter % len(api_keys)]


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
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        response = r.json()
        video_items = []
        if "videos" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        videos = response["videos"]
        # loop through each video in the result
        for v in videos:
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
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

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
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url, proxies=config.proxy, verify=_get_tls_verify(), timeout=(30, 60)
        )
        response = r.json()
        video_items = []
        if "hits" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        videos = response["hits"]
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["videos"]
            # loop through each url to determine the best quality
            for video_type in video_files:
                video = video_files[video_type]
                w = int(video["width"])
                # h = int(video["height"])
                if w >= video_width:
                    item = MaterialInfo()
                    item.provider = "pixabay"
                    item.url = video["url"]
                    item.duration = duration
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

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
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        response = r.json()
        video_items: List[MaterialInfo] = []

        if not isinstance(response, dict) or "hits" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items

        for v in response["hits"]:
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
            video_items.append(item)
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


DISCORD_API_BASE = "https://discord.com/api/v10"
# Discord 文本频道的 channel type 值（0 = GUILD_TEXT），其它类型（语音、分类、
# 论坛等）无法直接拉取消息历史，这里只保留文本频道供用户选择。
DISCORD_TEXT_CHANNEL_TYPE = 0
_DISCORD_VIDEO_EXTENSIONS = (".mp4", ".mov", ".webm", ".mkv", ".m4v")
_DISCORD_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp")


def _discord_headers(token: str) -> dict:
    return {
        "Authorization": f"Bot {token}",
        "User-Agent": "MoneyPrinterTurbo (https://github.com/harry0703/MoneyPrinterTurbo, 1.0)",
    }


def _discord_get(token: str, path: str, params: dict = None):
    url = f"{DISCORD_API_BASE}{path}"
    r = requests.get(
        url,
        headers=_discord_headers(token),
        params=params or {},
        proxies=config.proxy,
        verify=_get_tls_verify(),
        timeout=(30, 60),
    )
    if r.status_code != 200:
        raise ValueError(
            f"Discord API request failed: {path} => HTTP {r.status_code}: {r.text}"
        )
    return r.json()


def list_discord_guilds(token: str) -> List[tuple]:
    """返回机器人所在的服务器列表 [(guild_id, guild_name), ...]。"""
    guilds = _discord_get(token, "/users/@me/guilds")
    return [(g["id"], g.get("name", g["id"])) for g in guilds]


def list_discord_channels(token: str, guild_id: str) -> List[tuple]:
    """返回某个服务器下的文本频道列表 [(channel_id, channel_name), ...]。"""
    channels = _discord_get(token, f"/guilds/{guild_id}/channels")
    return [
        (c["id"], c.get("name", c["id"]))
        for c in channels
        if c.get("type") == DISCORD_TEXT_CHANNEL_TYPE
    ]


def _discord_attachment_kind(attachment: dict) -> str:
    """判断附件类型：返回 'video' / 'image' / ''（其它，忽略）。"""
    content_type = (attachment.get("content_type") or "").lower()
    filename = (attachment.get("filename") or "").lower()
    if content_type.startswith("video/") or filename.endswith(_DISCORD_VIDEO_EXTENSIONS):
        return "video"
    if content_type.startswith("image/") or filename.endswith(_DISCORD_IMAGE_EXTENSIONS):
        return "image"
    return ""


def fetch_discord_attachments(
    token: str, channel_id: str, count: int, media_type: str = "video"
) -> List[MaterialInfo]:
    """
    拉取频道里最近的素材附件，最多 count 个。

    media_type 控制收集哪些附件：
      - "video": 仅视频
      - "image": 仅图片
      - "both":  视频和图片都收集

    Discord 单次 messages 请求最多返回 100 条，这里用 `before` 游标向更早的
    消息分页，直到收集够 count 个附件或没有更多消息为止。Discord 附件对象
    不可靠地携带视频时长，因此 duration 统一记为 0，时长裁剪交给下游 video.py。
    每个 MaterialInfo 的 kind 字段记录是 'video' 还是 'image'，供下载阶段分流。
    """
    wanted = {"video", "image"} if media_type == "both" else {media_type}
    items: List[MaterialInfo] = []
    before = None
    # 诊断计数：扫描了多少消息、看到多少附件、其中视频/图片各多少。
    # 这样 0 结果时能区分“频道没有该类素材”和“附件字段为空（缺 Message
    # Content Intent）/ 读不到消息（权限不足）”等不同根因。
    scanned_messages = 0
    seen_attachments = 0
    seen_videos = 0
    seen_images = 0
    while len(items) < count:
        params = {"limit": 100}
        if before:
            params["before"] = before
        messages = _discord_get(token, f"/channels/{channel_id}/messages", params)
        if not messages:
            break
        for message in messages:
            scanned_messages += 1
            for attachment in message.get("attachments", []):
                seen_attachments += 1
                kind = _discord_attachment_kind(attachment)
                if kind == "video":
                    seen_videos += 1
                elif kind == "image":
                    seen_images += 1
                if kind not in wanted:
                    continue
                url = attachment.get("url")
                if not url:
                    continue
                item = MaterialInfo()
                item.provider = "discord"
                item.kind = kind
                item.url = url
                item.duration = 0
                items.append(item)
                if len(items) >= count:
                    _log_discord_scan(
                        media_type, scanned_messages, seen_attachments,
                        seen_videos, seen_images, len(items),
                    )
                    return items
        before = messages[-1]["id"]
        if len(messages) < 100:
            break

    _log_discord_scan(
        media_type, scanned_messages, seen_attachments,
        seen_videos, seen_images, len(items),
    )
    return items


def _log_discord_scan(media_type, scanned, attachments, videos, images, matched):
    logger.info(
        f"discord scan: media_type={media_type}, scanned {scanned} messages, "
        f"{attachments} attachments (videos={videos}, images={images}), "
        f"matched {matched}"
    )
    if matched == 0:
        if scanned == 0:
            logger.warning(
                "no messages returned — the bot likely lacks 'View Channel' / "
                "'Read Message History' permission on this channel, or the channel is empty."
            )
        elif attachments == 0:
            logger.warning(
                "messages were read but contained no attachments — enable the "
                "'Message Content Intent' for the bot in the Discord Developer Portal "
                "(Bot > Privileged Gateway Intents), otherwise Discord strips attachments "
                "from API responses."
            )
        else:
            logger.warning(
                f"attachments were found but none matched media_type='{media_type}' "
                f"(videos={videos}, images={images}); try a different Media Type."
            )


# 兼容旧名：仅拉取视频附件。
def fetch_discord_video_attachments(
    token: str, channel_id: str, count: int
) -> List[MaterialInfo]:
    return fetch_discord_attachments(token, channel_id, count, media_type="video")


def save_discord_image(image_url: str, save_dir: str) -> str:
    """
    下载 Discord 图片附件到 local_videos_dir。图片不能像视频那样被 combine_videos
    直接打开，必须先经过 video.preprocess_video 转成短视频片段，而 preprocess_video
    只接受 local_videos 目录内的素材，所以图片统一存到该目录。
    """
    os.makedirs(save_dir, exist_ok=True)
    url_without_query = image_url.split("?")[0]
    ext = utils.parse_extension(url_without_query) or "png"
    image_id = f"img-{utils.md5(url_without_query)}"
    image_path = f"{save_dir}/{image_id}.{ext}"

    if os.path.exists(image_path) and os.path.getsize(image_path) > 0:
        logger.info(f"image already exists: {image_path}")
        return image_path

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    with open(image_path, "wb") as f:
        f.write(
            requests.get(
                image_url,
                headers=headers,
                proxies=config.proxy,
                verify=_get_tls_verify(),
                timeout=(60, 240),
            ).content
        )
    if os.path.exists(image_path) and os.path.getsize(image_path) > 0:
        return image_path
    return ""


def download_discord_videos(
    task_id: str,
    token: str,
    channel_id: str,
    count: int,
    media_type: str = "video",
    material_directory: str = "",
    clip_duration: int = 5,
) -> List[str]:
    if not token:
        logger.error("discord_bot_token is not set")
        return []
    if not channel_id:
        logger.error("discord channel is not selected")
        return []

    try:
        items = fetch_discord_attachments(token, channel_id, count, media_type)
    except Exception as e:
        logger.error(f"failed to fetch discord attachments: {str(e)}")
        return []

    logger.info(f"found {len(items)} discord attachments (media_type={media_type})")
    material_paths = []
    image_materials = []
    local_videos_dir = utils.storage_dir("local_videos", create=True)

    for item in items:
        try:
            if getattr(item, "kind", "video") == "image":
                logger.info(f"downloading discord image: {item.url}")
                image_path = save_discord_image(item.url, local_videos_dir)
                if image_path:
                    # preprocess_video 通过 local_videos_dir 解析 url，这里只传文件名。
                    img_item = MaterialInfo()
                    img_item.provider = "discord"
                    img_item.url = os.path.basename(image_path)
                    image_materials.append(img_item)
            else:
                logger.info(f"downloading discord video: {item.url}")
                saved_video_path = save_video(
                    video_url=item.url, save_dir=material_directory
                )
                if saved_video_path:
                    logger.info(f"video saved: {saved_video_path}")
                    material_paths.append(saved_video_path)
        except Exception as e:
            logger.error(
                f"failed to download discord attachment: {utils.to_json(item)} => {str(e)}"
            )

    # 图片素材转成短视频片段，使其能被 combine_videos 直接拼接。
    if image_materials:
        # 延迟导入避免与 video 模块的潜在循环依赖。
        from app.services import video as video_service

        processed = video_service.preprocess_video(
            materials=image_materials, clip_duration=clip_duration
        )
        material_paths.extend(m.url for m in processed)

    logger.success(f"downloaded {len(material_paths)} discord materials")
    return material_paths


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


def download_videos(
    task_id: str,
    search_terms: List[str],
    source: str = "pexels",
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    audio_duration: float = 0.0,
    max_clip_duration: int = 5,
    match_script_order: bool = False,
    discord_channel_id: str = "",
    discord_count: int = 0,
    discord_media_type: str = "",
) -> List[str]:
    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    # Discord 不是基于搜索词的素材源：它直接拉取所选频道里最近的视频附件，
    # 因此在这里短路掉关键词搜索逻辑。
    if source == "discord":
        token = config.app.get("discord_bot_token", "")
        channel_id = discord_channel_id or config.app.get("discord_channel_id", "")
        count = discord_count or int(config.app.get("discord_count", 10) or 10)
        media_type = (
            discord_media_type
            or config.app.get("discord_media_type", "video")
            or "video"
        )
        return download_discord_videos(
            task_id=task_id,
            token=token,
            channel_id=channel_id,
            count=count,
            media_type=media_type,
            material_directory=material_directory,
            clip_duration=max_clip_duration,
        )

    search_videos = search_videos_pexels
    if source == "pixabay":
        search_videos = search_videos_pixabay
    elif source == "coverr":
        search_videos = search_videos_coverr

    if match_script_order:
        return _download_videos_by_script_order(
            task_id=task_id,
            search_terms=search_terms,
            search_videos=search_videos,
            video_aspect=video_aspect,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            material_directory=material_directory,
        )

    valid_video_items = []
    valid_video_urls = []
    found_duration = 0.0
    for search_term in search_terms:
        video_items = search_videos(
            search_term=search_term,
            minimum_duration=max_clip_duration,
            video_aspect=video_aspect,
        )
        logger.info(f"found {len(video_items)} videos for '{search_term}'")

        for item in video_items:
            if item.url not in valid_video_urls:
                valid_video_items.append(item)
                valid_video_urls.append(item.url)
                found_duration += item.duration

    logger.info(
        f"found total videos: {len(valid_video_items)}, required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )
    video_paths = []

    concat_mode_value = getattr(video_concat_mode, "value", video_concat_mode)
    if concat_mode_value == VideoConcatMode.random.value:
        random.shuffle(valid_video_items)

    total_duration = 0.0
    for item in valid_video_items:
        try:
            logger.info(f"downloading video: {item.url}")
            saved_video_path = save_video(
                video_url=item.url, save_dir=material_directory
            )
            if saved_video_path:
                logger.info(f"video saved: {saved_video_path}")
                video_paths.append(saved_video_path)
                seconds = min(max_clip_duration, item.duration)
                total_duration += seconds
                if total_duration > audio_duration:
                    logger.info(
                        f"total duration of downloaded videos: {total_duration} seconds, skip downloading more"
                    )
                    break
        except Exception as e:
            logger.error(f"failed to download video: {utils.to_json(item)} => {str(e)}")
    logger.success(f"downloaded {len(video_paths)} videos")
    return video_paths


def _download_videos_by_script_order(
    task_id: str,
    search_terms: List[str],
    search_videos,
    video_aspect: VideoAspect,
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
    valid_video_urls = set()
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
            if item.url in valid_video_urls:
                continue
            term_items.append(item)
            valid_video_urls.add(item.url)
            found_duration += item.duration

        if term_items:
            candidate_groups.append((search_term, term_items))

    logger.info(
        f"found total ordered video candidates: {sum(len(items) for _, items in candidate_groups)}, "
        f"required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )

    video_paths = []
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
                logger.info(
                    f"downloading ordered video for '{search_term}': {item.url}"
                )
                saved_video_path = save_video(
                    video_url=item.url, save_dir=material_directory
                )
                if saved_video_path:
                    logger.info(f"video saved: {saved_video_path}")
                    video_paths.append(saved_video_path)
                    total_duration += min(max_clip_duration, item.duration)
                    if total_duration > audio_duration:
                        logger.info(
                            f"total duration of downloaded videos: {total_duration} seconds, skip downloading more"
                        )
                        break
            except Exception as e:
                logger.error(
                    f"failed to download ordered video: {utils.to_json(item)} => {str(e)}"
                )

        if not has_candidate:
            break
        candidate_index += 1

    logger.success(f"downloaded {len(video_paths)} ordered videos")
    return video_paths


if __name__ == "__main__":
    download_videos(
        "test123", ["Money Exchange Medium"], audio_duration=100, source="pixabay"
    )
