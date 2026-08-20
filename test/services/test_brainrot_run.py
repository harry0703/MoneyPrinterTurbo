import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location(
    "brainrot_run", os.path.join(ROOT, "scripts", "brainrot_run.py")
)
runner = importlib.util.module_from_spec(_spec)
sys.modules["brainrot_run"] = runner
_spec.loader.exec_module(runner)


class CaptionTest(unittest.TestCase):
    def test_the_card_line_opens_the_caption(self):
        """卡片上写的那句就是标题，读者先看到的必须是它。"""
        caption = runner.build_caption("some line", 0)
        self.assertTrue(caption.startswith("some line"))

    def test_the_account_lines_are_present(self):
        caption = runner.build_caption("x", 0)
        for line in runner.load_caption_profile()["tagline"]:
            self.assertIn(line, caption)

    def test_five_hashtags_two_of_them_fixed(self):
        tags = runner.build_caption("x", 0).split("\n")[-1].split()
        self.assertEqual(len(tags), 5)
        self.assertEqual(tags[:2], runner.load_caption_profile()["hashtag_core"])

    def test_the_rotating_tags_move_with_the_index(self):
        """每条都挂同一串标签，正是平台判定模板化生产的依据。"""
        first = runner.build_caption("x", 0).split("\n")[-1]
        second = runner.build_caption("x", 1).split("\n")[-1]
        self.assertNotEqual(first, second)

    def test_every_hashtag_starts_with_a_hash(self):
        profile = runner.load_caption_profile()
        for tag in profile["hashtag_core"] + profile["hashtag_pool"]:
            self.assertTrue(tag.startswith("#"), tag)


class NextTextTest(unittest.TestCase):
    def test_the_index_selects_the_line(self):
        self.assertNotEqual(runner.next_text(0), runner.next_text(1))

    def test_an_exhausted_pool_reads_as_empty(self):
        self.assertEqual(runner.next_text(10**6), "")


class WaitForLockTest(unittest.TestCase):
    def test_a_free_lock_returns_at_once(self):
        with patch.object(runner, "generation_busy", return_value=""):
            slept = []
            self.assertTrue(runner.wait_for_lock(600, 60, sleep=slept.append))
        self.assertEqual(slept, [])

    def test_it_waits_and_then_proceeds(self):
        """中午那一轮要跑两个多小时，直接放弃就白白少发一条。"""
        answers = ["busy", "busy", ""]
        with patch.object(runner, "generation_busy", side_effect=answers):
            slept = []
            self.assertTrue(runner.wait_for_lock(600, 60, sleep=slept.append))
        self.assertEqual(slept, [60, 60])

    def test_it_gives_up_once_the_budget_is_spent(self):
        with patch.object(runner, "generation_busy", return_value="busy"):
            slept = []
            self.assertFalse(runner.wait_for_lock(120, 60, sleep=slept.append))
        self.assertEqual(slept, [60, 60])

    def test_giving_up_is_not_reported_as_a_failure(self):
        """撞锁不是错误，退出码必须和真正的失败分开。"""
        self.assertNotEqual(runner.EXIT_BUSY, 1)
        self.assertNotEqual(runner.EXIT_BUSY, 0)


class StateTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        from app.utils import utils
        storage = patch.object(utils, "storage_dir", return_value=self.temp_dir)
        storage.start()
        self.addCleanup(storage.stop)

    def test_publishing_appends_without_touching_the_cursors(self):
        """发布记录不能覆盖素材与文案的游标，否则下一条会重复。"""
        with open(runner.state_path(), "w", encoding="utf-8") as handle:
            json.dump({"used_bait": ["a.mp4"], "text_index": 3}, handle)

        runner.record_published("/x/one.mp4", "https://example.test/p/1")
        state = runner.read_state()
        self.assertEqual(state["text_index"], 3)
        self.assertEqual(state["used_bait"], ["a.mp4"])
        self.assertEqual(state["published"][0]["url"], "https://example.test/p/1")

    def test_records_accumulate(self):
        runner.record_published("/x/one.mp4", "u1")
        runner.record_published("/x/two.mp4", "u2")
        self.assertEqual(len(runner.read_state()["published"]), 2)

    def test_no_temporary_file_is_left_behind(self):
        runner.record_published("/x/one.mp4", "u1")
        leftovers = [n for n in os.listdir(self.temp_dir) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])


class PendingTest(unittest.TestCase):
    """
    渲染一成功游标就前进了，而发布可能因为会话失效或限流失败。没有这条记录，
    下一轮会另起一条新视频，做好的那条就白费——诱饵素材只有十几条。
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.video = os.path.join(self.temp_dir, "a.mp4")
        open(self.video, "wb").close()

        from app.utils import utils
        storage = patch.object(utils, "storage_dir", return_value=self.temp_dir)
        storage.start()
        self.addCleanup(storage.stop)

    def test_a_pending_render_is_picked_up_again(self):
        runner.set_pending(self.video, "caption")
        self.assertEqual(runner.take_pending()["video"], self.video)

    def test_the_caption_survives_with_it(self):
        """重发时必须用当初那条卡片文字，不是下一条。"""
        runner.set_pending(self.video, "the original line")
        self.assertEqual(runner.take_pending()["caption"], "the original line")

    def test_a_deleted_file_is_not_retried_forever(self):
        runner.set_pending(os.path.join(self.temp_dir, "gone.mp4"), "c")
        self.assertEqual(runner.take_pending(), {})

    def test_nothing_pending_reads_as_empty(self):
        self.assertEqual(runner.take_pending(), {})

    def test_publishing_clears_it(self):
        runner.set_pending(self.video, "caption")
        runner.record_published(self.video, "https://example.test/p/1")
        self.assertEqual(runner.take_pending(), {})

    def test_setting_it_does_not_disturb_the_cursors(self):
        with open(runner.state_path(), "w", encoding="utf-8") as handle:
            json.dump({"used_bait": ["a.mp4"], "text_index": 3}, handle)
        runner.set_pending(self.video, "caption")
        self.assertEqual(runner.read_state()["text_index"], 3)


class FinishTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        from app.utils import utils
        storage = patch.object(utils, "storage_dir", return_value=self.temp_dir)
        storage.start()
        self.addCleanup(storage.stop)

    def test_a_failed_publish_keeps_it_pending(self):
        """会话失效和限流都是暂时的，下一轮应当接着发同一条。"""
        video = os.path.join(self.temp_dir, "a.mp4")
        open(video, "wb").close()
        runner.set_pending(video, "caption")

        with patch.object(runner, "publish", return_value={"ok": False}):
            self.assertEqual(runner.finish(video, "caption"), 1)
        self.assertEqual(runner.take_pending()["video"], video)

    def test_a_successful_publish_clears_it(self):
        video = os.path.join(self.temp_dir, "a.mp4")
        open(video, "wb").close()
        runner.set_pending(video, "caption")

        with patch.object(runner, "publish", return_value={"url": "u"}):
            self.assertEqual(runner.finish(video, "caption"), 0)
        self.assertEqual(runner.take_pending(), {})


class PublishTest(unittest.TestCase):
    class Completed:
        def __init__(self, stdout, returncode=0, stderr=""):
            self.stdout, self.returncode, self.stderr = stdout, returncode, stderr

    def test_the_result_is_read_from_the_last_json_line(self):
        """发布脚本会先打日志再打结果，只有最后一行是 JSON。"""
        stdout = "load config from file\nINFO something\n" \
                 '{"url": "https://example.test/p/1"}\n'
        with patch.object(runner.subprocess, "run",
                          return_value=self.Completed(stdout)):
            self.assertEqual(
                runner.publish("/x/a.mp4", "caption")["url"],
                "https://example.test/p/1",
            )

    def test_an_error_result_is_returned_not_swallowed(self):
        stdout = '{"ok": false, "error_type": "rate_limit", "error": "429"}\n'
        with patch.object(runner.subprocess, "run",
                          return_value=self.Completed(stdout, returncode=1)):
            result = runner.publish("/x/a.mp4", "caption")
        self.assertEqual(result["error_type"], "rate_limit")

    def test_output_without_json_raises_instead_of_reporting_success(self):
        with patch.object(runner.subprocess, "run",
                          return_value=self.Completed("", 1, "boom")):
            with self.assertRaises(RuntimeError):
                runner.publish("/x/a.mp4", "caption")


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.out = os.path.join(self.temp_dir, "out.mp4")

    def test_metadata_comes_from_the_sidecar_not_from_stdout(self):
        """文案要进标题，靠解析标准输出会在格式一变时悄悄配错。"""
        with open(os.path.splitext(self.out)[0] + ".json", "w",
                  encoding="utf-8") as handle:
            json.dump({"text": "a line", "style": "rush"}, handle)

        class Completed:
            returncode = 0

        with patch.object(runner.subprocess, "run", return_value=Completed()):
            meta = runner.render(self.out, [])
        self.assertEqual(meta["text"], "a line")

    def test_a_failed_render_raises(self):
        class Completed:
            returncode = 1

        with patch.object(runner.subprocess, "run", return_value=Completed()):
            with self.assertRaises(RuntimeError):
                runner.render(self.out, [])


if __name__ == "__main__":
    unittest.main()
