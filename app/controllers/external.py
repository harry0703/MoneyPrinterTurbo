from __future__ import annotations

from fastapi import APIRouter, Request

from app.controllers import base
from app.integrations.provider_router import generate_with_provider
from app.models.schema import (
    ExternalGenerateRequest,
    ExternalGenerateResponse,
    ExternalRenderFinalRequest,
)
from app.services import state as sm
from app.utils import utils

router = APIRouter(prefix="/api/external", tags=["External"])


def _build_assets_from_task(task_id: str) -> list[dict]:
    task = sm.state.get_task(task_id)
    if not task:
        return []

    assets: list[dict] = []
    for video_path in task.get("videos", []) or []:
        assets.append({"type": "video", "url": video_path, "length": 5})

    for combined_path in task.get("combined_videos", []) or []:
        assets.append({"type": "video", "url": combined_path, "length": 5})

    for image_path in [task.get("cover_image")]:
        if image_path:
            assets.append({"type": "image", "url": image_path, "length": 5})

    audio_file = task.get("audio_file")
    if audio_file:
        assets.append({"type": "audio", "url": audio_file, "length": max(1, int(task.get("audio_duration", 5) or 5))})

    script = task.get("script")
    if script:
        assets.append({"type": "title", "text": str(script)[:120], "length": 4})

    return assets


@router.post("/generate", response_model=ExternalGenerateResponse)
def generate_external_asset(request: Request, body: ExternalGenerateRequest):
    request_id = base.get_task_id(request)
    payload = {
        "prompt": body.prompt,
        "imageUrl": body.imageUrl,
        "script": body.script,
        "templateId": body.templateId,
        "aspectRatio": body.aspectRatio,
        "duration": body.duration,
        "outputType": body.outputType or body.type,
        "metadata": body.metadata or {},
        "assets": body.assets or [],
    }

    result = generate_with_provider(body.provider, payload)
    if not result.get("success"):
        result["request_id"] = request_id
    return utils.get_response(200, result)


@router.post("/render-final", response_model=ExternalGenerateResponse)
def render_final_external(request: Request, body: ExternalRenderFinalRequest):
    request_id = base.get_task_id(request)
    provider = (body.provider or "shotstack").strip().lower()

    assets = body.assets or []
    if not assets and body.taskId:
        assets = _build_assets_from_task(body.taskId)

    payload = {
        "prompt": f"render-final-{body.taskId or 'manual'}",
        "templateId": body.templateId,
        "aspectRatio": body.aspectRatio,
        "duration": body.duration,
        "outputType": "video",
        "assets": assets,
        "metadata": body.metadata or {},
    }

    result = generate_with_provider(provider, payload)
    if not result.get("success"):
        result["request_id"] = request_id
    return utils.get_response(200, result)
