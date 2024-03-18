from os import path

from fastapi import Request, Depends, Path
from loguru import logger

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.models.schema import TaskVideoRequest, TaskQueryResponse, TaskResponse, TaskQueryRequest
from app.services import task as tm
from app.utils import utils

# 认证依赖项
# router = new_router(dependencies=[Depends(base.verify_token)])
router = new_router()


@router.post("/videos", response_model=TaskResponse, summary="使用主题来生成短视频")
def create_video(request: Request, body: TaskVideoRequest):
    task_id = utils.get_uuid()
    request_id = base.get_task_id(request)
    try:
        task = {
            "task_id": task_id,
            "request_id": request_id,
        }
        body_dict = body.dict()
        task.update(body_dict)
        result = tm.start(task_id=task_id, params=body)
        task["result"] = result
        logger.success(f"video created: {utils.to_json(task)}")
        return utils.get_response(200, task)
    except ValueError as e:
        raise HttpException(task_id=task_id, status_code=400, message=f"{request_id}: {str(e)}")


@router.get("/tasks/{task_id}", response_model=TaskQueryResponse, summary="查询任务状态")
def get_task(request: Request, task_id: str = Path(..., description="任务ID"),
                   query: TaskQueryRequest = Depends()):
    request_id = base.get_task_id(request)
    data = query.dict()
    data["task_id"] = task_id
    raise HttpException(task_id=task_id, status_code=404,
                        message=f"{request_id}: task not found", data=data)
