from fastapi import Request
from app.controllers.v1.base import new_router
from app.models.schema import VideoScriptResponse, VideoScriptRequest, VideoTermsResponse, VideoTermsRequest
from app.services import llm
from app.utils import utils
from app.controllers import base

# 认证依赖项
# router = new_router(dependencies=[Depends(base.verify_token)])
router = new_router()


@router.post("/generate_video_script", response_model=VideoScriptResponse, summary="Generate a video script")
def generate_video_script(request: Request, body: VideoScriptRequest):
    video_script = llm.generate_script(video_subject=body.video_subject,
                                       language=body.video_language,
                                       paragraph_number=body.paragraph_number)
    response = {
        "video_script": video_script
    }
    return utils.get_response(200, response)


@router.post("/generate_video_terms", response_model=VideoTermsResponse, summary="Generate video terms by video script")
def generate_video_terms(request: Request, body: VideoTermsRequest):
    video_terms = llm.generate_terms(video_subject=body.video_subject,
                                     video_script=body.video_script,
                                     amount=body.amount)
    response = {
        "video_terms": video_terms
    }
    return utils.get_response(200, response)
