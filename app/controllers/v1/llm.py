from typing import Any

from fastapi import Request
from pydantic import BaseModel, Field

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

# authentication dependency
# router = new_router(dependencies=[Depends(base.verify_token)])
router = new_router()


class RuntimeSettingsRequest(BaseModel):
    section: str = Field(min_length=1, max_length=40)
    values: dict[str, Any]


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
