import ast
import copy
import threading
from abc import ABC, abstractmethod

from redis.exceptions import ResponseError
from itertools import islice

from app.config import config
from app.models import const


_PATCH_EXISTING_TASK_SCRIPT = """
-- Match discovery/get_task ownership checks inside the same atomic operation.
-- Other services and our queue may share this database or reuse a deleted key.
if redis.call("TYPE", KEYS[1]).ok ~= "hash" then
    return 0
end
if redis.call("HGET", KEYS[1], "task_id") ~= KEYS[1] then
    return 0
end

for index = 1, #ARGV, 2 do
    redis.call("HSET", KEYS[1], ARGV[index], ARGV[index + 1])
end

return 1
"""


_DELETE_OWNED_TASK_SCRIPT = """
if redis.call("TYPE", KEYS[1]).ok ~= "hash" then
    return 0
end
if redis.call("HGET", KEYS[1], "task_id") ~= KEYS[1] then
    return 0
end

return redis.call("DEL", KEYS[1])
"""


# A queue worker writes its task record only while its running-slot token is
# still recorded as the owner of that task. Checking the owner and writing in
# one script means a worker that was declared gone cannot change, or re-create,
# the record afterwards.
_WRITE_OWNED_TASK_SCRIPT = """
if redis.call("HGET", KEYS[2], ARGV[1]) ~= KEYS[1] then
    return -1
end
if ARGV[2] == "1" then
    if redis.call("TYPE", KEYS[1]).ok ~= "hash" then
        return 0
    end
    if redis.call("HGET", KEYS[1], "task_id") ~= KEYS[1] then
        return 0
    end
end

for index = 3, #ARGV, 2 do
    redis.call("HSET", KEYS[1], ARGV[index], ARGV[index + 1])
end

return 1
"""


# The caller listed this slot as expired a moment ago. Everything it relied on
# is read again here, in the operation that writes the failure: the slot may
# have been released or renewed, and the task may have finished, in between.
_FAIL_TASK_OF_EXPIRED_SLOT_SCRIPT = """
if redis.call("HGET", KEYS[3], ARGV[1]) ~= KEYS[1] then
    return -1
end
local deadline = redis.call("ZSCORE", KEYS[2], ARGV[1])
if deadline and tonumber(deadline) > tonumber(ARGV[2]) then
    return -1
end

local failed = 0
if redis.call("TYPE", KEYS[1]).ok == "hash"
    and redis.call("HGET", KEYS[1], "task_id") == KEYS[1]
    and redis.call("HGET", KEYS[1], "state") == ARGV[3] then
    for index = 4, #ARGV, 2 do
        redis.call("HSET", KEYS[1], ARGV[index], ARGV[index + 1])
    end
    failed = 1
end

redis.call("HDEL", KEYS[3], ARGV[1])
redis.call("ZREM", KEYS[2], ARGV[1])
return failed
"""


class TaskOwnershipLostError(RuntimeError):
    """The worker's running slot no longer owns the task it tried to write."""


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
    def list_task_ids(self, scan_count: int = 100) -> list[str]:
        """获取一次遍历中的任务 ID，供启动恢复等全量操作使用。"""
        pass

    @abstractmethod
    def patch_task(self, task_id: str, **kwargs) -> bool:
        """只更新已有任务的指定字段；任务不存在时返回 False。"""
        pass

    def bind_task_owner(self, task_id: str, owners_key: str, token: str):
        """Tie this process's writes to a running-slot token.

        Only a backend shared with other processes has a worker to fence off,
        so the default does nothing.
        """

    def unbind_task_owner(self, task_id: str):
        pass


# Memory state management
class MemoryState(BaseState):
    def __init__(self):
        self._tasks = {}
        self._lock = threading.RLock()

    def get_all_tasks(self, page: int, page_size: int):
        start = (page - 1) * page_size
        end = start + page_size
        with self._lock:
            total = len(self._tasks)
            tasks = [
                copy.deepcopy(task)
                for task in islice(self._tasks.values(), start, end)
            ]
        return tasks, total

    def list_task_ids(self, scan_count: int = 100) -> list[str]:
        with self._lock:
            return list(self._tasks)

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
                # Keep fields from earlier pipeline stages, matching Redis
                # HSET updates. A progress-only update must not erase the
                # WebUI subject or diagnostic details already stored.
                **self._tasks.get(task_id, {}),
                "task_id": task_id,
                "state": state,
                "progress": progress,
                **copy.deepcopy(kwargs),
            }

    def get_task(self, task_id: str):
        with self._lock:
            task = self._tasks.get(task_id, None)
            return copy.deepcopy(task) if task is not None else None

    def patch_task(self, task_id: str, **kwargs) -> bool:
        # 异步发布只应补充发布状态，不能覆盖已经保存的视频、字幕等结果。
        # 在同一把锁内完成存在性判断和字段合并，也可避免任务删除后
        # 被后台线程重建。
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.update(copy.deepcopy(kwargs))
            return True

    def delete_task(self, task_id: str):
        with self._lock:
            self._tasks.pop(task_id, None)


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

    # task_id -> (owners_key, token) for the tasks this process is running from
    # the Redis queue. Pipeline stages write from several threads, so the
    # binding belongs to the process, not to a thread.
    _task_owners: dict = {}

    def bind_task_owner(self, task_id: str, owners_key: str, token: str):
        """Make this process's writes to ``task_id`` depend on its slot token."""
        self._task_owners[task_id] = (owners_key, token)

    def unbind_task_owner(self, task_id: str):
        self._task_owners.pop(task_id, None)

    def _write_owned_task(self, task_id: str, fields: dict, existing_only: bool):
        """Write through the owner check; return None when no owner is bound."""
        owner = self._task_owners.get(task_id)
        if owner is None:
            return None
        owners_key, token = owner
        arguments = []
        for field, value in fields.items():
            arguments.extend((field, self._serialize_field(field, value)))
        return self._redis.eval(
            _WRITE_OWNED_TASK_SCRIPT,
            2,
            task_id,
            owners_key,
            token,
            "1" if existing_only else "0",
            *arguments,
        )

    def fail_task_of_expired_slot(
        self,
        task_id: str,
        slots_key: str,
        owners_key: str,
        token: str,
        now_ms: int,
        **fields,
    ) -> bool | None:
        """Fail ``task_id`` if its slot is still expired and it is still running.

        Returns True when the task was failed, False when the slot was dropped
        but the task had already reached a final state, and None when the slot
        is no longer expired (released, renewed or reassigned meanwhile).
        """
        arguments = []
        for field, value in fields.items():
            arguments.extend((field, self._serialize_field(field, value)))
        outcome = self._redis.eval(
            _FAIL_TASK_OF_EXPIRED_SLOT_SCRIPT,
            3,
            task_id,
            slots_key,
            owners_key,
            token,
            now_ms,
            self._serialize_field("state", const.TASK_STATE_PROCESSING),
            *arguments,
        )
        return None if outcome == -1 else bool(outcome)

    def get_all_tasks(self, page: int, page_size: int):
        start = (page - 1) * page_size
        end = start + page_size
        # 每一页都以同一套确定性顺序切片，而不是依赖 SCAN 的返回顺序。
        # 这仍不是并发增删任务时的事务快照；无索引时优先保证静态任务集
        # 的分页正确性，并让 total 统计去重后的任务键。
        task_ids = self.list_task_ids(scan_count=page_size)
        tasks = []
        for task_id in task_ids[start:end]:
            task = self.get_task(task_id)
            if task is not None:
                tasks.append(task)
        return tasks, len(task_ids)

    def list_task_ids(self, scan_count: int = 100) -> list[str]:
        """Return only this application's task hashes from a possibly shared DB."""
        task_keys = set()
        cursor = 0
        while True:
            # Redis 数据库中除了任务 Hash，还可能存在 RedisTaskManager 使用的
            # List 队列。只扫描 Hash 可以避免对队列执行 HGETALL 时触发
            # WRONGTYPE。COUNT 是扫描工作量提示，不保证每批返回的数量。
            cursor, keys = self._redis.scan(
                cursor,
                count=scan_count,
                _type="HASH",
            )
            # Redis db 0 may also contain hashes belonging to other services.
            # Check the task marker in one pipelined round trip per SCAN batch;
            # exposing all HASH keys here can leak their fields through /tasks.
            candidates = [key for key in dict.fromkeys(keys) if key not in task_keys]
            if candidates:
                with self._redis.pipeline(transaction=False) as pipeline:
                    for key in candidates:
                        pipeline.hget(key, "task_id")
                    # A key can change type after SCAN. Isolate that row instead
                    # of letting one WRONGTYPE abort the whole task listing.
                    embedded_ids = pipeline.execute(raise_on_error=False)
                for key, embedded_id in zip(candidates, embedded_ids):
                    if isinstance(embedded_id, ResponseError):
                        if str(embedded_id).startswith("WRONGTYPE"):
                            continue
                        raise embedded_id
                    if embedded_id == key:
                        task_keys.add(key)
            if cursor == 0:
                break
        # 按任务键排序不依赖 Hash 扫描顺序；不额外维护索引，也不改变旧任务。
        return [key.decode("utf-8") for key in sorted(task_keys)]

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

        owned = self._write_owned_task(task_id, fields, existing_only=False)
        if owned is not None:
            if owned == -1:
                raise TaskOwnershipLostError(
                    f"running slot no longer owns task {task_id}"
                )
            return

        # One HSET writes the whole task state atomically. Separate commands
        # could expose a new state with the previous progress or result fields
        # to readers, and leave a partially updated record on network failure.
        self._redis.hset(
            task_id,
            mapping={
                field: self._serialize_field(field, value)
                for field, value in fields.items()
            },
        )

    def get_task(self, task_id: str):
        try:
            task_data = self._redis.hgetall(task_id)
        except ResponseError as exc:
            # Arbitrary task IDs can name the application's List queue or
            # another service's non-hash key. Those are not task records.
            if str(exc).startswith("WRONGTYPE"):
                return None
            raise
        # An API caller may ask for any Redis key by name. Require the same
        # marker as list_task_ids before returning a hash's contents.
        if not task_data or task_data.get(b"task_id") != task_id.encode("utf-8"):
            return None

        task = {
            key.decode("utf-8"): (
                value.decode("utf-8")
                if key == b"task_id"
                else self._convert_to_original_type(value)
            )
            for key, value in task_data.items()
        }
        return task

    def patch_task(self, task_id: str, **kwargs) -> bool:
        if not kwargs:
            return False

        owned = self._write_owned_task(task_id, kwargs, existing_only=True)
        if owned is not None:
            # A worker that lost its slot is told what a deleted task would
            # tell it: there is no record for it to add to.
            return owned == 1

        arguments = []
        for field, value in kwargs.items():
            arguments.extend((field, self._serialize_field(field, value)))

        # EXISTS 和 HSET 如果分成两条命令，后台发布线程与删除请求并发时，
        # HSET 可能在删除后重新创建一条残缺任务。Lua 脚本由 Redis 原子执行，
        # 可以保证任务不存在时不写入，且不会改变现有字段之外的数据。
        updated = self._redis.eval(
            _PATCH_EXISTING_TASK_SCRIPT,
            1,
            task_id,
            *arguments,
        )
        return bool(updated)

    def delete_task(self, task_id: str):
        # 调用方读取任务后还会清理目录，同名键可能在这段时间被其它服务复用。
        # 在一次 Lua 操作内检查类型、任务标记并删除，避免检查与删除之间的竞态。
        self._redis.eval(_DELETE_OWNED_TASK_SCRIPT, 1, task_id)

    @staticmethod
    def _serialize_field(field, value):
        # Quote strings so literal_eval cannot turn a subject like "2026" or
        # an error like "None" into an integer/None. Keep the ownership marker
        # raw: task discovery compares its bytes directly against the Redis key.
        if isinstance(value, str) and field != "task_id":
            return repr(value)
        return str(value)

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
