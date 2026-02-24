import glob
import os
import pathlib
import shutil
from typing import Any, Iterator

from fastapi import BackgroundTasks, Depends, Path, Query, Request, UploadFile
from fastapi.params import File
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger

from app.config import config
from app.controllers import base
from app.controllers.manager.base_manager import TaskManager
from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.controllers.manager.redis_manager import RedisTaskManager
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.models.schema import (
    AudioRequest,
    BgmRetrieveResponse,
    BgmUploadResponse,
    JiMengVideoRequest,
    SubtitleRequest,
    TaskDeletionResponse,
    TaskQueryRequest,
    TaskQueryResponse,
    TaskResponse,
    TaskVideoRequest,
    VideoMaterialRetrieveResponse,
    VideoMaterialUploadResponse,
)
from app.services import state as sm
from app.services import task as tm
from app.services.jimeng_video import jimeng_video_service
from app.utils import utils

router = new_router()

_enable_redis = config.app.get("enable_redis", False)
_redis_host = config.app.get("redis_host", "localhost")
_redis_port = config.app.get("redis_port", 6379)
_redis_db = config.app.get("redis_db", 0)
_redis_password = config.app.get("redis_password", None)
_max_concurrent_tasks = config.app.get("max_concurrent_tasks", 5)

redis_url = f"redis://:{_redis_password}@{_redis_host}:{_redis_port}/{_redis_db}"
if _enable_redis:
    task_manager: TaskManager = RedisTaskManager(
        max_concurrent_tasks=_max_concurrent_tasks, redis_url=redis_url
    )
else:
    task_manager = InMemoryTaskManager(max_concurrent_tasks=_max_concurrent_tasks)


@router.post("/videos", response_model=TaskResponse, summary="Generate a short video")
def create_video(
    _: BackgroundTasks, request: Request, body: TaskVideoRequest
) -> dict[str, Any]:
    return create_task(request, body, stop_at="video")


@router.post("/subtitle", response_model=TaskResponse, summary="Generate subtitle only")
def create_subtitle(
    _: BackgroundTasks, request: Request, body: SubtitleRequest
) -> dict[str, Any]:
    return create_task(request, body, stop_at="subtitle")


@router.post("/audio", response_model=TaskResponse, summary="Generate audio only")
def create_audio(
    _: BackgroundTasks, request: Request, body: AudioRequest
) -> dict[str, Any]:
    return create_task(request, body, stop_at="audio")


@router.post("/jimeng-video", summary="Generate video using JiMeng API")
async def create_jimeng_video(request: Request, body: JiMengVideoRequest) -> dict[str, Any]:
    """
    Generate a video using JiMeng Video API (VolcEngine).

    This endpoint submits a text-to-video generation task and waits for completion.
    """
    request_id = base.get_task_id(request)
    try:
        video_url = await jimeng_video_service.generate_video(
            prompt=body.prompt,
            seed=body.seed,
            frames=body.frames,
            aspect_ratio=body.aspect_ratio,
            poll_interval=body.poll_interval,
            timeout=body.timeout,
            req_json=body.req_json,
        )
        return utils.get_response(200, {"video_url": video_url})
    except ValueError as e:
        raise HttpException(task_id=request_id, status_code=400, message=str(e))
    except Exception as e:
        logger.error(f"Error generating JiMeng video: {e}")
        raise HttpException(
            task_id=request_id, status_code=500, message="Internal server error"
        )


def create_task(
    request: Request,
    body: TaskVideoRequest | SubtitleRequest | AudioRequest,
    stop_at: str,
) -> dict[str, Any]:
    task_id = utils.get_uuid()
    request_id = base.get_task_id(request)
    try:
        task = {
            "task_id": task_id,
            "request_id": request_id,
            "params": body.model_dump(),
        }
        sm.state.update_task(task_id)
        task_manager.add_task(tm.start, task_id=task_id, params=body, stop_at=stop_at)
        logger.success(f"Task created: {utils.to_json(task)}")
        return utils.get_response(200, task)
    except ValueError as e:
        raise HttpException(
            task_id=task_id, status_code=400, message=f"{request_id}: {str(e)}"
        )


@router.get("/tasks", response_model=TaskQueryResponse, summary="Get all tasks")
def get_all_tasks(
    _: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1),
) -> dict[str, Any]:
    tasks, total = sm.state.get_all_tasks(page, page_size)

    response = {
        "tasks": tasks,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
    return utils.get_response(200, response)


@router.get(
    "/tasks/{task_id}", response_model=TaskQueryResponse, summary="Query task status"
)
def get_task(
    request: Request,
    task_id: str = Path(..., description="Task ID"),
    _: TaskQueryRequest = Depends(),
) -> dict[str, Any]:
    endpoint = config.app.get("endpoint", "")
    if not endpoint:
        endpoint = str(request.base_url)
    endpoint = endpoint.rstrip("/")

    request_id = base.get_task_id(request)
    task = sm.state.get_task(task_id)
    if task:
        task_dir = utils.task_dir()

        def file_to_uri(file_path: str) -> str:
            if not file_path.startswith(endpoint):
                uri_path = file_path.replace(task_dir, "tasks").replace("\\", "/")
                return f"{endpoint}/{uri_path}"
            return file_path

        if "videos" in task:
            task["videos"] = [file_to_uri(v) for v in task["videos"]]
        if "combined_videos" in task:
            task["combined_videos"] = [file_to_uri(v) for v in task["combined_videos"]]

        return utils.get_response(200, task)

    raise HttpException(
        task_id=task_id, status_code=404, message=f"{request_id}: task not found"
    )


@router.delete(
    "/tasks/{task_id}",
    response_model=TaskDeletionResponse,
    summary="Delete a generated short video task",
)
def delete_video(request: Request, task_id: str = Path(..., description="Task ID")) -> dict[str, Any]:
    request_id = base.get_task_id(request)
    task = sm.state.get_task(task_id)
    if task:
        tasks_dir = utils.task_dir()
        current_task_dir = os.path.join(tasks_dir, task_id)
        if os.path.exists(current_task_dir):
            shutil.rmtree(current_task_dir)

        sm.state.delete_task(task_id)
        logger.success(f"video deleted: {utils.to_json(task)}")
        return utils.get_response(200)

    raise HttpException(
        task_id=task_id, status_code=404, message=f"{request_id}: task not found"
    )


@router.get(
    "/musics", response_model=BgmRetrieveResponse, summary="Retrieve local BGM files"
)
def get_bgm_list(_: Request) -> dict[str, Any]:
    suffix = "*.mp3"
    song_dir = utils.song_dir()
    files = glob.glob(os.path.join(song_dir, suffix))
    bgm_list: list[dict[str, Any]] = []
    for file in files:
        bgm_list.append(
            {
                "name": os.path.basename(file),
                "size": os.path.getsize(file),
                "file": file,
            }
        )
    response = {"files": bgm_list}
    return utils.get_response(200, response)


@router.post(
    "/musics",
    response_model=BgmUploadResponse,
    summary="Upload the BGM file to the songs directory",
)
def upload_bgm_file(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
    request_id = base.get_task_id(request)
    if file.filename is not None and file.filename.endswith("mp3"):
        song_dir = utils.song_dir()
        save_path = os.path.join(song_dir, file.filename)
        with open(save_path, "wb+") as buffer:
            file.file.seek(0)
            buffer.write(file.file.read())
        response = {"file": save_path}
        return utils.get_response(200, response)

    raise HttpException(
        task_id="",
        status_code=400,
        message=f"{request_id}: Only *.mp3 files can be uploaded",
    )


@router.get(
    "/video_materials",
    response_model=VideoMaterialRetrieveResponse,
    summary="Retrieve local video materials",
)
def get_video_materials_list(_: Request) -> dict[str, Any]:
    allowed_suffixes = ("mp4", "mov", "avi", "flv", "mkv", "jpg", "jpeg", "png")
    local_videos_dir = utils.storage_dir("local_videos", create=True)
    files: list[str] = []
    for suffix in allowed_suffixes:
        files.extend(glob.glob(os.path.join(local_videos_dir, f"*.{suffix}")))

    video_materials_list: list[dict[str, Any]] = []
    for file in files:
        video_materials_list.append(
            {
                "name": os.path.basename(file),
                "size": os.path.getsize(file),
                "file": file,
            }
        )
    response = {"files": video_materials_list}
    return utils.get_response(200, response)


@router.post(
    "/video_materials",
    response_model=VideoMaterialUploadResponse,
    summary="Upload the video material file to the local videos directory",
)
def upload_video_material_file(
    request: Request, file: UploadFile = File(...)
) -> dict[str, Any]:
    request_id = base.get_task_id(request)
    allowed_suffixes = ("mp4", "mov", "avi", "flv", "mkv", "jpg", "jpeg", "png")
    if file.filename is not None and file.filename.endswith(allowed_suffixes):
        local_videos_dir = utils.storage_dir("local_videos", create=True)
        save_path = os.path.join(local_videos_dir, file.filename)
        with open(save_path, "wb+") as buffer:
            file.file.seek(0)
            buffer.write(file.file.read())
        response = {"file": save_path}
        return utils.get_response(200, response)

    raise HttpException(
        task_id="",
        status_code=400,
        message=(
            f"{request_id}: Only files with extensions {', '.join(allowed_suffixes)} can "
            "be uploaded"
        ),
    )


@router.get("/stream/{file_path:path}")
async def stream_video(request: Request, file_path: str) -> StreamingResponse:
    tasks_dir = utils.task_dir()
    video_path = os.path.join(tasks_dir, file_path)
    range_header = request.headers.get("Range")
    video_size = os.path.getsize(video_path)
    start = 0
    end = video_size - 1

    length = video_size
    if range_header:
        range_value = range_header.split("bytes=")[1]
        start_str, end_str = range_value.split("-")
        range_start = int(start_str) if start_str else None
        range_end = int(end_str) if end_str else None

        if range_start is None and range_end is not None:
            start = video_size - range_end
            end = video_size - 1
        else:
            start = range_start if range_start is not None else 0
            end = range_end if range_end is not None else video_size - 1

        length = end - start + 1

    def file_iterator(
        target_file_path: str, offset: int = 0, bytes_to_read: int | None = None
    ) -> Iterator[bytes]:
        with open(target_file_path, "rb") as file_obj:
            file_obj.seek(offset, os.SEEK_SET)
            remaining = bytes_to_read or video_size
            while remaining > 0:
                chunk_size = min(4096, remaining)
                data = file_obj.read(chunk_size)
                if not data:
                    break
                remaining -= len(data)
                yield data

    response = StreamingResponse(
        file_iterator(video_path, start, length), media_type="video/mp4"
    )
    response.headers["Content-Range"] = f"bytes {start}-{end}/{video_size}"
    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Content-Length"] = str(length)
    response.status_code = 206

    return response


@router.get("/download/{file_path:path}")
async def download_video(_: Request, file_path: str) -> FileResponse:
    """
    download video
    :param _: Request request
    :param file_path: video file path, eg: /cd1727ed-3473-42a2-a7da-4faafafec72b/final-1.mp4
    :return: video file
    """
    tasks_dir = utils.task_dir()
    video_path = os.path.join(tasks_dir, file_path)
    local_file = pathlib.Path(video_path)
    filename = local_file.stem
    extension = local_file.suffix
    headers = {"Content-Disposition": f"attachment; filename={filename}{extension}"}
    return FileResponse(
        path=video_path,
        headers=headers,
        filename=f"{filename}{extension}",
        media_type=f"video/{extension[1:]}",
    )
