import unittest
import sys
from pathlib import Path

# add project root to python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import task as tm


class TestIsTaskBusyDefensiveDefault(unittest.TestCase):
    """is_task_busy() must keep tasks whose state is unparseable."""

    def setUp(self):
        # The registry is process-wide; clear it so cross-post futures
        # left behind by earlier tests cannot affect the assertions.
        with tm._cross_post_registry_lock:
            tm._cross_post_futures.clear()

    def tearDown(self):
        with tm._cross_post_registry_lock:
            tm._cross_post_futures.clear()

    def test_string_state_is_treated_as_busy(self):
        # Older Redis snapshots can surface the state as a string. The
        # delete endpoint must not be allowed to cancel a task whose
        # state cannot be parsed.
        self.assertTrue(tm.is_task_busy({"state": "processing"}))
        self.assertTrue(tm.is_task_busy({"state": "4"}))
        self.assertTrue(tm.is_task_busy({"state": "PROCESSING"}))

    def test_none_state_is_treated_as_busy(self):
        # A missing or None state still implies a task we cannot reason
        # about, so the conservative default must apply.
        self.assertTrue(tm.is_task_busy({"state": None}))
        self.assertTrue(tm.is_task_busy({"state": "not-an-int"}))

    def test_string_state_with_idle_cross_post_still_busy(self):
        # The previous code path returned False here, which let the
        # delete API silently cancel in-flight tasks.
        self.assertTrue(
            tm.is_task_busy(
                {
                    "state": "processing",
                    "cross_post_state": tm.const.CROSS_POST_STATE_COMPLETE,
                }
            )
        )

    def test_integer_processing_state_remains_busy(self):
        # Existing happy path stays unchanged.
        self.assertTrue(tm.is_task_busy({"state": tm.const.TASK_STATE_PROCESSING}))

    def test_integer_complete_with_idle_cross_post_remains_idle(self):
        # Existing happy path stays unchanged.
        self.assertFalse(
            tm.is_task_busy(
                {
                    "state": tm.const.TASK_STATE_COMPLETE,
                    "cross_post_state": tm.const.CROSS_POST_STATE_COMPLETE,
                }
            )
        )

    def test_none_task_remains_idle(self):
        # The existing None guard at the top of is_task_busy still wins.
        self.assertFalse(tm.is_task_busy(None))


if __name__ == "__main__":
    unittest.main()
