import os
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.config import config
from app.models.exception import HttpException
from app.models.schema import (
    VideoScriptRequest,
    VideoScriptResponse,
    VideoSocialMetadataRequest,
    VideoSocialMetadataResponse,
    VideoTermsRequest,
    VideoTermsResponse,
)
from app.services import llm
from app.utils import utils

# LLM 接口与视频接口共用同一鉴权规则，避免新增端点时遗漏保护。
# api_key 为空时 verify_token 直接放行，不改变默认本地使用体验。
router = new_router(dependencies=[Depends(base.verify_token)])


class RuntimeSettingsRequest(BaseModel):
    section: str = Field(min_length=1, max_length=40)
    values: dict[str, Any]


class VoicePreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    voice_name: str = Field(min_length=1, max_length=300)
    voice_rate: float = Field(default=1.0, ge=0.5, le=3.0)
    voice_volume: float = Field(default=1.0, ge=0.1, le=5.0)


_SETTINGS_SECTIONS = {
    "app": config.app,
    "azure": config.azure,
    "chatterbox": config.chatterbox,
    "elevenlabs": config.elevenlabs,
    "minimax_tts": config.minimax_tts,
    "siliconflow": config.siliconflow,
    "ui": config.ui,
}
_SECRET_KEY_PARTS = ("key", "token", "password", "secret")


def _safe_settings_snapshot() -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for section_name, section in _SETTINGS_SECTIONS.items():
        values: dict[str, Any] = {}
        for key, value in dict(section).items():
            if any(part in key.lower() for part in _SECRET_KEY_PARTS):
                values[key] = {"configured": bool(value)}
            else:
                values[key] = value
        snapshot[section_name] = values
    return snapshot


@router.get("/settings", summary="Read non-secret runtime settings")
def get_runtime_settings(request: Request):
    return utils.get_response(200, _safe_settings_snapshot())


@router.put("/settings", summary="Update runtime settings")
def update_runtime_settings(request: Request, body: RuntimeSettingsRequest):
    section = _SETTINGS_SECTIONS.get(body.section)
    if section is None:
        raise HttpException(
            task_id="",
            status_code=400,
            message=f"unsupported settings section: {body.section}",
        )

    for key, value in body.values.items():
        if not isinstance(key, str) or not key or len(key) > 100:
            continue
        config.update_config_nonblocking(section, key, value)
    config.try_save_config()
    return utils.get_response(200, _safe_settings_snapshot())


@router.post("/voice-preview", summary="Generate a short voice preview")
def generate_voice_preview(
    request: Request,
    body: VoicePreviewRequest,
    background_tasks: BackgroundTasks,
):
    preview_file = os.path.join(
        utils.storage_dir("temp", create=True), f"next-voice-{uuid4().hex}.mp3"
    )
    # Keep preview generation on the same voice dispatcher used by video tasks.
    from app.services import voice

    try:
        result = voice.tts(
            text=body.text,
            voice_name=body.voice_name,
            voice_rate=body.voice_rate,
            voice_file=preview_file,
            voice_volume=body.voice_volume,
        )
    except Exception as exc:
        raise HttpException(
            task_id="",
            status_code=502,
            message=f"voice preview failed: {str(exc)}",
        ) from exc
    if result is None or not os.path.isfile(preview_file):
        raise HttpException(task_id="", status_code=502, message="voice preview failed")

    background_tasks.add_task(_remove_preview_file, preview_file)
    return FileResponse(
        preview_file,
        media_type="audio/mpeg",
        filename="voice-preview.mp3",
        background=background_tasks,
    )


def _remove_preview_file(file_path: str):
    try:
        os.remove(file_path)
    except FileNotFoundError:
        pass


@router.post(
    "/scripts",
    response_model=VideoScriptResponse,
    summary="Create a script for the video",
)
def generate_video_script(request: Request, body: VideoScriptRequest):
    video_script = llm.generate_script(
        video_subject=body.video_subject,
        language=body.video_language,
        paragraph_number=body.paragraph_number,
        video_script_prompt=body.video_script_prompt,
        custom_system_prompt=body.custom_system_prompt,
    )
    response = {"video_script": video_script}
    return utils.get_response(200, response)


@router.post(
    "/terms",
    response_model=VideoTermsResponse,
    summary="Generate video terms based on the video script",
)
def generate_video_terms(request: Request, body: VideoTermsRequest):
    video_terms = llm.generate_terms(
        video_subject=body.video_subject,
        video_script=body.video_script,
        amount=body.amount,
        match_script_order=body.match_materials_to_script,
    )
    response = {"video_terms": video_terms}
    return utils.get_response(200, response)


@router.post(
    "/social-metadata",
    response_model=VideoSocialMetadataResponse,
    summary="Generate social publishing metadata",
)
def generate_video_social_metadata(
    request: Request, body: VideoSocialMetadataRequest
):
    metadata = llm.generate_social_metadata(
        video_subject=body.video_subject,
        video_script=body.video_script,
        language=body.language,
        platform=body.platform,
    )
    return utils.get_response(200, metadata)
