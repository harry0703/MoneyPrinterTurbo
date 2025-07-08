import logging
import os
import random
from typing import List
from urllib.parse import urlencode

import requests
from loguru import logger
import subprocess
import json

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoConcatMode
from app.services import llm
from app.utils import utils

requested_count = 0


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

    global requested_count
    requested_count += 1
    return api_keys[requested_count % len(api_keys)]


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
    params = {"query": search_term, "page": 1, "per_page": 5, "orientation": "landscape", "size": "medium","locale":"en-US"}
    query_url = f"https://api.pexels.com/videos/search?{urlencode(params)}"
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=False,
            timeout=(30, 60),
        )
        response = r.json()
        video_items = []
        if "videos" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        
        videos = response["videos"]
        
        for v in videos:
            duration = v.get("duration")
            if not duration or duration < minimum_duration:
                continue
            
            video_files = v.get("video_files", [])
            
            # ---- 新的筛选逻辑 ----
            best_landscape_file = None
            max_resolution = 0

            # 遍历所有文件版本，找到分辨率最高的横屏视频
            for video_file in video_files:
                width = video_file.get("width")
                height = video_file.get("height")

                # 确保有宽高信息，并且是横屏 (width > height)
                if not width or not height or width <= height:
                    continue

                # 计算当前分辨率的总像素
                current_resolution = width * height
                
                # 如果当前版本更清晰，则更新为最佳版本
                if current_resolution > max_resolution:
                    max_resolution = current_resolution
                    best_landscape_file = video_file

            # 如果在这个视频的所有版本中找到了至少一个横屏视频
            if best_landscape_file:
                item = MaterialInfo()
                item.provider = "pexels"
                item.url = best_landscape_file["link"] # 使用最佳版本的链接
                item.duration = duration
                item.path = ""
                item.start_time = 0.0
                video_items.append(item)
        logging.info("选取的Mp4链接地址为{}".format(item.url))
        return video_items

    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def search_videos_pixabay(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
    category: str = "",
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()
    api_key = get_api_key("pixabay_api_keys")

    def perform_search(params):
        params["key"] = api_key
        query_url = f"https://pixabay.com/api/videos/?{urlencode(params)}"
        logger.info(f"Searching videos: {query_url}, with proxies: {config.proxy}")
        try:
            r = requests.get(
                query_url,
                proxies=config.proxy,
                verify=False,
                timeout=(30, 60),
            )
            r.raise_for_status()
            response = r.json()
            if "hits" not in response or not response["hits"]:
                return []

            video_items = []
            for v in response["hits"]:
                duration = v.get("duration")
                if not duration or duration < minimum_duration:
                    continue

                video_files = v.get("videos", {})
                best_video = None
                # Simplified logic to find a suitable video rendition
                for size in ["large", "medium", "small", "tiny"]:
                    rendition = video_files.get(size)
                    if not rendition or not rendition.get("url"):
                        continue
                    
                    width = rendition.get("width", 0)
                    height = rendition.get("height", 0)

                    is_portrait = height > width
                    is_landscape = width > height

                    if aspect == VideoAspect.portrait and is_portrait:
                        best_video = rendition
                        break
                    elif aspect != VideoAspect.portrait and is_landscape:
                        best_video = rendition
                        break
                
                # Fallback to any available video if exact aspect not found
                if not best_video:
                    for size in ["large", "medium", "small", "tiny"]:
                        if video_files.get(size) and video_files.get(size).get("url"):
                            best_video = video_files.get(size)
                            break

                if best_video:
                    item = MaterialInfo()
                    item.provider = "pixabay"
                    item.url = best_video.get("url")
                    item.duration = duration
                    item.path = ""
                    item.start_time = 0.0
                    video_items.append(item)
            
            return video_items

        except requests.exceptions.RequestException as e:
            logger.error(f"Search videos failed: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"An unexpected error occurred during video search: {str(e)}")
            return []

    # Attempt 1: Strict search with category and editors_choice
    logger.info("Attempt 1: Strict search with category and editors_choice")
    params = {
        "q": search_term,
        "video_type": "film",
        "safesearch": "true",
        "editors_choice": "true",
        "order": "popular",
        "page": 1,
        "per_page": 80,
    }
    if category:
        params["category"] = category
    if video_width > 0:
        params["min_width"] = video_width
    if video_height > 0:
        params["min_height"] = video_height

    results = perform_search(params)
    if results:
        logger.success(f"Found {len(results)} videos on first attempt.")
        return results

    # Attempt 2: Search with editors_choice but without category
    logger.warning("First attempt failed. Attempt 2: Retrying without category.")
    params.pop("category", None)
    results = perform_search(params)
    if results:
        logger.success(f"Found {len(results)} videos on second attempt.")
        return results

    # Attempt 3: Broadest search, without editors_choice
    logger.warning("Second attempt failed. Attempt 3: Retrying with broadest settings.")
    params.pop("editors_choice", None)
    results = perform_search(params)
    if results:
        logger.success(f"Found {len(results)} videos on third attempt.")
    else:
        logger.error("All search attempts failed to find any videos.")
    
    return results


def _get_video_info_ffprobe(video_path: str) -> dict:
    """
    Get video information using ffprobe.
    """
    command = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        video_path
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)
        video_stream = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)
        if not video_stream:
            return None
        
        fps_str = video_stream.get('avg_frame_rate', video_stream.get('r_frame_rate', '0/1'))
        num, den = map(int, fps_str.split('/'))
        fps = num / den if den != 0 else 0

        return {
            "duration": float(video_stream.get('duration', info['format'].get('duration', 0))),
            "fps": fps
        }
    except (subprocess.CalledProcessError, json.JSONDecodeError, StopIteration, KeyError, ZeroDivisionError) as e:
        logger.error(f"Failed to get video info for {video_path} using ffprobe: {e}")
        return None


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
                verify=False,
                timeout=(60, 240),
            ).content
        )

    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        try:
            info = _get_video_info_ffprobe(video_path)
            if info and info.get("duration", 0) > 0 and info.get("fps", 0) > 0:
                logger.info(f"video validated: {video_path}")
                return video_path
            else:
                raise ValueError("Invalid video file, duration or fps is 0.")
        except Exception as e:
            try:
                os.remove(video_path)
            except Exception:
                pass
            logger.warning(f"invalid video file: {video_path} => {str(e)}")
    return ""


def download_videos(
    task_id: str,
    video_subject: str,
    search_terms: List[str],
    source: str = "pexels",
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    audio_duration: float = 0.0,
    max_clip_duration: int = 5,
) -> List[MaterialInfo]:
    """
    Download videos from Pexels or Pixabay based on search terms.
    """
    all_video_items: List[MaterialInfo] = []
    for term in search_terms:
        if source == "pexels":
            video_items = search_videos_pexels(
                search_term=term,
                minimum_duration=max_clip_duration,
                video_aspect=video_aspect,
            )
        elif source == "pixabay":
            video_items = search_videos_pixabay(
                search_term=term,
                minimum_duration=max_clip_duration,
                video_aspect=video_aspect,
            )
        else:
            video_items = []
        
        logger.info(f"found {len(video_items)} videos for '{term}'")
        all_video_items.extend(video_items)

    # Remove duplicates and calculate total duration
    unique_video_items = []
    seen_urls = set()
    for item in all_video_items:
        if item.url not in seen_urls:
            unique_video_items.append(item)
            seen_urls.add(item.url)

    if video_concat_mode == VideoConcatMode.random:
        random.shuffle(unique_video_items)

    found_duration = sum(item.duration for item in unique_video_items)
    logger.info(f"found total unique videos: {len(unique_video_items)}, required duration: {audio_duration:.4f} seconds, found duration: {found_duration:.2f} seconds")
    logger.info(f"Video download list (first 5): {[item.url for item in unique_video_items[:5]]}")

    if not unique_video_items:
        logger.warning("No videos found for the given search terms.")
        return []

    if found_duration < audio_duration:
        logger.warning(f"total duration of found videos ({found_duration:.2f}s) is less than audio duration ({audio_duration:.2f}s).")

    downloaded_materials: List[MaterialInfo] = []
    downloaded_duration = 0.0
    
    for item in unique_video_items:
        if downloaded_duration >= audio_duration:
            logger.info(f"total duration of downloaded videos: {downloaded_duration:.2f} seconds, skip downloading more")
            break
        
        try:
            logger.info(f"downloading video: {item.url}")
            file_path = save_video(video_url=item.url)
            if file_path:
                logger.info(f"video saved: {file_path}")
                material_info = MaterialInfo()
                material_info.path = file_path
                material_info.start_time = 0.0
                ffprobe_info = _get_video_info_ffprobe(file_path)
                if ffprobe_info and ffprobe_info.get("duration"):
                    material_info.duration = float(ffprobe_info.get("duration"))
                    downloaded_duration += material_info.duration
                else:
                    material_info.duration = item.duration # fallback
                    downloaded_duration += item.duration
                
                downloaded_materials.append(material_info)

        except Exception as e:
            logger.error(f"failed to download video: {item.url} => {e}")

    logger.success(f"downloaded {len(downloaded_materials)} videos")
    return downloaded_materials


# 以下为调试入口，仅供开发测试
if __name__ == "__main__":
    download_videos(
        "test123", ["Money Exchange Medium"], audio_duration=100, source="pixabay"
    )
