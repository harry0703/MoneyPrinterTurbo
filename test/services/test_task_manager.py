import json
import unittest
from unittest.mock import MagicMock, patch

from app.controllers.manager.base_manager import TaskQueueFullError
from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.controllers.manager.redis_manager import RedisTaskManager
from app.models import const
from app.models.schema import VideoParams
from app.services import task as task_service


def _queued_payload(func: str, **kwargs) -> str:
    """按 RedisTaskManager.enqueue 的落盘格式构造一条队列条目。"""
    return json.dumps({"func": func, "args": [], "kwargs": kwargs})


def _video_params() -> dict:
    """返回一份能通过当前校验的 VideoParams 序列化结果。"""
    return VideoParams(video_subject="Tea").model_dump(warnings=False)


class TestInMemoryTaskManager(unittest.TestCase):
    def test_queue_operations_preserve_task_payload(self):
        """内存队列应保持函数、位置参数和关键字参数，不得改变任务内容。"""
        manager = InMemoryTaskManager(max_concurrent_tasks=1, max_queued_tasks=2)
        task = {"func": len, "args": ([1, 2],), "kwargs": {}}

        manager.enqueue(task)

        self.assertFalse(manager.is_queue_empty())
        self.assertEqual(manager.queue_size(), 1)
        self.assertEqual(manager.dequeue(), task)
        self.assertTrue(manager.is_queue_empty())

    def test_add_task_rejects_only_after_queue_limit(self):
        """并发名额用尽后允许排队到上限，超过上限才返回明确错误。"""
        manager = InMemoryTaskManager(max_concurrent_tasks=0, max_queued_tasks=1)

        manager.add_task(len, [1])

        with self.assertRaises(TaskQueueFullError):
            manager.add_task(len, [2])

    def test_add_task_reserves_slot_before_background_thread_runs(self):
        """
        并发名额必须在线程启动前预占；即使 mock 的线程尚未进入 run_task，
        第二个请求也应进入队列，不能突破 max_concurrent_tasks。
        """
        manager = InMemoryTaskManager(max_concurrent_tasks=1, max_queued_tasks=1)

        with patch.object(manager, "execute_task") as execute_task:
            manager.add_task(len, [1])
            manager.add_task(len, [2])

        self.assertEqual(manager.current_tasks, 1)
        execute_task.assert_called_once_with(len, [1])
        self.assertEqual(manager.queue_size(), 1)

    def test_add_task_rolls_back_slot_when_thread_cannot_start(self):
        """线程启动失败不能永久占用并发名额，异常仍应交给调用方处理。"""
        manager = InMemoryTaskManager(max_concurrent_tasks=1)

        with patch.object(
            manager,
            "execute_task",
            side_effect=RuntimeError("thread unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "thread unavailable"):
                manager.add_task(len, [1])

        self.assertEqual(manager.current_tasks, 0)

    def test_task_done_starts_next_queued_task(self):
        """当前任务结束后应释放并发名额，并立即调度队列中的下一个任务。"""
        manager = InMemoryTaskManager(max_concurrent_tasks=1, max_queued_tasks=2)
        manager.current_tasks = 1
        manager.enqueue({"func": len, "args": ([1, 2],), "kwargs": {}})

        with patch.object(manager, "execute_task") as execute_task:
            manager.task_done()

        self.assertEqual(manager.current_tasks, 1)
        execute_task.assert_called_once_with(len, [1, 2])
        self.assertTrue(manager.is_queue_empty())

    def test_task_done_requeues_task_when_thread_cannot_start(self):
        """出队后若线程启动失败，应回滚名额并把任务放回队列，避免任务丢失。"""
        manager = InMemoryTaskManager(max_concurrent_tasks=1, max_queued_tasks=1)
        manager.current_tasks = 1
        queued_task = {"func": len, "args": ([1, 2],), "kwargs": {}}
        manager.enqueue(queued_task)

        with patch.object(
            manager,
            "execute_task",
            side_effect=RuntimeError("thread unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "thread unavailable"):
                manager.task_done()

        self.assertEqual(manager.current_tasks, 0)
        self.assertEqual(manager.dequeue(), queued_task)

    def test_run_task_releases_slot_after_failure(self):
        """任务函数抛出异常时 finally 仍必须释放名额，避免队列永久阻塞。"""
        manager = InMemoryTaskManager(max_concurrent_tasks=1)
        manager.current_tasks = 1

        with patch.object(manager, "task_done") as task_done:
            with self.assertRaisesRegex(RuntimeError, "task failed"):
                manager.run_task(MagicMock(side_effect=RuntimeError("task failed")))

        self.assertEqual(manager.current_tasks, 1)
        task_done.assert_called_once_with()

    def test_check_queue_handles_dequeue_returning_none(self):
        """
        dequeue() 可能在内部跳过所有已不满足当前校验的排队任务后返回 None，
        即使调用 check_queue 之前 is_queue_empty() 曾经是 False。check_queue
        不能假设 dequeue 一定能拿到可用任务，否则会在 task_info["func"] 上崩溃。
        """
        manager = InMemoryTaskManager(max_concurrent_tasks=1, max_queued_tasks=1)

        with patch.object(manager, "is_queue_empty", return_value=False), patch.object(
            manager, "dequeue", return_value=None
        ), patch.object(manager, "execute_task") as execute_task:
            manager.check_queue()

        execute_task.assert_not_called()
        self.assertEqual(manager.current_tasks, 0)

    def test_execute_task_starts_background_thread(self):
        """任务执行入口必须启动线程，并把函数参数完整传给 run_task。"""
        manager = InMemoryTaskManager(max_concurrent_tasks=1)
        fake_thread = MagicMock()

        with patch(
            "app.controllers.manager.base_manager.threading.Thread",
            return_value=fake_thread,
        ) as thread:
            manager.execute_task(len, [1, 2])

        thread.assert_called_once_with(
            target=manager.run_task,
            args=(len, [1, 2]),
            kwargs={},
        )
        fake_thread.start.assert_called_once_with()

    def test_limits_accept_quoted_toml_integers(self):
        """
        TOML 里把上限写成字符串时也要按整数比较；修复前并发名额的比较会抛
        TypeError，队列上限的比较则要等到名额用尽才触发。
        """
        manager = InMemoryTaskManager(max_concurrent_tasks="1", max_queued_tasks="1")

        with patch.object(manager, "execute_task") as execute_task:
            manager.add_task(len, [1])
            manager.add_task(len, [2])
            with self.assertRaises(TaskQueueFullError):
                manager.add_task(len, [3])

        self.assertEqual(manager.max_concurrent_tasks, 1)
        self.assertEqual(manager.max_queued_tasks, 1)
        execute_task.assert_called_once_with(len, [1])
        self.assertEqual(manager.queue_size(), 1)

    def test_invalid_limits_raise_a_named_error(self):
        """无法解析的上限要立刻指出配置键名，不能推迟成调度期的匿名异常。"""
        with self.assertRaisesRegex(ValueError, "max_concurrent_tasks"):
            InMemoryTaskManager(max_concurrent_tasks="abc")

        with self.assertRaisesRegex(ValueError, "max_queued_tasks"):
            InMemoryTaskManager(max_concurrent_tasks=1, max_queued_tasks="abc")

        with self.assertRaisesRegex(ValueError, "max_queued_tasks"):
            InMemoryTaskManager(max_concurrent_tasks=1, max_queued_tasks=True)

    def test_non_integral_limits_are_rejected_by_name(self):
        """修复前 `0.5` 会被 `int()` 截断成 0（任务入队后没有 worker 执行），`inf` 则漏出 OverflowError。"""
        cases = (
            (0.5, "an integer"),
            (1.5, "an integer"),
            ("0.5", "an integer"),
            (float("nan"), "a finite"),
            (float("inf"), "a finite"),
            (float("-inf"), "a finite"),
        )
        for field in ("max_concurrent_tasks", "max_queued_tasks"):
            for value, msg in cases:
                with self.subTest(field=field, value=value):
                    limits = {"max_concurrent_tasks": 1, "max_queued_tasks": 1}
                    limits[field] = value
                    pattern = f"{field} must be {msg}"
                    with self.assertRaisesRegex(ValueError, pattern):
                        InMemoryTaskManager(**limits)

        # 没有截断风险的整数值浮点仍然可用（TOML 允许 `max_queued_tasks = 2.0`）。
        integral = {"max_concurrent_tasks": 1, "max_queued_tasks": 2.0}
        self.assertEqual(InMemoryTaskManager(**integral).max_queued_tasks, 2)

    def test_zero_concurrency_keeps_queueing_without_executing(self):
        """0 与负数仍是合法取值：只排队、不执行，既有用例依赖这一语义。"""
        manager = InMemoryTaskManager(max_concurrent_tasks=0, max_queued_tasks=1)

        with patch.object(manager, "execute_task") as execute_task:
            manager.add_task(len, [1])

        execute_task.assert_not_called()
        self.assertEqual(manager.queue_size(), 1)


class TestRedisTaskManager(unittest.TestCase):
    def setUp(self):
        self.redis_client = MagicMock()
        patcher = patch(
            "app.controllers.manager.redis_manager.redis.Redis.from_url",
            return_value=self.redis_client,
        )
        self.addCleanup(patcher.stop)
        from_url = patcher.start()
        self.manager = RedisTaskManager(
            max_concurrent_tasks=1,
            redis_url="redis://localhost:6379/0",
            max_queued_tasks=3,
        )
        from_url.assert_called_once_with("redis://localhost:6379/0")

    def test_enqueue_serializes_video_params_without_mutating_task(self):
        """
        Redis 只能存 JSON；VideoParams 应转换成字典，但原任务仍需保留模型，
        避免序列化副作用影响日志、重试或调用方后续读取。
        """
        params = VideoParams(video_subject="Coffee")
        task = {
            "func": task_service.start,
            "args": (),
            "kwargs": {"task_id": "task-1", "params": params},
        }

        self.manager.enqueue(task)

        self.assertIs(task["kwargs"]["params"], params)
        queue_name, payload = self.redis_client.rpush.call_args.args
        decoded = json.loads(payload)
        self.assertEqual(queue_name, "task_queue")
        self.assertEqual(decoded["func"], "start")
        self.assertEqual(decoded["kwargs"]["task_id"], "task-1")
        self.assertEqual(decoded["kwargs"]["params"]["video_subject"], "Coffee")

    def test_dequeue_restores_function_and_video_params(self):
        """从 Redis 取出的任务应恢复可调用函数和 VideoParams 模型。"""
        payload = {
            "func": "start",
            "args": [],
            "kwargs": {
                "task_id": "task-1",
                "params": VideoParams(video_subject="Coffee").model_dump(
                    warnings=False
                ),
            },
        }
        self.redis_client.lpop.return_value = json.dumps(payload)

        task = self.manager.dequeue()

        self.redis_client.lpop.assert_called_once_with("task_queue")
        self.assertIs(task["func"], task_service.start)
        self.assertIsInstance(task["kwargs"]["params"], VideoParams)
        self.assertEqual(task["kwargs"]["params"].video_subject, "Coffee")

    def test_empty_queue_and_size_use_redis_length(self):
        """队列判空和长度必须直接反映 Redis 当前列表长度。"""
        self.redis_client.lpop.return_value = None
        self.redis_client.llen.side_effect = [0, 2]

        self.assertIsNone(self.manager.dequeue())
        self.assertTrue(self.manager.is_queue_empty())
        self.assertEqual(self.manager.queue_size(), 2)

    def test_dequeue_skips_task_that_fails_current_validation(self):
        """
        一条任务可能是在校验规则收紧前入队的（例如 video_count 曾允许为 0）。
        lpop 是破坏性操作，重建 VideoParams 失败时这条任务已经从 Redis 里
        永久移除了，不能再假装它还在；dequeue 不应该把校验异常抛给调用方
        （那样会让持锁的调用方崩溃且丢失这条任务却不打日志），而应该跳过它，
        继续尝试队列里的下一条，直到取到一条可用任务或者队列确实空了。
        """
        stale_payload = {
            "func": "start",
            "args": [],
            "kwargs": {
                "task_id": "task-stale",
                "params": {**VideoParams(video_subject="Coffee").model_dump(
                    warnings=False
                ), "video_count": 0},
            },
        }
        valid_payload = {
            "func": "start",
            "args": [],
            "kwargs": {
                "task_id": "task-valid",
                "params": VideoParams(video_subject="Tea").model_dump(
                    warnings=False
                ),
            },
        }
        self.redis_client.lpop.side_effect = [
            json.dumps(stale_payload),
            json.dumps(valid_payload),
        ]

        task = self.manager.dequeue()

        self.assertEqual(self.redis_client.lpop.call_count, 2)
        self.assertEqual(task["kwargs"]["task_id"], "task-valid")
        self.assertIsInstance(task["kwargs"]["params"], VideoParams)
        self.assertEqual(task["kwargs"]["params"].video_subject, "Tea")

    def test_dequeue_returns_none_when_every_queued_task_is_stale(self):
        """全部剩余任务都因当前校验规则被丢弃时，应返回 None 而不是抛出异常。"""
        stale_payload = {
            "func": "start",
            "args": [],
            "kwargs": {
                "task_id": "task-stale",
                "params": {**VideoParams(video_subject="Coffee").model_dump(
                    warnings=False
                ), "video_count": -1},
            },
        }
        self.redis_client.lpop.side_effect = [json.dumps(stale_payload), None]

        self.assertIsNone(self.manager.dequeue())
        self.assertEqual(self.redis_client.lpop.call_count, 2)

    def test_dequeue_marks_stale_task_failed_instead_of_leaving_it_processing(self):
        """
        任务状态记录在入队前就已创建，默认是 processing。仅仅在 dequeue 里跳过
        并丢弃这条队列项而不更新状态记录，会让这个任务在 API/WebUI 里永远显示
        为运行中。应该用 patch_task（而不是 update_task）把它标记为失败，
        这样如果任务已经被用户删除，我们不会又把它的状态记录建回来。
        """
        stale_payload = {
            "func": "start",
            "args": [],
            "kwargs": {
                "task_id": "task-stale",
                "params": {**VideoParams(video_subject="Coffee").model_dump(
                    warnings=False
                ), "video_count": 0},
            },
        }
        self.redis_client.lpop.side_effect = [json.dumps(stale_payload), None]

        with patch("app.controllers.manager.redis_manager.sm.state") as state:
            state.patch_task.return_value = True
            result = self.manager.dequeue()

        self.assertIsNone(result)
        state.patch_task.assert_called_once()
        call_args = state.patch_task.call_args
        self.assertEqual(call_args.args[0], "task-stale")
        self.assertEqual(call_args.kwargs["state"], const.TASK_STATE_FAILED)
        self.assertEqual(call_args.kwargs["failed_stage"], "dequeue")
        self.assertIn("video_count", call_args.kwargs["error"])

    def test_dequeue_does_not_recreate_state_for_already_deleted_task(self):
        """patch_task 在任务已被删除时返回 False；dequeue 不应把它当成错误处理。"""
        stale_payload = {
            "func": "start",
            "args": [],
            "kwargs": {
                "task_id": "task-deleted",
                "params": {**VideoParams(video_subject="Coffee").model_dump(
                    warnings=False
                ), "video_count": 0},
            },
        }
        self.redis_client.lpop.side_effect = [json.dumps(stale_payload), None]

        with patch("app.controllers.manager.redis_manager.sm.state") as state:
            state.patch_task.return_value = False
            result = self.manager.dequeue()

        self.assertIsNone(result)
        state.patch_task.assert_called_once()
        state.update_task.assert_not_called()

    def test_dequeue_skips_task_with_unknown_function_name(self):
        """
        FUNC_MAP 的成员会随部署变化（本文件里就保留着被注释掉的第二个入口），
        队列里可能残留旧入口函数的任务。对不在 FUNC_MAP 中的名称直接索引会抛
        KeyError，绕过 dequeue 自己的丢弃策略，因此必须和校验失败路径一样跳过它。
        """
        self.redis_client.lpop.side_effect = [
            _queued_payload("start_test", task_id="task-unknown-func"),
            _queued_payload("start", task_id="task-valid", params=_video_params()),
        ]

        with patch("app.controllers.manager.redis_manager.sm.state") as state:
            state.patch_task.return_value = True
            task = self.manager.dequeue()

        self.assertEqual(self.redis_client.lpop.call_count, 2)
        self.assertIs(task["func"], task_service.start)
        self.assertEqual(task["kwargs"]["task_id"], "task-valid")
        state.patch_task.assert_called_once()
        call_args = state.patch_task.call_args
        self.assertEqual(call_args.args[0], "task-unknown-func")
        self.assertEqual(call_args.kwargs["state"], const.TASK_STATE_FAILED)
        self.assertIn("start_test", call_args.kwargs["error"])

    def test_dequeue_skips_every_unusable_payload_shape(self):
        """
        队列里可能残留三种不可用条目：写入被截断的 JSON、不是对象的 JSON、以及
        引用了已移除入口函数（FUNC_MAP 里只留下注释）的任务。它们都不能把异常
        抛出 dequeue，否则排在后面的可用任务再也不会被调度；其中能读出 task_id
        的条目还要把已经永久离开队列的任务收敛为失败。
        """
        self.redis_client.lpop.side_effect = [
            '{"func": "start", "args": [',
            json.dumps(["not", "a", "mapping"]),
            _queued_payload("retired-entry", task_id="task-retired"),
            _queued_payload("start", task_id="task-valid", params=_video_params()),
        ]

        with patch("app.controllers.manager.redis_manager.sm.state") as state:
            state.patch_task.return_value = True
            task = self.manager.dequeue()

        self.assertEqual(self.redis_client.lpop.call_count, 4)
        self.assertIs(task["func"], task_service.start)
        self.assertEqual(task["kwargs"]["task_id"], "task-valid")
        state.patch_task.assert_called_once()
        self.assertEqual(state.patch_task.call_args.args[0], "task-retired")
        self.assertEqual(
            state.patch_task.call_args.kwargs["state"], const.TASK_STATE_FAILED
        )

    def test_dequeue_returns_none_when_only_unusable_entries_remain(self):
        """剩余条目全部不可用时，应返回 None 而不是抛出异常。"""
        self.redis_client.lpop.side_effect = [
            _queued_payload("retired-entry"),
            None,
        ]

        with patch("app.controllers.manager.redis_manager.sm.state") as state:
            result = self.manager.dequeue()

        self.assertIsNone(result)
        self.assertEqual(self.redis_client.lpop.call_count, 2)
        state.patch_task.assert_not_called()

    def test_task_done_keeps_draining_queue_when_entry_is_unusable(self):
        """
        跑完的任务释放名额后由 task_done 触发 check_queue 调度下一个任务。如果
        不可用条目让 check_queue 抛异常，异常会顺着 run_task 的 finally 把工作
        线程带崩；此后已没有任务在运行，也就不会有人再调用 check_queue，队列里
        后面的任务会永久停在 processing。因此 task_done 必须能继续调度下一个
        可用任务，而不是把整个队列留在原地。
        """
        self.manager.current_tasks = 1
        self.redis_client.lpop.side_effect = [
            _queued_payload("retired-entry"),
            _queued_payload("start", task_id="task-next", params=_video_params()),
        ]

        with patch.object(self.manager, "execute_task") as execute_task:
            self.manager.task_done()

        self.assertEqual(self.manager.current_tasks, 1)
        self.assertEqual(execute_task.call_args.kwargs["task_id"], "task-next")
        self.assertIs(execute_task.call_args.args[0], task_service.start)

    def test_dequeue_discards_payloads_that_cannot_be_dispatched(self):
        """
        三种能通过解析、却无法派发的条目：lpop 返回空值、args 写成 null / 对象 /
        数字 / 字符串。它们都不能让 dequeue 抛异常、也不能被当成"队列空了"——
        否则 check_queue 会重新入队或直接早退，后面排着的可用任务再也调度不到。
        """
        cases = (
            ("empty bytes", b"", None),
            ("empty string", "", None),
            ("args null", {"args": None}, "t-1"),
            ("args mapping", {"args": {}}, "t-2"),
            ("args number", {"args": 5}, "t-3"),
            ("args string", {"args": "x"}, "t-4"),
        )

        for case, broken, expected_task_id in cases:
            with self.subTest(case=case):
                if isinstance(broken, dict):
                    broken = json.dumps(
                        {
                            "func": "start",
                            "kwargs": {"task_id": expected_task_id},
                            **broken,
                        }
                    )
                self.redis_client.reset_mock()
                self.redis_client.lpop.side_effect = [
                    broken,
                    _queued_payload(
                        "start", task_id="task-valid", params=_video_params()
                    ),
                ]

                with patch("app.controllers.manager.redis_manager.sm.state") as state:
                    state.patch_task.return_value = True
                    task = self.manager.dequeue()

                self.assertEqual(self.redis_client.lpop.call_count, 2)
                self.assertEqual(task["kwargs"]["task_id"], "task-valid")
                self.assertIs(task["func"], task_service.start)
                if expected_task_id is None:
                    state.patch_task.assert_not_called()
                else:
                    self.assertEqual(
                        state.patch_task.call_args.args[0], expected_task_id
                    )
                    self.assertIn(
                        "positional arguments",
                        state.patch_task.call_args.kwargs["error"],
                    )

    def test_dequeue_dispatches_payload_without_args_field(self):
        """args 字段整体缺失是既有格式（check_queue 取默认空元组），不能被丢掉。"""
        self.redis_client.lpop.return_value = json.dumps(
            {
                "func": "start",
                "kwargs": {"task_id": "task-no-args", "params": _video_params()},
            }
        )

        with patch("app.controllers.manager.redis_manager.sm.state") as state:
            task = self.manager.dequeue()

        self.assertEqual(task["kwargs"]["task_id"], "task-no-args")
        self.assertIs(task["func"], task_service.start)
        state.patch_task.assert_not_called()

    def test_dequeue_ignores_non_string_task_id_in_every_discard_path(self):
        """
        task_id 是 JSON 数组 / 对象这类非字符串值时，交给 patch_task 会让 redis
        抛 DataError，把丢弃循环打断在一条坏条目上，后面排着的可用任务因此起不来。
        两条丢弃路径都要跳过状态回写，只丢弃条目本身。
        """
        cases = (
            ("unknown function", _queued_payload("retired-entry", task_id=["task-1"])),
            (
                "stale params",
                _queued_payload(
                    "start",
                    task_id={"nested": "task-2"},
                    params={**_video_params(), "video_count": 0},
                ),
            ),
        )

        for case, payload in cases:
            with self.subTest(case=case):
                self.redis_client.reset_mock()
                self.redis_client.lpop.side_effect = [
                    payload,
                    _queued_payload(
                        "start", task_id="task-valid", params=_video_params()
                    ),
                ]

                with patch("app.controllers.manager.redis_manager.sm.state") as state:
                    task = self.manager.dequeue()

                self.assertEqual(self.redis_client.lpop.call_count, 2)
                self.assertEqual(task["kwargs"]["task_id"], "task-valid")
                state.patch_task.assert_not_called()
                state.update_task.assert_not_called()


if __name__ == "__main__":
    unittest.main()
