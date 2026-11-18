import inspect
import json
import threading
import time
from typing import Dict
from uuid import uuid4

import redis
from loguru import logger
from pydantic import ValidationError

from app.controllers.manager.base_manager import TaskManager, TaskQueueFullError
from app.models import const
from app.models.schema import AudioRequest, SubtitleRequest, VideoParams
from app.services import state as sm
from app.services import task as tm

FUNC_MAP = {
    "start": tm.start,
    # 'start_test': tm.start_test
}

_ADMIT_QUEUED_TASK_SCRIPT = """
if redis.call("LLEN", KEYS[1]) >= tonumber(ARGV[1]) then
    return 0
end
redis.call("RPUSH", KEYS[1], ARGV[2])
return 1
"""

# Running slots are stored separately from the persisted queue. A sorted set
# gives every slot a lease deadline, so a crashed worker cannot consume global
# capacity forever. Active workers renew their own member periodically.
_ADMIT_TASK_SCRIPT = """
redis.call("ZREMRANGEBYSCORE", KEYS[2], "-inf", ARGV[1])
local running = redis.call("ZCARD", KEYS[2])
local queued = redis.call("LLEN", KEYS[1])
if running < tonumber(ARGV[2]) and queued == 0 then
    redis.call("ZADD", KEYS[2], ARGV[3], ARGV[4])
    return 1
end
if queued >= tonumber(ARGV[5]) then
    return -1
end
redis.call("RPUSH", KEYS[1], ARGV[6])
return 0
"""

_CLAIM_QUEUED_TASK_SCRIPT = """
redis.call("ZREMRANGEBYSCORE", KEYS[2], "-inf", ARGV[1])
if redis.call("ZCARD", KEYS[2]) >= tonumber(ARGV[2]) then
    return nil
end
local task = redis.call("LPOP", KEYS[1])
if not task then
    return nil
end
redis.call("ZADD", KEYS[2], ARGV[3], ARGV[4])
return task
"""

_RENEW_RUNNING_SLOT_SCRIPT = """
if redis.call("ZSCORE", KEYS[1], ARGV[1]) then
    redis.call("ZADD", KEYS[1], "XX", ARGV[2], ARGV[1])
    return 1
end
return 0
"""

_RUNNING_SLOT_LEASE_SECONDS = 90.0
_RUNNING_SLOT_HEARTBEAT_SECONDS = 30.0
_QUEUE_DISPATCH_RETRY_SECONDS = 5.0


class RedisTaskManager(TaskManager):
    def __init__(
        self,
        max_concurrent_tasks: int,
        redis_url: str,
        max_queued_tasks: int = 100,
    ):
        self.redis_client = redis.Redis.from_url(redis_url)
        self._dispatch_context = threading.local()
        self._worker_context = threading.local()
        self._dispatcher_stop = threading.Event()
        self._dispatcher_thread = None
        self._dispatcher_lock = threading.Lock()
        super().__init__(max_concurrent_tasks, max_queued_tasks=max_queued_tasks)

    def create_queue(self):
        return "task_queue"

    @property
    def running_slots_key(self) -> str:
        # Tests and deployments can override ``queue`` after construction; the
        # semaphore must follow the selected queue namespace automatically.
        return f"{self.queue}:running"

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    def _lease_deadline_ms(self) -> int:
        return self._now_ms() + int(_RUNNING_SLOT_LEASE_SECONDS * 1000)

    def add_task(self, func, *args, **kwargs):
        # Drain older persisted work first. Besides preserving FIFO order, this
        # lets a request that arrives after a crashed lease expires free one
        # queue position before its own atomic admission check.
        if self.max_concurrent_tasks > 0:
            self.check_queue()
        task = {"func": func, "args": args, "kwargs": kwargs}
        token = uuid4().hex
        admitted = self.redis_client.eval(
            _ADMIT_TASK_SCRIPT,
            2,
            self.queue,
            self.running_slots_key,
            self._now_ms(),
            self.max_concurrent_tasks,
            self._lease_deadline_ms(),
            token,
            self.max_queued_tasks,
            self._serialize_task(task),
        )
        if admitted == -1:
            raise TaskQueueFullError("task queue is full, please try again later")
        if admitted == 1:
            logger.info(f"add task: {func.__name__}, global slot: {token}")
            self._start_reserved_task(token, task, restore_on_failure=False)
            return

        logger.info(f"enqueue task: {func.__name__}, queue_size: {self.queue_size()}")
        # If a crashed worker's lease was pruned during admission, immediately
        # give the oldest queued item the newly available global slot.
        self.check_queue()

    def resume_queued_tasks(self):
        """Dispatch persisted queue entries when a new API process starts.

        Queued Redis items survive a restart, but no worker calls check_queue
        until an active task finishes. Fill each available local worker slot so
        an idle process does not leave old requests stuck in processing.
        """
        for _ in range(max(0, self.max_concurrent_tasks)):
            self.check_queue()

    def start_queue_dispatcher(self):
        """Keep persisted work moving after a process restart.

        A replacement process may start before a crashed worker's Redis lease
        expires. The one-shot startup recovery cannot claim the queued task in
        that case, so keep a lifecycle-owned dispatcher waiting for the next
        lease deadline. Normal completions and new requests still dispatch
        immediately through task_done() and add_task().
        """
        with self._dispatcher_lock:
            if (
                self._dispatcher_thread is not None
                and self._dispatcher_thread.is_alive()
            ):
                return
            self._dispatcher_stop.clear()
            self._dispatcher_thread = threading.Thread(
                target=self._dispatch_queued_until_stopped,
                name="redis-queue-dispatcher",
                daemon=True,
            )
            self._dispatcher_thread.start()

    def stop_queue_dispatcher(self):
        """Stop and join the lifecycle-owned queue dispatcher."""
        with self._dispatcher_lock:
            thread = self._dispatcher_thread
            self._dispatcher_stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=_QUEUE_DISPATCH_RETRY_SECONDS)
        with self._dispatcher_lock:
            if self._dispatcher_thread is thread:
                self._dispatcher_thread = None

    def _dispatch_queued_until_stopped(self):
        while not self._dispatcher_stop.is_set():
            try:
                self.check_queue()
                delay = self._next_queue_dispatch_delay()
            except redis.RedisError as exc:
                logger.error(f"Redis queue dispatcher failed: {exc}")
                delay = _QUEUE_DISPATCH_RETRY_SECONDS
            self._dispatcher_stop.wait(delay)

    def _next_queue_dispatch_delay(self) -> float:
        """Return when recovery should retry, preferring the next lease expiry."""
        if self.queue_size() == 0:
            return _QUEUE_DISPATCH_RETRY_SECONDS
        earliest = self.redis_client.zrange(
            self.running_slots_key, 0, 0, withscores=True
        )
        if not earliest:
            # A queue entry appeared after check_queue() returned. Retry soon
            # instead of waiting for unrelated traffic.
            return 0.01
        deadline_ms = earliest[0][1]
        return max(0.01, (deadline_ms - self._now_ms()) / 1000)

    def check_queue(self):
        while True:
            token = uuid4().hex
            payload = self.redis_client.eval(
                _CLAIM_QUEUED_TASK_SCRIPT,
                2,
                self.queue,
                self.running_slots_key,
                self._now_ms(),
                self.max_concurrent_tasks,
                self._lease_deadline_ms(),
                token,
            )
            if payload is None:
                return

            task = self._deserialize_task(payload)
            if task is None:
                self._release_slot(token)
                # A stale entry must not prevent the next valid item from
                # running. Iterate instead of recursing through an unbounded
                # queue of entries left by an older deployment.
                continue
            self._start_reserved_task(token, task, restore_on_failure=True)
            return

    def _start_reserved_task(self, token: str, task: Dict, restore_on_failure: bool):
        func = task["func"]
        args = task.get("args", ())
        kwargs = task.get("kwargs", {})
        with self.lock:
            self.current_tasks += 1
        self._dispatch_context.slot_token = token
        try:
            self.execute_task(func, *args, **kwargs)
        except Exception:
            with self.lock:
                self.current_tasks -= 1
            self._release_slot(token)
            if restore_on_failure:
                self.enqueue(task)
            raise
        finally:
            self._dispatch_context.slot_token = None

    def execute_task(self, func, *args, **kwargs):
        token = getattr(self._dispatch_context, "slot_token", None)
        if token is None:
            raise RuntimeError("Redis task execution requires a reserved slot")
        thread = threading.Thread(
            target=self._run_reserved_task,
            args=(token, func, *args),
            kwargs=kwargs,
        )
        thread.start()

    def _run_reserved_task(self, token: str, func, *args, **kwargs):
        stop_heartbeat = threading.Event()
        heartbeat = threading.Thread(
            target=self._renew_slot_until_done,
            args=(token, stop_heartbeat),
            daemon=True,
        )
        heartbeat.start()
        self._worker_context.slot_token = token
        try:
            func(*args, **kwargs)
        finally:
            stop_heartbeat.set()
            self.task_done()
            self._worker_context.slot_token = None

    def _renew_slot_until_done(self, token: str, stop: threading.Event):
        while not stop.wait(_RUNNING_SLOT_HEARTBEAT_SECONDS):
            try:
                renewed = self.redis_client.eval(
                    _RENEW_RUNNING_SLOT_SCRIPT,
                    1,
                    self.running_slots_key,
                    token,
                    self._lease_deadline_ms(),
                )
                if not renewed:
                    logger.error(f"lost Redis running slot lease: {token}")
                    return
            except redis.RedisError as exc:
                # A temporary Redis outage must not kill the user task. The
                # next heartbeat can still renew before the lease expires.
                logger.error(f"failed to renew Redis running slot {token}: {exc}")

    def _release_slot(self, token: str):
        try:
            self.redis_client.zrem(self.running_slots_key, token)
        except redis.RedisError as exc:
            # The lease will expire even if Redis is temporarily unavailable.
            logger.error(f"failed to release Redis running slot {token}: {exc}")

    def task_done(self):
        token = getattr(self._worker_context, "slot_token", None)
        if token is not None:
            self._release_slot(token)
        with self.lock:
            self.current_tasks = max(0, self.current_tasks - 1)
        self.check_queue()

    def enqueue(self, task: Dict):
        self.redis_client.rpush(self.queue, self._serialize_task(task))

    def enqueue_new_task(self, task: Dict):
        # Manager locks are process-local. Keep capacity validation and admission
        # in one Redis operation so other API workers cannot claim the same slot.
        admitted = self.redis_client.eval(
            _ADMIT_QUEUED_TASK_SCRIPT,
            1,
            self.queue,
            self.max_queued_tasks,
            self._serialize_task(task),
        )
        if not admitted:
            raise TaskQueueFullError("task queue is full, please try again later")

    @staticmethod
    def _serialize_task(task: Dict) -> str:
        task_with_serializable_params = task.copy()
        # task.copy() only copies the outermost dict; rewriting the nested kwargs directly would also replace the
        # VideoParams held by the caller with a dict. Later logs or retries may still read the original task,
        # so kwargs is copied separately here, making sure serialization has no unexpected side effects.
        task_kwargs = task.get("kwargs", {})
        task_with_serializable_params["kwargs"] = task_kwargs.copy()

        if "params" in task_kwargs and isinstance(
            task_kwargs["params"], (VideoParams, AudioRequest, SubtitleRequest)
        ):
            task_with_serializable_params["kwargs"]["params"] = task_kwargs[
                "params"
            ].model_dump(warnings=False)

        # Convert the function object to its name
        task_with_serializable_params["func"] = task["func"].__name__
        return json.dumps(task_with_serializable_params)

    def dequeue(self):
        # Loop instead of a single pop: a task may have satisfied the validation rules when it was enqueued, but validation rules and
        # FUNC_MAP members change with deployments (e.g. VideoParams gains a ge=1 constraint, or an entry
        # function is removed), so the queue may contain leftover entries written under an old schema or no longer parseable.
        # lpop is destructive and a popped item can't be put back in place; this task has already been permanently removed
        # from the queue, so we can't pretend it's still there. Rather than letting the exception propagate from here (check_queue calls
        # this method while holding the lock, so the exception would crash the worker thread through task_done → run_task's finally; after that
        # no task is running, nobody ever calls check_queue again, and later tasks in the queue would stay
        # in processing forever), drop it in place and try the next one, keeping the contract of "return a usable task
        # or the queue really is empty".
        while True:
            task_json = self.redis_client.lpop(self.queue)
            # Only lpop returning nothing means the queue is empty. An empty string (or empty bytes) is likewise
            # an unusable entry that may have usable tasks queued behind it, so it goes through the drop
            # path below instead of being treated as "end of queue" and returning directly.
            if task_json is None:
                return None

            task_info = self._deserialize_task(task_json)
            if task_info is not None:
                return task_info

    def _deserialize_task(self, task_json):
        """Restore one popped queue payload, or discard it as stale."""
        task_info = None
        try:
            task_info = json.loads(task_json)
            # Convert the function name back to the function object. A missing name, or one no longer in FUNC_MAP, can't
            # be indexed directly, otherwise a KeyError would bypass the drop policy for params below.
            task_info["func"] = FUNC_MAP[task_info["func"]]
            task_kwargs = task_info["kwargs"]
            if not isinstance(task_kwargs, dict):
                raise ValueError("queued task has no keyword argument mapping")
            # When args is missing entirely, check_queue's default applies; null or any other non-array
            # shape would make check_queue raise TypeError when unpacking `*args`, where it
            # would re-enqueue the entry and let the exception escape the worker thread, so it must be stopped here first.
            if not isinstance(task_info.get("args", []), list):
                raise ValueError("queued task positional arguments are not a list")
            # A persisted request can outlive a callable's signature. Fail
            # it before dispatch: Python argument-binding errors happen
            # before start() enters its pipeline failure handler.
            inspect.signature(task_info["func"]).bind(
                *task_info.get("args", []), **task_kwargs
            )
        except (TypeError, ValueError, KeyError) as e:
            logger.error(f"dropping unusable queued task: {e}")
            # Consistent with the params validation failure path below: as long as a usable task_id can be read, converge
            # this task, which has permanently left the queue, to failed, otherwise the API/WebUI would keep showing
            # it as processing. When the payload itself can't be parsed, or task_id isn't a string
            # (e.g. a JSON array), there's no record to write back and it can only be dropped — passing a non-string
            # directly to patch_task would make redis raise DataError, which would in turn break the drop loop.
            stale_kwargs = (
                task_info.get("kwargs") if isinstance(task_info, dict) else None
            )
            task_id = (
                stale_kwargs.get("task_id")
                if isinstance(stale_kwargs, dict)
                else None
            )
            if isinstance(task_id, str) and task_id:
                sm.state.patch_task(
                    task_id,
                    state=const.TASK_STATE_FAILED,
                    failed_stage="dequeue",
                    error=f"discarded stale queued task: {e}",
                )
            return None

        if "params" in task_kwargs and isinstance(task_kwargs["params"], dict):
            try:
                params_model = VideoParams
                # /audio and /subtitle use short-form request models without
                # video_subject. Preserve those schemas at the queue boundary;
                # full VideoParams can also stop at either of these stages.
                if "video_subject" not in task_kwargs["params"]:
                    if task_kwargs.get("stop_at") == "audio":
                        params_model = AudioRequest
                    elif task_kwargs.get("stop_at") == "subtitle":
                        params_model = SubtitleRequest
                task_kwargs["params"] = params_model(**task_kwargs["params"])
            except ValidationError as e:
                logger.error(
                    "dropping queued task with params that fail current "
                    f"request model validation (queued under an older, more "
                    f"permissive schema, or corrupted): {e}"
                )
                # The task state record is created before enqueueing and defaults to processing; if we only
                # dropped this queue item without touching the state record, the API/WebUI would keep showing the task as
                # running and it would never become failed. Use patch_task rather than update_task,
                # so if the user has already deleted this task, we don't recreate it.
                # Same when task_id isn't a string: there's no record to write back, so the state update is skipped.
                task_id = task_kwargs.get("task_id")
                if isinstance(task_id, str) and task_id:
                    sm.state.patch_task(
                        task_id,
                        state=const.TASK_STATE_FAILED,
                        failed_stage="dequeue",
                        error=f"discarded stale queued task: {e}",
                    )
                return None

        return task_info

    def is_queue_empty(self):
        return self.redis_client.llen(self.queue) == 0

    def queue_size(self):
        return self.redis_client.llen(self.queue)
