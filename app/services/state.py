import ast
import copy
import threading
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

    @abstractmethod
    def delete_task(self, task_id: str):
        pass

    @abstractmethod
    def reserve_idempotent_task(self, task_id: str, params_hash: str) -> str:
        """
        Atomically claim an idempotency key and its canonical parameters.

        Returns one of const.IDEMPOTENCY_CREATED / _DUPLICATE / _CONFLICT.
        - created:   first valid request for this key; caller may enqueue work.
        - duplicate: an identical prior submission exists; the caller must not
                     enqueue and should return the existing task id.
        - conflict:  the same key was used with different canonical parameters;
                     the caller must reject with HTTP 409.
        """
        pass

    @abstractmethod
    def clear_idempotency(self, task_id: str):
        """
        Drop any provisional idempotency reservation for task_id.

        Called when a reservation cannot be turned into enqueued work (e.g. the
        task queue is full) so a legitimate later retry can proceed.
        """
        pass


# Memory state management
class MemoryState(BaseState):
    def __init__(self):
        self._tasks = {}
        self._idem = {}
        self._lock = threading.RLock()

    def get_all_tasks(self, page: int, page_size: int):
        start = (page - 1) * page_size
        end = start + page_size
        with self._lock:
            tasks = [copy.deepcopy(task) for task in self._tasks.values()]
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

        with self._lock:
            self._tasks[task_id] = {
                "task_id": task_id,
                "state": state,
                "progress": progress,
                **kwargs,
            }

    def get_task(self, task_id: str):
        with self._lock:
            task = self._tasks.get(task_id, None)
            return copy.deepcopy(task) if task is not None else None

    def delete_task(self, task_id: str):
        with self._lock:
            self._tasks.pop(task_id, None)

    def reserve_idempotent_task(self, task_id: str, params_hash: str) -> str:
        with self._lock:
            existing = self._idem.get(task_id)
            if existing is None:
                self._idem[task_id] = params_hash
                return const.IDEMPOTENCY_CREATED
            if existing == params_hash:
                return const.IDEMPOTENCY_DUPLICATE
            return const.IDEMPOTENCY_CONFLICT

    def clear_idempotency(self, task_id: str):
        with self._lock:
            self._idem.pop(task_id, None)


# Redis state management
class RedisState(BaseState):
    """
    Redis-backed task state.

    Trust boundary: Redis is expected to be private to this application. Task
    values are written by MoneyPrinterTurbo and converted back from strings for
    compatibility with existing state records. Do not expose this Redis database
    to untrusted writers without replacing deserialization with a stricter
    schema-based format.
    """

    def __init__(self, host="localhost", port=6379, db=0, password=None):
        import redis

        self._redis = redis.StrictRedis(host=host, port=port, db=db, password=password)

    def get_all_tasks(self, page: int, page_size: int):
        start = (page - 1) * page_size
        end = start + page_size
        tasks = []
        cursor = 0
        total = 0
        while True:
            cursor, keys = self._redis.scan(cursor, count=page_size)
            # Idempotency reservations (idem:{task_id}) are STRING keys in the
            # same keyspace as task-record hashes. Drop them before counting or
            # materializing so the listing never HGETALLs a string (WRONGTYPE)
            # and the total reflects real task records only.
            keys = [
                k
                for k in keys
                if not (isinstance(k, bytes) and k.startswith(b"idem:"))
                and not (isinstance(k, str) and k.startswith("idem:"))
            ]
            batch_start = total
            batch_size = len(keys)
            total += batch_size

            # Redis SCAN 是分批返回 key。分页切片必须基于“当前批次起始索引”
            # 计算，而不能用累积后的 total 反推，否则第一页会切到空数组，
            # 第二页也可能只返回部分数据。
            if batch_start < end and total > start:
                slice_start = max(0, start - batch_start)
                slice_end = min(batch_size, end - batch_start)
                for key in keys[slice_start:slice_end]:
                    # Skip the idempotency reservation keys. They are STRING
                    # values (idem:{task_id}); HGETALL on a string raises
                    # WRONGTYPE and would break the listing. Task records are
                    # hashes, so only those are materialized.
                    if isinstance(key, bytes) and key.startswith(b"idem:"):
                        continue
                    if isinstance(key, str) and key.startswith("idem:"):
                        continue
                    task_data = self._redis.hgetall(key)
                    task = {
                        k.decode("utf-8"): self._convert_to_original_type(v)
                        for k, v in task_data.items()
                    }
                    tasks.append(task)

            # 即使当前页已经取满，也要继续 SCAN 到 cursor=0，
            # 因为调用方需要准确 total 来渲染分页信息。
            if cursor == 0:
                break
        return tasks, total

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

        fields = {
            "task_id": task_id,
            "state": state,
            "progress": progress,
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

    def reserve_idempotent_task(self, task_id: str, params_hash: str) -> str:
        # SET NX GET 是原子的：第一次写入返回 None（本请求赢得抢占，
        # 视为 created）；若该 key 已存在则返回旧值（其他请求已抢占）。
        # 用与任务记录同生命周期的 idem:{task_id} 记录规范的参数哈希，
        # 比较旧值即可区分 duplicate（参数一致）与 conflict（参数不同）。
        idem_key = f"idem:{task_id}"
        old = self._redis.set(
            idem_key, params_hash, nx=True, get=True, ex=86400
        )
        if old is None:
            return const.IDEMPOTENCY_CREATED
        old_value = old.decode("utf-8") if isinstance(old, bytes) else str(old)
        if old_value == params_hash:
            return const.IDEMPOTENCY_DUPLICATE
        return const.IDEMPOTENCY_CONFLICT

    def clear_idempotency(self, task_id: str):
        self._redis.delete(f"idem:{task_id}")

    @staticmethod
    def _convert_to_original_type(value):
        """
        Convert values written by this application back to common Python types.

        This compatibility parser assumes Redis is inside the application's
        trust boundary. If Redis can be written by untrusted clients, task state
        should move to a strict JSON/schema parser instead of open-ended literal
        conversion.
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
