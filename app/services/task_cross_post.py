"""Cross-post publishing subsystem for finished videos.

Handles background scheduling, the worker thread pool, per-process Future
tracking, startup recovery of interrupted publishes, and the actual calls
into YouTube/Upload-Post. Kept as its own module so the video-generation
pipeline in ``task.py`` stays focused on script/audio/subtitle/material/video
steps; ``task.py`` imports and re-exports everything here so
``task.<name>`` keeps working for every caller exactly as before the split.
"""

import ctypes
import os
import socket
import threading
import time
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import partial
from typing import Any
from uuid import uuid4

from loguru import logger

from app.config import config
from app.models import const
from app.models.schema import VideoParams
from app.services import llm, upload_post, webhook_notifier, youtube_upload
from app.services import state as sm

# 发布请求最长可等待数分钟，不能继续占用视频生成任务的并发名额。
# 固定大小的线程池将发布吞吐限制在可控范围内，同时让视频产物生成后
# 立即进入完成状态。
_cross_post_executor = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="mpt-cross-post",
)
_cross_post_max_pending_tasks = max(
    1,
    int(config.app.get("upload_post_max_pending_tasks", 10)),
)
_cross_post_slots = threading.BoundedSemaphore(_cross_post_max_pending_tasks)
_cross_post_registry_lock = threading.RLock()
_cross_post_futures: dict[str, Future] = {}
_cross_post_process_owner = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex}"
_ACTIVE_CROSS_POST_STATES = {
    const.CROSS_POST_STATE_PENDING,
    const.CROSS_POST_STATE_PROCESSING,
}
_CROSS_POST_STATE_WRITE_ATTEMPTS = 3
_CROSS_POST_STATE_RETRY_DELAY_SECONDS = 0.1
_INTERRUPTED_CROSS_POST_ERROR = (
    "cross-posting was interrupted before the process completed"
)
# Map upload-post platform ids to the social platform names llm.py accepts.
_CROSS_POST_SOCIAL_PLATFORMS = {
    "tiktok": "tiktok",
    "instagram": "instagram_reels",
    "facebook": "facebook_reels",
}
# 结果里区分渠道，任务查询可以直接看出失败发生在官方 YouTube 接口还是转发服务。
_UPLOAD_POST_RESULT_PLATFORM = "upload-post"


def _register_cross_post_future(task_id: str, future: Future) -> None:
    """登记当前进程持有的发布 Future，供启动恢复和测试判断真实运行状态。"""
    with _cross_post_registry_lock:
        _cross_post_futures[task_id] = future


def _unregister_cross_post_future(task_id: str, future: Future | None = None) -> None:
    """仅移除匹配的 Future，避免旧回调误删同任务后续注册的新工作。"""
    with _cross_post_registry_lock:
        current = _cross_post_futures.get(task_id)
        if current is None or (future is not None and current is not future):
            return
        _cross_post_futures.pop(task_id, None)


def _is_cross_post_active_in_process(task_id: str) -> bool:
    """判断当前进程是否仍持有未结束的发布任务。"""
    with _cross_post_registry_lock:
        future = _cross_post_futures.get(task_id)
        return future is not None and not future.done()


def _is_windows_process_alive(process_id: int) -> bool:
    """通过只读 Win32 API 判断进程状态，避免用 os.kill 误终止进程。"""

    process_query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5
    error_invalid_parameter = 87
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # ctypes 默认把未声明的返回值当作 32 位 int。Windows 64 位进程句柄可能
    # 因此被截断，必须显式声明 Win32 函数签名后再调用。
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(
        process_query_limited_information,
        False,
        process_id,
    )
    if not handle:
        error_code = ctypes.get_last_error()
        if error_code == error_invalid_parameter:
            return False
        if error_code == error_access_denied:
            # 进程存在但当前用户无查询权限时，必须保守地视为存活，避免错误
            # 回收其它账户正在执行的发布任务。
            return True
        logger.warning(
            "failed to open cross-post owner process on Windows, "
            f"process_id: {process_id}, error_code: {error_code}"
        )
        return True

    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            error_code = ctypes.get_last_error()
            logger.warning(
                "failed to read cross-post owner process state on Windows, "
                f"process_id: {process_id}, error_code: {error_code}"
            )
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _is_cross_post_owner_alive(owner: str | None) -> bool:
    """判断持久化发布任务的本机进程是否仍存在。"""
    if not owner:
        return False

    try:
        hostname, process_id_text, _ = owner.split(":", 2)
        process_id = int(process_id_text)
    except (TypeError, ValueError):
        logger.warning(f"invalid cross-post owner metadata: {owner}")
        return False

    # 无法可靠探测其它主机上的进程。共享 Redis 的多主机部署中必须保守地
    # 视为仍在运行，避免当前节点误删另一节点正在读取的视频文件。
    if hostname != socket.gethostname():
        return True

    # 当前进程内是否仍有真实发布工作，已经由 Future 注册表准确判断。运行到
    # 这里说明注册表中没有对应 Future，即使 owner 与当前进程完全一致，也应
    # 视为已中断；这可以覆盖终态写入持续失败、Future 已结束的场景。
    if process_id == os.getpid():
        return False

    # Windows 的 os.kill(pid, 0) 与 POSIX 语义不同，可能直接终止目标进程。
    # 使用只申请查询权限的 Win32 API，不向目标进程发送任何信号。
    if os.name == "nt":
        return _is_windows_process_alive(process_id)

    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        logger.warning(
            f"failed to inspect cross-post owner process, owner: {owner}, error: {exc}"
        )
        return True
    return True


def _patch_cross_post_state(task_id: str, **kwargs) -> bool | None:
    """安全更新发布字段；短暂状态后端故障时有限重试。"""
    for attempt in range(1, _CROSS_POST_STATE_WRITE_ATTEMPTS + 1):
        try:
            return sm.state.patch_task(task_id, **kwargs)
        except Exception as exc:
            # Redis 短暂断连不应让任务永久停留在 pending/processing。发布状态
            # 写入频率很低，这里使用固定次数和短等待即可覆盖瞬时故障，同时
            # 避免后台线程无限阻塞。最后一次失败保留完整堆栈便于定位。
            if attempt >= _CROSS_POST_STATE_WRITE_ATTEMPTS:
                logger.exception(
                    f"failed to update cross-post state after retries, "
                    f"task_id: {task_id}, fields: {', '.join(kwargs)}, "
                    f"attempts: {attempt}, error: {exc}"
                )
                return None

            logger.warning(
                f"retry cross-post state update, task_id: {task_id}, "
                f"fields: {', '.join(kwargs)}, attempt: {attempt}, error: {exc}"
            )
            time.sleep(_CROSS_POST_STATE_RETRY_DELAY_SECONDS)

    return None


def _record_cross_post_failure(
    task_id: str,
    error: Exception,
    results: list[dict] | None = None,
) -> None:
    """尽最大努力保存发布失败；状态后端不可用时由日志保留诊断信息。"""
    updated = _patch_cross_post_state(
        task_id,
        cross_post_state=const.CROSS_POST_STATE_FAILED,
        cross_post_results=results or None,
        cross_post_error=str(error),
        cross_post_owner=None,
    )
    if updated is False:
        logger.warning(f"discard cross-post failure for missing task: {task_id}")


def _ensure_cross_post_terminal_state(task_id: str) -> None:
    """Future 结束后把仍处于活动态的任务收敛为失败。"""
    try:
        task = sm.state.get_task(task_id)
    except Exception as exc:
        # 此处已经是 Future 的最终回调，没有后续同步调用方可以处理异常。
        # 状态后端恢复后，下一次进程启动仍会通过恢复逻辑处理遗留状态。
        logger.exception(
            f"failed to verify final cross-post state, task_id: {task_id}, error: {exc}"
        )
        return

    if not task or task.get("cross_post_state") not in _ACTIVE_CROSS_POST_STATES:
        return

    logger.warning(
        f"cross-post worker ended without terminal state, task_id: {task_id}, "
        f"state: {task.get('cross_post_state')}"
    )
    _record_cross_post_failure(
        task_id,
        RuntimeError("cross-post worker ended without persisting a terminal state"),
        task.get("cross_post_results"),
    )


def recover_interrupted_cross_posts(page_size: int = 100) -> int | None:
    """
    将进程重启后无法恢复的发布任务标记为失败。

    跨平台发布使用当前进程内的线程池，不是持久化任务队列。进程启动时，
    Redis 中残留的 pending/processing 不会自动继续执行；如果继续把它们视为
    运行中，用户将永久无法删除任务。这里分页扫描状态，只处理当前进程没有
    对应 Future 的活动记录，并保留已经生成的视频结果。
    """
    recovered = 0
    page = 1

    while True:
        try:
            tasks, total = sm.state.get_all_tasks(page, page_size)
        except Exception as exc:
            logger.exception(f"failed to recover interrupted cross-post tasks: {exc}")
            return None

        for task in tasks:
            task_id = str(task.get("task_id") or "")
            if (
                not task_id
                or task.get("cross_post_state") not in _ACTIVE_CROSS_POST_STATES
                or _is_cross_post_active_in_process(task_id)
                or _is_cross_post_owner_alive(task.get("cross_post_owner"))
            ):
                continue

            updated = _patch_cross_post_state(
                task_id,
                cross_post_state=const.CROSS_POST_STATE_FAILED,
                cross_post_error=_INTERRUPTED_CROSS_POST_ERROR,
                cross_post_owner=None,
            )
            if updated is True:
                recovered += 1

        if page * page_size >= total or not tasks:
            break
        page += 1

    if recovered:
        logger.warning(f"recovered interrupted cross-post tasks: {recovered}")
    return recovered


def _normalize_publish_result(
    result: object,
    platform: str,
    invalid_response_error: str,
) -> dict:
    """统一各渠道的发布结果，保证失败原因和目标渠道都能写入任务状态。"""
    if not isinstance(result, dict):
        return {
            "success": False,
            "platform": platform,
            "error": invalid_response_error,
        }
    if "platform" in result:
        return result
    return {**result, "platform": platform}


def _run_cross_post(
    task_id: str,
    video_paths: tuple[str, ...],
    video_subject: str,
    video_script: str,
    video_language: str,
    platforms: tuple[str, ...],
    publish_youtube: bool,
    youtube_privacy_status: str,
    youtube_title_override: str = "",
    youtube_description_override: str = "",
    youtube_tags_override: tuple[str, ...] = (),
    youtube_publish_offset_hours: float = 0.0,
) -> None:
    """后台执行跨平台发布，并只补充发布相关的任务字段。"""
    results = []
    try:
        state_updated = _patch_cross_post_state(
            task_id,
            cross_post_state=const.CROSS_POST_STATE_PROCESSING,
            cross_post_error=None,
            cross_post_owner=_cross_post_process_owner,
        )
        if state_updated is not True:
            # False 表示任务已删除，None 表示状态后端暂时不可用。两种情况都
            # 不应继续调用第三方接口，否则用户无法查询或控制这次发布。
            if state_updated is False:
                logger.warning(f"skip cross-post for missing task: {task_id}")
            else:
                _record_cross_post_failure(
                    task_id,
                    RuntimeError("failed to persist cross-post processing state"),
                )
            return

        targets = ([youtube_upload.PLATFORM] if publish_youtube else []) + list(
            platforms
        )
        logger.info(
            f"publishing started, task_id: {task_id}, targets: {', '.join(targets)}"
        )
        youtube_metadata: dict = {}
        post_title = video_subject or "Check out this video! #shorts #viral"
        # Título pré-configurado (agendamento ou geração avulsa) dispensa o
        # LLM pro YouTube; ainda assim ele roda se houver outras plataformas
        # em `platforms`, que sempre usam o texto gerado pra legenda/caption.
        have_youtube_override = publish_youtube and bool(youtube_title_override)
        needs_llm_metadata = bool(platforms) or (publish_youtube and not have_youtube_override)
        if needs_llm_metadata:
            # YouTube 走官方接口，其余平台仍由 Upload-Post 转发。只要目标里有
            # YouTube 就按 Shorts 规则生成一次文案，避免同一次任务出现两种风格。
            social_platform = "youtube_shorts"
            if not publish_youtube:
                first = (platforms[0] or "").strip().lower()
                # llm.py resolves unknown ids to its default platform.
                social_platform = _CROSS_POST_SOCIAL_PLATFORMS.get(first, first)
            metadata = llm.generate_social_metadata(
                video_subject=video_subject,
                video_script=video_script,
                language=video_language or "",
                platform=social_platform,
            )
            if publish_youtube and not have_youtube_override:
                youtube_metadata = {
                    "title": metadata.get("title") or video_subject,
                    "description": metadata.get("caption", ""),
                    "tags": metadata.get("hashtags", []),
                }
            post_title = (
                metadata.get("caption")
                or metadata.get("title")
                or video_subject
                or "Check out this video! #shorts #viral"
            )
        if have_youtube_override:
            youtube_metadata = {
                "title": youtube_title_override,
                "description": youtube_description_override,
                "tags": list(youtube_tags_override),
            }

        publish_at = None
        resolved_youtube_privacy = youtube_privacy_status
        if publish_youtube and youtube_publish_offset_hours > 0:
            publish_at = datetime.now() + timedelta(hours=youtube_publish_offset_hours)
            # publishAt só tem efeito com o vídeo private; sem isso o upload
            # publicaria na hora mesmo com um agendamento pedido.
            resolved_youtube_privacy = "private"

        for video_path in video_paths:
            if publish_youtube:
                youtube_title = youtube_metadata.get("title") or video_subject
                youtube_description = youtube_metadata.get("description", "")
                youtube_tags = youtube_metadata.get("tags", [])
                youtube_result = _normalize_publish_result(
                    youtube_upload.publish_video(
                        video_path=video_path,
                        title=youtube_title,
                        description=youtube_description,
                        tags=youtube_tags,
                        privacy_status=resolved_youtube_privacy,
                        publish_at=publish_at,
                    ),
                    youtube_upload.PLATFORM,
                    "YouTube returned an invalid response",
                )
                results.append(youtube_result)
                # publishAt agenda em private; o vídeo só fica público quando o
                # YouTube processar o agendamento, então não é "publicado" ainda.
                if youtube_result.get("success") and not publish_at:
                    webhook_notifier.notify_video_published(
                        task_id=task_id,
                        video_id=str(youtube_result.get("video_id") or ""),
                        url=str(youtube_result.get("url") or ""),
                        title=youtube_title,
                        description=youtube_description,
                        tags=list(youtube_tags),
                        privacy_status=str(
                            youtube_result.get("privacy_status")
                            or resolved_youtube_privacy
                        ),
                        video_subject=video_subject,
                        video_language=video_language,
                    )
            if platforms:
                results.append(
                    _normalize_publish_result(
                        upload_post.cross_post_video(
                            video_path=video_path,
                            title=post_title,
                            platforms=list(platforms),
                        ),
                        _UPLOAD_POST_RESULT_PLATFORM,
                        "Upload-Post returned an invalid response",
                    )
                )

        failures = [result for result in results if not result.get("success")]
        if failures:
            error_messages = [
                str(
                    result.get("error")
                    or result.get("message")
                    or "unknown upload error"
                )
                for result in failures
            ]
            cross_post_state = const.CROSS_POST_STATE_FAILED
            cross_post_error = "; ".join(error_messages)
            logger.warning(
                f"cross-post completed with failures, task_id: {task_id}, "
                f"failed: {len(failures)}, total: {len(results)}"
            )
        else:
            cross_post_state = const.CROSS_POST_STATE_COMPLETE
            cross_post_error = None
            logger.success(
                f"cross-post completed, task_id: {task_id}, videos: {len(results)}"
            )

        state_updated = _patch_cross_post_state(
            task_id,
            cross_post_state=cross_post_state,
            cross_post_results=results,
            cross_post_error=cross_post_error,
            cross_post_owner=None,
        )
        if state_updated is False:
            logger.warning(f"discard cross-post result for missing task: {task_id}")
        elif state_updated is None:
            # 上传已经结束但结果没有持久化时，不能继续保留 processing。
            # 失败状态写入会再次经过有限重试，至少让调用方得到明确终态。
            _record_cross_post_failure(
                task_id,
                RuntimeError("failed to persist final cross-post result"),
                results,
            )
    except Exception as exc:
        # 发布失败只影响发布状态，不能反向覆盖已经完成的视频任务。
        # 异常原文写入任务状态，API 调用方无需访问服务端日志也能定位问题。
        logger.exception(f"cross-post failed, task_id: {task_id}, error: {exc}")
        _record_cross_post_failure(task_id, exc, results)


def _run_cross_post_with_slot(*args) -> None:
    """执行发布任务，并确保成功、失败或异常时都会归还队列容量。"""
    try:
        _run_cross_post(*args)
    except Exception as exc:
        # _run_cross_post 已处理预期异常；这里是最后一道保护，避免未来新增
        # 逻辑抛出的异常只保存在无人读取的 Future 中。
        task_id = str(args[0]) if args else "unknown"
        logger.exception(f"cross-post worker crashed, task_id: {task_id}, error: {exc}")
        if args:
            _record_cross_post_failure(task_id, exc)
    finally:
        _cross_post_slots.release()


def _finalize_cross_post_future(task_id: str, future: Future) -> None:
    """清理 Future 注册，并确保取消、异常和状态写入失败都能收敛。"""
    _unregister_cross_post_future(task_id, future)

    try:
        error = future.exception()
    except CancelledError:
        logger.warning(f"cross-post future was cancelled, task_id: {task_id}")
        # Future 在开始执行前被取消时，worker 的 finally 不会运行，因此需要
        # 在回调中归还队列容量，并把持久化状态改为失败。
        _cross_post_slots.release()
        _record_cross_post_failure(
            task_id,
            RuntimeError("cross-post job was cancelled before execution"),
        )
        return
    except Exception as exc:
        logger.exception(
            f"failed to inspect cross-post future, task_id: {task_id}, error: {exc}"
        )
        _ensure_cross_post_terminal_state(task_id)
        return

    if error is not None:
        logger.error(
            f"cross-post future failed, task_id: {task_id}, "
            f"error: {type(error).__name__}: {error}"
        )

    _ensure_cross_post_terminal_state(task_id)


def _resolve_publish_targets(task_id: str) -> tuple[list[str], bool]:
    """
    解析本次任务的发布目标。

    YouTube 由官方 Data API v3 直接发布，Upload-Post 只负责其余平台。旧配置
    里残留的 ``youtube`` 会从转发列表中剔除，避免同一个成片被发布两次。
    """
    cross_post_enabled = (
        upload_post.upload_post_service.is_configured()
        and upload_post.upload_post_service.auto_upload
    )
    configured = (
        [
            str(platform or "").strip().lower()
            for platform in upload_post.upload_post_service.platforms
        ]
        if cross_post_enabled
        else []
    )
    platforms = [
        platform
        for platform in configured
        if platform and not platform.startswith("youtube")
    ]
    if cross_post_enabled and not configured:
        logger.warning(
            f"skip cross-post because no platforms are configured, task_id: {task_id}"
        )
    elif len(platforms) != len(configured):
        logger.info(
            f"youtube is published through the official API instead of "
            f"upload-post, task_id: {task_id}"
        )

    youtube_service = youtube_upload.youtube_upload_service
    publish_youtube = youtube_service.is_configured() and youtube_service.auto_upload

    return platforms, publish_youtube


def _schedule_cross_post(
    task_id: str,
    video_paths: list[str],
    params: VideoParams,
    video_script: str,
    platforms: list[str],
    publish_youtube: bool,
    youtube_privacy_status: str,
) -> str | None:
    """提交后台发布任务；成功返回 None，调度失败返回可查询的错误原因。"""
    if not _cross_post_slots.acquire(blocking=False):
        error = "cross-post queue is full; publishing was skipped"
        logger.warning(
            f"skip cross-post because queue is full, task_id: {task_id}, "
            f"capacity: {_cross_post_max_pending_tasks}"
        )
        _patch_cross_post_state(
            task_id,
            cross_post_state=const.CROSS_POST_STATE_FAILED,
            cross_post_error=error,
            cross_post_owner=None,
        )
        return error

    try:
        future = _cross_post_executor.submit(
            _run_cross_post_with_slot,
            task_id,
            tuple(video_paths),
            params.video_subject or "",
            video_script,
            params.video_language or "",
            tuple(platforms),
            publish_youtube,
            youtube_privacy_status,
            params.youtube_title_override or "",
            params.youtube_description_override or "",
            tuple(params.youtube_tags_override or ()),
            params.youtube_publish_offset_hours or 0.0,
        )
        _register_cross_post_future(task_id, future)
        future.add_done_callback(partial(_finalize_cross_post_future, task_id))
    except RuntimeError as exc:
        _unregister_cross_post_future(task_id)
        _cross_post_slots.release()
        logger.exception(
            f"failed to schedule cross-post, task_id: {task_id}, error: {exc}"
        )
        _patch_cross_post_state(
            task_id,
            cross_post_state=const.CROSS_POST_STATE_FAILED,
            cross_post_error=f"failed to schedule cross-post: {exc}",
            cross_post_owner=None,
        )
        return f"failed to schedule cross-post: {exc}"

    return None


def _upload_youtube_review_drafts(
    task_id: str,
    video_paths: tuple[str, ...],
    video_subject: str,
    video_script: str,
    video_language: str,
    title_override: str,
    description_override: str,
    tags_override: tuple[str, ...],
) -> None:
    """
    Sobe cada vídeo do task como rascunho "private" no YouTube pra revisão.

    Ao contrário do fluxo normal de cross-post, aqui não existe ``publishAt``:
    o vídeo fica parado em private até o usuário confirmar (ou editar) título/
    descrição/tags via ``youtube_upload.update_video_metadata`` e escolher
    publicar agora ou agendar, no endpoint de revisão.
    """
    have_override = bool(title_override)
    metadata: dict = {}
    if not have_override:
        try:
            metadata = llm.generate_social_metadata(
                video_subject=video_subject,
                video_script=video_script,
                language=video_language or "",
                platform="youtube_shorts",
            )
        except Exception as exc:
            logger.warning(
                f"failed to draft youtube review metadata via LLM, "
                f"falling back to the subject: task_id: {task_id}, error: {exc}"
            )

    title = title_override or metadata.get("title") or video_subject or "Untitled video"
    description = description_override or metadata.get("caption", "")
    tags = list(tags_override) if tags_override else metadata.get("hashtags", [])

    drafts = []
    for video_path in video_paths:
        result = youtube_upload.publish_video(
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            privacy_status="private",
        )
        drafts.append(
            {
                "video_path": video_path,
                "success": bool(result.get("success")),
                "video_id": result.get("video_id"),
                "url": result.get("url"),
                "error": result.get("error"),
                "title": title,
                "description": description,
                "tags": tags,
            }
        )

    all_uploaded = all(draft["success"] for draft in drafts)
    if all_uploaded:
        logger.success(
            f"youtube review drafts uploaded, task_id: {task_id}, "
            f"videos: {len(drafts)}"
        )
    else:
        logger.warning(
            f"some youtube review drafts failed to upload, task_id: {task_id}"
        )
    _patch_cross_post_state(
        task_id,
        youtube_review_state=(
            const.YOUTUBE_REVIEW_STATE_PENDING
            if all_uploaded
            else const.YOUTUBE_REVIEW_STATE_FAILED
        ),
        youtube_review_drafts=drafts,
    )


def schedule_youtube_review(
    task_id: str,
    video_paths: list[str],
    params: VideoParams,
    video_script: str,
) -> None:
    """
    Agenda o upload dos rascunhos de revisão em background.

    Reaproveita o mesmo executor do cross-post normal (capacidade já limitada
    a 2 workers); não disputa o semáforo de fila porque a revisão é um upload
    simples, sem os riscos de repetição/custo do fluxo de publicação paga.
    """
    _cross_post_executor.submit(
        _upload_youtube_review_drafts,
        task_id,
        tuple(video_paths),
        params.video_subject or "",
        video_script,
        params.video_language or "",
        params.youtube_title_override or "",
        params.youtube_description_override or "",
        tuple(params.youtube_tags_override or ()),
    )


def confirm_youtube_review(
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    publish_at: Any = None,
    privacy_status: str | None = None,
) -> dict:
    """
    Confirma (com edição opcional) o rascunho de revisão do YouTube de uma task.

    Chamada tanto pelo endpoint HTTP (``POST /tasks/{id}/publish-youtube``)
    quanto diretamente pela WebUI, que roda em processo separado da API e
    mexe direto no estado da task em vez de se auto-chamar por HTTP.

    ``publish_at`` agenda via publishAt nativo (mantém private); sem ele,
    publica de vez com ``privacy_status`` (padrão "public").
    """
    task = sm.state.get_task(task_id)
    if not task:
        return {"success": False, "error": "task not found"}

    drafts = task.get("youtube_review_drafts") or []
    if task.get("youtube_review_state") != const.YOUTUBE_REVIEW_STATE_PENDING or not drafts:
        return {"success": False, "error": "no pending YouTube review for this task"}

    resolved_privacy = "private" if publish_at else (privacy_status or "public")

    results = []
    for draft in drafts:
        video_id = draft.get("video_id")
        if not draft.get("success") or not video_id:
            continue
        result = youtube_upload.update_video_metadata(
            video_id=video_id,
            title=title,
            description=description,
            tags=tags,
            privacy_status=resolved_privacy,
            publish_at=publish_at,
        )
        results.append(result)
        # Agendado (publishAt) fica private até o YouTube publicar sozinho;
        # só notifica quando o vídeo já sai público/unlisted nesta chamada.
        if result.get("success") and resolved_privacy != "private":
            webhook_notifier.notify_video_published(
                task_id=task_id,
                video_id=str(result.get("video_id") or video_id),
                url=str(result.get("url") or ""),
                title=str(title if title is not None else draft.get("title") or ""),
                description=str(
                    description if description is not None else draft.get("description") or ""
                ),
                tags=list(tags if tags is not None else draft.get("tags") or []),
                privacy_status=str(result.get("privacy_status") or resolved_privacy),
            )

    all_ok = bool(results) and all(result.get("success") for result in results)
    new_review_state = (
        (
            const.YOUTUBE_REVIEW_STATE_SCHEDULED
            if publish_at
            else const.YOUTUBE_REVIEW_STATE_PUBLISHED
        )
        if all_ok
        else const.YOUTUBE_REVIEW_STATE_FAILED
    )
    sm.state.patch_task(
        task_id,
        youtube_review_state=new_review_state,
        youtube_review_results=results,
    )
    if not all_ok:
        logger.warning(f"failed to confirm YouTube review, task_id: {task_id}")
    return {
        "success": all_ok,
        "youtube_review_state": new_review_state,
        "results": results,
    }
