import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple
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

# Download configuration constants
_MAX_DOWNLOAD_RETRIES = 3
_DOWNLOAD_RETRY_BACKOFF = 2.0
_DEFAULT_MAX_WORKERS = 4
_DOWNLOAD_TIMEOUT = (60, 240)  # (connect_timeout, read_timeout)
_SEARCH_TIMEOUT = (30, 60)


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
            timeout=_SEARCH_TIMEOUT,
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
            query_url, proxies=config.proxy, verify=_get_tls_verify(), timeout=_SEARCH_TIMEOUT
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


def save_video(video_url: str, save_dir: str = "") -> str:
    """Download and save a video with retry mechanism.
    
    Args:
        video_url: URL of the video to download
        save_dir: Directory to save the video (default: cache_videos)
        
    Returns:
        Path to the downloaded video file, or empty string if failed
        
    Raises:
        Propagates exceptions after all retries exhausted
    """
    if not save_dir:
        save_dir = utils.storage_dir("cache_videos")

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    url_without_query = video_url.split("?")[0]
    url_hash = utils.md5(url_without_query)
    video_id = f"vid-{url_hash}"
    video_path = f"{save_dir}/{video_id}.mp4"

    # if video already exists, validate and return the path
    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        logger.info(f"video already exists: {video_path}")
        return video_path

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }

    # Download with retry mechanism
    last_exception = None
    for attempt in range(_MAX_DOWNLOAD_RETRIES):
        try:
            logger.debug(f"downloading video (attempt {attempt + 1}/{_MAX_DOWNLOAD_RETRIES}): {video_url}")
            response = requests.get(
                video_url,
                headers=headers,
                proxies=config.proxy,
                verify=_get_tls_verify(),
                timeout=_DOWNLOAD_TIMEOUT,
                stream=False,
            )
            response.raise_for_status()
            
            with open(video_path, "wb") as f:
                f.write(response.content)
            
            logger.info(f"video downloaded successfully: {video_path}")
            return video_path
            
        except requests.Timeout as e:
            last_exception = e
            logger.warning(f"timeout downloading video (attempt {attempt + 1}/{_MAX_DOWNLOAD_RETRIES}): {video_url}")
            if attempt < _MAX_DOWNLOAD_RETRIES - 1:
                wait_time = _DOWNLOAD_RETRY_BACKOFF ** attempt
                logger.debug(f"waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                
        except requests.RequestException as e:
            last_exception = e
            logger.warning(f"request error downloading video (attempt {attempt + 1}/{_MAX_DOWNLOAD_RETRIES}): {str(e)}")
            if attempt < _MAX_DOWNLOAD_RETRIES - 1:
                wait_time = _DOWNLOAD_RETRY_BACKOFF ** attempt
                time.sleep(wait_time)
                
        except Exception as e:
            last_exception = e
            logger.error(f"unexpected error downloading video: {str(e)}")
            raise
    
    # Clean up partial file if download failed
    try:
        if os.path.exists(video_path):
            os.remove(video_path)
    except Exception as cleanup_error:
        logger.warning(f"failed to cleanup partial download {video_path}: {str(cleanup_error)}")
    
    logger.error(f"failed to download video after {_MAX_DOWNLOAD_RETRIES} attempts: {video_url} => {str(last_exception)}")
    return ""

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


def _download_single_video(
    item: MaterialInfo, 
    save_dir: str,
    max_clip_duration: int
) -> Tuple[Optional[str], float]:
    """Download a single video and return path with duration.
    
    Args:
        item: MaterialInfo object containing video URL and metadata
        save_dir: Directory to save the video
        max_clip_duration: Maximum clip duration to use
        
    Returns:
        Tuple of (video_path, duration) or (None, 0) if failed
    """
    try:
        saved_video_path = save_video(video_url=item.url, save_dir=save_dir)
        if saved_video_path:
            seconds = min(max_clip_duration, item.duration)
            logger.info(f"video saved: {saved_video_path} (duration: {seconds}s)")
            return saved_video_path, seconds
    except Exception as e:
        logger.error(f"failed to download video: {utils.to_json(item)} => {str(e)}")
    
    return None, 0.0


def download_videos(
    task_id: str,
    search_terms: List[str],
    source: str = "pexels",
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_contact_mode: VideoConcatMode = VideoConcatMode.random,
    audio_duration: float = 0.0,
    max_clip_duration: int = 5,
    max_workers: int = _DEFAULT_MAX_WORKERS,
) -> List[str]:
    """Download videos concurrently with automatic retry and progress tracking.
    
    Args:
        task_id: Task ID for organizing output
        search_terms: List of search terms to find videos
        source: Video source ('pexels' or 'pixabay')
        video_aspect: Video aspect ratio (portrait, landscape, etc.)
        video_contact_mode: How to concat videos (random or sequential)
        audio_duration: Target audio duration (stop downloading when exceeded)
        max_clip_duration: Maximum duration to use from each clip
        max_workers: Number of concurrent download threads (default: 4)
        
    Returns:
        List of local video file paths
    """
    valid_video_items = []
    valid_video_urls = []
    found_duration = 0.0
    search_videos = search_videos_pexels
    if source == "pixabay":
        search_videos = search_videos_pixabay

    # Search for videos from all search terms
    for search_term in search_terms:
        try:
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
        except Exception as e:
            logger.error(f"error searching for videos with term '{search_term}': {str(e)}")

    logger.info(
        f"found total videos: {len(valid_video_items)}, required duration: {audio_duration}s, found duration: {found_duration}s"
    )

    # Setup download directory
    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    # Optionally shuffle for random concat mode
    if video_contact_mode.value == VideoConcatMode.random.value:
        random.shuffle(valid_video_items)

    # Concurrent download with thread pool
    video_paths = []
    total_duration = 0.0
    
    # Limit max_workers to number of videos
    actual_workers = min(max_workers, len(valid_video_items))
    logger.info(f"starting concurrent download with {actual_workers} workers")
    
    with ThreadPoolExecutor(max_workers=actual_workers) as executor:
        # Submit all download tasks
        future_to_item = {
            executor.submit(
                _download_single_video,
                item,
                material_directory,
                max_clip_duration
            ): item for item in valid_video_items
        }
        
        # Process completed downloads
        for future in as_completed(future_to_item):
            if total_duration >= audio_duration and audio_duration > 0:
                logger.info(
                    f"reached target duration {total_duration}s >= {audio_duration}s, stopping downloads"
                )
                # Cancel remaining tasks
                for f in future_to_item:
                    f.cancel()
                break
            
            try:
                saved_video_path, duration = future.result(timeout=300)
                if saved_video_path:
                    video_paths.append(saved_video_path)
                    total_duration += duration
            except Exception as e:
                item = future_to_item[future]
                logger.error(f"download task failed for {item.url}: {str(e)}")
    
    logger.success(
        f"downloaded {len(video_paths)} videos with total duration {total_duration}s"
    )
    return video_paths


if __name__ == "__main__":
    download_videos(
        "test123", ["Money Exchange Medium"], audio_duration=100, source="pixabay"
    )
