"""
ComfyUI Image Generation Service for MoneyPrinterTurbo

Calls ComfyUI API to generate AI images for video scenes using Flux.1-dev.
Replaces Pexels/Pixabay stock footage with AI-generated scene-specific visuals.
"""

import json
import time
import urllib.request
import urllib.error
import shutil
from pathlib import Path
from typing import List, Optional
from loguru import logger

from app.config import config

# ─── Default Settings ────────────────────────────────────────────────────────

COMFYUI_URL = "http://localhost:8188"
OUTPUT_DIR = Path("/home/alanpaul1969/ComfyUI/output")

# Flux.1-dev model paths (fp8 for VRAM efficiency on shared GPU)
UNET_NAME = "flux1-dev-fp8.safetensors"
CLIP_NAME1 = "clip_l.safetensors"
CLIP_NAME2 = "t5xxl_fp8.safetensors"
VAE_NAME = "flux1-vae.safetensors"
NEGATIVE_PROMPT = (
    "blurry, noisy, low quality, distorted, ugly, bad anatomy, "
    "extra limbs, watermark, signature, deformed, disfigured, "
    "poorly drawn, childish, amateur, pixelated, out of focus"
)


class ComfyUIImageGen:
    """Generates images via ComfyUI API using Flux.1-dev."""

    def __init__(
        self,
        width: int = 540,
        height: int = 960,
        steps: int = 28,
        guidance: float = 3.5,
        seed: int = 42,
        timeout: int = 300,
    ):
        self.width = width
        self.height = height
        self.steps = steps
        self.guidance = guidance
        self.seed = seed
        self.timeout = timeout
        self.comfyui_url = config.app.get("comfyui_url", COMFYUI_URL)

    # ── Workflow Builder ─────────────────────────────────────────────────

    def _build_workflow(self, prompt: str, prefix: str, seed: int) -> dict:
        """Build Flux.1-dev workflow JSON (UNET + Dual CLIP + VAE)."""
        return {
            "1": {
                "class_type": "UNETLoader",
                "inputs": {
                    "unet_name": UNET_NAME,
                    "weight_dtype": "default",
                },
            },
            "2": {
                "class_type": "DualCLIPLoader",
                "inputs": {
                    "clip_name1": CLIP_NAME1,
                    "clip_name2": CLIP_NAME2,
                    "type": "flux",
                },
            },
            "11": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": VAE_NAME},
            },
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": self.steps,
                    "cfg": 1.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["1", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": self.width,
                    "height": self.height,
                    "batch_size": 1,
                },
            },
            "6": {
                "class_type": "CLIPTextEncodeFlux",
                "inputs": {
                    "clip": ["2", 0],
                    "clip_l": prompt,
                    "t5xxl": prompt,
                    "guidance": self.guidance,
                },
            },
            "7": {
                "class_type": "CLIPTextEncodeFlux",
                "inputs": {
                    "clip": ["2", 0],
                    "clip_l": NEGATIVE_PROMPT,
                    "t5xxl": NEGATIVE_PROMPT,
                    "guidance": self.guidance,
                },
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["3", 0],
                    "vae": ["11", 0],
                },
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["8", 0],
                    "filename_prefix": prefix,
                },
            },
        }

    # ── API Calls ────────────────────────────────────────────────────────

    def _queue_prompt(self, workflow: dict) -> str:
        """Submit workflow, return prompt_id."""
        data = json.dumps({"prompt": workflow}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.comfyui_url}/prompt",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI returned no prompt_id: {result}")
        return prompt_id

    def _wait_for_completion(self, prompt_id: str) -> dict:
        """Poll until generation completes. Returns history entry."""
        start = time.time()
        while time.time() - start < self.timeout:
            try:
                req = urllib.request.Request(
                    f"{self.comfyui_url}/history/{prompt_id}", method="GET"
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    history = json.loads(resp.read())
                if prompt_id in history:
                    return history[prompt_id]
            except Exception:
                pass
            time.sleep(3)
        raise TimeoutError(
            f"ComfyUI generation timed out after {self.timeout}s for {prompt_id}"
        )

    def _get_output_path(self, history: dict, prefix: str) -> Optional[Path]:
        """Extract the first output image path from history."""
        for node_data in history.get("outputs", {}).values():
            for img in node_data.get("images", []):
                fname = img["filename"]
                subfolder = img.get("subfolder", "")
                if prefix in fname:
                    path = (
                        OUTPUT_DIR / subfolder / fname
                        if subfolder
                        else OUTPUT_DIR / fname
                    )
                    if path.exists():
                        return path
        return None

    # ── Public API ───────────────────────────────────────────────────────

    def generate(
        self,
        prompt: str,
        prefix: str = "mpt_scene",
        seed: Optional[int] = None,
    ) -> Path:
        """Generate a single image. Returns path to the generated file."""
        if seed is None:
            seed = self.seed
            self.seed += 1

        logger.info(f"[ImageGen] generating: {prefix} ({self.width}x{self.height})")
        workflow = self._build_workflow(prompt, prefix, seed)
        prompt_id = self._queue_prompt(workflow)
        logger.debug(f"[ImageGen] prompt_id={prompt_id}, waiting...")

        history = self._wait_for_completion(prompt_id)
        output_path = self._get_output_path(history, prefix)

        if not output_path:
            raise RuntimeError(
                f"Image generated but could not find output file with prefix '{prefix}'"
            )

        logger.success(f"[ImageGen] done: {output_path.name} ({output_path.stat().st_size / 1024:.0f} KB)")
        return output_path

    def generate_scenes(
        self,
        scene_prompts: List[dict],
        prefix_base: str = "mpt_scene",
    ) -> List[Path]:
        """Generate images for multiple scenes.

        Args:
            scene_prompts: List of {"index": int, "visual_prompt": str}
            prefix_base: Base filename prefix

        Returns:
            List of Paths to generated images, in scene order.
        """
        results = []
        for scene in scene_prompts:
            idx = scene.get("index", len(results))
            prompt = scene.get("visual_prompt", scene.get("description", ""))
            prefix = f"{prefix_base}_{idx:02d}"

            try:
                path = self.generate(prompt=prompt, prefix=prefix)
                results.append(path)
            except Exception as e:
                logger.error(f"[ImageGen] scene {idx} failed: {e}")
                # Continue with remaining scenes
                results.append(None)

        return results


# ─── Convenience function ────────────────────────────────────────────────────

def generate_ai_images(
    scene_prompts: List[dict],
    width: int = 896,
    height: int = 1152,
) -> List[Path]:
    """Generate AI images for video scenes via ComfyUI Flux.1.

    Args:
        scene_prompts: List of {"index": int, "visual_prompt": str}
        width, height: Output resolution

    Returns:
        List of image file paths.
    """
    gen = ComfyUIImageGen(width=width, height=height)
    return gen.generate_scenes(scene_prompts)
