import copy
import hashlib
import json
import threading
import time
from collections import deque
from dataclasses import asdict

from loguru import logger

from app.config import config
from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.models import const
from app.models.schema import VideoParams
from app.services import state as sm
from app.services import task as tm
from app.services import codex_image, jalapeno_video, volcengine_seedance
from app.services.loomloom import LoomLoomConfirmedVideoRequest
from app.utils.logging_utils import (
    format_log_record,
    log_scope_thread_id,
    runtime_log_filter,
)


# WebUI 的配置保存在进程级全局字典中。原来的同步实现会在完整生成期间持有
# runtime_config_lock，因此不同浏览器会话实际上也是串行执行。这里把并发数固定
# 为 1，既延续原有配置一致性，也避免多个线程只是在配置锁外无意义地等待。
_task_manager = InMemoryTaskManager(
    max_concurrent_tasks=1,
    max_queued_tasks=max(1, int(config.app.get("max_queued_tasks", 100))),
)
_task_logs: dict[str, deque[str]] = {}
_task_logs_lock = threading.RLock()
_MAX_LOG_TASKS = 20
_MAX_LOG_RECORDS_PER_TASK = 1000
_submission_lock = threading.RLock()
_active_submissions: dict[str, str] = {}
# Streamlit 无法由后台线程直接推送组件更新，只能通过 Fragment 轮询。0.5 秒
# 足以让 WebUI 日志接近终端实时输出，又不会像高频刷新那样持续占用浏览器资源。
TASK_LOG_REFRESH_INTERVAL_SECONDS = 0.5


def is_generation_active(task_id: str) -> bool:
    """以后台预占名额为准，覆盖入队及状态发布之间的窗口。"""
    with _submission_lock:
        return task_id in _active_submissions.values()


def _submission_signature(
    params, references, request, endpoint, preview, codex_image_context=None
):
    # 仅保留摘要，不保存凭据或上传内容。不同 Key/模型/输入是不同请求，
    # 相同内容在完成后允许再次生成；只合并仍在排队或执行的重复提交。
    request_inputs = asdict(request) if request is not None else None
    if request_inputs is not None:
        # 两个标签页会为相同报价输入各自生成一个幂等 ID；它不是内容差异。
        # 保留账号、模型、输入行和报价版本，以首个已确认请求继续执行。
        request_inputs.pop("client_request_id", None)
    payload = {
        "params": params.model_dump(mode="json", warnings=False),
        "settings": {
            name: config.snapshot_config_with_pending(getattr(config, name))
            for name in ("app", "azure", "elevenlabs", "siliconflow", "chatterbox")
        },
        "references": [hashlib.sha256(value or b"").hexdigest() for value in references],
        "request": request_inputs,
        "endpoint": asdict(endpoint) if endpoint is not None else None,
        # 配音来源会改变实际输出；暂存路径随本地任务 ID 变化，不属于输入差异。
        "voice_preview": {
            key: preview[key]
            for key in ("script", "voice_name", "voice_rate", "voice_volume", "duration", "params", "audio_digest")
            if key in preview
        } if preview else None,
    }
    if codex_image_context is not None:
        payload["codex_image"] = asdict(codex_image_context)
    if preview and not preview.get("audio_digest"):
        # 旧调用方没有内容摘要时，不能仅凭同一时长推断两个文件相同。
        # 不在校验前读取任意路径；宁可保留不同文件的独立请求。
        payload["voice_preview"]["audio_file"] = preview.get("audio_file")
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def _append_task_log(task_id: str, message: str) -> None:
    """按任务保存有限数量的日志，供 Streamlit Fragment 安全轮询。"""
    with _task_logs_lock:
        records = _task_logs.get(task_id)
        if records is None:
            # 只保留最近任务的日志，避免 WebUI 服务长时间运行后持续占用内存。
            # dict 保持插入顺序；任务日志仅用于界面诊断，淘汰最早记录不影响任务。
            if len(_task_logs) >= _MAX_LOG_TASKS:
                oldest_task_id = next(iter(_task_logs))
                _task_logs.pop(oldest_task_id, None)
            records = deque(maxlen=_MAX_LOG_RECORDS_PER_TASK)
            _task_logs[task_id] = records
        records.append(message.rstrip())


def get_task_logs(task_id: str) -> list[str]:
    """返回日志快照，避免页面渲染期间持有后台线程使用的锁。"""
    with _task_logs_lock:
        return list(_task_logs.get(task_id, ()))


def _run_generation(
    task_id: str,
    params: VideoParams,
    capture_logs: bool,
    voice_preview: dict | None = None,
    loomloom_video_request: LoomLoomConfirmedVideoRequest | None = None,
    voxcpm_reference_audio: bytes | None = None,
    voxcpm_prompt_audio: bytes | None = None,
    voxcpm_prompt_text: str = "",
    jalapeno_video_endpoint: volcengine_seedance.SeedanceEndpoint | None = None,
    codex_image_context: codex_image.CodexImageContext | None = None,
) -> dict:
    """
    在后台线程中执行现有视频流水线。

    Loguru 的 sink 是进程级资源，因此必须按当前工作线程过滤。否则同时运行的
    API 任务或其它页面日志会混入当前任务。任务为下载、片段编码和心跳启动的
    辅助线程通过 bind_log_scope 归属到工作线程，它们的日志同样要收集，否则
    这些耗时阶段在 WebUI 里没有任何输出。页面只读取普通列表快照，不会从后台
    线程访问 Streamlit session_state，从根源上避免刷新时的 delta 路径错乱。
    """
    log_handler_id = None
    worker_thread_id = threading.get_ident()
    try:
        if capture_logs:
            log_handler_id = logger.add(
                lambda message: _append_task_log(task_id, str(message)),
                level=0,
                format=format_log_record,
                colorize=False,
                filter=lambda record: (
                    log_scope_thread_id(record["thread"].id) == worker_thread_id
                    and runtime_log_filter(record)
                ),
            )

        # 完整任务仍使用原来的配置锁，防止另一个 WebUI 会话在生成中途修改
        # Provider、密钥等进程级配置，造成同一条视频前后使用不同设置。
        with config.runtime_config_lock():
            return tm.start(
                task_id=task_id,
                params=params,
                voice_preview=voice_preview,
                loomloom_video_request=loomloom_video_request,
                voxcpm_reference_audio=voxcpm_reference_audio,
                voxcpm_prompt_audio=voxcpm_prompt_audio,
                voxcpm_prompt_text=voxcpm_prompt_text,
                **({"codex_image_context": codex_image_context}
                   if codex_image_context is not None else {}),
                **({"jalapeno_video_endpoint": jalapeno_video_endpoint}
                   if jalapeno_video_endpoint is not None else {}),
            )
    except Exception as exc:
        # tm.start 已负责把流水线异常转换成失败状态；这里额外保护日志 sink、
        # 配置锁等 WebUI 包装层。任何后台线程异常都必须留下终态，不能让任务
        # 管理器在工作线程退出后仍永久显示“生成中”。
        error = f"{type(exc).__name__}: {exc}"
        failure = {
            "task_id": task_id,
            "state": const.TASK_STATE_FAILED,
            "progress": 0,
            "failed_stage": "webui_worker",
            "error": error,
        }
        sm.state.update_task(
            task_id,
            state=failure["state"],
            progress=failure["progress"],
            failed_stage=failure["failed_stage"],
            error=failure["error"],
        )
        logger.exception(
            f"unexpected WebUI generation worker failure, "
            f"task_id={task_id}, error={exc}"
        )
        return failure
    finally:
        with _submission_lock:
            for signature, active_id in list(_active_submissions.items()):
                if active_id == task_id:
                    del _active_submissions[signature]
        if log_handler_id is not None:
            try:
                logger.remove(log_handler_id)
            except ValueError:
                logger.debug(
                    f"WebUI task log handler already removed: task_id={task_id}"
                )


def submit_generation(
    task_id: str,
    params: VideoParams,
    capture_logs: bool = True,
    voice_preview: dict | None = None,
    loomloom_video_request: LoomLoomConfirmedVideoRequest | None = None,
    voxcpm_reference_audio: bytes | None = None,
    voxcpm_prompt_audio: bytes | None = None,
    voxcpm_prompt_text: str = "",
    jalapeno_video_endpoint: volcengine_seedance.SeedanceEndpoint | None = None,
) -> str:
    """
    登记并提交 WebUI 视频生成任务，调用后立即返回。

    任务状态必须在线程启动前写入。这样页面本次脚本执行结束时即可查询到任务，
    浏览器刷新或 WebSocket 重连也不依赖旧页面内存中的占位符。
    """
    task_params = params.model_copy(deep=True)
    # The subtitle timeline and nested preview parameters remain mutable in
    # Streamlit session state. Snapshot them before this job enters the queue.
    voice_preview_snapshot = copy.deepcopy(voice_preview) if voice_preview else None
    # Reference audio belongs only to this queued request. It is deliberately
    # separate from VideoParams so it cannot reach task history, presets, state
    # persistence, or logs. ``bytes`` is immutable; make an explicit snapshot
    # before the background worker starts so later WebUI reruns cannot share
    # mutable upload state with this task.
    voxcpm_reference_audio_snapshot = (
        bytes(voxcpm_reference_audio) if voxcpm_reference_audio else None
    )
    voxcpm_prompt_audio_snapshot = (
        bytes(voxcpm_prompt_audio) if voxcpm_prompt_audio else None
    )
    voxcpm_prompt_text_snapshot = str(voxcpm_prompt_text or "")
    # 已确认请求是冻结的数据对象，只在当前进程内传递。API Key 不会进入
    # VideoParams、任务状态、日志或落盘历史，也不会受后续页面 rerun 影响。
    loomloom_request_snapshot = loomloom_video_request
    # 排队期间允许准备下一条内容，但已确认的付费配置不能随全局表单变化。
    # 快照的密钥不参与 repr，仅随进程内任务参数传递，不写入 VideoParams。
    if task_params.video_source == "jalapeno" and jalapeno_video_endpoint is None:
        jalapeno_video_endpoint = jalapeno_video.endpoint(
            config.snapshot_config_with_pending(config.app)
        )
    codex_image_context = (
        codex_image.capture_context(config.snapshot_config_with_pending(config.app))
        if task_params.video_source == "codex_image"
        else None
    )
    signature = _submission_signature(
        task_params,
        (
            voxcpm_reference_audio_snapshot,
            voxcpm_prompt_audio_snapshot,
            voxcpm_prompt_text_snapshot.encode(),
        ),
        loomloom_request_snapshot,
        jalapeno_video_endpoint,
        voice_preview_snapshot,
        codex_image_context,
    )
    # 同一锁内查重并预占，两个标签页同时点击也只会真正入队一次。
    with _submission_lock:
        existing = _active_submissions.get(signature)
        if existing:
            return existing
        if task_id in _active_submissions.values():
            return task_id
        _active_submissions[signature] = task_id
    try:
        _enqueue_generation(
            task_id,
            task_params,
            capture_logs,
            voice_preview_snapshot,
            loomloom_request_snapshot,
            voxcpm_reference_audio_snapshot,
            voxcpm_prompt_audio_snapshot,
            voxcpm_prompt_text_snapshot,
            jalapeno_video_endpoint,
            codex_image_context,
        )
    except Exception:
        with _submission_lock:
            if _active_submissions.get(signature) == task_id:
                del _active_submissions[signature]
        raise
    return task_id


def _enqueue_generation(
    task_id,
    task_params,
    capture_logs,
    voice_preview_snapshot,
    loomloom_request_snapshot,
    voxcpm_reference_audio_snapshot,
    voxcpm_prompt_audio_snapshot,
    voxcpm_prompt_text_snapshot,
    jalapeno_video_endpoint,
    codex_image_context=None,
):
    submitted_at = time.time()
    sm.state.update_task(
        task_id,
        state=const.TASK_STATE_PROCESSING,
        progress=0,
        video_subject=task_params.video_subject or task_params.video_script or task_id,
        generation_submitted_at=submitted_at,
        generation_activity={"phase": "queued", "started_at": submitted_at,
                             "updated_at": submitted_at},
    )
    try:
        _task_manager.add_task(
            _run_generation,
            task_id=task_id,
            params=task_params,
            capture_logs=capture_logs,
            voice_preview=voice_preview_snapshot,
            loomloom_video_request=loomloom_request_snapshot,
            voxcpm_reference_audio=voxcpm_reference_audio_snapshot,
            voxcpm_prompt_audio=voxcpm_prompt_audio_snapshot,
            voxcpm_prompt_text=voxcpm_prompt_text_snapshot,
            **({"codex_image_context": codex_image_context}
               if codex_image_context is not None else {}),
            **({"jalapeno_video_endpoint": jalapeno_video_endpoint}
               if jalapeno_video_endpoint is not None else {}),
        )
    except Exception as exc:
        # 调度失败与流水线失败一样必须成为可查询状态，避免任务管理器永久显示
        # “生成中”。保留异常类型便于从 Docker 或本机日志快速定位队列问题。
        error = f"{type(exc).__name__}: {exc}"
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_FAILED,
            progress=0,
            failed_stage="scheduling",
            error=error,
        )
        logger.exception(
            f"failed to submit WebUI generation task, task_id={task_id}, error={exc}"
        )
        raise
