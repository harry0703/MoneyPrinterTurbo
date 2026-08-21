import json
from typing import Dict

import redis
from loguru import logger
from pydantic import ValidationError

from app.controllers.manager.base_manager import TaskManager
from app.models import const
from app.models.schema import VideoParams
from app.services import state as sm
from app.services import task as tm

FUNC_MAP = {
    "start": tm.start,
    # 'start_test': tm.start_test
}


class RedisTaskManager(TaskManager):
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
        task_with_serializable_params = task.copy()
        # task.copy() only copies the outermost dict; mutating nested kwargs directly would also replace the
        # caller's VideoParams with a dict. Later logging or retries may still read the original task, so
        # copy kwargs separately to keep serialization free of side effects.
        task_kwargs = task.get("kwargs", {})
        task_with_serializable_params["kwargs"] = task_kwargs.copy()

        if "params" in task_kwargs and isinstance(task_kwargs["params"], VideoParams):
            task_with_serializable_params["kwargs"]["params"] = task_kwargs[
                "params"
            ].model_dump(warnings=False)

        # Convert a function object to its name
        task_with_serializable_params["func"] = task["func"].__name__
        self.redis_client.rpush(self.queue, json.dumps(task_with_serializable_params))

    def dequeue(self):
        # Loop instead of popping once: a task may have passed the VideoParams validation rules in force when it was enqueued,
        # while those rules later tightened between deployments (e.g. a new ge=1 constraint). lpop is destructive:
        # once popped, an entry cannot be put back. If validation fails only when rebuilding VideoParams,
        # the task is already permanently gone from the queue. Rather than letting the exception propagate upward
        # and crash the lock holder of this already-lost task, drop it in place and continue with the next queue entry,
        # preserving the contract of "hand out one usable task, or confirm the queue is truly empty".
        while True:
            task_json = self.redis_client.lpop(self.queue)
            if not task_json:
                return None

            task_info = json.loads(task_json)
            # Convert a function name back to a function object
            task_info["func"] = FUNC_MAP[task_info["func"]]

            if "params" in task_info["kwargs"] and isinstance(
                task_info["kwargs"]["params"], dict
            ):
                try:
                    task_info["kwargs"]["params"] = VideoParams(
                        **task_info["kwargs"]["params"]
                    )
                except ValidationError as e:
                    logger.error(
                        "dropping queued task with params that fail current "
                        f"VideoParams validation (queued under an older, more "
                        f"permissive schema, or corrupted): {e}"
                    )
                    # The task state record is created before enqueueing and defaults to processing; if the queue entry
                    # is simply dropped without touching the state record, the API/WebUI would keep showing the task
                    # as running forever. Use patch_task instead of update_task,
                    # so we do not recreate a task the user has already deleted.
                    task_id = task_info["kwargs"].get("task_id")
                    if task_id:
                        sm.state.patch_task(
                            task_id,
                            state=const.TASK_STATE_FAILED,
                            failed_stage="dequeue",
                            error=f"discarded stale queued task: {e}",
                        )
                    continue

            return task_info

    def is_queue_empty(self):
        return self.redis_client.llen(self.queue) == 0

    def queue_size(self):
        return self.redis_client.llen(self.queue)
