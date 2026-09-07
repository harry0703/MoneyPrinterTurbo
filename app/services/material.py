import json
import os
import random
import subprocess
import threading
from typing import Any, List, Tuple
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
_CACHE_INDEX_FILE = "cache_index.json"


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

    # Determine target orientation for post-search filtering
    if video_width > video_height:
        target_orientation = "landscape"
    elif video_height > video_width:
        target_orientation = "portrait"
    else:
        target_orientation = "square"

    api_key = get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    }
    # Build URL — pass orientation to narrow server-side results
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
            # Pick the best-quality file with matching orientation (no exact-pixel match)
            best = None
            best_pixels = 0
            for video in video_files:
                w = int(video["width"] or 0)
                h = int(video["height"] or 0)
                if w == 0 or h == 0:
                    continue
                # Orientation check
                if target_orientation == "portrait" and h <= w:
                    continue
                if target_orientation == "landscape" and w <= h:
                    continue
                if target_orientation == "square" and abs(w - h) > max(w, h) * 0.15:
                    continue
                pixels = w * h
                if pixels > best_pixels:
                    best_pixels = pixels
                    best = video
            if best:
                item = MaterialInfo()
                item.provider = "pexels"
                item.url = best["link"]
                item.duration = duration
                video_items.append(item)
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

    # Determine target orientation for post-search filtering
    if video_width > video_height:
        target_orientation = "landscape"
    elif video_height > video_width:
        target_orientation = "portrait"
    else:
        target_orientation = "square"

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
            # Prefer highest quality; iterate in descending quality order
            for video_type in ["large", "medium", "small", "tiny"]:
                if video_type not in video_files:
                    continue
                video = video_files[video_type]
                w = int(video["width"])
                h = int(video["height"])
                if w == 0 or h == 0:
                    continue
                # Filter by orientation to match the requested video_aspect
                if target_orientation == "portrait" and h <= w:
                    continue
                if target_orientation == "landscape" and w <= h:
                    continue
                if target_orientation == "square" and abs(w - h) > max(w, h) * 0.15:
                    continue
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


def _get_video_info(video_path: str) -> Tuple[int, int, float]:
    """Return (width, height, duration) for a local video file using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-select_streams",
                "v:0",
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        data = json.loads(result.stdout or "{}")
        streams = data.get("streams") or []
        if not streams:
            return 0, 0, 0.0
        stream = streams[0]
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        duration = float(stream.get("duration") or 0)
        return width, height, duration
    except Exception:
        return 0, 0, 0.0


def _normalize_search_terms(search_terms: List[str]) -> list[str]:
    tokens: list[str] = []
    for term in search_terms or []:
        normalized = str(term or "").strip().lower()
        if normalized:
            tokens.extend([piece for piece in normalized.replace("-", " ").replace("_", " ").split() if piece])
    return list(dict.fromkeys(tokens))


def _cache_index_path(cache_dir: str) -> str:
    return os.path.join(cache_dir, _CACHE_INDEX_FILE)


def _load_cache_index(cache_dir: str) -> dict[str, Any]:
    index_path = _cache_index_path(cache_dir)
    if not os.path.exists(index_path):
        return {}
    try:
        with open(index_path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache_index(cache_dir: str, index_data: dict[str, Any]) -> None:
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(_cache_index_path(cache_dir), "w", encoding="utf-8") as fp:
            json.dump(index_data, fp, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning(f"failed to save cache index in {cache_dir}: {str(exc)}")


def _register_cache_entry(cache_dir: str, video_path: str, video_url: str, source: str, search_term: str) -> None:
    file_name = os.path.basename(video_path)
    if not file_name:
        return
    index_data = _load_cache_index(cache_dir)
    record = dict(index_data.get(file_name) or {})
    existing_terms = record.get("terms") if isinstance(record.get("terms"), list) else []
    merged_terms = list(dict.fromkeys([*existing_terms, str(search_term or "").strip().lower()]))
    record.update(
        {
            "url": str(video_url or ""),
            "source": str(source or ""),
            "terms": [term for term in merged_terms if term],
        }
    )
    index_data[file_name] = record
    _save_cache_index(cache_dir, index_data)


def _cache_relevance_score(cache_record: dict[str, Any], normalized_terms: list[str]) -> int:
    if not normalized_terms:
        return 0
    record_terms = [str(term).strip().lower() for term in cache_record.get("terms", []) if str(term).strip()]
    if not record_terms:
        return 0
    # Tokenize the cached record's terms into a set so we match whole words,
    # not substrings (avoids "art" matching "heart", "sea" matching "season").
    record_tokens = set(_normalize_search_terms(record_terms))
    if not record_tokens:
        return 0
    score = 0
    for term in normalized_terms:
        if term in record_tokens:
            score += 1
    return score


def _scan_cache_for_reuse(
    cache_dir: str,
    target_orientation: str,
    minimum_duration: int,
    search_terms: List[str] | None = None,
) -> List[Tuple[str, float, int]]:
    """Return cached MP4 files that match orientation and minimum duration."""
    if not os.path.isdir(cache_dir):
        return []

    cache_index = _load_cache_index(cache_dir)
    normalized_terms = _normalize_search_terms(search_terms or [])
    results: List[Tuple[str, float, int]] = []
    for file_name in sorted(os.listdir(cache_dir)):
        if not file_name.lower().endswith(".mp4"):
            continue

        path = os.path.join(cache_dir, file_name)
        width, height, duration = _get_video_info(path)
        if width == 0 or height == 0 or duration < minimum_duration:
            continue

        if target_orientation == "portrait" and height <= width:
            continue
        if target_orientation == "landscape" and width <= height:
            continue
        if target_orientation == "square" and abs(width - height) > max(width, height) * 0.15:
            continue

        record = cache_index.get(file_name, {}) if isinstance(cache_index, dict) else {}
        score = _cache_relevance_score(record if isinstance(record, dict) else {}, normalized_terms)
        results.append((path, duration, score))

    logger.info(
        f"cache scan: {len(results)} reusable videos "
        f"(orientation={target_orientation}, min_dur={minimum_duration}s) in {cache_dir}"
    )
    return results


def save_video(video_url: str, save_dir: str = "", source: str = "", search_term: str = "") -> str:
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
        _register_cache_entry(save_dir, video_path, video_url, source, search_term)
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
                _register_cache_entry(save_dir, video_path, video_url, source, search_term)
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
    video_contact_mode: VideoConcatMode = VideoConcatMode.random,
    audio_duration: float = 0.0,
    max_clip_duration: int = 5,
) -> List[str]:
    # Resolve storage directory
    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""
    cache_dir = material_directory or utils.storage_dir("cache_videos")

    # Determine target orientation for cache scanning
    aspect = VideoAspect(video_aspect)
    vw, vh = aspect.to_resolution()
    if vw > vh:
        target_orientation = "landscape"
    elif vh > vw:
        target_orientation = "portrait"
    else:
        target_orientation = "square"

    is_random = video_contact_mode.value == VideoConcatMode.random.value
    normalized_terms = _normalize_search_terms(search_terms)

    # ── Phase 1: reuse ONLY keyword-relevant cached videos (score > 0) ──
    # Off-topic clips left over from previous generations are held aside and
    # used only as last-resort filler (Phase 3), so they can never silently
    # replace footage that actually matches the entered text.
    cache_index = _load_cache_index(cache_dir)
    cached_base = _scan_cache_for_reuse(
        cache_dir,
        target_orientation,
        max_clip_duration,
        search_terms=search_terms,
    )

    relevant_cache: List[Tuple[str, float, int]] = []
    neutral_cache: List[Tuple[str, float, int]] = []
    for path, dur, _ in cached_base:
        record = cache_index.get(os.path.basename(path), {}) if isinstance(cache_index, dict) else {}
        score = _cache_relevance_score(record if isinstance(record, dict) else {}, normalized_terms)
        if score > 0:
            relevant_cache.append((path, dur, score))
        else:
            neutral_cache.append((path, dur, score))

    if is_random:
        random.shuffle(relevant_cache)
        random.shuffle(neutral_cache)
    else:
        relevant_cache = sorted(relevant_cache, key=lambda item: (-item[2], item[0]))
        neutral_cache = sorted(neutral_cache, key=lambda item: item[0])

    video_paths: List[str] = []
    cached_path_set: set = set()
    total_duration = 0.0

    # Cap how much of the timeline can come from cache so fresh clips are always
    # downloaded.  Without this cap every run after the first reuses the exact
    # same cached clips because they already match the keywords and cover the
    # full duration.  0.4 means at most 40 % of the video comes from cache;
    # the rest is always fetched fresh from the API.
    max_cache_duration = audio_duration * 0.4

    for path, dur, score in relevant_cache:
        if total_duration >= max_cache_duration:
            break
        seconds = min(max_clip_duration, dur)
        video_paths.append(path)
        cached_path_set.add(path)
        total_duration += seconds
        logger.debug(f"reusing relevant cached video: {path} (score={score})")

    if total_duration >= audio_duration:
        logger.info(
            f"relevant cache covers {total_duration:.1f}s >= {audio_duration:.1f}s needed — "
            f"reusing {len(video_paths)} on-topic cached clips, skipping API download"
        )
        logger.success(f"total reused videos: {len(video_paths)}")
        return video_paths

    remaining = audio_duration - total_duration
    logger.info(
        f"relevant cache provides {total_duration:.1f}s of {audio_duration:.1f}s needed — "
        f"downloading {remaining:.1f}s more from {source}"
    )

    # ── Phase 2: fetch from API, grouped per term, selected round-robin ──
    # Each search term gets its own result bucket; we interleave the buckets so
    # every keyword is represented instead of letting one term fill the timeline.
    search_fn = search_videos_pexels if source != "pixabay" else search_videos_pixabay

    per_term_items: list[list[tuple[MaterialInfo, str]]] = []
    seen_urls: set = set()
    for search_term in search_terms:
        video_items = search_fn(
            search_term=search_term,
            minimum_duration=max_clip_duration,
            video_aspect=video_aspect,
        )
        logger.info(f"found {len(video_items)} videos for '{search_term}'")
        bucket: list[tuple[MaterialInfo, str]] = []
        for item in video_items:
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            bucket.append((item, search_term))
        if is_random:
            random.shuffle(bucket)
        per_term_items.append(bucket)

    # Round-robin: term1[0], term2[0], ..., term1[1], term2[1], ...
    ordered_items: list[tuple[MaterialInfo, str]] = []
    max_len = max((len(b) for b in per_term_items), default=0)
    for i in range(max_len):
        for bucket in per_term_items:
            if i < len(bucket):
                ordered_items.append(bucket[i])

    found_duration = sum(item.duration for item, _ in ordered_items)
    logger.info(
        f"found total videos: {len(ordered_items)}, "
        f"required additional duration: {remaining:.1f}s, "
        f"found duration: {found_duration:.1f}s"
    )

    for item, matched_term in ordered_items:
        if remaining <= 0:
            break
        try:
            logger.info(f"downloading video for term '{matched_term}': {item.url}")
            saved_path = save_video(
                video_url=item.url,
                save_dir=material_directory,
                source=source,
                search_term=matched_term,
            )
            if saved_path and saved_path not in cached_path_set:
                logger.info(f"video saved: {saved_path} (term='{matched_term}')")
                video_paths.append(saved_path)
                cached_path_set.add(saved_path)
                seconds = min(max_clip_duration, item.duration)
                remaining -= seconds
                total_duration += seconds
                if remaining <= 0:
                    logger.info(
                        f"total duration of downloaded videos: {total_duration:.1f}s, "
                        f"skip downloading more"
                    )
        except Exception as e:
            logger.error(f"failed to download video: {utils.to_json(item)} => {str(e)}")

    # ── Phase 3: last-resort filler from off-topic (neutral) cache ──
    # Only reached if relevant cache + API together cannot cover the audio.
    if remaining > 0 and neutral_cache:
        logger.warning(
            f"still short by {remaining:.1f}s after API download — "
            f"falling back to {len(neutral_cache)} off-topic cached clips as filler"
        )
        for path, dur, _ in neutral_cache:
            if remaining <= 0:
                break
            if path in cached_path_set:
                continue
            seconds = min(max_clip_duration, dur)
            video_paths.append(path)
            cached_path_set.add(path)
            remaining -= seconds
            total_duration += seconds

    logger.success(
        f"collected {len(video_paths)} videos, total {total_duration:.1f}s "
        f"(needed {audio_duration:.1f}s)"
    )
    return video_paths


if __name__ == "__main__":
    download_videos(
        "test123", ["Money Exchange Medium"], audio_duration=100, source="pixabay"
    )
