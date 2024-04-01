from fastapi import Request, Depends, Path, BackgroundTasks
from loguru import logger

from app.config import config
from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.models.schema import TaskVideoRequest, TaskQueryResponse, TaskResponse, TaskQueryRequest
from app.services import task as tm
from app.services import state as sm
from app.utils import utils

# 认证依赖项
# router = new_router(dependencies=[Depends(base.verify_token)])
router = new_router()


@router.post("/videos", response_model=TaskResponse, summary="Generate a short video")
def create_video(background_tasks: BackgroundTasks, request: Request, body: TaskVideoRequest):
    task_id = utils.get_uuid()
    request_id = base.get_task_id(request)
    try:
        task = {
            "task_id": task_id,
            "request_id": request_id,
            "params": body.dict(),
        }
        sm.update_task(task_id)
        background_tasks.add_task(tm.start, task_id=task_id, params=body)
        logger.success(f"video created: {utils.to_json(task)}")
        return utils.get_response(200, task)
    except ValueError as e:
        raise HttpException(task_id=task_id, status_code=400, message=f"{request_id}: {str(e)}")


@router.get("/tasks/{task_id}", response_model=TaskQueryResponse, summary="Query task status")
def get_task(request: Request, task_id: str = Path(..., description="Task ID"),
             query: TaskQueryRequest = Depends()):
    endpoint = config.app.get("endpoint", "")
    if not endpoint:
        endpoint = str(request.base_url)
    endpoint = endpoint.rstrip("/")

    request_id = base.get_task_id(request)
    task = sm.get_task(task_id)
    if task:
        if "videos" in task:
            videos = task["videos"]
            task_dir = utils.task_dir()
            urls = []
            for v in videos:
                uri_path = v.replace(task_dir, "tasks")
                urls.append(f"{endpoint}/{uri_path}")
            task["videos"] = urls
        return utils.get_response(200, task)

    raise HttpException(task_id=task_id, status_code=404, message=f"{request_id}: task not found")
