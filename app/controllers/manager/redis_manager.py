import copy
import json
import time
from typing import Dict
from uuid import uuid4

import redis

from app.controllers.manager.base_manager import TaskManager
from app.models import const
from app.models.schema import VideoParams
from app.services import task as tm

FUNC_MAP = {
    "start": tm.start,
    # 'start_test': tm.start_test
}


class RedisTaskManager(TaskManager):
    _DISPATCH_CLAIM_SECONDS = 5.0

    def __init__(
        self,
        max_concurrent_tasks: int,
        redis_url: str,
        max_queued_tasks: int = 100,
    ):
        self.redis_client = redis.Redis.from_url(redis_url)
        super().__init__(max_concurrent_tasks, max_queued_tasks=max_queued_tasks)

    def create_queue(self):
        return "task_queue"

    def enqueue(self, task: Dict):
        self.redis_client.rpush(self.queue, self._serialize_task(task))

    def enqueue_transaction(self, pipeline, task: Dict):
        """Append a serialized job to the active Redis transaction."""
        pipeline.rpush(self.queue, self._serialize_task(task))

    def requeue(self, task: Dict):
        """Owner-safely return a claimed Redis job after worker-start failure."""
        self._finish_claim(task, requeue=True)

    def acknowledge_dispatch(self, task: Dict):
        """Owner-safely remove a Redis claim after its worker finishes."""
        self._finish_claim(task, requeue=False)

    def renew_active_dispatches(self):
        """Renew owner claims for workers still running in this process."""
        for task in self._active_dispatch_snapshot():
            claim_id = task.get("_dispatch_claim_id")
            payload = task.get("_dispatch_payload")
            if not claim_id or payload is None:
                continue
            claim_key = self._dispatch_claim_key(claim_id)
            while True:
                with self.redis_client.pipeline() as pipe:
                    try:
                        pipe.watch(claim_key, self._processing_deadlines_key)
                        claim_type = self._require_key_type(
                            pipe,
                            claim_key,
                            {"none", "string"},
                            "dispatch claim",
                        )
                        self._require_key_type(
                            pipe,
                            self._processing_deadlines_key,
                            {"none", "zset"},
                            "dispatch deadline",
                        )
                        if claim_type == "none":
                            pipe.unwatch()
                            self._discard_dispatch_active(task)
                            break
                        claimed_payload = pipe.get(claim_key)
                        expected_payload = payload.encode("utf-8")
                        if claimed_payload != expected_payload:
                            pipe.unwatch()
                            self._discard_dispatch_active(task)
                            break
                        pipe.multi()
                        pipe.zadd(
                            self._processing_deadlines_key,
                            {
                                claim_id: time.time()
                                + self._DISPATCH_CLAIM_SECONDS
                            },
                        )
                        pipe.execute()
                        break
                    except redis.WatchError:
                        continue

    @property
    def _processing_deadlines_key(self):
        return f"{self.queue}:processing:deadlines"

    def _dispatch_claim_key(self, claim_id: str):
        return f"{self.queue}:processing:{claim_id}"

    @staticmethod
    def _type_name(redis_type):
        if isinstance(redis_type, bytes):
            return redis_type.decode("utf-8")
        return redis_type

    def _require_key_type(self, pipe, key: str, allowed_types, label: str):
        key_type = self._type_name(pipe.type(key))
        if key_type not in allowed_types:
            raise TypeError(f"{label} key has incompatible Redis type: {key_type}")
        return key_type

    def _finish_claim(self, task: Dict, requeue: bool):
        claim_id = task.get("_dispatch_claim_id")
        payload = task.get("_dispatch_payload")
        if not claim_id or payload is None:
            return
        claim_key = self._dispatch_claim_key(claim_id)
        while True:
            with self.redis_client.pipeline() as pipe:
                try:
                    watched_keys = [claim_key, self._processing_deadlines_key]
                    if requeue:
                        watched_keys.append(self.queue)
                    pipe.watch(*watched_keys)
                    claim_type = self._require_key_type(
                        pipe, claim_key, {"none", "string"}, "dispatch claim"
                    )
                    self._require_key_type(
                        pipe,
                        self._processing_deadlines_key,
                        {"none", "zset"},
                        "dispatch deadline",
                    )
                    if requeue:
                        self._require_key_type(
                            pipe, self.queue, {"none", "list"}, "task queue"
                        )
                    if claim_type == "none":
                        pipe.unwatch()
                        return
                    claimed_payload = pipe.get(claim_key)
                    expected_payload = payload.encode("utf-8")
                    if claimed_payload != expected_payload:
                        pipe.unwatch()
                        return
                    pipe.multi()
                    pipe.delete(claim_key)
                    pipe.zrem(self._processing_deadlines_key, claim_id)
                    if requeue:
                        pipe.lpush(self.queue, payload)
                    pipe.execute()
                    return
                except redis.WatchError:
                    continue

    @staticmethod
    def _serialize_task(task: Dict) -> str:
        task_with_serializable_params = copy.deepcopy(task)

        if "params" in task["kwargs"] and isinstance(
            task["kwargs"]["params"], VideoParams
        ):
            task_with_serializable_params["kwargs"]["params"] = task["kwargs"][
                "params"
            ].dict()

        # 将函数对象转换为其名称
        task_with_serializable_params["func"] = task["func"].__name__
        return json.dumps(task_with_serializable_params)

    def dequeue(self):
        """Atomically claim one queued job under a short visibility lease."""
        claim_id = str(uuid4())
        claim_key = self._dispatch_claim_key(claim_id)
        while True:
            with self.redis_client.pipeline() as pipe:
                try:
                    pipe.watch(
                        self.queue,
                        claim_key,
                        self._processing_deadlines_key,
                    )
                    self._require_key_type(
                        pipe, self.queue, {"none", "list"}, "task queue"
                    )
                    self._require_key_type(
                        pipe, claim_key, {"none"}, "dispatch claim"
                    )
                    self._require_key_type(
                        pipe,
                        self._processing_deadlines_key,
                        {"none", "zset"},
                        "dispatch deadline",
                    )
                    task_json = pipe.lindex(self.queue, 0)
                    if not task_json:
                        pipe.unwatch()
                        return None
                    payload = (
                        task_json.decode("utf-8")
                        if isinstance(task_json, bytes)
                        else task_json
                    )
                    pipe.multi()
                    pipe.lpop(self.queue)
                    pipe.set(claim_key, payload)
                    pipe.zadd(
                        self._processing_deadlines_key,
                        {claim_id: time.time() + self._DISPATCH_CLAIM_SECONDS},
                    )
                    pipe.execute()
                    break
                except redis.WatchError:
                    continue
        if task_json:
            task_info = json.loads(payload)
            task_info["_dispatch_claim_id"] = claim_id
            task_info["_dispatch_payload"] = payload
            # 将函数名称转换回函数对象
            task_info["func"] = FUNC_MAP[task_info["func"]]

            if "params" in task_info["kwargs"] and isinstance(
                task_info["kwargs"]["params"], dict
            ):
                task_info["kwargs"]["params"] = VideoParams(
                    **task_info["kwargs"]["params"]
                )

            return task_info
        return None

    def recover_expired_dispatches(self):
        """Owner-safely recover expired claims unless their task is terminal."""
        while True:
            with self.redis_client.pipeline() as pipe:
                try:
                    pipe.watch(self._processing_deadlines_key, self.queue)
                    deadline_type = self._require_key_type(
                        pipe,
                        self._processing_deadlines_key,
                        {"none", "zset"},
                        "dispatch deadline",
                    )
                    self._require_key_type(
                        pipe, self.queue, {"none", "list"}, "task queue"
                    )
                    if deadline_type == "none":
                        pipe.unwatch()
                        return
                    claim_ids = pipe.zrangebyscore(
                        self._processing_deadlines_key, "-inf", time.time()
                    )
                    if not claim_ids:
                        pipe.unwatch()
                        return
                    claim_keys = [
                        self._dispatch_claim_key(
                            claim_id.decode("utf-8")
                            if isinstance(claim_id, bytes)
                            else claim_id
                        )
                        for claim_id in claim_ids
                    ]
                    pipe.watch(*claim_keys)
                    claim_types = [
                        self._require_key_type(
                            pipe,
                            claim_key,
                            {"none", "string"},
                            "dispatch claim",
                        )
                        for claim_key in claim_keys
                    ]
                    claims = [
                        (
                            claim_key,
                            pipe.get(claim_key)
                            if claim_type == "string"
                            else None,
                        )
                        for claim_key, claim_type in zip(
                            claim_keys, claim_types
                        )
                    ]
                    claim_task_ids = [
                        self._task_id_from_payload(payload)
                        for _, payload in claims
                    ]
                    task_ids = list(
                        dict.fromkeys(
                            task_id
                            for task_id in claim_task_ids
                            if task_id is not None
                        )
                    )
                    terminal_keys = {
                        task_id: (
                            f"{const.TASK_TERMINAL_MARKER_PREFIX}{task_id}"
                        )
                        for task_id in task_ids
                    }
                    watched_task_keys = [
                        key
                        for task_id in task_ids
                        for key in (task_id, terminal_keys[task_id])
                    ]
                    if watched_task_keys:
                        pipe.watch(*watched_task_keys)
                    task_types = {
                        task_id: self._require_key_type(
                            pipe,
                            task_id,
                            {"none", "hash"},
                            "task record",
                        )
                        for task_id in task_ids
                    }
                    terminal_marker_types = {
                        task_id: self._require_key_type(
                            pipe,
                            terminal_key,
                            {"none", "string"},
                            "terminal task marker",
                        )
                        for task_id, terminal_key in terminal_keys.items()
                    }
                    terminal_task_ids = {
                        task_id
                        for task_id, task_type in task_types.items()
                        if (
                            terminal_marker_types[task_id] == "string"
                            or (
                                task_type == "hash"
                                and self._is_terminal_state(
                                    pipe.hget(task_id, "state")
                                )
                            )
                        )
                    }
                    pipe.multi()
                    pipe.zrem(self._processing_deadlines_key, *claim_ids)
                    pipe.delete(*claim_keys)
                    for (_, payload), task_id in zip(
                        claims, claim_task_ids
                    ):
                        if (
                            payload is not None
                            and task_id not in terminal_task_ids
                        ):
                            pipe.lpush(self.queue, payload)
                    pipe.execute()
                    return
                except redis.WatchError:
                    continue

    @staticmethod
    def _task_id_from_payload(payload):
        if payload is None:
            return None
        try:
            task_info = json.loads(payload)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            return None
        if not isinstance(task_info, dict):
            return None
        kwargs = task_info.get("kwargs")
        if not isinstance(kwargs, dict):
            return None
        task_id = kwargs.get("task_id")
        return task_id if isinstance(task_id, str) and task_id else None

    @staticmethod
    def _is_terminal_state(raw_state):
        if isinstance(raw_state, bytes):
            raw_state = raw_state.decode("utf-8")
        return raw_state in {
            str(const.TASK_STATE_COMPLETE),
            str(const.TASK_STATE_FAILED),
        }

    def is_queue_empty(self):
        return self.redis_client.llen(self.queue) == 0

    def queue_size(self):
        return self.redis_client.llen(self.queue)
