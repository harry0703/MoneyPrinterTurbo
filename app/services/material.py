import base64
import io
import os
import random
import threading
import time
import uuid
from enum import Enum
from typing import List
from urllib.parse import quote, urlencode

import numpy as np
from PIL import Image

import requests
from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.video.VideoClip import ImageClip
import openai

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

class ZoomEffect(str, Enum):
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    PAN_UP = "pan_up"
    PAN_DOWN = "pan_down"


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


def enhance_prompt_with_llm(prompt: str, video_script: str = "") -> str:
    """
    Enhances a prompt for image generation using the selected LLM to make it more detailed and professional.
    Uses the LLM provider selected by the user in the web UI.
    
    Args:
        prompt: The original prompt to enhance
        video_script: Optional video script for additional context
        
    Returns:
        Enhanced prompt string
    """
    try:
        # Use the selected LLM provider from config
        from app.services import llm as llm_service

        # Prepare system message and prompt
        system_message = """You are a professional image prompt creator. 
        Your task is to enhance the given prompt to generate a high-quality, detailed, and professional image. 
        The enhanced prompt should include details about lighting, style, composition, mood, and any relevant artistic elements.
        Your response should ONLY include the enhanced prompt text, nothing else."""
        
        user_message = f"Original prompt: {prompt}"
        
        # Add video script context if available
        if video_script and video_script.strip():
            user_message += f"\n\nContext from video script: {video_script}"
        
        # Combine messages into a complete prompt
        complete_prompt = f"{system_message}\n\n{user_message}"
        
        # Use the LLM service to generate the response
        response = llm_service._generate_response(complete_prompt)
        
        # Get enhanced prompt (response is already a string)
        enhanced_prompt = response.strip()

        # _generate_response reports provider failures as "Error: ..." strings
        # instead of raising; never use those as an image prompt.
        if not enhanced_prompt or enhanced_prompt.startswith("Error: "):
            logger.warning(
                f"prompt enhancement failed ({enhanced_prompt or 'empty response'}), "
                "using the original prompt"
            )
            return prompt

        logger.info(f"Enhanced prompt: {enhanced_prompt}")
        return enhanced_prompt
        
    except Exception as e:
        logger.error(f"Error enhancing prompt with LLM: {str(e)}")
        return prompt  # Return original prompt if enhancement fails


def _image_provider_setting(provider: str, suffix: str) -> str:
    # Image settings live under "{provider}_image_{suffix}". Reading falls
    # back to the legacy un-namespaced keys, except where those belong to
    # the LLM config: "*_model_name" is the chat model everywhere, and
    # "pollinations_base_url" is the text endpoint.
    plain_is_llm = suffix == "model_name" or (
        provider == "pollinations" and suffix == "base_url"
    )
    candidates = [f"{provider}_image_{suffix}"]
    if not plain_is_llm:
        candidates.append(f"{provider}_{suffix}")
    if "_" in provider:
        spaced = provider.replace("_", " ")
        candidates.append(f"{spaced}_image_{suffix}")
        if not plain_is_llm:
            candidates.append(f"{spaced}_{suffix}")
    for key in candidates:
        value = config.app.get(key, "")
        if value:
            return value.strip() if isinstance(value, str) else value
    return ""


def _generate_image_openai_compatible(client, prompt: str, model: str, size: str) -> bytes:
    request_args = {"prompt": prompt, "size": size, "n": 1}
    if model:
        request_args["model"] = model
    response = client.images.generate(**request_args)
    image = response.data[0]
    b64_data = getattr(image, "b64_json", None)
    if b64_data:
        return base64.b64decode(b64_data)
    image_response = requests.get(
        image.url,
        proxies=config.proxy,
        verify=_get_tls_verify(),
        timeout=(30, 60),
    )
    image_response.raise_for_status()
    return image_response.content


def _generate_image_stability(
    prompt: str, api_key: str, base_url: str, model: str, width: int, height: int
) -> bytes:
    api_host = (base_url or "https://api.stability.ai").rstrip("/")
    engine = model or "stable-diffusion-xl-1024-v1-0"
    response = requests.post(
        f"{api_host}/v1/generation/{engine}/text-to-image",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        json={
            "text_prompts": [{"text": prompt}],
            "width": width,
            "height": height,
            "samples": 1,
        },
        proxies=config.proxy,
        verify=_get_tls_verify(),
        timeout=(30, 120),
    )
    response.raise_for_status()
    return base64.b64decode(response.json()["artifacts"][0]["base64"])


def _generate_image_pollinations(
    prompt: str, api_key: str, base_url: str, model: str, width: int, height: int
) -> bytes:
    api_host = (base_url or "https://image.pollinations.ai/prompt/").rstrip("/")
    params = {"width": width, "height": height, "nologo": "true"}
    if model and model.lower() != "default":
        params["model"] = model
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    response = requests.get(
        # safe="" keeps '/' and '..' inside the prompt percent-encoded so the
        # prompt can never rewrite the request path on the configured host.
        f"{api_host}/{quote(prompt, safe='')}",
        params=params,
        headers=headers,
        proxies=config.proxy,
        verify=_get_tls_verify(),
        timeout=(30, 120),
    )
    response.raise_for_status()
    return response.content


def _openai_image_size(model: str, aspect: VideoAspect) -> tuple:
    # Each OpenAI image model accepts a different fixed set of sizes; sending
    # an unsupported one is a hard 400 for every prompt.
    model_lower = (model or "").lower()
    if model_lower.startswith("dall-e-2"):
        return (1024, 1024)
    if model_lower.startswith("gpt-image"):
        return {
            VideoAspect.landscape: (1536, 1024),
            VideoAspect.portrait: (1024, 1536),
        }.get(aspect, (1024, 1024))
    return {
        VideoAspect.landscape: (1792, 1024),
        VideoAspect.portrait: (1024, 1792),
    }.get(aspect, (1024, 1024))


def generate_ai_images(
    task_id: str,
    prompt: List[str],
    count_per_prompt: int = 1,
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    max_clip_duration: int = 5,
    audio_duration: float = 0.0,
    enhance_prompt: bool = False,
    video_script: str = "",
) -> List[str]:
    """
    Generate images with AI and convert them to videos with zoom effects.

    Args:
        task_id: The task ID
        prompt: List of prompts to generate images for
        count_per_prompt: Number of images to generate per prompt
        video_aspect: The video aspect ratio
        video_concat_mode: The video concatenation mode
        max_clip_duration: Maximum duration of each video clip in seconds
        audio_duration: The target duration of the audio to match with videos

    Returns:
        List of paths to generated video files
    """
    # Create a directory for the generated images and videos
    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""
        
    # If no directory is set, use a default one
    if not material_directory:
        material_directory = os.path.join(utils.task_dir(task_id), "ai_images")
        
    # Create directory if it doesn't exist
    os.makedirs(material_directory, exist_ok=True)
    
    provider = str(config.app.get("image_provider", "openai")).strip().lower().replace(" ", "_")
    known_providers = ("openai", "stability_ai", "pollinations", "midjourney", "other")
    if provider not in known_providers:
        logger.error(
            f"unknown image provider '{provider}', expected one of: {', '.join(known_providers)}"
        )
        return []
    api_key = _image_provider_setting(provider, "api_key")
    base_url = _image_provider_setting(provider, "base_url")
    model = _image_provider_setting(provider, "model_name")

    if provider == "openai" and not api_key:
        try:
            api_key = get_api_key("openai_api_keys")
        except ValueError:
            pass

    if provider in ("openai", "stability_ai") and not api_key:
        logger.error(f"API key for image provider '{provider}' is not set in config")
        return []
    if provider in ("midjourney", "other") and not base_url:
        logger.error(
            f"Image provider '{provider}' requires a base URL pointing to an OpenAI-compatible images endpoint"
        )
        return []

    aspect = VideoAspect(video_aspect)
    if provider == "stability_ai":
        # SDXL v1 engines only accept specific dimension pairs.
        width, height = {
            VideoAspect.landscape: (1216, 832),
            VideoAspect.portrait: (832, 1216),
        }.get(aspect, (1024, 1024))
    elif provider == "pollinations":
        width, height = aspect.to_resolution()
    else:
        if provider == "openai" and not model:
            model = "dall-e-3"
        width, height = _openai_image_size(model, aspect)
    size = f"{width}x{height}"

    if provider == "stability_ai":
        def generate_image(image_prompt: str) -> bytes:
            return _generate_image_stability(image_prompt, api_key, base_url, model, width, height)
    elif provider == "pollinations":
        def generate_image(image_prompt: str) -> bytes:
            return _generate_image_pollinations(image_prompt, api_key, base_url, model, width, height)
    else:
        # The SDK default timeout is 10 minutes; image generation should fail
        # fast enough for the per-image retry loop to matter.
        client_args = {"api_key": api_key or "EMPTY", "timeout": 120.0}
        if base_url:
            client_args["base_url"] = base_url
        client = openai.OpenAI(**client_args)

        def generate_image(image_prompt: str) -> bytes:
            return _generate_image_openai_compatible(client, image_prompt, model, size)

    logger.info(f"Generating AI images with provider '{provider}', model '{model or 'default'}', size {size}")

    video_paths = []
    total_duration = 0.0

    # Copy before shuffling: the caller's video_terms list must keep the
    # original order it was persisted with in script.json.
    prompt = list(prompt)
    if getattr(video_concat_mode, "value", video_concat_mode) == VideoConcatMode.random.value:
        random.shuffle(prompt)

    for text_prompt in prompt:
        try:
            # Enhance prompt with LLM if enabled
            if enhance_prompt:
                enhanced_prompt = enhance_prompt_with_llm(text_prompt, video_script)
                logger.info(f"Enhanced original prompt: '{text_prompt}' to '{enhanced_prompt}'")
                final_prompt = enhanced_prompt
            else:
                final_prompt = text_prompt
                
            logger.info(f"Generating {count_per_prompt} images for prompt: {final_prompt}")
            
            for i in range(count_per_prompt):
                # Generate a unique image filename
                image_id = str(uuid.uuid4())[:8]
                image_path = os.path.join(material_directory, f"ai_image_{image_id}.png")
                
                try:
                    image_data = None
                    for attempt in range(3):
                        try:
                            image_data = generate_image(final_prompt)
                            # A 200 response is not necessarily an image (rate
                            # limit pages, proxy errors) — verify before writing.
                            Image.open(io.BytesIO(image_data)).verify()
                            break
                        except Exception as e:
                            if attempt == 2:
                                raise
                            logger.warning(
                                f"image generation attempt {attempt + 1} failed: {str(e)}, retrying"
                            )
                            time.sleep(2**attempt)
                    with open(image_path, "wb") as img_file:
                        img_file.write(image_data)

                    logger.info(f"Image saved to {image_path}")
                    
                    # Convert image to video with random zoom effect
                    video_path = convert_image_to_video(
                        image_path=image_path,
                        video_duration=max_clip_duration,
                        effect=random.choice(list(ZoomEffect))
                    )
                    
                    if video_path:
                        video_paths.append(video_path)
                        total_duration += max_clip_duration
                        logger.info(f"Video created: {video_path}")
                        
                        if total_duration > audio_duration:
                            logger.info(
                                f"Total duration of created videos: {total_duration} seconds, skip generating more"
                            )
                            break
                            
                except Exception as e:
                    logger.error(f"Error generating image: {str(e)}")
                    continue
                    
            if total_duration > audio_duration:
                break
                
        except Exception as e:
            logger.error(f"Failed to generate AI images: {str(e)}")
    
    logger.success(f"Created {len(video_paths)} videos from AI-generated images")
    return video_paths


def convert_image_to_video(image_path: str, video_duration: int = 5, effect: ZoomEffect = ZoomEffect.ZOOM_IN) -> str:
    """
    Convert an image to a video with a zoom or pan effect.
    
    Args:
        image_path: Path to the image
        video_duration: Duration of the video in seconds
        effect: The effect to apply (zoom in, zoom out, pan left, etc.)
    
    Returns:
        Path to the generated video file
    """
    img_clip = None
    final_clip = None
    try:
        video_path = f"{image_path}.mp4"

        img_clip = ImageClip(image_path).with_duration(video_duration)
        width, height = img_clip.size
        duration = max(video_duration, 0.001)

        # All effects are a moving crop window over the still image, resized
        # back to the source resolution: constant canvas, no black borders.
        def ken_burns(get_frame, t):
            progress = min(max(t / duration, 0.0), 1.0)
            if effect == ZoomEffect.ZOOM_OUT:
                scale = 1.2 - 0.2 * progress
                offset_x = offset_y = 0.5
            elif effect == ZoomEffect.PAN_LEFT:
                scale = 1.15
                offset_x, offset_y = 1 - progress, 0.5
            elif effect == ZoomEffect.PAN_RIGHT:
                scale = 1.15
                offset_x, offset_y = progress, 0.5
            elif effect == ZoomEffect.PAN_UP:
                scale = 1.15
                offset_x, offset_y = 0.5, 1 - progress
            elif effect == ZoomEffect.PAN_DOWN:
                scale = 1.15
                offset_x, offset_y = 0.5, progress
            else:  # ZOOM_IN and fallback
                scale = 1 + 0.2 * progress
                offset_x = offset_y = 0.5

            frame = get_frame(t)
            crop_w = max(int(width / scale), 1)
            crop_h = max(int(height / scale), 1)
            x1 = int((width - crop_w) * offset_x)
            y1 = int((height - crop_h) * offset_y)
            cropped = frame[y1 : y1 + crop_h, x1 : x1 + crop_w]
            image = Image.fromarray(cropped)
            return np.asarray(image.resize((width, height), Image.LANCZOS))

        final_clip = img_clip.transform(ken_burns)
        final_clip.write_videofile(video_path, fps=30, codec="libx264", audio=False, logger=None)
        return video_path
    except Exception as e:
        logger.error(f"Error converting image to video: {str(e)}")
        return ""
    finally:
        if final_clip is not None:
            final_clip.close()
        if img_clip is not None:
            img_clip.close()


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
    search_videos = search_videos_pexels
    if source == "pixabay":
        search_videos = search_videos_pixabay
    elif source == "coverr":
        search_videos = search_videos_coverr

    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

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
