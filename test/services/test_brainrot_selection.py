import importlib.util
import json
import os
import random
import sys
import tempfile
import unittest
from collections import Counter
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location(
    "make_brainrot", os.path.join(ROOT, "scripts", "make_brainrot.py")
)
brainrot = importlib.util.module_from_spec(_spec)
sys.modules["make_brainrot"] = brainrot
_spec.loader.exec_module(brainrot)


class WeightedStyleTest(unittest.TestCase):
    def test_weights_sum_to_a_hundred(self):
        """权重直接当百分比读，加起来不是 100 就没人能预期实际比例。"""
        self.assertEqual(sum(brainrot.STYLE_WEIGHTS.values()), 100)

    def test_every_weighted_style_exists(self):
        for name in brainrot.STYLE_WEIGHTS:
            self.assertIn(name, brainrot.STYLES)

    def test_observed_share_matches_the_weights(self):
        counts = Counter(
            brainrot.weighted_style(random.Random(seed)) for seed in range(20000)
        )
        for name, weight in brainrot.STYLE_WEIGHTS.items():
            self.assertAlmostEqual(counts[name] / 20000 * 100, weight, delta=2.0)

    def test_the_draw_is_reproducible(self):
        self.assertEqual(
            brainrot.weighted_style(random.Random(4)),
            brainrot.weighted_style(random.Random(4)),
        )


class NextBaitTest(unittest.TestCase):
    CLIPS = ["/b/a.mp4", "/b/b.mp4", "/b/c.mp4"]

    def test_the_first_run_takes_the_first_clip(self):
        self.assertEqual(brainrot.next_bait(self.CLIPS, []), "/b/a.mp4")

    def test_used_clips_are_skipped(self):
        self.assertEqual(brainrot.next_bait(self.CLIPS, ["a.mp4"]), "/b/b.mp4")

    def test_clips_are_never_reused(self):
        """重复投放同一素材正是平台判定模板化生产的依据。"""
        used, seen = [], []
        while True:
            clip = brainrot.next_bait(self.CLIPS, used)
            if not clip:
                break
            seen.append(clip)
            used.append(os.path.basename(clip))
        self.assertEqual(sorted(seen), sorted(self.CLIPS))

    def test_an_exhausted_pool_returns_nothing(self):
        used = [os.path.basename(clip) for clip in self.CLIPS]
        self.assertEqual(brainrot.next_bait(self.CLIPS, used), "")

    def test_matching_is_by_basename_not_full_path(self):
        """状态里存的是文件名，移动目录不该让素材重新变成"没用过"。"""
        self.assertEqual(brainrot.next_bait(["/other/a.mp4"], ["a.mp4"]), "")


class StateTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        from app.utils import utils
        storage = patch.object(utils, "storage_dir", return_value=self.temp_dir)
        storage.start()
        self.addCleanup(storage.stop)

    def test_a_missing_state_reads_as_empty(self):
        self.assertEqual(brainrot.load_state(), {})

    def test_state_survives_a_round_trip(self):
        brainrot.save_state({"used_bait": ["a.mp4"], "text_index": 1})
        self.assertEqual(brainrot.load_state()["text_index"], 1)

    def test_corrupt_state_reads_as_empty_instead_of_crashing(self):
        path = os.path.join(self.temp_dir, brainrot.STATE_FILENAME)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(brainrot.load_state(), {})

    def test_no_temporary_file_is_left_behind(self):
        brainrot.save_state({"text_index": 3})
        leftovers = [n for n in os.listdir(self.temp_dir) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])


class TextsTest(unittest.TestCase):
    def test_the_pool_is_readable_and_not_empty(self):
        self.assertGreater(len(brainrot.load_texts()), 0)

    def test_blank_lines_are_dropped(self):
        """空行会渲染出一张什么都没有的卡片。"""
        with patch.object(brainrot, "project_root", return_value=self.temp()):
            self.assertEqual(brainrot.load_texts(), ["real line"])

    def temp(self):
        directory = tempfile.mkdtemp()
        with open(os.path.join(directory, brainrot.TEXTS_FILENAME), "w",
                  encoding="utf-8") as handle:
            json.dump({"texts": ["real line", "   ", ""]}, handle)
        return directory


class NextRunTest(unittest.TestCase):
    """
    --next 解析出来的文案必须真的传到渲染里。曾经有一版只更新了局部变量，
    渲染仍在读命令行参数，于是产出一批空白卡片的成片——日志看不出异常，
    只有打开视频才知道。
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.bait_dir = os.path.join(self.temp_dir, "bait")
        os.makedirs(self.bait_dir)
        for name in ("01.mp4", "02.mp4"):
            open(os.path.join(self.bait_dir, name), "wb").close()

        with open(os.path.join(self.temp_dir, brainrot.TEXTS_FILENAME), "w",
                  encoding="utf-8") as handle:
            json.dump({"texts": ["first line", "second line"]}, handle)

        from app.utils import utils
        storage = patch.object(utils, "storage_dir", return_value=self.temp_dir)
        storage.start()
        self.addCleanup(storage.stop)

        root = patch.object(brainrot, "project_root", return_value=self.temp_dir)
        root.start()
        self.addCleanup(root.stop)

        self.calls = []

        def fake_build(**kwargs):
            self.calls.append(kwargs)
            return 26.4

        build = patch.object(brainrot, "build_video", side_effect=fake_build)
        build.start()
        self.addCleanup(build.stop)

    def _run(self, *extra):
        return brainrot.main([
            "--next",
            "--bait-dir", self.bait_dir,
            "--out", os.path.join(self.temp_dir, "out.mp4"),
            *extra,
        ])

    def test_the_pooled_text_reaches_the_renderer(self):
        self._run()
        self.assertEqual(self.calls[0]["text"], "first line")

    def test_consecutive_runs_advance_both_indexes(self):
        self._run()
        self._run()
        self.assertEqual(self.calls[1]["text"], "second line")
        self.assertEqual(
            os.path.basename(self.calls[1]["bait_path"]), "02.mp4"
        )

    def test_an_explicit_text_still_wins(self):
        self._run("--text", "mine")
        self.assertEqual(self.calls[0]["text"], "mine")

    def test_an_explicit_style_still_wins(self):
        self._run("--style", "classic")
        self.assertEqual(self.calls[0]["cameos"], brainrot.STYLES["classic"].cameos)

    def test_an_exhausted_bait_folder_stops_instead_of_repeating(self):
        self._run()
        self._run()
        with self.assertRaises(SystemExit):
            self._run()

    def test_a_plain_run_still_gets_a_text(self):
        """不带 --next 时也不该被迫先想一句词。"""
        brainrot.main([
            "--bait-dir", self.bait_dir,
            "--bait-file", os.path.join(self.bait_dir, "01.mp4"),
            "--out", os.path.join(self.temp_dir, "out.mp4"),
        ])
        self.assertIn(self.calls[0]["text"], ["first line", "second line"])

    def test_a_plain_run_does_not_advance_the_index(self):
        """试渲染一条不该占用排期里的下一句。"""
        brainrot.main([
            "--bait-dir", self.bait_dir,
            "--bait-file", os.path.join(self.bait_dir, "01.mp4"),
            "--out", os.path.join(self.temp_dir, "out.mp4"),
        ])
        self._run()
        self.assertEqual(self.calls[1]["text"], "first line")

    def test_an_empty_pool_says_so_instead_of_rendering_a_blank_card(self):
        with open(os.path.join(self.temp_dir, brainrot.TEXTS_FILENAME), "w",
                  encoding="utf-8") as handle:
            json.dump({"texts": []}, handle)
        with self.assertRaises(SystemExit):
            brainrot.main([
                "--bait-dir", self.bait_dir,
                "--bait-file", os.path.join(self.bait_dir, "01.mp4"),
                "--out", os.path.join(self.temp_dir, "out.mp4"),
            ])

    def test_the_card_is_off_by_default(self):
        """文案默认只当标题：诱饵本身已经够无厘头，压张白卡反而像个模板。"""
        self._run()
        self.assertFalse(self.calls[0]["show_card"])

    def test_the_card_can_be_switched_back_on(self):
        self._run("--card")
        self.assertTrue(self.calls[0]["show_card"])

    def test_the_line_still_reaches_the_renderer_without_the_card(self):
        """卡片关掉了，但这条文案仍要写进旁边的 JSON 供发布时用。"""
        self._run()
        self.assertEqual(self.calls[0]["text"], "first line")

    def test_a_failed_render_does_not_consume_the_clip(self):
        """失败后重跑应当拿到同一条素材，而不是把它悄悄跳过。"""
        with patch.object(brainrot, "build_video", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self._run()
        self._run()
        self.assertEqual(self.calls[0]["text"], "first line")


if __name__ == "__main__":
    unittest.main()
