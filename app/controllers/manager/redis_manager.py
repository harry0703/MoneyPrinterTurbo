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
        # task.copy() 只复制最外层字典；如果直接改写嵌套 kwargs，会把调用方
        # 持有的 VideoParams 同步替换成 dict。后续日志或重试仍可能读取原任务，
        # 因此这里单独复制 kwargs，确保序列化过程没有意外副作用。
        task_kwargs = task.get("kwargs", {})
        task_with_serializable_params["kwargs"] = task_kwargs.copy()

        if "params" in task_kwargs and isinstance(task_kwargs["params"], VideoParams):
            task_with_serializable_params["kwargs"]["params"] = task_kwargs[
                "params"
            ].model_dump(warnings=False)

        # 将函数对象转换为其名称
        task_with_serializable_params["func"] = task["func"].__name__
        self.redis_client.rpush(self.queue, json.dumps(task_with_serializable_params))

    def dequeue(self):
        # 循环而非单次弹出：某个任务在入队时可能满足当时的校验规则，但校验规则与
        # FUNC_MAP 成员会随部署变化（例如 VideoParams 新增 ge=1 约束、某个入口
        # 函数被移除），队列里因此可能残留按旧 schema 写入、或已无法解析的条目。
        # lpop 是破坏性操作，一旦弹出就不能放回原位；这条任务已经从队列中永久
        # 移除了，不能再假装它还在。与其让异常从这里往上抛（check_queue 持锁调用
        # 本方法，异常会顺着 task_done → run_task 的 finally 把工作线程带崩；此后
        # 没有任务在跑，就再也不会有人调用 check_queue，队列里后面的任务会永久
        # 停在 processing），不如原地丢弃并继续尝试下一条，把"拿到一条可用任务
        # 或者队列确实空了"这个约定维持住。
        while True:
            task_json = self.redis_client.lpop(self.queue)
            # 只有 lpop 什么都没弹出来才代表队列空了。空字符串（或空 bytes）同样
            # 是一条不可用条目，它后面可能还排着可用的任务，所以要走下面的丢弃
            # 路径，而不是当成"队列结束"直接返回。
            if task_json is None:
                return None

            task_info = None
            try:
                task_info = json.loads(task_json)
                # 将函数名称转换回函数对象。名称缺失、或已不在 FUNC_MAP 中时不能
                # 直接索引，否则 KeyError 会绕过下面针对 params 的丢弃策略。
                task_info["func"] = FUNC_MAP[task_info["func"]]
                task_kwargs = task_info["kwargs"]
                if not isinstance(task_kwargs, dict):
                    raise ValueError("queued task has no keyword argument mapping")
                # args 整体缺失时沿用 check_queue 的默认值；写成 null 或其它不是
                # 数组的形态则会让 check_queue 展开 `*args` 时抛 TypeError，那里
                # 会把条目重新入队并让异常逃出工作线程，必须在这里先拦下。
                if not isinstance(task_info.get("args", []), list):
                    raise ValueError("queued task positional arguments are not a list")
            except (TypeError, ValueError, KeyError) as e:
                logger.error(f"dropping unusable queued task: {e}")
                # 与下面的 params 校验失败路径一致：只要能读出可用的 task_id，就把
                # 这条已经永久离开队列的任务收敛为失败，否则 API/WebUI 会一直显示
                # 它在 processing。payload 本身没法解析、或 task_id 不是字符串
                # （例如 JSON 数组）时则没有可回写的记录，只能丢弃 —— 把非字符串
                # 直接交给 patch_task 会让 redis 抛 DataError，反过来打断丢弃循环。
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
                continue

            if "params" in task_kwargs and isinstance(task_kwargs["params"], dict):
                try:
                    task_kwargs["params"] = VideoParams(**task_kwargs["params"])
                except ValidationError as e:
                    logger.error(
                        "dropping queued task with params that fail current "
                        f"VideoParams validation (queued under an older, more "
                        f"permissive schema, or corrupted): {e}"
                    )
                    # 任务状态记录在入队前就已创建，且默认是 processing；如果只是
                    # 丢弃这条队列项而不动状态记录，API/WebUI 会一直显示任务在
                    # 运行，永远不会变成失败。用 patch_task 而不是 update_task，
                    # 这样如果用户已经删除了这个任务，我们不会又把它建回来。
                    # task_id 不是字符串时同上：没有可回写的记录，跳过状态更新。
                    task_id = task_kwargs.get("task_id")
                    if isinstance(task_id, str) and task_id:
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
