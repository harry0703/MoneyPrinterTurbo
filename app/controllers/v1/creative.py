"""Creative pipeline director endpoints.

Expose the rough-cut checkpoint actions of the flag-gated creative pipeline
(approve/resume plus per-shot edits) and a stage-by-stage pipeline status
view for external orchestration, on top of the shared video task queue.
The vanilla MoneyPrinterTurbo flow is not affected by this router.
"""

import io
from typing import Optional

from fastapi import Path, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.manager.base_manager import TaskQueueFullError
from app.controllers.v1 import video as video_controller
from app.controllers.v1.base import new_router
from app.models import const
from app.models.exception import HttpException
from app.services import rough_cut
from app.services.creative import premiere as creative_premiere
from app.services.creative import pipeline as creative_pipeline
from app.services.creative import qc as creative_qc
from app.services import state as sm
from app.services import task as task_service
from app.utils import utils

router = new_router()


class ReorderShotsRequest(BaseModel):
    order: list[int] = Field(min_length=1)


class ShotDurationRequest(BaseModel):
    duration: float = Field(gt=0.5, le=600)


class ReplaceShotRequest(BaseModel):
    asset_path: str = Field(min_length=1)


class RegenerateShotRequest(BaseModel):
    prompt: Optional[str] = None
    provider: Optional[str] = None


def _run_director_action(request: Request, task_id: str, action) -> dict:
    request_id = base.get_task_id(request)
    try:
        timeline = action()
    except rough_cut.RoughCutError as exc:
        raise HttpException(
            task_id=task_id,
            status_code=exc.status_code,
            message=f"{request_id}: {exc}",
        ) from exc
    return utils.get_response(200, {"task_id": task_id, "rough_cut": timeline})


def _resume_task(request: Request, task_id: str) -> dict:
    request_id = base.get_task_id(request)
    task = sm.state.get_task(task_id)
    if not task or task.get("state") != const.TASK_STATE_WAITING_FOR_DIRECTOR:
        raise HttpException(
            task_id=task_id,
            status_code=409,
            message=f"{request_id}: task is not waiting for director approval",
        )
    try:
        video_controller.task_manager.add_task(
            task_service.resume_after_director, task_id=task_id
        )
    except TaskQueueFullError as exc:
        raise HttpException(
            task_id=task_id,
            status_code=429,
            message=f"{request_id}: {exc}",
        ) from exc
    return utils.get_response(
        200, {"task_id": task_id, "state": const.TASK_STATE_PROCESSING}
    )


@router.post(
    "/creative/tasks/{task_id}/approve",
    summary="Approve the rough cut and render the final video",
)
def approve_rough_cut(request: Request, task_id: str = Path(...)):
    return _resume_task(request, task_id)


@router.post(
    "/creative/tasks/{task_id}/resume",
    summary="Resume a creative task waiting for director approval",
)
def resume_rough_cut(request: Request, task_id: str = Path(...)):
    return _resume_task(request, task_id)


@router.get(
    "/creative/tasks/{task_id}/rough_cut",
    summary="Get the current rough cut timeline",
)
def get_rough_cut(request: Request, task_id: str = Path(...)):
    request_id = base.get_task_id(request)
    timeline = rough_cut.load_rough_cut(task_id)
    if timeline is None:
        raise HttpException(
            task_id=task_id,
            status_code=404,
            message=f"{request_id}: no rough cut found for task",
        )
    return utils.get_response(200, {"task_id": task_id, "rough_cut": timeline})


@router.get(
    "/creative/tasks/{task_id}/qc",
    summary="Get the advisory QC report for the creative task",
)
def get_qc_report(request: Request, task_id: str = Path(...)):
    request_id = base.get_task_id(request)
    report = creative_qc.load_report(task_id)
    if report is None:
        raise HttpException(
            task_id=task_id,
            status_code=404,
            message=f"{request_id}: no qc report found for task",
        )
    return utils.get_response(200, {"task_id": task_id, "qc": report})


@router.get(
    "/creative/tasks/{task_id}/pipeline",
    summary="Get the stage-by-stage creative pipeline status",
)
def get_pipeline_status(request: Request, task_id: str = Path(...)):
    request_id = base.get_task_id(request)
    status = creative_pipeline.build_pipeline_status(task_id)
    if status is None:
        raise HttpException(
            task_id=task_id,
            status_code=404,
            message=f"{request_id}: unknown creative task",
        )
    return utils.get_response(
        200, {"task_id": task_id, "pipeline": status}
    )


@router.get(
    "/creative/tasks/{task_id}/premiere",
    summary="Download the Premiere Pro handoff package (zip)",
)
def download_premiere_handoff(request: Request, task_id: str = Path(...)):
    request_id = base.get_task_id(request)
    try:
        payload, filename = creative_premiere.build_premiere_zip(task_id)
    except creative_premiere.PremiereExportError as exc:
        raise HttpException(
            task_id=task_id,
            status_code=404,
            message=f"{request_id}: {exc}",
        ) from exc
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


@router.post(
    "/creative/tasks/{task_id}/shots/reorder",
    summary="Reorder the shots of the rough cut",
)
def reorder_shots(
    request: Request, body: ReorderShotsRequest, task_id: str = Path(...)
):
    return _run_director_action(
        request, task_id, lambda: rough_cut.reorder_shots(task_id, body.order)
    )


@router.post(
    "/creative/tasks/{task_id}/shots/{index}/duration",
    summary="Change the duration of a rough cut shot",
)
def set_shot_duration(
    request: Request,
    body: ShotDurationRequest,
    task_id: str = Path(...),
    index: int = Path(ge=1),
):
    return _run_director_action(
        request,
        task_id,
        lambda: rough_cut.set_shot_duration(task_id, index, body.duration),
    )


@router.put(
    "/creative/tasks/{task_id}/shots/{index}",
    summary="Replace the asset of a rough cut shot",
)
def replace_shot_asset(
    request: Request,
    body: ReplaceShotRequest,
    task_id: str = Path(...),
    index: int = Path(ge=1),
):
    return _run_director_action(
        request,
        task_id,
        lambda: rough_cut.replace_shot_asset(task_id, index, body.asset_path),
    )


@router.delete(
    "/creative/tasks/{task_id}/shots/{index}",
    summary="Delete a shot from the rough cut",
)
def delete_shot(request: Request, task_id: str = Path(...), index: int = Path(ge=1)):
    return _run_director_action(
        request, task_id, lambda: rough_cut.delete_shot(task_id, index)
    )


@router.post(
    "/creative/tasks/{task_id}/shots/{index}/regenerate",
    summary="Regenerate the image of a rough cut shot",
)
def regenerate_shot(
    request: Request,
    body: RegenerateShotRequest,
    task_id: str = Path(...),
    index: int = Path(ge=1),
):
    return _run_director_action(
        request,
        task_id,
        lambda: rough_cut.regenerate_shot(
            task_id, index, prompt=body.prompt, provider=body.provider
        ),
    )
