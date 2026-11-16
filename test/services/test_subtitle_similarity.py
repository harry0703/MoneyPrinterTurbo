import sys
import unittest
from pathlib import Path

# 允许从仓库根目录直接运行本文件。
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import subtitle


class TestSubtitleSimilarityBoundaries(unittest.TestCase):
    """correct() 用 similarity() 决定是否合并相邻字幕，结果必须始终有定义。"""

    def test_two_empty_strings_are_identical(self):
        self.assertEqual(subtitle.similarity("", ""), 1.0)

    def test_one_empty_string_has_zero_similarity(self):
        self.assertEqual(subtitle.similarity("", "hello"), 0.0)
        self.assertEqual(subtitle.similarity("hello", ""), 0.0)

    def test_case_folding_that_grows_text_stays_within_range(self):
        # U+0130 (LATIN CAPITAL LETTER I WITH DOT ABOVE) 折叠后是 "i" + U+0307，
        # 长度从 1 变成 2，旧实现用折叠前的长度作分母会得到负的相似度。
        self.assertEqual(len("İ".lower()), 2)
        for left, right in (
            ("İ", ""),
            ("", "İ"),
            ("İ", "i"),
            ("İstanbul", "istanbul"),
        ):
            with self.subTest(left=left, right=right):
                score = subtitle.similarity(left, right)
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 1.0)

    def test_existing_matching_behaviour_is_unchanged(self):
        self.assertEqual(subtitle.similarity("Hello", "hello"), 1.0)
        self.assertEqual(subtitle.similarity("same", "same"), 1.0)
        self.assertLess(subtitle.similarity("hello", "world"), 0.5)

    def test_similarity_is_symmetric_for_case_folded_input(self):
        self.assertEqual(subtitle.similarity("İ", "i"), subtitle.similarity("i", "İ"))


if __name__ == "__main__":
    unittest.main()
