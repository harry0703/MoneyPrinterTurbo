import ast
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.config import config
from app.models import const

TaskPayload = dict[str, Any]


@dataclass(slots=True)
class TaskSnapshot:
    task_id: str
    state: int
    progress: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> TaskPayload:
        return {
            "task_id": self.task_id,
            "state": self.state,
            "progress": self.progress,
            **self.extra,
        }


class BaseState(ABC):
    @abstractmethod
    def update_task(
        self,
        task_id: str,
        state: int = const.TASK_STATE_PROCESSING,
        progress: int = 0,
        **kwargs: Any,
    ) -> None:
        pass

    @abstractmethod
    def get_task(self, task_id: str) -> TaskPayload | None:
        pass

    @abstractmethod
    def get_all_tasks(self, page: int, page_size: int) -> tuple[list[TaskPayload], int]:
        pass


class MemoryState(BaseState):
    def __init__(self) -> None:
        self._tasks: dict[str, TaskSnapshot] = {}

    def get_all_tasks(self, page: int, page_size: int) -> tuple[list[TaskPayload], int]:
        start = (page - 1) * page_size
        end = start + page_size
        tasks = [task.to_dict() for task in self._tasks.values()]
        total = len(tasks)
        return tasks[start:end], total

    def update_task(
        self,
        task_id: str,
        state: int = const.TASK_STATE_PROCESSING,
        progress: int = 0,
        **kwargs: Any,
    ) -> None:
        progress = min(int(progress), 100)
        self._tasks[task_id] = TaskSnapshot(
            task_id=task_id,
            state=state,
            progress=progress,
            extra=kwargs,
        )

    def get_task(self, task_id: str) -> TaskPayload | None:
        task = self._tasks.get(task_id)
        return task.to_dict() if task else None

    def delete_task(self, task_id: str) -> None:
        if task_id in self._tasks:
            del self._tasks[task_id]


class RedisState(BaseState):
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
    ) -> None:
        import redis

        self._redis = redis.StrictRedis(host=host, port=port, db=db, password=password)

    def get_all_tasks(self, page: int, page_size: int) -> tuple[list[TaskPayload], int]:
        start = (page - 1) * page_size
        end = start + page_size
        tasks: list[TaskPayload] = []
        cursor = 0
        total = 0
        while True:
            cursor, keys = self._redis.scan(cursor, count=page_size)
            total += len(keys)
            if total > start:
                slice_start = max(0, start - total)
                slice_end = end - total
                for key in keys[slice_start:slice_end]:
                    task_data = self._redis.hgetall(key)
                    task = {
                        k.decode("utf-8"): self._convert_to_original_type(v)
                        for k, v in task_data.items()
                    }
                    tasks.append(task)
                    if len(tasks) >= page_size:
                        break
            if cursor == 0 or len(tasks) >= page_size:
                break
        return tasks, total

    def update_task(
        self,
        task_id: str,
        state: int = const.TASK_STATE_PROCESSING,
        progress: int = 0,
        **kwargs: Any,
    ) -> None:
        progress = min(int(progress), 100)

        fields: TaskPayload = {
            "task_id": task_id,
            "state": state,
            "progress": progress,
            **kwargs,
        }

        for field, value in fields.items():
            self._redis.hset(task_id, field, str(value))

    def get_task(self, task_id: str) -> TaskPayload | None:
        task_data = self._redis.hgetall(task_id)
        if not task_data:
            return None

        return {
            key.decode("utf-8"): self._convert_to_original_type(value)
            for key, value in task_data.items()
        }

    def delete_task(self, task_id: str) -> None:
        self._redis.delete(task_id)

    @staticmethod
    def _convert_to_original_type(value: bytes) -> Any:
        """
        Convert the value from byte string to its original data type.
        You can extend this method to handle other data types as needed.
        """
        value_str = value.decode("utf-8")

        try:
            return ast.literal_eval(value_str)
        except (ValueError, SyntaxError):
            pass

        if value_str.isdigit():
            return int(value_str)
        return value_str


_enable_redis = config.app.get("enable_redis", False)
_redis_host = config.app.get("redis_host", "localhost")
_redis_port = config.app.get("redis_port", 6379)
_redis_db = config.app.get("redis_db", 0)
_redis_password = config.app.get("redis_password", None)

state: BaseState = (
    RedisState(
        host=_redis_host, port=_redis_port, db=_redis_db, password=_redis_password
    )
    if _enable_redis
    else MemoryState()
)
