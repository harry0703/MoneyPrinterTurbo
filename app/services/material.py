import logging
import os
import random
from typing import List
from urllib.parse import urlencode
import math

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


def download_videos_for_clips(video_search_terms: List[str], num_clips: int, source: str) -> List[MaterialInfo]:
    logger.info(f"Attempting to download {num_clips} unique video clips for {len(video_search_terms)} terms.")
    downloaded_videos = []
    used_video_urls = set()

    if not video_search_terms:
        logger.error("No video search terms provided. Cannot download videos.")
        return []

    import itertools
    # Expand search terms if not enough for the number of clips
    if len(video_search_terms) < num_clips:
        logger.warning(f"Number of search terms ({len(video_search_terms)}) is less than the required number of clips ({num_clips}). Reusing terms.")
        video_search_terms = list(itertools.islice(itertools.cycle(video_search_terms), num_clips))

    search_term_queue = list(video_search_terms)
    random.shuffle(search_term_queue)

    while len(downloaded_videos) < num_clips and search_term_queue:
        term = search_term_queue.pop(0)
        try:
            if source == "pexels":
                video_items = search_videos_pexels(
                    search_term=term,
                    minimum_duration=5,
                    video_aspect=VideoAspect.portrait,
                )
            elif source == "pixabay":
                video_items = search_videos_pixabay(
                    search_term=term,
                    minimum_duration=5,
                    video_aspect=VideoAspect.portrait,
                )
            else:
                video_items = []
            
            if not video_items:
                logger.warning(f"No video results for term: '{term}'")
                continue

            random.shuffle(video_items)

            for item in video_items:
                if item.url in used_video_urls:
                    continue

                logger.info(f"Downloading video for term '{term}': {item.url}")
                file_path = save_video(item.url)
                if file_path:
                    video_material = MaterialInfo(
                        path=file_path,
                        url=item.url,
                        duration=_get_video_info_ffprobe(file_path).get("duration", 0.0),
                        start_time=0.0
                    )
                    downloaded_videos.append(video_material)
                    used_video_urls.add(item.url)
                    logger.info(f"Video saved: {file_path}")
                    break  # Move to the next search term
                else:
                    logger.warning(f"Video download failed: {item.url}")

        except Exception as e:
            logger.error(f"Error processing search term '{term}': {e}")

    # Fallback: If not enough unique videos were found, reuse the ones we have
    if downloaded_videos and len(downloaded_videos) < num_clips:
        logger.warning(f"Could not find enough unique videos. Required: {num_clips}, Found: {len(downloaded_videos)}. Reusing downloaded videos.")
        needed = num_clips - len(downloaded_videos)
        reused_videos = list(itertools.islice(itertools.cycle(downloaded_videos), needed))
        downloaded_videos.extend(reused_videos)

    if len(downloaded_videos) < num_clips:
        logger.error(f"Failed to download enough videos. Required: {num_clips}, Found: {len(downloaded_videos)}. Aborting.")
        return []

    logger.success(f"Successfully downloaded {len(downloaded_videos)} video clips.")
    return downloaded_videos

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
    sm.state.update_task(task_id, status_message=f"Downloading videos for terms: {search_terms}")
    num_clips = math.ceil(audio_duration / max_clip_duration) if max_clip_duration > 0 else 1
    logger.info(f"Required audio duration: {audio_duration:.2f}s, max_clip_duration: {max_clip_duration}s. Calculated number of clips: {num_clips}")
    return download_videos_for_clips(video_search_terms=search_terms, num_clips=num_clips, source=source)


# 以下为调试入口，仅供开发测试
if __name__ == "__main__":
    download_videos(
        "test123", ["Money Exchange Medium"], ["Money Exchange Medium"], audio_duration=100, source="pixabay"
    )
