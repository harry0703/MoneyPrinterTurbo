import os
import random
from urllib.parse import urlencode

import requests
from typing import List
from loguru import logger

from app.config import config
from app.models.schema import VideoAspect, VideoConcatMode, MaterialInfo
from app.utils import utils

requested_count = 0
pexels_api_keys = config.app.get("pexels_api_keys")
if not pexels_api_keys:
    raise ValueError(f"\n\n##### pexels_api_keys is not set #####\n\nPlease set it in the config.toml file: {config.config_file}\n\n{utils.to_json(config.app)}")


def round_robin_api_key():
    # if only one key is provided, return it
    if isinstance(pexels_api_keys, str):
        return pexels_api_keys

    global requested_count
    requested_count += 1
    return pexels_api_keys[requested_count % len(pexels_api_keys)]


def search_videos(search_term: str,
                  minimum_duration: int,
                  video_aspect: VideoAspect = VideoAspect.portrait,
                  ) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)
    video_orientation = aspect.name
    video_width, video_height = aspect.to_resolution()

    headers = {
        "Authorization": round_robin_api_key()
    }
    proxies = config.pexels.get("proxies", None)
    # Build URL
    params = {
        "query": search_term,
        "per_page": 20,
        "orientation": video_orientation
    }
    query_url = f"https://api.pexels.com/videos/search?{urlencode(params)}"
    logger.info(f"searching videos: {query_url}, with proxies: {proxies}")

    try:
        r = requests.get(query_url, headers=headers, proxies=proxies, verify=False)
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


def save_video(video_url: str, save_dir: str = "") -> str:
    if not save_dir:
        save_dir = utils.storage_dir("cache_videos")

    url_without_query = video_url.split("?")[0]
    url_hash = utils.md5(url_without_query)
    video_id = f"vid-{url_hash}"
    video_path = f"{save_dir}/{video_id}.mp4"

    # if video already exists, return the path
    if os.path.exists(video_path):
        logger.info(f"video already exists: {video_path}")
        return video_path

    # if video does not exist, download it
    proxies = config.pexels.get("proxies", None)
    with open(video_path, "wb") as f:
        f.write(requests.get(video_url, proxies=proxies, verify=False, timeout=(10, 180)).content)

    return video_path


def download_videos(task_id: str,
                    search_terms: List[str],
                    video_aspect: VideoAspect = VideoAspect.portrait,
                    video_contact_mode: VideoConcatMode = VideoConcatMode.random,
                    audio_duration: float = 0.0,
                    max_clip_duration: int = 5,
                    ) -> List[str]:
    valid_video_items = []
    valid_video_urls = []
    found_duration = 0.0
    for search_term in search_terms:
        # logger.info(f"searching videos for '{search_term}'")
        video_items = search_videos(search_term=search_term,
                                    minimum_duration=max_clip_duration,
                                    video_aspect=video_aspect)
        logger.info(f"found {len(video_items)} videos for '{search_term}'")

        for item in video_items:
            if item.url not in valid_video_urls:
                valid_video_items.append(item)
                valid_video_urls.append(item.url)
                found_duration += item.duration

    logger.info(
        f"found total videos: {len(valid_video_items)}, required duration: {audio_duration} seconds, found duration: {found_duration} seconds")
    video_paths = []

    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    if video_contact_mode.value == VideoConcatMode.random.value:
        random.shuffle(valid_video_items)

    total_duration = 0.0
    for item in valid_video_items:
        try:
            logger.info(f"downloading video: {item.url}")
            saved_video_path = save_video(video_url=item.url, save_dir=material_directory)
            logger.info(f"video saved: {saved_video_path}")
            video_paths.append(saved_video_path)
            seconds = min(max_clip_duration, item.duration)
            total_duration += seconds
            if total_duration > audio_duration:
                logger.info(f"total duration of downloaded videos: {total_duration} seconds, skip downloading more")
                break
        except Exception as e:
            logger.error(f"failed to download video: {utils.to_json(item)} => {str(e)}")
    logger.success(f"downloaded {len(video_paths)} videos")
    return video_paths


if __name__ == "__main__":
    download_videos("test123", ["cat"], audio_duration=100)
