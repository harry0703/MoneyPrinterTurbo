import threading
from typing import Any, Callable, Dict

from loguru import logger

from app.models import const


class TaskQueueFullError(ValueError):
    pass


class TaskManager:
    def __init__(self, max_concurrent_tasks: int, max_queued_tasks: int = 100):
        self.max_concurrent_tasks = max_concurrent_tasks
        self.max_queued_tasks = max_queued_tasks
        self.current_tasks = 0
        self.lock = threading.Lock()
        self.queue = self.create_queue()

    def create_queue(self):
        raise NotImplementedError()

    def add_task(self, func: Callable, *args: Any, **kwargs: Any):
        with self.lock:
            if self.current_tasks < self.max_concurrent_tasks:
                logger.info(
                    f"add task: {func.__name__}, current_tasks: {self.current_tasks}"
                )
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

    def submit_idempotent(
        self,
        state,
        task_id: str,
        params_hash: str,
        owner_token: str,
        task_fields: dict,
        func: Callable,
        task_kwargs: dict,
    ) -> str:
        """Atomically accept idempotent work before attempting worker dispatch."""
        task_info = {"func": func, "args": (), "kwargs": task_kwargs}
        with self.lock:
            available_slots = max(
                0, self.max_concurrent_tasks - self.current_tasks
            )
            queue_capacity = self.max_queued_tasks + available_slots
            try:
                outcome = state.accept_idempotent_task(
                    task_id=task_id,
                    params_hash=params_hash,
                    owner_token=owner_token,
                    task_fields=task_fields,
                    task_info=task_info,
                    task_manager=self,
                    queue_capacity=queue_capacity,
                )
            except Exception:
                state.abort_idempotent_task(task_id, owner_token)
                raise

        if outcome == const.IDEMPOTENCY_QUEUE_FULL:
            state.abort_idempotent_task(task_id, owner_token)
            return outcome
        if outcome != const.IDEMPOTENCY_ACCEPTED:
            return outcome

        try:
            self.check_queue()
        except Exception as exc:
            # Acceptance is already durable. check_queue restores the item when
            # thread creation fails, so the caller may safely receive success.
            logger.exception(
                f"accepted task remains queued after dispatch failure: {task_id}: {exc}"
            )
        return outcome

    def execute_task(self, func: Callable, *args: Any, **kwargs: Any):
        thread = threading.Thread(
            target=self.run_task, args=(func, *args), kwargs=kwargs
        )
        thread.start()

    def run_task(self, func: Callable, *args: Any, **kwargs: Any):
        try:
            func(*args, **kwargs)  # call the function here, passing *args and **kwargs.
        finally:
            self.task_done()

    def check_queue(self):
        with self.lock:
            while (
                self.current_tasks < self.max_concurrent_tasks
                and not self.is_queue_empty()
            ):
                task_info = self.dequeue()
                func = task_info["func"]
                args = task_info.get("args", ())
                kwargs = task_info.get("kwargs", {})
                self.current_tasks += 1
                try:
                    self.execute_task(func, *args, **kwargs)
                except Exception:
                    self.current_tasks -= 1
                    self.requeue(task_info)
                    raise

    def task_done(self):
        with self.lock:
            self.current_tasks -= 1
        self.check_queue()

    def enqueue(self, task: Dict):
        raise NotImplementedError()

    def enqueue_transaction(self, pipeline, task: Dict):
        if pipeline is not None:
            raise TypeError("this task manager does not support Redis transactions")
        self.enqueue(task)

    def requeue(self, task: Dict):
        self.enqueue(task)

    def dequeue(self):
        raise NotImplementedError()

    def is_queue_empty(self):
        raise NotImplementedError()

    def queue_size(self):
        raise NotImplementedError()
