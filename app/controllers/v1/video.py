import mimetypes
import os
import pathlib
import shutil
from typing import Union
from urllib.parse import quote

from fastapi import BackgroundTasks, Depends, Path, Query, Request, UploadFile
from fastapi.params import File
from fastapi.responses import FileResponse, Response, StreamingResponse
from loguru import logger
from starlette.background import BackgroundTask

from app.config import config
from app.controllers import base
from app.controllers.manager.base_manager import TaskQueueFullError
from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.controllers.manager.redis_manager import RedisTaskManager
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.models.schema import (
    AudioRequest,
    BgmRetrieveResponse,
    BgmUploadResponse,
    SubtitleRequest,
    TaskDeletionResponse,
    TaskListResponse,
    TaskQueryRequest,
    TaskQueryResponse,
    TaskResponse,
    TaskVideoRequest,
    VideoMaterialUploadResponse,
    VideoMaterialRetrieveResponse
)
from app.services import bgm as bgm_service
from app.services import material_upload as material_upload_service
from app.services import state as sm
from app.services import task as tm
from app.utils import file_security, utils

# Authentication is enforced uniformly at the V1 video route entry. verify_token keeps the existing no-auth behavior
# when api_key is empty, and only affects clients once an administrator configures it explicitly.
router = new_router(dependencies=[Depends(base.verify_token)])

_enable_redis = config.app.get("enable_redis", False)
_redis_host = config.app.get("redis_host", "localhost")
_redis_port = config.app.get("redis_port", 6379)
_redis_db = config.app.get("redis_db", 0)
_redis_password = config.app.get("redis_password", None)
_max_concurrent_tasks = config.app.get("max_concurrent_tasks", 5)
_max_queued_tasks = config.app.get("max_queued_tasks", 100)


def _build_redis_url(host: str, port: int, db: int, password: str | None) -> str:
    # Passwords are URL userinfo. Escape reserved characters so Redis receives
    # the exact configured secret rather than parsing part of it as a host,
    # port, path, query, or fragment.
    auth = f":{quote(password, safe='')}@" if password else ""
    # URL authorities require brackets around IPv6 literals. RedisState also
    # accepts a plain IPv6 host, so keep the queue client compatible with it.
    url_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"redis://{auth}{url_host}:{port}/{db}"


redis_url = _build_redis_url(_redis_host, _redis_port, _redis_db, _redis_password)
# Choose the appropriate task manager based on config
if _enable_redis:
    task_manager = RedisTaskManager(
        max_concurrent_tasks=_max_concurrent_tasks,
        redis_url=redis_url,
        max_queued_tasks=_max_queued_tasks,
    )
else:
    task_manager = InMemoryTaskManager(
        max_concurrent_tasks=_max_concurrent_tasks,
        max_queued_tasks=_max_queued_tasks,
    )


def _sanitize_upload_filename(filename: str, request_id: str) -> str:
    # Browsers or clients sometimes include directory info, possibly even traversal fragments like ../.
    # Only the bare filename is kept here, so the upload endpoint can't write files outside the target directory.
    normalized_name = (filename or "").replace("\\", "/").split("/")[-1].strip()
    if not normalized_name or normalized_name in {".", ".."}:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: invalid filename",
        )
    return normalized_name


def _resolve_path_within_directory(base_dir: str, unsafe_path: str, request_id: str) -> str:
    try:
        return file_security.resolve_path_within_directory(base_dir, unsafe_path)
    except ValueError as exc:
        logger.warning(
            f"reject unsafe file path, request_id: {request_id}, path: {unsafe_path}, "
            f"error: {str(exc)}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=404 if str(exc) == "file does not exist" else 403,
            message=f"{request_id}: invalid file path",
        )


def _public_task_data(task: dict) -> dict:
    """Copy the task state and remove internal fields used only for server-side process coordination."""
    public_task = dict(task)
    public_task.pop("cross_post_owner", None)
    return public_task


def _task_file_to_uri(file: str, endpoint: str, task_dir: str, request_id: str) -> str:
    if not isinstance(file, str):
        return file

    if file.startswith(("http://", "https://")):
        return file

    try:
        resolved_path = file_security.resolve_path_within_directory(task_dir, file)
    except ValueError as exc:
        # Task state should in theory only store output paths inside the task directory. URLs are no longer joined here,
        # so abnormal paths aren't wrapped into accessible links; the original value is kept to help diagnose historical dirty data.
        logger.warning(
            f"skip unsafe task output path, request_id: {request_id}, path: {file}, "
            f"error: {str(exc)}"
        )
        return file

    relative_path = os.path.relpath(
        resolved_path, os.path.realpath(task_dir)
    ).replace("\\", "/")
    uri_path = f"tasks/{quote(relative_path, safe='/')}"
    if endpoint:
        return f"{endpoint.rstrip('/')}/{uri_path}"
    return f"/{uri_path}"


def _task_response_data(task: dict, endpoint: str, task_dir: str, request_id: str) -> dict:
    response_task = _public_task_data(task)
    for key in ("videos", "combined_videos"):
        if key in task:
            response_task[key] = [
                _task_file_to_uri(file, endpoint, task_dir, request_id)
                for file in task[key]
            ]
    for key in ("audio_file", "subtitle_path"):
        if task.get(key):
            response_task[key] = _task_file_to_uri(
                task[key], endpoint, task_dir, request_id
            )
    return response_task


def _parse_byte_range(
    range_header: str | None, file_size: int, request_id: str
) -> tuple[int, int]:
    """Parse a single-range HTTP Range header, consistently turning invalid or out-of-bounds requests into 416."""
    # 416 is only used to answer Range requests. Without Range, an empty file is still a complete representation,
    # so a 0-byte 200 is returned, consistent with /download.
    if not range_header:
        return 0, file_size - 1

    if file_size <= 0:
        raise HttpException(
            task_id=request_id,
            status_code=416,
            message=f"{request_id}: requested range is not satisfiable",
        )

    try:
        # The video player only needs single-range bytes here. Rejecting multi-range requests avoids a response body
        # inconsistent with Content-Range, and keeps malformed strings from reaching int() and causing a 500.
        unit, separator, positions = range_header.strip(" \t").partition("=")
        if unit.lower() != "bytes" or not separator or "," in positions:
            raise ValueError("unsupported range format")
        start_text, end_text = positions.split("-", 1)
        if not start_text and not end_text:
            raise ValueError("empty range")
        # HTTP positions use ASCII DIGIT, not Python's broader int syntax.
        if any(value and not (value.isascii() and value.isdigit())
               for value in (start_text, end_text)):
            raise ValueError("invalid byte position")

        if not start_text:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise ValueError("invalid suffix length")
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
            if start < 0 or start >= file_size or end < start:
                raise ValueError("range outside file")
            end = min(end, file_size - 1)
    except (TypeError, ValueError) as exc:
        logger.warning(
            f"reject invalid video range, request_id: {request_id}, "
            f"range: {range_header}, file_size: {file_size}, error: {str(exc)}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=416,
            message=f"{request_id}: requested range is not satisfiable",
        ) from exc

    return start, end


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
    try:
        if (
            stop_at == "video"
            and isinstance(body, TaskVideoRequest)
            and body.subtitle_enabled
        ):
            tm.video.validate_subtitle_colors(body)
            # The font name can be submitted directly by API clients, so path escapes can't wait to be discovered at background render time.
            # The directory boundary check is shared with the render layer, so invalid requests return 403/404 before a paid task is created.
            # Route the font pre-check through the file-serving
            # wrapper so the 403/404 error codes match the other
            # task-output paths in this file instead of 400. The
            # create_task outer except ValueError no longer covers
            # this branch.
            _resolve_path_within_directory(
                utils.font_dir(),
                body.font_name or "STHeitiMedium.ttc",
                request_id,
            )
        task = {
            "task_id": task_id,
            "request_id": request_id,
            "params": body.model_dump(),
        }
        sm.state.update_task(task_id)
        try:
            task_manager.add_task(
                tm.start, task_id=task_id, params=body, stop_at=stop_at
            )
        except Exception:
            # The state record is created before scheduling and defaults to processing. If the scheduler failed to
            # take over the task (e.g. thread start failure or Redis queue unavailable), the record must be rolled back,
            # otherwise the API and WebUI would forever show a task that never actually ran.
            sm.state.delete_task(task_id)
            raise
        logger.success(f"Task created: {utils.to_json(task)}")
        return utils.get_response(200, task)
    except TaskQueueFullError as e:
        logger.warning(
            f"reject task because queue is full, request_id: {request_id}, task_id: {task_id}"
        )
        raise HttpException(
            task_id=task_id, status_code=429, message=f"{request_id}: {str(e)}"
        )
    except ValueError as e:
        raise HttpException(
            task_id=task_id, status_code=400, message=f"{request_id}: {str(e)}"
        )

@router.get("/tasks", response_model=TaskListResponse, summary="Get all tasks")
def get_all_tasks(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=1000),
):
    tasks, total = sm.state.get_all_tasks(page, page_size)
    request_id = base.get_task_id(request)
    endpoint = config.app.get("endpoint", "").rstrip("/")
    task_dir = utils.task_dir()

    response = {
        "tasks": [
            _task_response_data(task, endpoint, task_dir, request_id) for task in tasks
        ],
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
    request_id = base.get_task_id(request)
    endpoint = config.app.get("endpoint", "").rstrip("/")
    task = sm.state.get_task(task_id)
    if task:
        task_dir = utils.task_dir()
        response_task = _task_response_data(task, endpoint, task_dir, request_id)
        return utils.get_response(200, response_task)

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
        if tm.is_task_busy(task):
            logger.warning(
                f"refuse to delete busy task, request_id: {request_id}, "
                f"task_id: {task_id}, state: {task.get('state')}, "
                f"cross_post_state: {task.get('cross_post_state')}"
            )
            raise HttpException(
                task_id=task_id,
                status_code=409,
                message=f"{request_id}: task is still running",
            )

        tasks_dir = utils.task_dir()
        current_task_dir = os.path.join(tasks_dir, task_id)
        if os.path.exists(current_task_dir):
            try:
                shutil.rmtree(current_task_dir)
            except FileNotFoundError:
                # Another completed-task deletion may remove this directory
                # after our existence check. Only accept an absent root;
                # partial deletion and other filesystem errors must keep state.
                if os.path.lexists(current_task_dir):
                    raise

        sm.state.delete_task(task_id)
        logger.success(f"video deleted: {utils.to_json(task)}")
        return utils.get_response(200)

    raise HttpException(
        task_id=task_id, status_code=404, message=f"{request_id}: task not found"
    )


@router.get(
    "/musics", response_model=BgmRetrieveResponse, summary="Retrieve local BGM files"
)
def get_bgm_list(request: Request):
    bgm_list = []
    for file in bgm_service.list_bgm_files():
        filename = os.path.basename(file)
        try:
            size = os.path.getsize(file)
        except OSError as exc:
            logger.warning(f"skip unavailable background music: name={filename}, error={exc}")
            continue
        bgm_list.append(
            {
                "name": filename,
                "size": size,
                # Only return the filename, so absolute server paths aren't exposed to callers. The server re-resolves
                # it within the two allowlisted directories storage/bgm and resource/songs.
                "file": filename,
            }
        )
    response = {"files": bgm_list}
    return utils.get_response(200, response)


@router.post(
    "/musics",
    response_model=BgmUploadResponse,
    summary="Upload a background music file",
    description=(
        "Validate an MP3, M4A, AAC, WAV, FLAC, OGG, OPUS, or WMA file up to "
        "30 MB and store it under an immutable UUID filename in storage/bgm."
    ),
    responses={
        400: {"description": "The filename, format, size, or audio stream is invalid"},
        500: {"description": "FFmpeg validation or persistent storage is unavailable"},
    },
)
def upload_bgm_file(request: Request, file: UploadFile = File(...)):
    request_id = base.get_task_id(request)
    try:
        safe_filename = bgm_service.save_bgm_upload(file.filename, file.file)
    except bgm_service.BgmUploadError as exc:
        # Upload failures can usually be fixed by the user choosing another file, so the request_id and a clear reason are logged,
        # but not the file content or absolute path, so logs don't leak user data.
        logger.warning(
            f"background music upload rejected: request_id={request_id}, error={str(exc)}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: {str(exc)}",
        )
    except bgm_service.BgmServiceError as exc:
        # Toolchain or storage failures are server-side problems and must not be disguised as user file errors. The log keeps
        # the request_id and internal reason, while the HTTP response only returns stable text, so server paths aren't exposed.
        logger.error(
            f"background music upload failed: request_id={request_id}, error={str(exc)}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message=f"{request_id}: background music validation is unavailable",
        )

    response = {"file": safe_filename}
    return utils.get_response(200, response)

@router.get(
    "/video_materials", response_model=VideoMaterialRetrieveResponse, summary="Retrieve local video materials"
)
def get_video_materials_list(request: Request):
    allowed_suffixes = material_upload_service.SUPPORTED_MATERIAL_EXTENSIONS
    local_videos_dir = utils.storage_dir("local_videos", create=True)
    video_materials_list = []
    with os.scandir(local_videos_dir) as entries:
        for entry in entries:
            if (
                entry.name.startswith(".")
                or pathlib.Path(entry.name).suffix.lower() not in allowed_suffixes
            ):
                continue
            try:
                # Do not follow links outside local_videos or list an upload
                # that disappeared while the directory was being scanned.
                if not entry.is_file(follow_symlinks=False):
                    continue
                size = entry.stat(follow_symlinks=False).st_size
            except OSError as exc:
                logger.warning(
                    f"skip unavailable local material: name={entry.name}, error={exc}"
                )
                continue
            video_materials_list.append(
                {"name": entry.name, "size": size, "file": entry.name}
            )
    # Keep ordered material selection stable across file systems and runs.
    video_materials_list.sort(key=lambda item: (item["name"].casefold(), item["name"]))
    response = {"files": video_materials_list}
    return utils.get_response(200, response)


@router.post(
    "/video_materials",
    response_model=VideoMaterialUploadResponse,
    summary="Upload the video material file to the local videos directory",
)
def upload_video_material_file(request: Request, file: UploadFile = File(...)):
    request_id = base.get_task_id(request)
    try:
        # Keep accepting browser-supplied client paths, but persist an immutable
        # UUID storage key so repeated names cannot overwrite queued task inputs.
        safe_filename = _sanitize_upload_filename(file.filename, request_id)
        stored_filename = material_upload_service.save_material_upload(
            safe_filename, file.file
        )
    except material_upload_service.MaterialUploadError as exc:
        logger.warning(
            f"local material upload rejected: request_id={request_id}, "
            f"error={str(exc)}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: {str(exc)}",
        )
    except material_upload_service.MaterialServiceError as exc:
        logger.error(
            f"local material upload failed: request_id={request_id}, "
            f"error={str(exc)}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message=f"{request_id}: local material validation is unavailable",
        )

    response = {"file": stored_filename}
    return utils.get_response(200, response)

@router.get("/stream/{file_path:path}")
@router.head("/stream/{file_path:path}", summary="Inspect video stream metadata")
async def stream_video(request: Request, file_path: str):
    request_id = base.get_task_id(request)
    tasks_dir = utils.task_dir()
    video_path = _resolve_path_within_directory(tasks_dir, file_path, request_id)
    range_header = request.headers.get("Range")
    if range_header and request.headers.get("If-Range") is not None:
        # This stream does not publish strong ETag/Last-Modified validators.
        # An unverifiable If-Range must fall back to the full representation,
        # so a client cannot combine old cached bytes with a new video tail.
        range_header = None
    # The body is produced after this handler returns. Open now so a task
    # deletion or replacement between headers and iteration cannot make the
    # stream fail or mismatch the size used for Content-Range.
    try:
        video_file = open(video_path, "rb")
    except FileNotFoundError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"{request_id}: file no longer exists",
        ) from exc
    try:
        video_size = os.fstat(video_file.fileno()).st_size
        if request.method == "HEAD":
            # Range applies to GET only. Close before returning metadata; no
            # generator or deferred background cleanup is needed for HEAD.
            video_file.close()
            return Response(
                media_type="video/mp4",
                headers={"Accept-Ranges": "bytes", "Content-Length": str(video_size)},
            )
        start, end = _parse_byte_range(range_header, video_size, request_id)
    except Exception:
        video_file.close()
        raise
    length = end - start + 1

    def file_iterator():
        try:
            video_file.seek(start, os.SEEK_SET)
            remaining = length
            while remaining > 0:
                data = video_file.read(min(4096, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data
        finally:
            video_file.close()

    response = StreamingResponse(
        file_iterator(),
        media_type="video/mp4",
        background=BackgroundTask(video_file.close),
    )
    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Content-Length"] = str(length)
    if range_header:
        response.headers["Content-Range"] = f"bytes {start}-{end}/{video_size}"
        response.status_code = 206  # Partial Content

    return response


@router.get("/download/{file_path:path}")
@router.head("/download/{file_path:path}", summary="Inspect artifact download metadata")
async def download_video(request: Request, file_path: str):
    """
    download video
    :param request: Request request
    :param file_path: video file path, eg: /cd1727ed-3473-42a2-a7da-4faafafec72b/final-1.mp4
    :return: video file
    """
    request_id = base.get_task_id(request)
    tasks_dir = utils.task_dir()
    video_path = _resolve_path_within_directory(tasks_dir, file_path, request_id)
    file_path = pathlib.Path(video_path)
    filename = file_path.name
    media_type, _ = mimetypes.guess_type(filename)
    stat_result = None
    if request.method == "HEAD":
        try:
            stat_result = os.stat(video_path)
        except FileNotFoundError as exc:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"{request_id}: file no longer exists",
            ) from exc
    response = FileResponse(
        path=video_path,
        filename=filename,
        media_type=media_type or "application/octet-stream",
        stat_result=stat_result,
    )
    if request.method == "HEAD":
        # Reuse FileResponse's metadata without reading its body or applying
        # GET-only Range processing to this HEAD request.
        return Response(headers=response.headers)
    return response
