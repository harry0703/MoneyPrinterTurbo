import os
import glob
from fastapi import Request, Depends, Path, BackgroundTasks, UploadFile
from fastapi.params import File
from loguru import logger

from app.config import config
from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.models.schema import TaskVideoRequest, TaskQueryResponse, TaskResponse, TaskQueryRequest, BgmListResponse, \
    BgmUploadResponse
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
        if "combined_videos" in task:
            combined_videos = task["combined_videos"]
            task_dir = utils.task_dir()
            urls = []
            for v in combined_videos:
                uri_path = v.replace(task_dir, "tasks")
                urls.append(f"{endpoint}/{uri_path}")
            task["combined_videos"] = urls
        return utils.get_response(200, task)

    raise HttpException(task_id=task_id, status_code=404, message=f"{request_id}: task not found")


@router.get("/get_bgm_list", response_model=BgmListResponse, summary="get local bgm file list")
def get_bgm_list(request: Request):
    suffix = "*.mp3"
    song_dir = utils.song_dir()
    files = glob.glob(os.path.join(song_dir, suffix))
    bgm_list = []
    for file in files:
        bgm_list.append({
            "filename": os.path.basename(file),
            "size": os.path.getsize(file),
            "filepath": file,
        })
    response = {
        "bgm_list": bgm_list
    }
    return utils.get_response(200, response)


@router.post("/upload_bgm_file", response_model=BgmUploadResponse, summary="upload bgm file to songs directory")
def upload_bgm_file(request: Request, file: UploadFile = File(...)):
    request_id = base.get_task_id(request)
    # check file ext
    if file.filename.endswith('mp3'):
        song_dir = utils.song_dir()
        save_path = os.path.join(song_dir, file.filename)
        # save file
        with open(save_path, "wb+") as buffer:
            # If the file already exists, it will be overwritten
            file.file.seek(0)
            buffer.write(file.file.read())
        response = {
            "uploaded_path": save_path
        }
        return utils.get_response(200, response)

    raise HttpException('', status_code=400, message=f"{request_id}: Only *.mp3 files can be uploaded")
