"""OpenAI-compatible /v1/images/generations server running SDXL Lightning locally."""

import base64
import io
import os
import random
import threading
import time
from contextlib import asynccontextmanager

import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator

import policy

MODEL = os.environ.get("IMAGE_MODEL", "SG161222/RealVisXL_V5.0_Lightning")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
STEPS = int(os.environ.get("IMAGE_STEPS", "6"))
GUIDANCE = float(os.environ.get("IMAGE_GUIDANCE", "1.5"))
IDLE_SECONDS = float(os.environ.get("IMAGE_IDLE_SECONDS", "90"))
IDLE_CHECK_SECONDS = float(os.environ.get("IMAGE_IDLE_CHECK_SECONDS", "10"))
OLLAMA_UNLOAD_TIMEOUT = float(os.environ.get("OLLAMA_UNLOAD_TIMEOUT", "30"))
HOST = os.environ.get("IMAGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("IMAGE_PORT", "7861"))
POLICY = policy.load(os.environ.get("CONTENT_POLICY"))

STYLE = (
    "candid cinematic photograph, natural light, highly detailed, sharp focus, "
    "documentary style, 35mm film"
)
NEGATIVE = (
    "text, letters, words, watermark, logo, signature, caption, deformed, "
    "distorted, bad anatomy, extra fingers, blurry, lowres, cartoon, 3d render, "
    "eyeglasses, modern clothing, map, looking at camera, posed portrait"
)

# sdxl sizes near 1 megapixel
BUCKETS = [
    (1024, 1024), (896, 1152), (832, 1216), (768, 1344), (640, 1536),
    (1152, 896), (1216, 832), (1344, 768), (1536, 640),
]
DEFAULT_SIZE = (832, 1216)

# one lock guards the pipeline and the gpu state below
lock = threading.Lock()
pipe = None
on_gpu = False
last_used = 0.0
stop_idle = threading.Event()
idle_thread = None


class ImageRequest(BaseModel):
    prompt: str
    model: str | None = None
    n: int = 1
    size: str | None = "1024x1536"
    response_format: str | None = "b64_json"

    @field_validator("size")
    @classmethod
    def check_size(cls, v):
        if v is None or v.strip().lower() in ("", "auto"):
            return None
        w, sep, h = v.strip().lower().partition("x")
        if not (sep and w.isdigit() and h.isdigit() and int(w) > 0 and int(h) > 0):
            raise ValueError("size must be WIDTHxHEIGHT with positive integers, e.g. 1024x1536")
        return v.strip().lower()


def pick_size(size):
    if size is None:
        return DEFAULT_SIZE
    w, h = (int(v) for v in size.split("x"))
    return min(BUCKETS, key=lambda b: abs(b[0] / b[1] - w / h))


def build_prompts(prompt):
    negative = NEGATIVE
    if POLICY:
        r = POLICY.apply(prompt)
        prompt, negative = r.prompt, f"{NEGATIVE}, {r.negative}"
        if r.rules:
            print(f"policy {','.join(r.rules)}: {prompt}")
    return f"{prompt}, {STYLE}", negative


def ollama_models():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/ps", timeout=5)
        return [m["name"] for m in r.json().get("models", [])]
    except (requests.RequestException, ValueError):
        return []


def unload_ollama():
    # ollama can load again between requests, so this runs before every image
    names = ollama_models()
    for name in names:
        try:
            requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": name, "keep_alive": 0},
                timeout=30,
            )
        except requests.RequestException:
            pass
    if not names:
        return []
    # wait until ollama reports the models gone, so their vram is free
    deadline = time.time() + OLLAMA_UNLOAD_TIMEOUT
    while (left := ollama_models()) and time.time() < deadline:
        time.sleep(0.5)
    if left:
        print(f"ollama still holds {', '.join(left)} after {OLLAMA_UNLOAD_TIMEOUT:g}s, painting anyway")
    else:
        print(f"unloaded ollama: {', '.join(names)}")
    return names


def load_pipeline():
    import torch
    from diffusers import DPMSolverMultistepScheduler, StableDiffusionXLPipeline

    p = StableDiffusionXLPipeline.from_pretrained(MODEL, torch_dtype=torch.float16, variant="fp16")
    p.scheduler = DPMSolverMultistepScheduler.from_config(
        p.scheduler.config,
        algorithm_type="sde-dpmsolver++",
        use_karras_sigmas=True,
    )
    return p


def empty_cuda_cache():
    try:
        import torch
    except ImportError:
        return
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def claim_gpu():
    """Make SDXL the only large model on the gpu. Call with the lock held."""
    global pipe, on_gpu
    unload_ollama()
    if pipe is None:
        pipe = load_pipeline()
    if not on_gpu:
        pipe.to("cuda")
        on_gpu = True
    return pipe


def paint(p, prompt, negative, width, height):
    import torch

    return p(
        prompt=prompt,
        negative_prompt=negative,
        width=width,
        height=height,
        num_inference_steps=STEPS,
        guidance_scale=GUIDANCE,
        generator=torch.Generator("cuda").manual_seed(random.randint(0, 2**31 - 1)),
    ).images[0]


def offload_if_idle():
    """Move SDXL back to the cpu once it has been idle long enough."""
    global on_gpu
    with lock:
        if not on_gpu or time.time() - last_used < IDLE_SECONDS:
            return False
        pipe.to("cpu")
        empty_cuda_cache()
        on_gpu = False
    print("idle: moved pipeline to cpu")
    return True


def idle_worker():
    while not stop_idle.wait(IDLE_CHECK_SECONDS):
        offload_if_idle()


@asynccontextmanager
async def lifespan(app):
    # runs under both `python server.py` and `uvicorn server:app`
    global idle_thread
    stop_idle.clear()
    idle_thread = threading.Thread(target=idle_worker, name="idle-offload", daemon=True)
    idle_thread.start()
    try:
        yield
    finally:
        stop_idle.set()
        idle_thread.join(timeout=5)


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "ok": True,
        "on_gpu": on_gpu,
        "idle_worker": bool(idle_thread and idle_thread.is_alive()),
    }


@app.get("/v1/models")
def models():
    return {"data": [{"id": MODEL, "object": "model"}]}


@app.post("/v1/images/generations")
def generate(req: ImageRequest):
    global last_used
    if not req.prompt.strip():
        raise HTTPException(400, "prompt is empty")
    width, height = pick_size(req.size)
    prompt, negative = build_prompts(req.prompt)
    data = []
    with lock:
        for _ in range(max(1, min(req.n, 4))):
            # reclaim per image: ollama may have loaded while the last one painted
            p = claim_gpu()
            image = paint(p, prompt, negative, width, height)
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            data.append({"b64_json": base64.b64encode(buf.getvalue()).decode()})
        # torch keeps ~7 GB of decode buffers cached; give it back so ollama fits
        empty_cuda_cache()
        last_used = time.time()
    return {"created": int(time.time()), "data": data}


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
