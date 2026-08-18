import subprocess
import sys
import textwrap
import unittest
from unittest.mock import patch

from app.models import const
from app.models.schema import VideoParams
from app.services import generation_lock
from app.services import task as task_service
from app.utils import utils


class TestGenerationLock(unittest.TestCase):
    def test_lock_can_be_reacquired_after_release(self):
        """正常释放后必须能再次加锁，否则一次生成就会永久占用主机。"""
        with generation_lock.acquire():
            pass

        with generation_lock.acquire():
            pass

    def test_second_acquisition_is_rejected_while_held(self):
        """持有期间的第二次加锁必须立即失败，而不是排队等待。"""
        with generation_lock.acquire():
            with self.assertRaises(generation_lock.GenerationBusyError):
                with generation_lock.acquire():
                    pass

    def test_lock_is_released_when_body_raises(self):
        """流水线异常不能让锁泄漏，否则后续任务全部无法启动。"""
        with self.assertRaises(ValueError):
            with generation_lock.acquire():
                raise ValueError("pipeline exploded")

        with generation_lock.acquire():
            pass

    def test_busy_error_reports_current_owner(self):
        """失败信息需要指明持有者，方便判断是 CLI 还是 WebUI 正在生成。"""
        with generation_lock.acquire():
            with self.assertRaises(generation_lock.GenerationBusyError) as ctx:
                with generation_lock.acquire():
                    pass

        self.assertIn("pid=", str(ctx.exception))

    def test_lock_is_released_when_owner_process_dies(self):
        """进程被杀死后操作系统必须自动释放锁，不能留下死锁文件。"""
        script = textwrap.dedent(
            """
            import os, sys, time
            sys.path.insert(0, os.getcwd())
            from app.services import generation_lock
            with generation_lock.acquire():
                print("HELD", flush=True)
                time.sleep(60)
            """
        )
        process = subprocess.Popen(
            [sys.executable, "-c", script],
            cwd=utils.root_dir(),
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            self.assertEqual(process.stdout.readline().strip(), "HELD")
            with self.assertRaises(generation_lock.GenerationBusyError):
                with generation_lock.acquire():
                    pass
        finally:
            process.kill()
            process.wait(timeout=30)

        # 进程消失后锁必须立刻可用。
        with generation_lock.acquire():
            pass


class TestTaskStartConcurrency(unittest.TestCase):
    def test_start_fails_fast_when_another_generation_runs(self):
        """并发请求必须在消耗 LLM、TTS 额度之前就被拒绝。"""
        with generation_lock.acquire():
            with patch.object(task_service, "_run_pipeline") as run_pipeline:
                result = task_service.start(
                    "concurrent-task",
                    VideoParams(video_subject="test"),
                    stop_at="script",
                )

        run_pipeline.assert_not_called()
        self.assertEqual(result["state"], const.TASK_STATE_FAILED)
        self.assertEqual(result["failed_stage"], "preflight")
        self.assertIn("already running", result["error"])

    def test_start_runs_pipeline_when_lock_is_free(self):
        """没有并发时不得引入额外限制，流水线必须照常执行。"""
        with patch.object(
            task_service, "_run_pipeline", return_value={"script": "ok"}
        ) as run_pipeline:
            result = task_service.start(
                "free-task",
                VideoParams(video_subject="test"),
                stop_at="script",
            )

        run_pipeline.assert_called_once()
        self.assertEqual(result, {"script": "ok"})


if __name__ == "__main__":
    unittest.main()
