import time

import requests
from typing import List
from loguru import logger

from app.config import config
from app.models.schema import VideoAspect
from app.utils import utils

requested_count = 0
pexels_api_keys = config.app.get("pexels_api_keys")
if not pexels_api_keys:
    raise ValueError("pexels_api_keys is not set, please set it in the config.toml file.")


def round_robin_api_key():
    global requested_count
    requested_count += 1
    return pexels_api_keys[requested_count % len(pexels_api_keys)]


def search_videos(search_term: str,
                  wanted_count: int,
                  minimum_duration: int,
                  video_aspect: VideoAspect = VideoAspect.portrait,
                  locale: str = "zh-CN"
                  ) -> List[str]:
    aspect = VideoAspect(video_aspect)
    video_orientation = aspect.name
    video_width, video_height = aspect.to_resolution()

    headers = {
        "Authorization": round_robin_api_key()
    }
    proxies = config.pexels.get("proxies", None)
    # Build URL
    query_url = f"https://api.pexels.com/videos/search?query={search_term}&per_page=15&orientation={video_orientation}&locale={locale}"
    logger.info(f"searching videos: {query_url}, with proxies: {proxies}")
    # Send the request
    r = requests.get(query_url, headers=headers, proxies=proxies, verify=False)

    # Parse the response
    response = r.json()
    video_urls = []

    try:
        videos_count = min(len(response["videos"]), wanted_count)
        # loop through each video in the result
        for i in range(videos_count):
            # check if video has desired minimum duration
            if response["videos"][i]["duration"] < minimum_duration:
                continue
            video_files = response["videos"][i]["video_files"]
            # loop through each url to determine the best quality
            for video in video_files:
                # Check if video has a valid download link
                # if ".com/external" in video["link"]:
                w = int(video["width"])
                h = int(video["height"])
                if w == video_width and h == video_height:
                    video_urls.append(video["link"])
                    break

    except Exception as e:
        logger.error(f"search videos failed: {e}")

    return video_urls


def save_video(video_url: str, save_dir: str) -> str:
    video_id = f"vid-{str(int(time.time() * 1000))}"
    video_path = f"{save_dir}/{video_id}.mp4"
    proxies = config.pexels.get("proxies", None)
    with open(video_path, "wb") as f:
        f.write(requests.get(video_url, proxies=proxies, verify=False).content)

    return video_path


def download_videos(task_id: str,
                    search_terms: List[str],
                    video_aspect: VideoAspect = VideoAspect.portrait,
                    wanted_count: int = 15,
                    minimum_duration: int = 5
                    ) -> List[str]:
    valid_video_urls = []
    for search_term in search_terms:
        # logger.info(f"searching videos for '{search_term}'")
        video_urls = search_videos(search_term=search_term,
                                   wanted_count=wanted_count,
                                   minimum_duration=minimum_duration,
                                   video_aspect=video_aspect)
        logger.info(f"found {len(video_urls)} videos for '{search_term}'")
        i = 0
        for url in video_urls:
            if url not in valid_video_urls:
                valid_video_urls.append(url)
                i += 1
                if i >= 3:
                    break

    logger.info(f"downloading videos: {len(valid_video_urls)}")
    video_paths = []
    save_dir = utils.task_dir(task_id)
    for video_url in valid_video_urls:
        try:
            saved_video_path = save_video(video_url, save_dir)
            video_paths.append(saved_video_path)
        except Exception as e:
            logger.error(f"failed to download video: {video_url}, {e}")
    logger.success(f"downloaded {len(video_paths)} videos")
    return video_paths
