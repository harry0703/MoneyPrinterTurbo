import asyncio

from fastapi import Request

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

# authentication dependency
# router = new_router(dependencies=[Depends(base.verify_token)])
router = new_router()


# 这些 LLM 端点声明为 async，并通过 asyncio.to_thread 在后台线程执行同步的
# generate_* 调用。原因：现有 20+ provider 的 SDK（dashscope / g4f / requests
# 类的 cloudflare/ernie/pollinations/litellm 等）都是同步阻塞接口，无法直接
# 改成原生 async。如果端点本身是同步 def，FastAPI 会把请求交给 anyio 线程池
# （默认 40 个 worker），LLM 等待期间会占满线程池，挤占其它同步端点。改为
# async def 后，等待期间不占线程池容量；同步 SDK 调用仍由 to_thread 隔离，
# 避免阻塞事件循环。WebUI / CLI 走 task.start 同步直调路径，不受影响。
@router.post(
    "/scripts",
    response_model=VideoScriptResponse,
    summary="Create a script for the video",
)
async def generate_video_script(request: Request, body: VideoScriptRequest):
    video_script = await asyncio.to_thread(
        llm.generate_script,
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
async def generate_video_terms(request: Request, body: VideoTermsRequest):
    video_terms = await asyncio.to_thread(
        llm.generate_terms,
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
async def generate_video_social_metadata(
    request: Request, body: VideoSocialMetadataRequest
):
    metadata = await asyncio.to_thread(
        llm.generate_social_metadata,
        video_subject=body.video_subject,
        video_script=body.video_script,
        language=body.language,
        platform=body.platform,
    )
    return utils.get_response(200, metadata)
