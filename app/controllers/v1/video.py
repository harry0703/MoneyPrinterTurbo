import glob
import os
import pathlib
import shutil
from typing import Union

from fastapi import BackgroundTasks, Depends, Path, Request, UploadFile
from fastapi.params import File
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger

from app.config import config
from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.models import const
from app.models.schema import (
    AudioRequest,
    BgmRetrieveResponse,
    BgmUploadResponse,
    SubtitleRequest,
    TaskDeletionResponse,
    TaskQueryRequest,
    TaskQueryResponse,
    TaskResponse,
    TaskVideoRequest,
    VideoMaterialUploadResponse,
    VideoMaterialRetrieveResponse
)
from app.services import state as sm
from app.services import task as tm
from app.utils import utils

# 认证依赖项
# router = new_router(dependencies=[Depends(base.verify_token)])
router = new_router()


@router.post("/videos", response_model=TaskResponse, summary="Generate a short video")
def create_video(
    background_tasks: BackgroundTasks, request: Request, body: TaskVideoRequest
):
    return create_task(request, body, stop_at="video")


@router.post("/subtitle", response_model=TaskResponse, summary="Generate subtitle only")
def create_subtitle(
    background_tasks: BackgroundTasks, request: Request, body: SubtitleRequest
):
    return create_task(request, body, stop_at="subtitle")


@router.post("/audio", response_model=TaskResponse, summary="Generate audio only")
def create_audio(
    background_tasks: BackgroundTasks, request: Request, body: AudioRequest
):
    return create_task(request, body, stop_at="audio")


def create_task(
    request: Request,
    body: Union[TaskVideoRequest, SubtitleRequest, AudioRequest],
    stop_at: str,
):
    task_id = utils.get_uuid()
    request_id = base.get_task_id(request)
    
    # Task will be queued if another task is running (handled by thread_manager)
    try:
        task = {
            "task_id": task_id,
            "request_id": request_id,
            "params": body.model_dump(),
        }
        
        # Debug: Check what voice_name is being received
        if hasattr(body, 'voice_name'):
            logger.info(f"[Task Creation] voice_name received: {body.voice_name[:100]}...")
            logger.info(f"[Task Creation] voice_name starts with 'coze|': {body.voice_name.startswith('coze|')}")
        
        # Debug: Check host_visible
        if hasattr(body, 'host_visible'):
            logger.info(f"[Task Creation] host_visible received: {body.host_visible}")
            logger.info(f"[Task Creation] host_visible type: {type(body.host_visible)}")
        
        sm.state.update_task(task_id, state=const.TASK_STATE_PENDING, progress=0, task_type="video_generation")
        logger.debug(f"video_controller: Calling start_async for task_id={task_id}, thread_manager_id={id(tm)}")
        _, queue_status = tm.start_async(task_id, body, stop_at)
        
        # Get the task with task_type from state
        created_task = sm.state.get_task(task_id)
        
        # Provide appropriate message based on queue status
        if queue_status == "queued":
            message = "Parallel running task capacity used up and your task will be queued for next slot"
            logger.info(f"Task {task_id} queued: {message}")
        else:
            message = "success"
            logger.success(f"Task created: {utils.to_json(created_task)}")
        
        return utils.get_response(200, created_task, message=message)
    except ValueError as e:
        raise HttpException(
            task_id=task_id, status_code=400, message=f"{request_id}: {str(e)}"
        )

from fastapi import Query

@router.get("/tasks", response_model=TaskQueryResponse, summary="Get all tasks")
def get_all_tasks(request: Request, page: int = Query(1, ge=1), page_size: int = Query(10, ge=1)):
    request_id = base.get_task_id(request)
    tasks, total = sm.state.get_all_tasks(page, page_size)
    
    endpoint = config.app.get("endpoint", "")
    if not endpoint:
        endpoint = str(request.base_url)
    endpoint = endpoint.rstrip("/")
    task_dir = utils.task_dir()
    
    def file_to_uri(file):
        if not file.startswith(endpoint):
            _uri_path = file.replace(task_dir, "tasks").replace("\\", "/")
            _uri_path = f"{endpoint}/{_uri_path}"
        else:
            _uri_path = file
        return _uri_path
    
    def convert_task(task):
        status_map = {
            const.TASK_STATE_FAILED: "failed",
            const.TASK_STATE_PENDING: "pending",
            const.TASK_STATE_COMPLETE: "completed",
            const.TASK_STATE_PROCESSING: "running"
        }
        if "state" in task:
            task["status"] = status_map.get(task["state"], "pending")
            del task["state"]
        
        if "videos" in task and task["videos"]:
            videos = task["videos"]
            urls = []
            for v in videos:
                urls.append(file_to_uri(v))
            task["videos"] = urls
        if "combined_videos" in task and task["combined_videos"]:
            combined_videos = task["combined_videos"]
            urls = []
            for v in combined_videos:
                urls.append(file_to_uri(v))
            task["combined_videos"] = urls
        return task
    
    converted_tasks = [convert_task(task) for task in tasks]

    response = {
        "tasks": converted_tasks,
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
    query: TaskQueryRequest = Depends(),
):
    endpoint = config.app.get("endpoint", "")
    if not endpoint:
        endpoint = str(request.base_url)
    endpoint = endpoint.rstrip("/")

    request_id = base.get_task_id(request)
    task = sm.state.get_task(task_id)
    if task:
        # Convert numeric status to string status
        status_map = {
            const.TASK_STATE_FAILED: "failed",
            const.TASK_STATE_PENDING: "pending",
            const.TASK_STATE_COMPLETE: "completed",
            const.TASK_STATE_PROCESSING: "running"
        }
        if "state" in task:
            task["status"] = status_map.get(task["state"], "pending")
            del task["state"]
        
        task_dir = utils.task_dir()

        def file_to_uri(file):
            if not file.startswith(endpoint):
                _uri_path = file.replace(task_dir, "tasks").replace("\\", "/")
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

    raise HttpException(
        task_id=task_id, status_code=404, message=f"{request_id}: task not found"
    )


@router.delete(
    "/tasks/{task_id}",
    response_model=TaskDeletionResponse,
    summary="Delete a generated short video task",
)
def delete_video(request: Request, task_id: str = Path(..., description="Task ID")):
    request_id = base.get_task_id(request)
    task = sm.state.get_task(task_id)
    if task:
        tasks_dir = utils.task_dir()
        current_task_dir = os.path.join(tasks_dir, task_id)
        if os.path.exists(current_task_dir):
            shutil.rmtree(current_task_dir)

        # 删除任务的日志
        from app.services.log_service import log_service
        log_service.clear_task_logs(task_id)

        sm.state.delete_task(task_id)
        logger.success(f"video deleted: {utils.to_json(task)}")
        return utils.get_response(200)

    raise HttpException(
        task_id=task_id, status_code=404, message=f"{request_id}: task not found"
    )


@router.post(
    "/tasks/{task_id}/cancel",
    response_model=TaskDeletionResponse,
    summary="Cancel a running task",
)
def cancel_task(request: Request, task_id: str = Path(..., description="Task ID")):
    request_id = base.get_task_id(request)
    task = sm.state.get_task(task_id)
    if task:
        # 这里需要调用 thread_manager.cancel_task 来取消任务
        # 但是我们需要确保 thread_manager 能够访问到
        from app.services.thread_manager import thread_manager
        thread_manager.cancel_task(task_id)
        
        # 更新任务状态为 cancelled
        sm.state.update_task(task_id, const.TASK_STATE_FAILED, **{"status": "cancelled"})
        
        logger.success(f"Task cancelled: {task_id}")
        return utils.get_response(200)

    raise HttpException(
        task_id=task_id, status_code=404, message=f"{request_id}: task not found"
    )


@router.get(
    "/musics", response_model=BgmRetrieveResponse, summary="Retrieve local BGM files"
)
def get_bgm_list(request: Request):
    suffix = "*.mp3"
    song_dir = utils.song_dir()
    files = glob.glob(os.path.join(song_dir, suffix))
    bgm_list = []
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
def upload_bgm_file(request: Request, file: UploadFile = File(...)):
    request_id = base.get_task_id(request)
    # check file ext
    if file.filename.endswith("mp3"):
        song_dir = utils.song_dir()
        save_path = os.path.join(song_dir, file.filename)
        # save file
        with open(save_path, "wb+") as buffer:
            # If the file already exists, it will be overwritten
            file.file.seek(0)
            buffer.write(file.file.read())
        response = {"file": save_path}
        return utils.get_response(200, response)

    raise HttpException(
        "", status_code=400, message=f"{request_id}: Only *.mp3 files can be uploaded"
    )

@router.get(
    "/video_materials", response_model=VideoMaterialRetrieveResponse, summary="Retrieve local video materials"
)
def get_video_materials_list(request: Request):
    allowed_suffixes = ("mp4", "mov", "avi", "flv", "mkv", "jpg", "jpeg", "png")
    local_videos_dir = utils.storage_dir("local_videos", create=True)
    files = []
    for suffix in allowed_suffixes:
        files.extend(glob.glob(os.path.join(local_videos_dir, f"*.{suffix}")))
    video_materials_list = []
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
def upload_video_material_file(request: Request, file: UploadFile = File(...)):
    request_id = base.get_task_id(request)
    # check file ext
    allowed_suffixes = ("mp4", "mov", "avi", "flv", "mkv", "jpg", "jpeg", "png", "gif")
    if file.filename.endswith(allowed_suffixes):
        local_videos_dir = utils.storage_dir("local_videos", create=True)
        save_path = os.path.join(local_videos_dir, file.filename)
        # save file
        with open(save_path, "wb+") as buffer:
            # If the file already exists, it will be overwritten
            file.file.seek(0)
            buffer.write(file.file.read())
        response = {"file": save_path}
        return utils.get_response(200, response)

    raise HttpException(
        "", status_code=400, message=f"{request_id}: Only files with extensions {', '.join(allowed_suffixes)} can be uploaded"
    )


@router.post(
    "/intro-video/{task_id}",
    response_model=VideoMaterialUploadResponse,
    summary="Upload intro video to task-specific intro_videos directory",
)
def upload_intro_video(request: Request, task_id: str, file: UploadFile = File(...)):
    request_id = base.get_task_id(request)
    # check file ext
    allowed_suffixes = ("mp4", "mov", "avi", "flv", "mkv", "jpg", "jpeg", "png", "gif")
    if file.filename.endswith(allowed_suffixes):
        # Create task-specific intro_videos directory at storage root
        task_intro_videos_dir = utils.storage_dir("intro_videos", create=True)
        task_intro_videos_dir = os.path.join(task_intro_videos_dir, task_id)
        if not os.path.exists(task_intro_videos_dir):
            os.makedirs(task_intro_videos_dir)
        
        save_path = os.path.join(task_intro_videos_dir, file.filename)
        # save file
        with open(save_path, "wb+") as buffer:
            # If the file already exists, it will be overwritten
            file.file.seek(0)
            buffer.write(file.file.read())
        response = {"file": save_path}
        return utils.get_response(200, response)

    raise HttpException(
        "", status_code=400, message=f"{request_id}: Only files with extensions {', '.join(allowed_suffixes)} can be uploaded"
    )

@router.get("/stream/{file_path:path}")
async def stream_video(request: Request, file_path: str):
    tasks_dir = utils.task_dir()
    video_path = os.path.join(tasks_dir, file_path)
    range_header = request.headers.get("Range")
    video_size = os.path.getsize(video_path)
    start, end = 0, video_size - 1

    length = video_size
    if range_header:
        range_ = range_header.split("bytes=")[1]
        start, end = [int(part) if part else None for part in range_.split("-")]
        if start is None:
            start = video_size - end
            end = video_size - 1
        if end is None:
            end = video_size - 1
        length = end - start + 1

    def file_iterator(file_path, offset=0, bytes_to_read=None):
        with open(file_path, "rb") as f:
            f.seek(offset, os.SEEK_SET)
            remaining = bytes_to_read or video_size
            while remaining > 0:
                bytes_to_read = min(4096, remaining)
                data = f.read(bytes_to_read)
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
    response.status_code = 206  # Partial Content

    return response


@router.get("/download/{file_path:path}")
async def download_video(_: Request, file_path: str):
    """
    download video
    :param _: Request request
    :param file_path: video file path, eg: /cd1727ed-3473-42a2-a7da-4faafafec72b/final-1.mp4
    :return: video file
    """
    tasks_dir = utils.task_dir()
    video_path = os.path.join(tasks_dir, file_path)
    file_path = pathlib.Path(video_path)
    filename = file_path.stem
    extension = file_path.suffix
    headers = {"Content-Disposition": f"attachment; filename={filename}{extension}"}
    return FileResponse(
        path=video_path,
        headers=headers,
        filename=f"{filename}{extension}",
        media_type=f"video/{extension[1:]}",
    )


@router.get("/title-styles", summary="Get available title styles")
def get_title_styles(request: Request):
    from app.services.title import get_available_title_styles
    
    styles = get_available_title_styles()
    return utils.get_response(200, styles)


@router.post("/title-preview", summary="Preview title style")
def preview_title(request: Request, body: dict):
    from app.services.title import create_title_clip, _get_valid_font_path
    from app.models.schema import VideoParams
    from app.models.schema import VideoAspect
    from loguru import logger
    
    params = VideoParams()
    params.title_enabled = body.get('title_enabled', True)
    params.title_text = body.get('title_text', 'Preview Title')
    params.title_font_name = body.get('title_font_name', 'MicrosoftYaHeiBold.ttc')
    params.title_font_size = body.get('title_font_size', 72)
    params.title_text_color = body.get('title_text_color', '#FFFFFF')
    params.title_stroke_color = body.get('title_stroke_color', '#000000')
    params.title_stroke_width = body.get('title_stroke_width', 2.0)
    params.title_background_color = body.get('title_background_color', 'transparent')
    params.title_position = body.get('title_position', 'center')
    params.title_margin = body.get('title_margin', 0.05)
    params.title_margin_left = body.get('title_margin_left', 0.05)
    params.title_margin_right = body.get('title_margin_right', 0.05)
    params.title_align = body.get('title_align', 'center')
    params.title_animation = body.get('title_animation', 'none')
    params.title_animation_duration = body.get('title_animation_duration', 0.5)
    
    logger.info(f"Title preview request - text: '{params.title_text}', font: '{params.title_font_name}'")
    
    font_path = _get_valid_font_path(params.title_font_name)
    logger.info(f"Resolved font path: '{font_path}', exists: {os.path.exists(font_path)}")
    logger.info(f"Font directory: '{utils.font_dir()}'")
    logger.info(f"Available fonts: {os.listdir(utils.font_dir())}")
    
    video_aspect = body.get('video_aspect', '9:16')
    if video_aspect == '9:16':
        width, height = 1080, 1920
    elif video_aspect == '16:9':
        width, height = 1920, 1080
    elif video_aspect == '1:1':
        width, height = 1080, 1080
    else:
        width, height = 1080, 1920
    
    title_clip = create_title_clip(width, height, params)
    
    if title_clip is None:
        raise HttpException(task_id="", status_code=400, message="Failed to create title clip")
    
    preview_dir = utils.storage_dir("title_previews", create=True)
    preview_path = os.path.join(preview_dir, f"title_preview_{utils.get_uuid()[:8]}.png")
    
    title_clip.save_frame(preview_path, t=0)
    
    logger.info(f"Title preview saved to: {preview_path}")
    
    response = {"preview_path": preview_path}
    return utils.get_response(200, response)


@router.post("/scene-integration/scan", summary="Scan task directory for scene integration")
def scan_scene_integration(request: Request, body: dict):
    """Scan task directory for scene integration"""
    task_id_or_path = body.get("task_id") or body.get("task_path")
    if not task_id_or_path:
        raise HttpException(task_id="", status_code=400, message="Task ID or path is required")
    
    from app.services.video import scan_task_files
    
    try:
        result = scan_task_files(task_id_or_path)
        
        scene_videos = [s for s in result["scene_videos"] if s["video"] is not None]
        
        response = {
            "sceneVideos": len(scene_videos),
            "sceneAudio": len([s for s in result["scene_videos"] if s["audio"] is not None]),
            "subtitle": result["global_subtitle"] is not None,
            "totalScenes": result["total_scenes"],
            "isValid": result["is_valid"],
            "taskDir": result["task_dir"]
        }
        
        return utils.get_response(200, response)
    except Exception as e:
        logger.error(f"Error scanning scene integration: {e}")
        raise HttpException(task_id=task_id_or_path, status_code=500, message=f"Failed to scan task: {str(e)}")


@router.post("/scene-integration/recover", summary="Recover video synthesis from existing scene files")
def recover_scene_integration(request: Request, body: dict):
    """Recover video synthesis from existing scene files"""
    task_id_or_path = body.get("task_id") or body.get("task_path")
    start_scene = body.get("start_scene", 1)
    end_scene = body.get("end_scene", None)
    
    # Extract subtitle parameters from request
    subtitle_params = {
        'subtitle_enabled': body.get('subtitle_enabled'),
        'font_name': body.get('font_name'),
        'font_size': body.get('font_size'),
        'text_fore_color': body.get('text_fore_color'),
        'text_background_color': body.get('text_background_color'),
        'stroke_color': body.get('stroke_color'),
        'stroke_width': body.get('stroke_width'),
        'subtitle_position': body.get('subtitle_position'),
        'custom_position': body.get('custom_position')
    }
    
    # Extract BGM parameters from request
    bgm_params = {
        'bgm_type': body.get('bgm_type'),
        'bgm_file': body.get('bgm_file'),
        'bgm_volume': body.get('bgm_volume')
    }
    
    if not task_id_or_path:
        raise HttpException(task_id="", status_code=400, message="Task ID or path is required")
    
    from app.services import state as sm
    from app.models import const
    from app.services.task import thread_manager
    
    # Generate unique task_id for tracking
    task_id = utils.get_uuid()
    
    # Register task immediately so it appears in task management
    sm.state.update_task(task_id, state=const.TASK_STATE_PENDING, progress=0, task_type="scene_integration")
    
    # Submit to thread manager for proper concurrency control
    from app.services.video import recover_video_synthesis
    _, queue_status = thread_manager.submit_task(
        task_id,
        recover_video_synthesis,
        task_id_or_path,
        start_scene=start_scene,
        end_scene=end_scene,
        task_id=task_id,
        subtitle_params=subtitle_params,
        bgm_params=bgm_params
    )
    
    # Get the task with task_type from state
    created_task = sm.state.get_task(task_id)
    
    # Provide appropriate message based on queue status
    if queue_status == "queued":
        message = "Parallel running task capacity used up and your task will be queued for next slot"
        logger.info(f"Scene integration task {task_id} queued: {message}")
    else:
        message = "success"
        logger.success(f"Scene integration task created: {utils.to_json(created_task)}")
    
    return utils.get_response(200, created_task, message=message)
