"""같은 작업이 두 번 제출되는 것을 막는다."""

import ast
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models import const
from app.models.schema import VideoParams
from app.services import state as sm
from app.services import webui_task


class TestDuplicateSubmit(unittest.TestCase):
    def setUp(self):
        self.params = VideoParams(video_subject="커피")
        sm.state.delete_task("same-task")

    def tearDown(self):
        sm.state.delete_task("same-task")

    def test_a_running_task_is_refused_but_a_finished_one_can_run_again(self):
        """
        페이지가 다시 실행되면서 같은 작업 ID 로 제출이 반복될 수 있다. 막지 않으면
        같은 영상을 만드는 렌더링이 여러 개 떠서 같은 출력 파일에 동시에 쓴다.

        그렇다고 영영 막으면 '다시 만들기' 가 사라진다. 돌고 있는 동안만 거절해야
        한다 — 세 번 제출했지만 실제로 도는 것은 두 번이어야 한다.
        """
        with patch.object(webui_task._task_manager, "add_task") as add_task:
            webui_task.submit_generation("same-task", self.params)
            webui_task.submit_generation("same-task", self.params)
            self.assertEqual(add_task.call_count, 1, "도는 중에 또 시작했다")

            sm.state.update_task("same-task", state=const.TASK_STATE_COMPLETE)
            webui_task.submit_generation("same-task", self.params)

        self.assertEqual(add_task.call_count, 2, "끝난 작업을 다시 만들 수 없다")

    def test_only_one_of_many_concurrent_submits_gets_through(self):
        """
        확인과 기록이 나뉘어 있으면 두 요청이 동시에 '비어 있다' 를 보고 둘 다
        시작한다. 페이지 rerun 이 겹치면 실제로 일어나는 일이다.
        """
        start = threading.Barrier(8)

        def submit():
            start.wait()
            webui_task.submit_generation("same-task", self.params)

        with patch.object(webui_task._task_manager, "add_task") as add_task:
            threads = [threading.Thread(target=submit) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        add_task.assert_called_once()


class TestPendingIdIsCleared(unittest.TestCase):
    def test_the_reserved_id_is_dropped_after_submitting(self):
        """
        예약해 둔 ID 가 남아 있으면, 버튼 상태가 살아 있는 다음 실행이 같은 ID 로
        다시 제출한다. 그러면 같은 작업이 겹쳐 뜬다.
        """
        source = Path("webui/Main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        cleared = any(
            isinstance(node, ast.Call)
            and getattr(node.func, "attr", "") == "pop"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "pending_generation_task_id"
            for node in ast.walk(tree)
        )
        self.assertTrue(cleared, "제출 후 예약 ID 를 비우지 않는다")


if __name__ == "__main__":
    unittest.main()
