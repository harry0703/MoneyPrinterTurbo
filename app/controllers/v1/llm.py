"""文案、素材关键词和社交发布元数据的 LLM 接口。"""

from fastapi import Depends, Request

from app.controllers import base
from app.controllers.v1.base import new_router
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


@router.post(
    "/scripts",
    response_model=VideoScriptResponse,
    summary="根据主题生成视频文案",
)
def generate_video_script(request: Request, body: VideoScriptRequest):
    """调用当前配置的 LLM 生成视频脚本。"""
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
    summary="根据文案生成素材搜索关键词",
)
def generate_video_terms(request: Request, body: VideoTermsRequest):
    """从视频主题和文案提炼素材检索词。"""
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
    summary="生成社交平台发布标题、简介和标签",
)
def generate_video_social_metadata(
    request: Request, body: VideoSocialMetadataRequest
):
    """根据主题和文案生成适合指定平台的标题、简介和话题标签。"""
    metadata = llm.generate_social_metadata(
        video_subject=body.video_subject,
        video_script=body.video_script,
        language=body.language,
        platform=body.platform,
    )
    return utils.get_response(200, metadata)
