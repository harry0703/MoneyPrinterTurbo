import threading
from typing import Any, Callable, Dict

from loguru import logger

from app.models import const


class TaskQueueFullError(ValueError):
    pass


class TaskManager:
    _DISPATCH_RETRY_SECONDS = 0.1

    def __init__(self, max_concurrent_tasks: int, max_queued_tasks: int = 100):
        self.max_concurrent_tasks = max_concurrent_tasks
        self.max_queued_tasks = max_queued_tasks
        self.current_tasks = 0
        self.lock = threading.Lock()
        self.queue = self.create_queue()
        self._dispatcher_lock = threading.Lock()
        self._dispatcher_wake = threading.Event()
        self._dispatcher_stop = threading.Event()
        self._dispatcher_thread = None
        self._pending_ack_lock = threading.Lock()
        self._pending_acknowledgements = []

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
        from app.services.state import IdempotentAcceptance

        task_info = {"func": func, "args": (), "kwargs": task_kwargs}
        with self.lock:
            available_slots = max(
                0, self.max_concurrent_tasks - self.current_tasks
            )
            queue_capacity = self.max_queued_tasks + available_slots
            try:
                acceptance = IdempotentAcceptance(
                    task_id=task_id,
                    params_hash=params_hash,
                    owner_token=owner_token,
                    task_fields=task_fields,
                    task_info=task_info,
                    queue_capacity=queue_capacity,
                )
                outcome = state.accept_idempotent_task(acceptance, self)
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
            self.start_dispatcher()
        return outcome

    def start_dispatcher(self):
        """Start the queue consumer and immediately drain recoverable work."""
        with self._dispatcher_lock:
            if self._dispatcher_thread and self._dispatcher_thread.is_alive():
                self._dispatcher_wake.set()
                return
            self._dispatcher_stop.clear()
            self._dispatcher_wake.clear()
            self._dispatcher_thread = threading.Thread(
                target=self._dispatch_loop,
                name="task-queue-dispatcher",
                daemon=True,
            )
            self._dispatcher_thread.start()
            self._dispatcher_wake.set()

    def wake_dispatcher(self):
        """Signal a running queue consumer that accepted work may be waiting."""
        self._dispatcher_wake.set()

    def stop_dispatcher(self):
        """Stop the queue consumer without interrupting active task workers."""
        with self._dispatcher_lock:
            thread = self._dispatcher_thread
            if thread is None:
                return
            self._dispatcher_stop.set()
            self._dispatcher_wake.set()
        if thread is not threading.current_thread():
            thread.join(timeout=2)
        with self._dispatcher_lock:
            if self._dispatcher_thread is thread and not thread.is_alive():
                self._dispatcher_thread = None

    def _dispatch_loop(self):
        while not self._dispatcher_stop.is_set():
            self._dispatcher_wake.wait(timeout=self._DISPATCH_RETRY_SECONDS)
            self._dispatcher_wake.clear()
            if self._dispatcher_stop.is_set():
                break
            try:
                self._retry_pending_acknowledgements()
                self.recover_expired_dispatches()
                self.check_queue()
            except Exception as exc:
                logger.exception(f"task dispatch failed; retrying queued work: {exc}")
                if not self._dispatcher_stop.wait(self._DISPATCH_RETRY_SECONDS):
                    self._dispatcher_wake.set()

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
                if task_info is None:
                    break
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
                try:
                    self.acknowledge_dispatch(task_info)
                except Exception as exc:
                    # The worker owns the reserved slot once thread.start()
                    # succeeds. Never requeue or release that slot merely
                    # because the backend acknowledgement was ambiguous.
                    logger.exception(
                        f"worker started but dispatch acknowledgement failed: {exc}"
                    )
                    self._defer_acknowledgement(task_info)
                    self.start_dispatcher()

    def task_done(self):
        with self.lock:
            self.current_tasks -= 1
        try:
            self.check_queue()
        except Exception as exc:
            logger.exception(f"task dispatch failed after worker completion: {exc}")
            self.start_dispatcher()

    def enqueue(self, task: Dict):
        raise NotImplementedError()

    def enqueue_transaction(self, pipeline, task: Dict):
        """Append a job through a backend transaction, or directly for memory."""
        if pipeline is not None:
            raise TypeError("this task manager does not support Redis transactions")
        self.enqueue(task)

    def requeue(self, task: Dict):
        """Restore a dequeued job after worker dispatch fails."""
        self.enqueue(task)

    def acknowledge_dispatch(self, task: Dict):
        """Remove backend dispatch bookkeeping after worker start succeeds."""

    def recover_expired_dispatches(self):
        """Return expired backend claims to the queue when supported."""

    def _defer_acknowledgement(self, task: Dict):
        with self._pending_ack_lock:
            self._pending_acknowledgements.append(task)

    def _retry_pending_acknowledgements(self):
        with self._pending_ack_lock:
            pending = list(self._pending_acknowledgements)
        for task in pending:
            try:
                self.acknowledge_dispatch(task)
            except Exception:
                continue
            with self._pending_ack_lock:
                if task in self._pending_acknowledgements:
                    self._pending_acknowledgements.remove(task)

    def dequeue(self):
        raise NotImplementedError()

    def is_queue_empty(self):
        raise NotImplementedError()

    def queue_size(self):
        raise NotImplementedError()
