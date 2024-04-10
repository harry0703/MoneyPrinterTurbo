import os
import glob
from fastapi import Request, Depends, Path, BackgroundTasks, UploadFile
from fastapi.params import File
from loguru import logger

from app.config import config
from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.models.schema import TaskVideoRequest, TaskQueryResponse, TaskResponse, TaskQueryRequest, \
    BgmUploadResponse, BgmRetrieveResponse
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
        sm.state.update_task(task_id)
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
    task = sm.state.get_task(task_id)
    if task:
        task_dir = utils.task_dir()

        def file_to_uri(file):
            if not file.startswith(endpoint):
                _uri_path = v.replace(task_dir, "tasks").replace("\\", "/")
                _uri_path = f"{endpoint}/{_uri_path}"
            else:
                _uri_path = file
            return _uri_path

        if "videos" in task:
            videos = task["videos"]
            urls = []
            for v in videos:
                urls.append(file_to_uri(v))
            task["videos"] = urls
        if "combined_videos" in task:
            combined_videos = task["combined_videos"]
            urls = []
            for v in combined_videos:
                urls.append(file_to_uri(v))
            task["combined_videos"] = urls
        return utils.get_response(200, task)

    raise HttpException(task_id=task_id, status_code=404, message=f"{request_id}: task not found")


@router.get("/musics", response_model=BgmRetrieveResponse, summary="Retrieve local BGM files")
def get_bgm_list(request: Request):
    suffix = "*.mp3"
    song_dir = utils.song_dir()
    files = glob.glob(os.path.join(song_dir, suffix))
    bgm_list = []
    for file in files:
        bgm_list.append({
            "name": os.path.basename(file),
            "size": os.path.getsize(file),
            "file": file,
        })
    response = {
        "files": bgm_list
    }
    return utils.get_response(200, response)


@router.post("/musics", response_model=BgmUploadResponse, summary="Upload the BGM file to the songs directory")
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
            "file": save_path
        }
        return utils.get_response(200, response)

    raise HttpException('', status_code=400, message=f"{request_id}: Only *.mp3 files can be uploaded")
