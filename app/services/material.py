import os
import random
import math
from typing import List
from typing import Optional
from urllib.parse import urlencode

import requests
from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoConcatMode
from app.utils import utils
from app.services.llm import add_english_translations
from app.services.download_manager import download_video, initialize_download_system, get_download_status

# Style keyword mapping based on visual requirements
STYLE_KEYWORDS = {
    'people': ['people', 'human', 'lifestyle', 'person', 'character', 'humanoid'],
    'scenery': ['nature', 'landscape', 'scenery', 'travel', 'outdoor', 'environment'],
    'animation': ['animation', 'cartoon', 'illustration', 'animated', 'cartoony'],
    'ai': ['ai', 'artificial intelligence', 'machine learning', 'neural', 'robot', 'digital', 'futuristic']
}

# Visual cues for each style
VISUAL_CUES = {
    'people': ['people', 'human', 'person', 'character', 'man', 'woman', 'child', 'family', 'group', 'individual', 'lifestyle', 'portrait', 'face', 'figure', 'body'],
    'scenery': ['nature', 'landscape', 'scenery', 'travel', 'outdoor', 'environment', 'mountain', 'forest', 'ocean', 'beach', 'sky', 'sunset', 'landform', 'natural'],
    'animation': ['animation', 'cartoon', 'illustration', 'animated', 'cartoony', 'cartoonish', 'anime', 'comic', 'drawing', 'sketch', 'digital art'],
    'ai': ['ai', 'artificial intelligence', 'machine learning', 'deep learning', 'neural network', 'robot', 'robotic', 'digital', 'futuristic', 'technology', 'cyber', 'automation', 'algorithm']
}

def extract_style_keyword(visual_requirement: str) -> str:
    """
    Extract style keyword from visual requirements
    
    Args:
        visual_requirement: Visual requirements text
    
    Returns:
        Style keyword in English
    """
    if not visual_requirement:
        return ""
    
    # Convert to lowercase for case-insensitive matching
    text = visual_requirement.lower()
    
    # Check for visual cues in order of priority
    for style, cues in VISUAL_CUES.items():
        for cue in cues:
            if cue in text:
                # Return the first matching style's primary keyword
                return STYLE_KEYWORDS[style][0]
    
    # Default to no style keyword
    return ""

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
    style_keyword: str = "",
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)
    # Map aspect to Pexels API orientation parameter
    if aspect == VideoAspect.portrait or aspect == VideoAspect.portrait_3_4:
        video_orientation = "portrait"
    elif aspect == VideoAspect.landscape:
        video_orientation = "landscape"
    elif aspect == VideoAspect.square:
        video_orientation = "square"
    else:
        video_orientation = "portrait"
    video_width, video_height = aspect.to_resolution()
    api_key = get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    }
    # Build search query with style keyword if provided
    full_search_term = search_term
    if style_keyword and style_keyword != "none":
        full_search_term = f"{style_keyword} {search_term}"
        logger.info(f"Adding style keyword '{style_keyword}' to search term")
    
    # Build URL
    params = {"query": full_search_term, "per_page": 20, "orientation": video_orientation}
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
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["video_files"]
            # loop through each url to determine the best quality
            # First try to find exact match
            best_video = None
            best_quality_score = -1
            
            for video in video_files:
                w = int(video["width"])
                h = int(video["height"])
                
                # Calculate quality score (prefer higher resolution)
                quality_score = w * h
                
                # Check if this is an exact match
                if w == video_width and h == video_height:
                    best_video = video
                    best_quality_score = quality_score
                    break  # Exact match found, use it
                
                # If no exact match yet, track the best quality video
                # that is at least as large as target resolution
                if best_video is None or quality_score > best_quality_score:
                    if w >= video_width and h >= video_height:
                        best_video = video
                        best_quality_score = quality_score
            
            # If no suitable video found, use the highest quality available
            if best_video is None and video_files:
                for video in video_files:
                    w = int(video["width"])
                    h = int(video["height"])
                    quality_score = w * h
                    if best_video is None or quality_score > best_quality_score:
                        best_video = video
                        best_quality_score = quality_score
            
            # Filter out low quality videos
            if best_video:
                w = int(best_video["width"])
                h = int(best_video["height"])
                # Calculate minimum acceptable resolution (90% of target to ensure quality)
                min_width = int(video_width * 0.90)
                min_height = int(video_height * 0.90)
                
                # Skip videos that are too low quality
                if w < min_width or h < min_height:
                    logger.warning(f"Skipping low quality video: {w}x{h}, minimum required: {min_width}x{min_height} (90% of target)")
                    continue
                
                # Check if video needs to be upscaled (enlarged)
                scale_w = video_width / w if w < video_width else 1.0
                scale_h = video_height / h if h < video_height else 1.0
                max_scale = max(scale_w, scale_h)
                
                # Log video quality information
                if max_scale > 1.0:
                    if max_scale <= 1.10:  # Allow up to 110% upscaling
                        logger.info(f"Video needs upscaling: {w}x{h} -> {video_width}x{video_height} (scale: {max_scale:.2f}x, within 110% limit)")
                    else:
                        logger.warning(f"Skipping video requiring too much upscaling: {w}x{h} -> {video_width}x{video_height} (scale: {max_scale:.2f}x, max allowed: 1.10x)")
                        continue
                
                # Create item for videos that passed quality checks
                item = MaterialInfo()
                item.provider = "pexels"
                item.url = best_video["link"]
                item.duration = duration
                item.width = w
                item.height = h
                
                video_items.append(item)
                # logger.info(f"Selected video: {w}x{h}, target: {video_width}x{video_height}, scale_factor: {max_scale:.2f}x")
        
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def search_videos_pixabay(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
    style_keyword: str = "",
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)

    video_width, video_height = aspect.to_resolution()

    api_key = get_api_key("pixabay_api_keys")
    # Build search query with style keyword if provided
    full_search_term = search_term
    if style_keyword and style_keyword != "none":
        full_search_term = f"{style_keyword} {search_term}"
        logger.info(f"Adding style keyword '{style_keyword}' to search term")
    
    # Build URL
    params = {
        "q": full_search_term,
        "video_type": "all",  # Accepted values: "all", "film", "animation"
        "per_page": 50,
        "key": api_key,
    }
    query_url = f"https://pixabay.com/api/videos/?{urlencode(params)}"
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url, proxies=config.proxy, verify=False, timeout=(30, 60)
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
            # First try to find exact match
            best_video = None
            best_quality_score = -1
            
            for video_type in video_files:
                video = video_files[video_type]
                w = int(video["width"])
                h = int(video["height"])
                
                # Calculate quality score (prefer higher resolution)
                quality_score = w * h
                
                # Check if this is an exact match
                if w == video_width and h == video_height:
                    best_video = video
                    best_quality_score = quality_score
                    break  # Exact match found, use it
                
                # If no exact match yet, track the best quality video
                # that is at least as large as target resolution
                if best_video is None or quality_score > best_quality_score:
                    if w >= video_width and h >= video_height:
                        best_video = video
                        best_quality_score = quality_score
            
            # If no suitable video found, use the highest quality available
            if best_video is None and video_files:
                for video_type in video_files:
                    video = video_files[video_type]
                    w = int(video["width"])
                    h = int(video["height"])
                    quality_score = w * h
                    if best_video is None or quality_score > best_quality_score:
                        best_video = video
                        best_quality_score = quality_score
            
            # Filter out low quality videos
            if best_video:
                w = int(best_video["width"])
                h = int(best_video["height"])
                # Calculate minimum acceptable resolution (75% of target)
                min_width = int(video_width * 0.75)
                min_height = int(video_height * 0.75)
                
                # Skip videos that are too low quality
                if w < min_width or h < min_height:
                    logger.warning(f"Skipping low quality video: {w}x{h}, minimum required: {min_width}x{min_height}")
                    continue
                
                item = MaterialInfo()
                item.provider = "pixabay"
                item.url = best_video["url"]
                item.duration = duration
                video_items.append(item)
                logger.info(f"selected video: {best_video['width']}x{best_video['height']}, target: {video_width}x{video_height}")
        
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

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
                verify=False,
                timeout=(60, 240),
            ).content
        )

    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        try:
            clip = VideoFileClip(video_path)
            duration = clip.duration
            fps = clip.fps
            clip.close()
            if duration > 0 and fps > 0:
                return video_path
        except Exception as e:
            try:
                os.remove(video_path)
            except Exception:
                pass
            logger.warning(f"invalid video file: {video_path} => {str(e)}")
    return ""


def download_videos(
    task_id: str,
    search_terms: List[str],
    source: str = "pexels",
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    audio_duration: float = 0.0,
    max_clip_duration: int = 5,
    style_keyword: str = "",
    target_number_of_clips: Optional[int] = None,
) -> List[str]:
    # Initialize download system
    initialize_download_system()
    
    valid_video_items = []
    valid_video_urls = []
    found_duration = 0.0
    
    # Determine primary and fallback sources
    primary_source = source
    fallback_source = "pixabay" if source == "pexels" else "pexels"
    
    search_videos_primary = search_videos_pexels if primary_source == "pexels" else search_videos_pixabay
    search_videos_fallback = search_videos_pixabay if primary_source == "pexels" else search_videos_pexels

    # Filter out empty search terms
    valid_search_terms = [term for term in search_terms if term and term.strip()]
    
    if not valid_search_terms:
        logger.warning("No valid search terms provided for video download")
        return []
    
    # Add English translations for non-English terms to maximize search coverage
    enhanced_search_terms = add_english_translations(valid_search_terms)
    logger.info(f"Enhanced search terms with translations: {enhanced_search_terms}")
    valid_search_terms = enhanced_search_terms

    # Search with primary source
    logger.info(f"Searching videos from primary source: {primary_source}")
    for search_term in valid_search_terms:
        video_items = search_videos_primary(
            search_term=search_term,
            minimum_duration=max_clip_duration,
            video_aspect=video_aspect,
            style_keyword=style_keyword,
        )
        logger.info(f"found {len(video_items)} videos for '{search_term}' from {primary_source}")

        for item in video_items:
            if item.url not in valid_video_urls:
                valid_video_items.append(item)
                valid_video_urls.append(item.url)
                found_duration += item.duration

    logger.info(
        f"found total videos: {len(valid_video_items)}, required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )
    
    # If no videos found from primary source, try fallback source
    if len(valid_video_items) == 0:
        logger.warning(f"No videos found from {primary_source}, trying fallback source: {fallback_source}")
        for search_term in valid_search_terms:
            video_items = search_videos_fallback(
                search_term=search_term,
                minimum_duration=max_clip_duration,
                video_aspect=video_aspect,
                style_keyword=style_keyword,
            )
            logger.info(f"found {len(video_items)} videos for '{search_term}' from {fallback_source}")

            for item in video_items:
                if item.url not in valid_video_urls:
                    valid_video_items.append(item)
                    valid_video_urls.append(item.url)
                    found_duration += item.duration
        
        if len(valid_video_items) > 0:
            logger.success(f"Found {len(valid_video_items)} videos from fallback source {fallback_source}")
    
    video_paths = []
    downloaded_paths = []
    download_count = 0
    download_failures = 0
    total_download_attempts = 0

    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    if video_concat_mode.value == VideoConcatMode.random.value:
        random.shuffle(valid_video_items)

    # Calculate and limit the number of videos to download
    total_available_videos = len(valid_video_items)
    if target_number_of_clips is None:
        # Calculate minimum required clips based on audio duration
        min_required_clips = max(1, int(math.ceil(audio_duration / max_clip_duration)))
        # Set target to 1.5x the required clips for better coverage
        target_number_of_clips = int(min_required_clips * 1.5)
        logger.info(f"No target specified - calculated: min_required={min_required_clips}, target={target_number_of_clips} (1.5x)")
    else:
        # Set target to 1.5x the provided target for better coverage
        target_number_of_clips = int(target_number_of_clips * 1.5)
        logger.info(f"Using provided target: {target_number_of_clips} (1.5x)")
    
    # Randomly select specific number of videos from search results
    if len(valid_video_items) > target_number_of_clips:
        # Shuffle to ensure random selection, then pick target number
        random.shuffle(valid_video_items)
        valid_video_items = valid_video_items[:target_number_of_clips]
        logger.info(f"Randomly selected {target_number_of_clips} videos from {total_available_videos} available for download")
    else:
        logger.info(f"Downloading all {len(valid_video_items)} available videos (less than target of {target_number_of_clips})")

    total_duration = 0.0
    
    # Function to handle download completion
    def download_callback(success, path=None, error=None):
        nonlocal download_count, total_duration, download_failures, total_download_attempts
        total_download_attempts += 1
        if success and path:
            downloaded_paths.append(path)
            # Get video duration
            try:
                clip = VideoFileClip(path)
                duration = clip.duration
                clip.close()
                seconds = min(max_clip_duration, duration)
                total_duration += seconds
            except Exception as e:
                logger.error(f"Failed to get video duration: {e}")
                seconds = max_clip_duration
                total_duration += seconds
            download_count += 1
            logger.info(f"Video downloaded: {path}, total downloaded: {download_count}")
        elif error:
            download_failures += 1
            logger.error(f"Download failed: {error}")

    # Add download tasks to queue
    for item in valid_video_items:
        try:
            # Generate save path
            url_without_query = item.url.split("?")[0]
            url_hash = utils.md5(url_without_query)
            video_id = f"vid-{url_hash}"
            if material_directory:
                save_path = f"{material_directory}/{video_id}.mp4"
            else:
                save_dir = utils.storage_dir("cache_videos")
                save_path = f"{save_dir}/{video_id}.mp4"
            
            # Check if video already exists
            if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
                logger.info(f"Video already exists: {save_path}")
                downloaded_paths.append(save_path)
                seconds = min(max_clip_duration, item.duration)
                total_duration += seconds
                download_count += 1
            else:
                # Add to download queue
                logger.info(f"Adding video to download queue: {item.url}")
                download_video(item.url, save_path, download_callback)
                
            # Check if we have enough duration
            if total_duration > audio_duration:
                logger.info(
                    f"Total duration of downloaded videos: {total_duration} seconds, skip downloading more"
                )
                break
        except Exception as e:
            logger.error(f"Failed to add video to download queue: {utils.to_json(item)} => {str(e)}")
    
    # Wait for downloads to complete (simple approach)
    # In a production environment, you might want to use a more robust mechanism
    import time
    start_time = time.time()
    timeout = 600  # 10 minutes timeout
    
    while len(downloaded_paths) < len(valid_video_items) and time.time() - start_time < timeout:
        status = get_download_status()
        logger.debug(f"Download status: {status}")
        if status['active_downloads'] == 0 and status['queue_size'] == 0:
            break
        time.sleep(5)  # Check every 5 seconds
    
    # Check if we need to fallback to alternative source due to high failure rate
    failure_rate = download_failures / total_download_attempts if total_download_attempts > 0 else 0
    if failure_rate > 0.5 and len(downloaded_paths) < 3:
        logger.warning(f"High download failure rate ({failure_rate*100:.1f}%) from {primary_source}, trying fallback source: {fallback_source}")
        
        # Try downloading from fallback source
        valid_video_items_fallback = []
        for search_term in valid_search_terms:
            video_items = search_videos_fallback(
                search_term=search_term,
                minimum_duration=max_clip_duration,
                video_aspect=video_aspect,
                style_keyword=style_keyword,
            )
            for item in video_items:
                # Avoid duplicates from primary source
                if item.url not in valid_video_urls:
                    valid_video_items_fallback.append(item)
        
        # Download from fallback source
        for item in valid_video_items_fallback:
            if total_duration > audio_duration:
                break
            try:
                url_without_query = item.url.split("?")[0]
                url_hash = utils.md5(url_without_query)
                video_id = f"vid-{url_hash}"
                if material_directory:
                    save_path = f"{material_directory}/{video_id}.mp4"
                else:
                    save_dir = utils.storage_dir("cache_videos")
                    save_path = f"{save_dir}/{video_id}.mp4"
                
                if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
                    logger.info(f"Video already exists: {save_path}")
                    downloaded_paths.append(save_path)
                    seconds = min(max_clip_duration, item.duration)
                    total_duration += seconds
                else:
                    logger.info(f"Adding fallback video to download queue: {item.url}")
                    download_video(item.url, save_path, download_callback)
                    time.sleep(2)  # Small delay between fallback downloads
            except Exception as e:
                logger.error(f"Failed to add fallback video: {str(e)}")
        
        # Wait for fallback downloads
        fallback_start = time.time()
        fallback_timeout = 300  # 5 minutes for fallback
        while len(downloaded_paths) < len(valid_video_items) + len(valid_video_items_fallback) and time.time() - fallback_start < fallback_timeout:
            status = get_download_status()
            if status['active_downloads'] == 0 and status['queue_size'] == 0:
                break
            time.sleep(5)
    
    logger.success(f"Downloaded {len(downloaded_paths)} videos (failures: {download_failures}/{total_download_attempts})")
    return downloaded_paths


if __name__ == "__main__":
    download_videos(
        "test123", ["Money Exchange Medium"], audio_duration=100, source="pixabay"
    )
