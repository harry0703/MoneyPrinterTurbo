"""OpenAI-compatible /v1/images/generations server running SDXL Lightning locally."""

import base64
import io
import os
import random
import threading
import time

import requests
import torch
import uvicorn
from diffusers import DPMSolverMultistepScheduler, StableDiffusionXLPipeline
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import policy

MODEL = os.environ.get("IMAGE_MODEL", "SG161222/RealVisXL_V5.0_Lightning")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
STEPS = int(os.environ.get("IMAGE_STEPS", "6"))
GUIDANCE = float(os.environ.get("IMAGE_GUIDANCE", "1.5"))
IDLE_SECONDS = int(os.environ.get("IMAGE_IDLE_SECONDS", "90"))
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

app = FastAPI()
lock = threading.Lock()
pipe = None
on_gpu = False
last_used = 0.0


class ImageRequest(BaseModel):
    prompt: str
    model: str | None = None
    n: int = 1
    size: str | None = "1024x1536"
    response_format: str | None = "b64_json"


def pick_size(size):
    try:
        w, h = (int(v) for v in (size or "").lower().split("x"))
    except ValueError:
        return 832, 1216
    return min(BUCKETS, key=lambda b: abs(b[0] / b[1] - w / h))


def build_prompts(prompt):
    negative = NEGATIVE
    if POLICY:
        r = POLICY.apply(prompt)
        prompt, negative = r.prompt, f"{NEGATIVE}, {r.negative}"
        if r.rules:
            print(f"policy {','.join(r.rules)}: {prompt}")
    return f"{prompt}, {STYLE}", negative


def unload_ollama():
    # free vram if ollama is serving the script llm on the same gpu
    try:
        for m in requests.get(f"{OLLAMA_URL}/api/ps", timeout=5).json().get("models", []):
            requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": m["name"], "keep_alive": 0},
                timeout=30,
            )
    except requests.RequestException:
        pass


def get_pipe():
    global pipe, on_gpu
    if pipe is None:
        pipe = StableDiffusionXLPipeline.from_pretrained(
            MODEL, torch_dtype=torch.float16, variant="fp16"
        )
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(
            pipe.scheduler.config,
            algorithm_type="sde-dpmsolver++",
            use_karras_sigmas=True,
        )
    if not on_gpu:
        unload_ollama()
        pipe.to("cuda")
        on_gpu = True
    return pipe


def offload_when_idle():
    global on_gpu
    while True:
        time.sleep(10)
        with lock:
            if on_gpu and time.time() - last_used > IDLE_SECONDS:
                pipe.to("cpu")
                torch.cuda.empty_cache()
                on_gpu = False


@app.get("/health")
def health():
    return {"ok": True, "on_gpu": on_gpu}


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
        p = get_pipe()
        for _ in range(max(1, min(req.n, 4))):
            image = p(
                prompt=prompt,
                negative_prompt=negative,
                width=width,
                height=height,
                num_inference_steps=STEPS,
                guidance_scale=GUIDANCE,
                generator=torch.Generator("cuda").manual_seed(random.randint(0, 2**31 - 1)),
            ).images[0]
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            data.append({"b64_json": base64.b64encode(buf.getvalue()).decode()})
        last_used = time.time()
    return {"created": int(time.time()), "data": data}


if __name__ == "__main__":
    threading.Thread(target=offload_when_idle, daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT)
