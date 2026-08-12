import threading
from collections import deque

from loguru import logger

from app.config import config
from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.models import const
from app.models.schema import VideoParams
from app.services import state as sm
from app.services import task as tm
from app.utils.logging_utils import format_log_record


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
# Streamlit 无法由后台线程直接推送组件更新，只能通过 Fragment 轮询。0.5 秒
# 足以让 WebUI 日志接近终端实时输出，又不会像高频刷新那样持续占用浏览器资源。
TASK_LOG_REFRESH_INTERVAL_SECONDS = 0.5


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
) -> dict:
    """
    在后台线程中执行现有视频流水线。

    Loguru 的 sink 是进程级资源，因此必须按当前工作线程过滤。否则同时运行的
    API 任务或其它页面日志会混入当前任务。页面只读取普通列表快照，不会从后台
    线程访问 Streamlit session_state，从根源上避免刷新时的 delta 路径错乱。
    """
    log_handler_id = None
    worker_thread_id = threading.get_ident()
    try:
        if capture_logs:
            log_handler_id = logger.add(
                lambda message: _append_task_log(task_id, str(message)),
                level="DEBUG",
                format=format_log_record,
                colorize=False,
                filter=lambda record: record["thread"].id == worker_thread_id,
            )

        # 完整任务仍使用原来的配置锁，防止另一个 WebUI 会话在生成中途修改
        # Provider、密钥等进程级配置，造成同一条视频前后使用不同设置。
        with config.runtime_config_lock():
            return tm.start(
                task_id=task_id,
                params=params,
                voice_preview=voice_preview,
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
) -> None:
    """
    登记并提交 WebUI 视频生成任务，调用后立即返回。

    任务状态必须在线程启动前写入。这样页面本次脚本执行结束时即可查询到任务，
    浏览器刷新或 WebSocket 重连也不依赖旧页面内存中的占位符。
    """
    task_params = params.model_copy(deep=True)
    # 预览载荷只包含不可变音频路径、参数快照和只读字幕时间轴。复制外层字典，
    # 避免页面后续 rerun 替换缓存字段时影响已经提交到后台队列的任务。
    voice_preview_snapshot = dict(voice_preview) if voice_preview else None
    sm.state.update_task(
        task_id,
        state=const.TASK_STATE_PROCESSING,
        progress=0,
        video_subject=task_params.video_subject or task_params.video_script or task_id,
    )
    try:
        _task_manager.add_task(
            _run_generation,
            task_id=task_id,
            params=task_params,
            capture_logs=capture_logs,
            voice_preview=voice_preview_snapshot,
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
