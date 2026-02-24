import threading
from dataclasses import dataclass
from typing import Any, Callable


TaskCallable = Callable[..., Any]


@dataclass(slots=True)
class QueuedTask:
    func: TaskCallable
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


class TaskManager:
    def __init__(self, max_concurrent_tasks: int) -> None:
        self.max_concurrent_tasks = max_concurrent_tasks
        self.current_tasks = 0
        self.lock = threading.Lock()
        self.queue = self.create_queue()

    def create_queue(self) -> Any:
        raise NotImplementedError()

    def add_task(self, func: TaskCallable, *args: Any, **kwargs: Any) -> None:
        with self.lock:
            if self.current_tasks < self.max_concurrent_tasks:
                print(f"add task: {func.__name__}, current_tasks: {self.current_tasks}")
                self.execute_task(func, *args, **kwargs)
            else:
                print(
                    f"enqueue task: {func.__name__}, current_tasks: {self.current_tasks}"
                )
                self.enqueue(QueuedTask(func=func, args=args, kwargs=kwargs))

    def execute_task(self, func: TaskCallable, *args: Any, **kwargs: Any) -> None:
        thread = threading.Thread(
            target=self.run_task, args=(func, *args), kwargs=kwargs
        )
        thread.start()

    def run_task(self, func: TaskCallable, *args: Any, **kwargs: Any) -> None:
        try:
            with self.lock:
                self.current_tasks += 1
            func(*args, **kwargs)  # call the function here, passing *args and **kwargs.
        finally:
            self.task_done()

    def check_queue(self) -> None:
        with self.lock:
            if (
                self.current_tasks < self.max_concurrent_tasks
                and not self.is_queue_empty()
            ):
                task_info = self.dequeue()
                if task_info is None:
                    return
                self.execute_task(task_info.func, *task_info.args, **task_info.kwargs)

    def task_done(self) -> None:
        with self.lock:
            self.current_tasks -= 1
        self.check_queue()

    def enqueue(self, task: QueuedTask) -> None:
        raise NotImplementedError()

    def dequeue(self) -> QueuedTask | None:
        raise NotImplementedError()

    def is_queue_empty(self) -> bool:
        raise NotImplementedError()
