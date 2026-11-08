"""Motion Studio API: character uploads, video jobs, progress and downloads.

The LLM API key in a job request is used for one provider call and never stored, logged or returned.
"""

import re

from fastapi import Depends, File, Path, Request, UploadFile
from fastapi.responses import FileResponse

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.models.motion import MotionJobRequest
from app.services.motion import jobs, writer
from app.services.motion.errors import MotionError
from app.services.motion.speech import VOICE_BY_ID, VOICES
from app.utils import utils

# Same auth rule as the rest of /api/v1: no-op unless app.api_key is configured.
router = new_router(dependencies=[Depends(base.verify_token)])

CHARACTER_ID = r"^(up|preset)-[A-Za-z0-9_-]{1,80}$"
JOB_ID = r"^[0-9a-f]{16}$"


def _fail(request: Request, status: int, message: str) -> HttpException:
    return HttpException(task_id=base.get_task_id(request), status_code=status, message=message)


def _job(request: Request, job_id: str) -> jobs.Job:
    job = jobs.get(job_id)
    if job is None:
        raise _fail(request, 404, "job not found")
    return job


@router.get("/motion/options", summary="Motion Studio: providers, voices, saved characters")
def motion_options():
    return utils.get_response(200, {
        "providers": writer.provider_options(),
        "voices": VOICES,
        "characters": jobs.list_characters(),
        "renderer": {"installed": jobs.renderer_installed()},
        "limits": {"glb_mb": jobs.GLB_MAX_BYTES // 2**20, "image_mb": jobs.IMAGE_MAX_BYTES // 2**20},
    })


@router.post("/motion/characters", summary="Motion Studio: upload a character (.glb or image)")
def upload_character(request: Request, file: UploadFile = File(...)):
    data = file.file.read(jobs.GLB_MAX_BYTES + 1)
    try:
        return utils.get_response(200, jobs.save_upload(file.filename or "", data))
    except MotionError as error:
        raise _fail(request, 413 if "MB" in str(error) else 400, str(error)) from None


@router.get("/motion/characters/{character_id}", summary="Motion Studio: character file")
def get_character(request: Request, character_id: str = Path(pattern=CHARACTER_ID)):
    try:
        return FileResponse(jobs.resolve_character(character_id))
    except MotionError as error:
        raise _fail(request, 404, str(error)) from None


@router.post("/motion/jobs", summary="Motion Studio: start making a video")
def create_job(request: Request, body: MotionJobRequest):
    if body.voice not in VOICE_BY_ID:
        raise _fail(request, 400, f"unknown voice: {body.voice}")
    try:
        job = jobs.submit(body)
    except jobs.Busy:
        raise _fail(request, 429, "Too many videos in the queue. Wait for one to finish.") from None
    except MotionError as error:
        raise _fail(request, 400, str(error)) from None
    return utils.get_response(200, {"job_id": job.id})


@router.get("/motion/jobs/{job_id}", summary="Motion Studio: job progress and result")
def job_status(request: Request, job_id: str = Path(pattern=JOB_ID)):
    return utils.get_response(200, _job(request, job_id).public())


@router.post("/motion/jobs/{job_id}/cancel", summary="Motion Studio: cancel a job")
def cancel_job(request: Request, job_id: str = Path(pattern=JOB_ID)):
    job = _job(request, job_id)
    jobs.cancel(job)
    return utils.get_response(200, job.public())


@router.get("/motion/jobs/{job_id}/video", summary="Motion Studio: download the video")
def job_video(request: Request, job_id: str = Path(pattern=JOB_ID)):
    job = _job(request, job_id)
    path = jobs.video_path(job)
    if job.status != "done" or not path.is_file():
        raise _fail(request, 404, "video not ready")
    # Only filesystem-unsafe characters become dashes, so Devanagari vowel signs survive.
    slug = re.sub(r'[\s\\/:*?"<>|]+', "-", job.title).strip("-")[:60] or "short"
    return FileResponse(path, media_type="video/mp4", filename=f"{slug}.mp4")
