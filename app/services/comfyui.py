"""ComfyUI API client for local AI image/video generation."""
import os
import random
import subprocess
import time
import uuid
from typing import List

import requests
from loguru import logger

from app.config import config
from app.models.schema import VideoAspect


def _get_comfyui_url() -> str:
    return config.app.get("comfyui_api_url", "http://127.0.0.1:8188").rstrip("/")


def _build_flux_workflow(prompt: str, width: int, height: int, seed: int = None) -> dict:
    """Build a FLUX.1-schnell text-to-image workflow for ComfyUI API."""
    if seed is None:
        seed = random.randint(0, 2**32 - 1)

    return {
        "4": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": config.app.get("comfyui_flux_model", "flux1-schnell.safetensors"),
                "weight_dtype": "default",
            },
        },
        "5": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["11", 0]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "", "clip": ["11", 0]},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 4,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["10", 0]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "mpt_gen", "images": ["8", 0]},
        },
        "10": {
            "class_type": "VAELoader",
            "inputs": {
                "vae_name": config.app.get("comfyui_flux_vae", "ae.safetensors"),
            },
        },
        "11": {
            "class_type": "DualCLIPLoader",
            "inputs": {
                "clip_name1": config.app.get("comfyui_t5xxl", "t5xxl_fp16.safetensors"),
                "clip_name2": config.app.get("comfyui_clip_l", "clip_l.safetensors"),
                "type": "flux",
            },
        },
    }


def generate_image(prompt: str, aspect: VideoAspect, seed: int = None) -> str:
    """Generate an image via ComfyUI FLUX.1-schnell. Returns image download URL."""
    base_url = _get_comfyui_url()
    width, height = VideoAspect(aspect).to_resolution()

    workflow = _build_flux_workflow(prompt, width, height, seed)
    payload = {"prompt": workflow, "client_id": str(uuid.uuid4())}

    try:
        r = requests.post(f"{base_url}/prompt", json=payload, timeout=30)
        r.raise_for_status()
        prompt_id = r.json()["prompt_id"]
        logger.info(f"ComfyUI prompt queued: {prompt_id}")
    except Exception as e:
        logger.error(f"ComfyUI prompt failed: {e}")
        return ""

    max_wait = int(config.app.get("comfyui_timeout", 120))
    for _ in range(max_wait):
        time.sleep(1)
        try:
            hist = requests.get(f"{base_url}/history/{prompt_id}", timeout=10).json()
            if prompt_id in hist:
                outputs = hist[prompt_id].get("outputs", {})
                for _node_id, node_out in outputs.items():
                    images = node_out.get("images", [])
                    if images:
                        img = images[0]
                        return (
                            f"{base_url}/view?filename={img['filename']}"
                            f"&subfolder={img.get('subfolder', '')}"
                            f"&type={img.get('type', 'output')}"
                        )
                logger.error(f"ComfyUI: no images in output for {prompt_id}")
                return ""
        except Exception:
            continue

    logger.error(f"ComfyUI: timeout waiting for {prompt_id}")
    return ""


def download_image(image_url: str, save_path: str) -> bool:
    """Download image from ComfyUI server."""
    try:
        r = requests.get(image_url, timeout=60)
        r.raise_for_status()
        with open(save_path, "wb") as f:
            f.write(r.content)
        return os.path.getsize(save_path) > 0
    except Exception as e:
        logger.error(f"download image failed: {e}")
        return False


def image_to_video_kenburns(
    image_path: str,
    output_path: str,
    duration: float = 5.0,
    fps: int = 25,
    width: int = 1920,
    height: int = 1080,
) -> bool:
    """Convert a still image to a video clip with Ken Burns (zoom+pan) effect."""
    d = int(duration * fps)
    effects = [
        f"zoompan=z='min(zoom+0.002,1.8)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={d}:s={width}x{height}:fps={fps}",
        f"zoompan=z='if(eq(on,1),1.8,max(zoom-0.002,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={d}:s={width}x{height}:fps={fps}",
        f"zoompan=z=1.3:x='if(eq(on,1),0,min(x+2,iw-iw/zoom))':y='ih/2-(ih/zoom/2)':d={d}:s={width}x{height}:fps={fps}",
        f"zoompan=z=1.3:x='if(eq(on,1),iw-iw/zoom,max(x-2,0))':y='ih/2-(ih/zoom/2)':d={d}:s={width}x{height}:fps={fps}",
    ]
    effect = random.choice(effects)

    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", image_path,
        "-filter_complex", effect,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            logger.error(f"ffmpeg Ken Burns failed: {result.stderr[:500]}")
            return False
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        logger.error(f"Ken Burns conversion failed: {e}")
        return False


def enhance_prompt(search_term: str) -> str:
    """Enhance a search keyword into a detailed image generation prompt."""
    prefix = config.app.get(
        "comfyui_prompt_prefix",
        "Professional cinematic photo, high quality, detailed, 4K, ",
    )
    suffix = config.app.get("comfyui_prompt_suffix", "")
    return f"{prefix}{search_term}{suffix}"


def generate_videos_ai(
    search_terms: List[str],
    video_aspect: VideoAspect,
    audio_duration: float,
    clip_duration: float = 5.0,
    save_dir: str = "",
) -> List[str]:
    """Generate video clips using ComfyUI AI image generation + Ken Burns effect."""
    if not save_dir:
        from app.utils import utils

        save_dir = utils.storage_dir("ai_materials")
    os.makedirs(save_dir, exist_ok=True)

    width, height = VideoAspect(video_aspect).to_resolution()
    video_paths = []
    total_duration = 0.0
    clips_needed = max(1, int(audio_duration / clip_duration) + 2)

    for idx, term in enumerate(search_terms):
        if total_duration >= audio_duration:
            break

        prompt = enhance_prompt(term)
        per_term = max(1, clips_needed // len(search_terms))

        for j in range(per_term):
            if total_duration >= audio_duration:
                break

            uid = uuid.uuid4().hex[:8]
            img_path = os.path.join(save_dir, f"ai_{idx}_{j}_{uid}.png")
            vid_path = os.path.join(save_dir, f"ai_{idx}_{j}_{uid}.mp4")

            logger.info(
                f"generating image {idx + 1}/{len(search_terms)} variant {j + 1}: {term}"
            )
            img_url = generate_image(prompt, video_aspect)
            if not img_url:
                logger.warning(f"failed to generate image for: {term}")
                continue

            if not download_image(img_url, img_path):
                continue

            logger.info(f"converting to video clip with Ken Burns effect: {vid_path}")
            if image_to_video_kenburns(
                img_path, vid_path, clip_duration, width=width, height=height
            ):
                video_paths.append(vid_path)
                total_duration += clip_duration
                logger.info(
                    f"generated clip {len(video_paths)}, "
                    f"total: {total_duration:.1f}s / {audio_duration:.1f}s"
                )

            try:
                os.remove(img_path)
            except OSError:
                pass

    logger.success(
        f"AI generated {len(video_paths)} video clips, total {total_duration:.1f}s"
    )
    return video_paths
