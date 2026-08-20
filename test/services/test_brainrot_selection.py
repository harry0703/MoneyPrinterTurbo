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


if __name__ == "__main__":
    unittest.main()
