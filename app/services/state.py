import ast
from abc import ABC, abstractmethod

from app.config import config
from app.models import const


# Base class for state management
class BaseState(ABC):
    @abstractmethod
    def update_task(self, task_id: str, state: int, progress: int = 0, **kwargs):
        pass

    @abstractmethod
    def get_task(self, task_id: str):
        pass

    @abstractmethod
    def get_all_tasks(self, page: int, page_size: int):
        pass


# Memory state management
class MemoryState(BaseState):
    def __init__(self):
        self._tasks = {}
        self._task_sequence_counter = 0

    def get_all_tasks(self, page: int, page_size: int):
        start = (page - 1) * page_size
        end = start + page_size
        tasks = list(self._tasks.values())
        # Sort tasks by status priority first (Running > Pending > Others), then by sequence_number
        tasks.sort(key=lambda x: (
            x.get("state", 0) != const.TASK_STATE_PROCESSING,
            x.get("state", 0) != const.TASK_STATE_PENDING,
            x.get("sequence_number", 0)
        ))
        total = len(tasks)
        return tasks[start:end], total

    def update_task(
        self,
        task_id: str,
        state: int = const.TASK_STATE_PROCESSING,
        progress: int = 0,** kwargs,
    ):
        progress = int(progress)
        if progress > 100:
            progress = 100

        # Merge with existing task data to preserve fields like task_type
        existing_task = self._tasks.get(task_id, {})
        
        # Add sequence number for new tasks
        if not existing_task:
            self._task_sequence_counter += 1
            sequence_number = self._task_sequence_counter
        else:
            sequence_number = existing_task.get("sequence_number", self._task_sequence_counter)
        
        self._tasks[task_id] = {
            **existing_task,  # Preserve existing fields
            "task_id": task_id,
            "state": state,
            "progress": progress,
            "sequence_number": sequence_number,** kwargs,
        }

    def get_task(self, task_id: str):
        return self._tasks.get(task_id, None)

    def delete_task(self, task_id: str):
        if task_id in self._tasks:
            del self._tasks[task_id]


# Redis state management
class RedisState(BaseState):
    def __init__(self, host="localhost", port=6379, db=0, password=None):
        import redis

        self._redis = redis.StrictRedis(host=host, port=port, db=db, password=password)
        self._sequence_counter_key = "task_sequence_counter"

    def get_all_tasks(self, page: int, page_size: int):
        start = (page - 1) * page_size
        end = start + page_size
        tasks = []
        cursor = 0
        while True:
            cursor, keys = self._redis.scan(cursor, count=page_size)
            for key in keys:
                task_data = self._redis.hgetall(key)
                task = {
                    k.decode("utf-8"): self._convert_to_original_type(v) for k, v in task_data.items()
                }
                tasks.append(task)
            if cursor == 0:
                break
        # Sort tasks by status priority first (Running > Pending > Others), then by sequence_number
        tasks.sort(key=lambda x: (
            x.get("state", 0) != const.TASK_STATE_PROCESSING,
            x.get("state", 0) != const.TASK_STATE_PENDING,
            x.get("sequence_number", 0)
        ))
        total = len(tasks)
        return tasks[start:end], total

    def update_task(
        self,
        task_id: str,
        state: int = const.TASK_STATE_PROCESSING,
        progress: int = 0,
        **kwargs,
    ):
        progress = int(progress)
        if progress > 100:
            progress = 100

        # Check if task already exists
        existing_task_data = self._redis.hgetall(task_id)
        is_new_task = not existing_task_data
        
        # Get sequence number for new tasks
        if is_new_task:
            sequence_number = self._redis.incr(self._sequence_counter_key)
        else:
            existing_seq_num = self._redis.hget(task_id, "sequence_number")
            sequence_number = int(existing_seq_num.decode("utf-8")) if existing_seq_num else self._redis.get(self._sequence_counter_key)
            if sequence_number is None:
                sequence_number = 1

        fields = {
            "task_id": task_id,
            "state": state,
            "progress": progress,
            "sequence_number": sequence_number,
            **kwargs,
        }

        for field, value in fields.items():
            self._redis.hset(task_id, field, str(value))

    def get_task(self, task_id: str):
        task_data = self._redis.hgetall(task_id)
        if not task_data:
            return None

        task = {
            key.decode("utf-8"): self._convert_to_original_type(value)
            for key, value in task_data.items()
        }
        return task

    def delete_task(self, task_id: str):
        self._redis.delete(task_id)

    @staticmethod
    def _convert_to_original_type(value):
        """
        Convert the value from byte string to its original data type.
        You can extend this method to handle other data types as needed.
        """
        value_str = value.decode("utf-8")

        try:
            # try to convert byte string array to list
            return ast.literal_eval(value_str)
        except (ValueError, SyntaxError):
            pass

        if value_str.isdigit():
            return int(value_str)
        # Add more conversions here if needed
        return value_str


# Global task running state
_is_task_running = False
_task_type = None  # Can be 'video_generation' or 'scene_integration'
_task_id = None  # Current running task ID

# Global state
_enable_redis = config.app.get("enable_redis", False)
_redis_host = config.app.get("redis_host", "localhost")
_redis_port = config.app.get("redis_port", 6379)
_redis_db = config.app.get("redis_db", 0)
_redis_password = config.app.get("redis_password", None)

state = (
    RedisState(
        host=_redis_host, port=_redis_port, db=_redis_db, password=_redis_password
    )
    if _enable_redis
    else MemoryState()
)


def is_task_running():
    """Check if any task is running"""
    global _is_task_running
    return _is_task_running


def get_running_task_type():
    """Get the type of the currently running task"""
    global _task_type
    return _task_type


def get_running_task_id():
    """Get the ID of the currently running task"""
    global _task_id
    return _task_id


def set_task_running(task_type, task_id=None):
    """Set task as running"""
    global _is_task_running, _task_type, _task_id
    _is_task_running = True
    _task_type = task_type
    _task_id = task_id


def set_task_completed():
    """Set task as completed"""
    global _is_task_running, _task_type, _task_id
    _is_task_running = False
    _task_type = None
    _task_id = None
