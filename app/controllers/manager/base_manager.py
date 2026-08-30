"""后台任务并发调度的抽象基类。

并发名额在线程启动前预占，避免连续请求同时看到 current_tasks=0 而突破上限。
队列满时拒绝新任务，防止匿名接口无限堆积请求对象。
"""

import threading
from typing import Any, Callable, Dict

from loguru import logger


class TaskQueueFullError(ValueError):
    """并发已满且等待队列也已达到上限。"""


class TaskManager:
    """按最大并发数执行任务，超出部分进入有上限的等待队列。"""

    def __init__(self, max_concurrent_tasks: int, max_queued_tasks: int = 100):
        self.max_concurrent_tasks = max_concurrent_tasks
        self.max_queued_tasks = max_queued_tasks
        self.current_tasks = 0
        self.lock = threading.Lock()
        self.queue = self.create_queue()

    def create_queue(self):
        """由子类创建内存队列或 Redis 队列标识。"""
        raise NotImplementedError()

    def add_task(self, func: Callable, *args: Any, **kwargs: Any):
        """立即执行或入队；队列已满时抛出 ``TaskQueueFullError``。"""
        with self.lock:
            if self.current_tasks < self.max_concurrent_tasks:
                logger.info(
                    f"add task: {func.__name__}, current_tasks: {self.current_tasks}"
                )
                # 在线程启动前先预占并发名额。原实现在线程内部递增，连续请求
                # 可能都在子线程获得锁之前看到 current_tasks=0，从而突破并发
                # 上限。启动失败时回滚名额，让后续请求仍可正常调度。
                self.current_tasks += 1
                try:
                    self.execute_task(func, *args, **kwargs)
                except Exception:
                    self.current_tasks -= 1
                    raise
            else:
                queue_size = self.queue_size()
                # 并发数已满时才进入排队。队列必须有上限，否则匿名接口可以持续
                # 堆积任务对象和请求参数，最终造成内存耗尽或第三方 API 成本失控。
                if queue_size >= self.max_queued_tasks:
                    logger.warning(
                        f"reject task: {func.__name__}, queue_size: {queue_size}, "
                        f"max_queued_tasks: {self.max_queued_tasks}"
                    )
                    raise TaskQueueFullError("task queue is full, please try again later")

                logger.info(
                    f"enqueue task: {func.__name__}, current_tasks: {self.current_tasks}, "
                    f"queue_size: {queue_size}"
                )
                self.enqueue({"func": func, "args": args, "kwargs": kwargs})

    def execute_task(self, func: Callable, *args: Any, **kwargs: Any):
        thread = threading.Thread(
            target=self.run_task, args=(func, *args), kwargs=kwargs
        )
        thread.start()

    def run_task(self, func: Callable, *args: Any, **kwargs: Any):
        try:
            func(*args, **kwargs)
        finally:
            self.task_done()

    def check_queue(self):
        with self.lock:
            if (
                self.current_tasks < self.max_concurrent_tasks
                and not self.is_queue_empty()
            ):
                task_info = self.dequeue()
                if task_info is None:
                    # dequeue() 可能跳过并丢弃已不再通过当前校验的队列项
                    #（见 RedisTaskManager.dequeue）。即使刚才 is_queue_empty()
                    # 为 False，弹出后也可能已经没有可用任务。
                    return
                func = task_info["func"]
                args = task_info.get("args", ())
                kwargs = task_info.get("kwargs", {})
                # 与直接创建任务保持同一计数时机，避免刚出队的任务尚未在线程
                # 内计数时，又有新请求绕过队列占用同一个并发名额。
                self.current_tasks += 1
                try:
                    self.execute_task(func, *args, **kwargs)
                except Exception:
                    self.current_tasks -= 1
                    self.enqueue(task_info)
                    raise

    def task_done(self):
        with self.lock:
            self.current_tasks -= 1
        self.check_queue()

    def enqueue(self, task: Dict):
        raise NotImplementedError()

    def dequeue(self):
        raise NotImplementedError()

    def is_queue_empty(self):
        raise NotImplementedError()

    def queue_size(self):
        raise NotImplementedError()
