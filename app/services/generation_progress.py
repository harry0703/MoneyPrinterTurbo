"""把不同供应商的长任务状态传给共享任务存储，不改变计费请求及重试策略。"""

import re
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar

from loguru import logger

from app.services import state as sm


_current = ContextVar("generation_progress", default=None)
_SUCCESS = {"succeeded", "completed", "success", "successful"}
_QUEUED = {"queued", "pending", "waiting", "created"}
_RUNNING = {"running", "processing", "in_progress", "executing", "active"}
_FAILED = {"failed", "error", "cancelled", "canceled", "expired"}
_IDENTIFIER = re.compile(r"^[\w.:-]{1,200}$")


class _Reporter:
    def __init__(self, task_id):
        self.task_id = task_id
        self.activity = {}
        self.lock = threading.RLock()
        self.last_log_at = 0

    def publish(self, phase, *, reset=False, **fields):
        # 状态展示属于辅助能力。Redis 短暂不可用不能中断已付费任务，也不能
        # 因异常重试而触发新的生成。这里只写白名单字段，不接收响应或下载 URL。
        try:
            with self.lock:
                now = time.time()
                previous = self.activity.get("phase")
                if (phase == previous == "downloading"
                        and now - self.activity.get("updated_at", 0) < 1):
                    return
                self.activity = {} if reset else dict(self.activity)
                self.activity.setdefault("started_at", now)
                self.activity.update(phase=phase, updated_at=now, **fields)
                sm.state.patch_task(self.task_id, generation_activity=self.activity)
                if previous != phase or now - self.last_log_at >= 30:
                    self.last_log_at = now
                    logger.info(
                        "generation activity: phase={}, provider={}, remote_id={}, elapsed={}s",
                        phase, self.activity.get("provider", ""),
                        self.activity.get("remote_id", ""),
                        int(max(0, now - self.activity["started_at"])),
                    )
        except Exception as exc:
            logger.debug("could not publish generation activity: {}", type(exc).__name__)


@contextmanager
def task_scope(task_id):
    token = _current.set(_Reporter(task_id))
    try:
        yield
    finally:
        _current.reset(token)


def stage(phase):
    reporter = _current.get()
    if reporter:
        reporter.publish(phase, reset=True)


def submitting(provider):
    reporter = _current.get()
    if reporter:
        reporter.publish("submitting", reset=True, provider=provider)


def remote(provider, task_id, status="", *, retrying=False):
    reporter = _current.get()
    if not reporter:
        return
    # 任务 ID 只用于排障。拒绝异常网关把完整 URL/凭据放进此字段。
    task_id = str(task_id or "")
    task_id = task_id if _IDENTIFIER.fullmatch(task_id) else ""
    status = str(status or "").strip().lower()
    phase = (
        "checking" if retrying or not status else
        "generated" if status in _SUCCESS else
        "remote_queued" if status in _QUEUED else
        "generating" if status in _RUNNING else "checking"
    )
    fields = {"provider": provider or reporter.activity.get("provider", ""),
              "remote_id": task_id, "retrying": retrying}
    if not retrying and status:
        fields["confirmed_at"] = time.time()
        # 只保留固定状态类别，不把网关的任意文本落到界面和日志。
        fields["remote_status"] = (
            "succeeded" if status in _SUCCESS else
            "queued" if status in _QUEUED else
            "running" if status in _RUNNING else
            "failed" if status in _FAILED else "unknown"
        )
    reporter.publish(phase, **fields)


def downloading(downloaded=0, total=0):
    reporter = _current.get()
    if reporter:
        reporter.publish("downloading", downloaded_bytes=downloaded, total_bytes=total)


def verifying():
    reporter = _current.get()
    if reporter:
        reporter.publish("verifying")
