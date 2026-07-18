from fastapi import Request

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.models.schema import (
    RollSubjectRequest,
    RollSubjectResponse,
    VideoScriptRequest,
    VideoScriptResponse,
    VideoSocialMetadataRequest,
    VideoSocialMetadataResponse,
    VideoTermsRequest,
    VideoTermsResponse,
)
from app.services import llm, task as tm
from app.utils import utils

# authentication dependency
# router = new_router(dependencies=[Depends(base.verify_token)])
router = new_router()


@router.post(
    "/roll",
    response_model=RollSubjectResponse,
    summary="Suggest the next video subject",
)
def roll_next_subject(request: Request, body: RollSubjectRequest):
    recent_subjects, all_subjects = tm.collect_subject_history()
    based_on_recent = (
        body.based_on_previous
        if body.based_on_previous is not None
        else body.based_on_recent
    )
    subject = llm.generate_next_video_subject(
        video_subject=body.video_subject,
        recent_subjects=recent_subjects,
        language=body.video_language,
        based_on_recent=based_on_recent,
        excluded_subjects=all_subjects,
    )
    if not subject or subject.startswith("Error: "):
        request_id = base.get_task_id(request)
        raise HttpException(
            task_id=request_id,
            status_code=502,
            message=f"{request_id}: {subject or 'failed to generate next subject'}",
        )

    response = {
        "video_subject": subject,
        "based_on_recent": based_on_recent,
    }
    return utils.get_response(200, response)


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
