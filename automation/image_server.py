"""Local text-to-image server for Apple silicon (MPS), OpenAI /v1/images/generations compatible.

Adapted from docs/local-image-server/server.py (which targets NVIDIA/CUDA).
Runs RealVisXL V5.0 Lightning (photoreal SDXL, 6 steps). First start downloads
about 6.6 GB of weights into the Hugging Face cache.

    .venv-images/bin/python image_server.py          # listens on 127.0.0.1:7861
"""
from __future__ import annotations

import base64
import io
import os
import random
import threading
import time

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

MODEL = os.environ.get("IMAGE_MODEL", "SG161222/RealVisXL_V5.0_Lightning")
STEPS = int(os.environ.get("IMAGE_STEPS", "6"))
GUIDANCE = float(os.environ.get("IMAGE_GUIDANCE", "1.5"))
PORT = int(os.environ.get("IMAGE_PORT", "7861"))
DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"

STYLES = {
    "photo": (
        "candid cinematic photograph, natural light, highly detailed, sharp focus, "
        "documentary style, 35mm film",
        "text, letters, words, watermark, logo, signature, caption, deformed, "
        "distorted, bad anatomy, extra fingers, blurry, lowres, cartoon, 3d render, "
        "eyeglasses, modern clothing, map, looking at camera, posed portrait",
    ),
    "3d": (
        "stylized 3D render, Pixar style animation still, smooth clean shapes, soft studio "
        "lighting, vibrant saturated colors, subsurface scattering, octane render, 4k, "
        "shallow depth of field",
        "text, letters, words, watermark, logo, signature, caption, deformed, distorted, "
        "bad anatomy, extra fingers, blurry, lowres, photograph, photorealistic, grainy, "
        "dark, gloomy, realistic skin pores",
    ),
}
STYLE_NAME = os.environ.get("IMAGE_STYLE", "photo")
STYLE, NEGATIVE = STYLES[STYLE_NAME]
# Always-on safety negatives: this channel never shows bodies.
NEGATIVE += ", nsfw, nude, naked, underwear, lingerie, sexual, suggestive, cleavage, child, teenager, realistic human body"
BUCKETS = [
    (1024, 1024), (896, 1152), (832, 1216), (768, 1344), (640, 1536),
    (1152, 896), (1216, 832), (1344, 768), (1536, 640),
]
DEFAULT_SIZE = (832, 1216)

app = FastAPI()
lock = threading.Lock()
pipe = None


def pick_size(size: str | None):
    if not size or size == "auto":
        return DEFAULT_SIZE
    try:
        w, h = (int(v) for v in size.lower().split("x"))
        if w <= 0 or h <= 0:
            raise ValueError
    except ValueError:
        raise HTTPException(422, "size must be WIDTHxHEIGHT")
    return min(BUCKETS, key=lambda b: abs(b[0] / b[1] - w / h))


def load_pipeline():
    from diffusers import DPMSolverMultistepScheduler, StableDiffusionXLPipeline

    print(f"loading {MODEL} on {DEVICE} ...", flush=True)
    t = time.time()
    p = StableDiffusionXLPipeline.from_pretrained(MODEL, torch_dtype=torch.float16, variant="fp16")
    p.scheduler = DPMSolverMultistepScheduler.from_config(
        p.scheduler.config, algorithm_type="sde-dpmsolver++", use_karras_sigmas=True
    )
    p.to(DEVICE)
    p.set_progress_bar_config(disable=True)
    print(f"model ready in {time.time() - t:.0f}s", flush=True)
    return p


def get_pipe():
    global pipe
    if pipe is None:
        pipe = load_pipeline()
    return pipe


class ImageRequest(BaseModel):
    prompt: str
    model: str | None = None
    n: int | None = 1
    size: str | None = None
    response_format: str | None = None


@app.get("/health")
def health():
    return {"ok": True, "device": DEVICE, "loaded": pipe is not None, "style": STYLE_NAME}


@app.get("/v1/models")
def models():
    return {"data": [{"id": "realvisxl-v5-lightning", "object": "model"}]}


@app.post("/v1/images/generations")
def generate(req: ImageRequest):
    if not req.prompt.strip():
        raise HTTPException(422, "prompt is required")
    width, height = pick_size(req.size)
    prompt = f"{req.prompt.strip()}, {STYLE}"
    with lock:
        p = get_pipe()
        t = time.time()
        image = p(
            prompt=prompt,
            negative_prompt=NEGATIVE,
            width=width,
            height=height,
            num_inference_steps=STEPS,
            guidance_scale=GUIDANCE,
            generator=torch.Generator("cpu").manual_seed(random.randint(0, 2**31 - 1)),
        ).images[0]
        print(f"painted {width}x{height} in {time.time() - t:.1f}s: {req.prompt[:80]!r}", flush=True)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return {"created": int(time.time()), "data": [{"b64_json": base64.b64encode(buf.getvalue()).decode()}]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
