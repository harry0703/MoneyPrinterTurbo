import json
from typing import Any, Callable

import redis

from app.controllers.manager.base_manager import QueuedTask, TaskManager
from app.models.schema import VideoParams
from app.services import task as tm

FUNC_MAP: dict[str, Callable[..., Any]] = {
    "start": tm.start,
    # 'start_test': tm.start_test
}


class RedisTaskManager(TaskManager):
    def __init__(self, max_concurrent_tasks: int, redis_url: str) -> None:
        self.redis_client = redis.Redis.from_url(redis_url)
        super().__init__(max_concurrent_tasks)

    def create_queue(self) -> str:
        return "task_queue"

    def enqueue(self, task: QueuedTask) -> None:
        task_with_serializable_params: dict[str, Any] = {
            "func": task.func.__name__,
            "args": list(task.args),
            "kwargs": task.kwargs.copy(),
        }

        if "params" in task.kwargs and isinstance(task.kwargs["params"], VideoParams):
            task_with_serializable_params["kwargs"]["params"] = task.kwargs[
                "params"
            ].model_dump()

        self.redis_client.rpush(self.queue, json.dumps(task_with_serializable_params))

    def dequeue(self) -> QueuedTask | None:
        task_json = self.redis_client.lpop(self.queue)
        if task_json:
            task_info = json.loads(task_json)
            task_name = task_info["func"]
            task_func = FUNC_MAP[task_name]

            if "params" in task_info["kwargs"] and isinstance(
                task_info["kwargs"]["params"], dict
            ):
                task_info["kwargs"]["params"] = VideoParams(
                    **task_info["kwargs"]["params"]
                )

            return QueuedTask(
                func=task_func,
                args=tuple(task_info.get("args", [])),
                kwargs=task_info.get("kwargs", {}),
            )
        return None

    def is_queue_empty(self) -> bool:
        return self.redis_client.llen(self.queue) == 0
