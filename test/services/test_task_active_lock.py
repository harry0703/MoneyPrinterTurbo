import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import task as tm


class TestTaskActiveLockCrossProcess(unittest.TestCase):
    """
    With the default enable_redis=false config, each process (API, WebUI,
    CLI) keeps its own isolated in-memory task registry. A task started by
    one process is invisible to is_task_busy() calls made from another --
    the on-disk lock written by _mark_task_active()/_clear_task_active()
    (used by start()) is the one signal every process can see.
    """

    def setUp(self):
        self.task_id = f"test-active-lock-{int(time.time() * 1000)}"

    def tearDown(self):
        tm._clear_task_active(self.task_id)

    def test_no_lock_means_not_actively_running(self):
        self.assertFalse(tm.is_task_actively_running(self.task_id))

    def test_lock_present_means_actively_running(self):
        tm._mark_task_active(self.task_id)
        self.assertTrue(tm.is_task_actively_running(self.task_id))

    def test_clear_removes_the_lock(self):
        tm._mark_task_active(self.task_id)
        tm._clear_task_active(self.task_id)
        self.assertFalse(tm.is_task_actively_running(self.task_id))

    def test_stale_lock_is_not_treated_as_active(self):
        # A process that dies without reaching start()'s finally block
        # (kill -9, OOM, host reboot) leaves the lock file behind forever.
        tm._mark_task_active(self.task_id)
        stale_time = time.time() - (tm._ACTIVE_LOCK_STALE_SECONDS + 60)
        os.utime(tm._active_lock_path(self.task_id), (stale_time, stale_time))
        self.assertFalse(tm.is_task_actively_running(self.task_id))

    def test_start_holds_the_lock_for_the_whole_pipeline_duration(self):
        # Models the maintainer's repro: start() is paused mid-pipeline in
        # one process; a different process (or this same test, standing in
        # for it) must see the task as actively running for that whole
        # window, and see it clear once the pipeline returns.
        release_pipeline = mock.Mock()

        def paused_pipeline(*_args, **_kwargs):
            self.assertTrue(
                tm.is_task_actively_running(self.task_id),
                "lock must already be held once the pipeline starts running",
            )
            release_pipeline()
            return "ok"

        with mock.patch.object(tm, "_run_pipeline", side_effect=paused_pipeline):
            result = tm.start(self.task_id, params=mock.Mock())

        release_pipeline.assert_called_once()
        self.assertEqual(result, "ok")
        self.assertFalse(
            tm.is_task_actively_running(self.task_id),
            "lock must be cleared once start() returns",
        )

    def test_start_clears_the_lock_even_on_pipeline_exception(self):
        with mock.patch.object(tm, "_run_pipeline", side_effect=RuntimeError("boom")):
            with mock.patch.object(tm, "_mark_task_failed") as mark_failed:
                tm.start(self.task_id, params=mock.Mock())
                mark_failed.assert_called_once()

        self.assertFalse(
            tm.is_task_actively_running(self.task_id),
            "lock must be cleared even when the pipeline raises",
        )


if __name__ == "__main__":
    unittest.main()
