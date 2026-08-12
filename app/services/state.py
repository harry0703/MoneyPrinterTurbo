import ast
import copy
import json
import math
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.config import config
from app.models import const


_PATCH_EXISTING_TASK_SCRIPT = """
if redis.call("EXISTS", KEYS[1]) == 0 then
    return 0
end

for index = 1, #ARGV, 2 do
    redis.call("HSET", KEYS[1], ARGV[index], ARGV[index + 1])
end

return 1
"""


@dataclass(frozen=True)
class IdempotentAcceptance:
    """Values required to atomically publish and queue one claimed task."""

    task_id: str
    params_hash: str
    owner_token: str
    task_fields: dict
    task_info: dict
    queue_capacity: int

    def task_record(self) -> dict:
        """Return the complete initial task hash written at acceptance."""
        return {
            "task_id": self.task_id,
            "state": self.task_fields.get("state", const.TASK_STATE_QUEUED),
            "progress": int(self.task_fields.get("progress", 0)),
            **self.task_fields,
        }

    def accepted_record(self) -> dict:
        """Return the durable idempotency record for accepted work."""
        return {
            "params_hash": self.params_hash,
            "phase": const.IDEMPOTENCY_PHASE_ACCEPTED,
            "owner_token": self.owner_token,
        }


def _pending_claim_matches(existing: dict | None, acceptance: IdempotentAcceptance):
    return (
        existing is not None
        and existing["phase"] == const.IDEMPOTENCY_PHASE_PENDING
        and existing["params_hash"] == acceptance.params_hash
        and existing["owner_token"] == acceptance.owner_token
    )


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
    def patch_task(self, task_id: str, **kwargs) -> bool:
        """只更新已有任务的指定字段；任务不存在时返回 False。"""
        pass

    @abstractmethod
    def delete_task(self, task_id: str):
        pass

    @abstractmethod
    def reserve_idempotent_task(
        self,
        task_id: str,
        params_hash: str,
        owner_token: str,
        lease_seconds: float = 5.0,
    ) -> str:
        """
        Atomically claim an idempotency key and its canonical parameters.

        Returns CREATED, PENDING, DUPLICATE, or CONFLICT.
        - created:   first valid request for this key; caller may enqueue work.
        - pending:   an identical request currently owns the short submit lease.
        - duplicate: identical work was atomically accepted; return its task id.
        - conflict:  the same key was used with different canonical parameters;
                     the caller must reject with HTTP 409.
        """
        pass

    @abstractmethod
    def get_idempotency(self, task_id: str):
        """Return the current pending/accepted record, or None if absent."""
        pass

    @abstractmethod
    def abort_idempotent_task(self, task_id: str, owner_token: str) -> bool:
        """Remove a pending claim only when owner_token still owns it."""
        pass

    @abstractmethod
    def accept_idempotent_task(
        self,
        acceptance: IdempotentAcceptance,
        task_manager,
    ) -> str:
        """Atomically publish a task, enqueue it, and accept its claim."""
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

    def reserve_idempotent_task(
        self,
        task_id: str,
        params_hash: str,
        owner_token: str,
        lease_seconds: float = 5.0,
    ) -> str:
        with self._lock:
            existing = self._idem.get(task_id)
            now = time.monotonic()
            if (
                existing is not None
                and existing["phase"] == const.IDEMPOTENCY_PHASE_PENDING
                and existing["expires_at"] <= now
            ):
                existing = None
                self._idem.pop(task_id, None)

            if existing is None:
                self._idem[task_id] = {
                    "params_hash": params_hash,
                    "phase": const.IDEMPOTENCY_PHASE_PENDING,
                    "owner_token": owner_token,
                    "expires_at": now + lease_seconds,
                }
                return const.IDEMPOTENCY_CREATED
            if existing["params_hash"] != params_hash:
                return const.IDEMPOTENCY_CONFLICT
            if existing["phase"] == const.IDEMPOTENCY_PHASE_ACCEPTED:
                return const.IDEMPOTENCY_DUPLICATE
            return const.IDEMPOTENCY_PENDING

    def get_idempotency(self, task_id: str):
        """Return a snapshot of a live claim, expiring stale pending claims."""
        with self._lock:
            existing = self._idem.get(task_id)
            if existing is None:
                return None
            if (
                existing["phase"] == const.IDEMPOTENCY_PHASE_PENDING
                and existing["expires_at"] <= time.monotonic()
            ):
                self._idem.pop(task_id, None)
                return None
            return {
                "params_hash": existing["params_hash"],
                "phase": existing["phase"],
                "owner_token": existing["owner_token"],
            }

    def abort_idempotent_task(self, task_id: str, owner_token: str) -> bool:
        with self._lock:
            existing = self._idem.get(task_id)
            if (
                existing is None
                or existing["phase"] != const.IDEMPOTENCY_PHASE_PENDING
                or existing["owner_token"] != owner_token
            ):
                return False
            self._idem.pop(task_id, None)
            return True

    def accept_idempotent_task(
        self,
        acceptance: IdempotentAcceptance,
        task_manager,
    ) -> str:
        """Accept under the memory state lock while the manager lock is held."""
        with self._lock:
            existing = self._idem.get(acceptance.task_id)
            if (
                not _pending_claim_matches(existing, acceptance)
                or existing["expires_at"] <= time.monotonic()
            ):
                return const.IDEMPOTENCY_STALE
            if task_manager.queue_size() >= acceptance.queue_capacity:
                return const.IDEMPOTENCY_QUEUE_FULL

            task_manager.enqueue_transaction(None, acceptance.task_info)
            self._tasks[acceptance.task_id] = acceptance.task_record()
            self._idem[acceptance.task_id] = {
                **acceptance.accepted_record(),
                "expires_at": float("inf"),
            }
            return const.IDEMPOTENCY_ACCEPTED


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
            # Redis 数据库中除了任务 Hash，还可能存在 RedisTaskManager 使用的
            # List 队列。只扫描 Hash 可以避免对队列执行 HGETALL 时触发
            # WRONGTYPE，同时保证 total 只统计真正的任务记录。
            cursor, keys = self._redis.scan(
                cursor,
                count=page_size,
                _type="HASH",
            )
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

    def patch_task(self, task_id: str, **kwargs) -> bool:
        if not kwargs:
            return False

        arguments = []
        for field, value in kwargs.items():
            arguments.extend((field, str(value)))

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
        self._redis.delete(task_id)

    def reserve_idempotent_task(
        self,
        task_id: str,
        params_hash: str,
        owner_token: str,
        lease_seconds: float = 5.0,
    ) -> str:
        idem_key = f"idem:{task_id}"
        pending = {
            "params_hash": params_hash,
            "phase": const.IDEMPOTENCY_PHASE_PENDING,
            "owner_token": owner_token,
        }
        lease_ms = max(1, math.ceil(lease_seconds * 1000))
        encoded = json.dumps(pending, sort_keys=True, separators=(",", ":"))

        while True:
            if self._redis.set(idem_key, encoded, nx=True, px=lease_ms):
                return const.IDEMPOTENCY_CREATED
            existing = self.get_idempotency(task_id)
            if existing is None:
                continue
            if existing["params_hash"] != params_hash:
                return const.IDEMPOTENCY_CONFLICT
            if existing["phase"] == const.IDEMPOTENCY_PHASE_ACCEPTED:
                return const.IDEMPOTENCY_DUPLICATE
            return const.IDEMPOTENCY_PENDING

    def get_idempotency(self, task_id: str):
        """Read and decode a Redis idempotency record."""
        value = self._redis.get(f"idem:{task_id}")
        if value is None:
            return None
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return json.loads(value)

    def abort_idempotent_task(self, task_id: str, owner_token: str) -> bool:
        from redis.exceptions import WatchError

        idem_key = f"idem:{task_id}"
        while True:
            with self._redis.pipeline() as pipe:
                try:
                    pipe.watch(idem_key)
                    existing = self._decode_idempotency(pipe.get(idem_key))
                    if (
                        existing is None
                        or existing["phase"] != const.IDEMPOTENCY_PHASE_PENDING
                        or existing["owner_token"] != owner_token
                    ):
                        pipe.unwatch()
                        return False
                    pipe.multi()
                    pipe.delete(idem_key)
                    pipe.execute()
                    return True
                except WatchError:
                    continue

    def accept_idempotent_task(
        self,
        acceptance: IdempotentAcceptance,
        task_manager,
    ) -> str:
        """Atomically write task, queue item, and accepted record in Redis."""
        from redis.exceptions import WatchError

        idem_key = f"idem:{acceptance.task_id}"
        encoded_task = {
            field: str(value) for field, value in acceptance.task_record().items()
        }
        accepted = json.dumps(
            acceptance.accepted_record(),
            sort_keys=True,
            separators=(",", ":"),
        )

        while True:
            with self._redis.pipeline() as pipe:
                try:
                    pipe.watch(
                        idem_key,
                        acceptance.task_id,
                        task_manager.queue,
                    )
                    raw = pipe.get(idem_key)
                    existing = self._decode_idempotency(raw)
                    if not _pending_claim_matches(existing, acceptance):
                        pipe.unwatch()
                        return const.IDEMPOTENCY_STALE
                    task_type = self._redis_type_name(pipe.type(acceptance.task_id))
                    queue_type = self._redis_type_name(pipe.type(task_manager.queue))
                    if task_type != "none":
                        pipe.unwatch()
                        return const.IDEMPOTENCY_STALE
                    if queue_type not in {"none", "list"}:
                        pipe.unwatch()
                        raise TypeError(
                            f"Redis queue key has unexpected type: {queue_type}"
                        )
                    if pipe.llen(task_manager.queue) >= acceptance.queue_capacity:
                        pipe.unwatch()
                        return const.IDEMPOTENCY_QUEUE_FULL

                    pipe.multi()
                    pipe.hset(acceptance.task_id, mapping=encoded_task)
                    task_manager.enqueue_transaction(pipe, acceptance.task_info)
                    pipe.set(
                        idem_key,
                        accepted,
                        ex=const.IDEMPOTENCY_ACCEPTED_TTL_SECONDS,
                    )
                    pipe.execute()
                    return const.IDEMPOTENCY_ACCEPTED
                except WatchError:
                    continue

    @staticmethod
    def _decode_idempotency(value):
        if value is None:
            return None
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return json.loads(value)

    @staticmethod
    def _redis_type_name(value) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")
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