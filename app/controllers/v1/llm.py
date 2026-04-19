from fastapi import Request, Body
from loguru import logger

from app.controllers.v1.base import new_router
from app.models.schema import (
    VideoScriptRequest,
    VideoScriptResponse,
    VideoTermsRequest,
    VideoTermsResponse,
)
from app.services import llm
from app.services import scene_parser
from app.utils import utils

# authentication dependency
# router = new_router(dependencies=[Depends(base.verify_token)])
router = new_router()


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
    )
    response = {"video_terms": video_terms}
    return utils.get_response(200, response)


@router.post(
    "/parse-script",
    summary="Parse video script into scenes",
)
def parse_video_script(request: Request, body: dict = Body(...)):
    video_script = body.get("video_script")
    language = body.get("language")
    
    if not video_script:
        return utils.get_response(400, {"error": "Video script is required"})
    
    result = scene_parser.auto_parse_script(video_script, language=language)
    logger.info(f"Parse script result: status={result['status']}, scenes_count={len(result.get('scenes', []))}")
    return utils.get_response(200, result)
