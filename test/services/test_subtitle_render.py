import os
import unittest

import numpy as np
from PIL import Image, ImageDraw

from app.services.utils import subtitle_render
from app.utils import utils

FONT = os.path.join(utils.font_dir(), "BeVietnamPro-Bold.ttf")


def _opaque_columns(frame: np.ndarray) -> np.ndarray:
    """返回每一列是否有可见像素，用于判断内容的水平分布。"""
    return frame[..., 3].max(axis=0) > 0


class RenderCaptionTest(unittest.TestCase):
    def _render(self, words, active_index, **kwargs):
        options = {
            "font_path": FONT,
            "font_size": 80,
            "max_width": 900,
            "stroke_width": 6,
        }
        options.update(kwargs)
        return subtitle_render.render_caption(
            words=words, active_index=active_index, **options
        )

    def test_returns_rgba_with_transparent_background(self):
        """字幕要叠加在画面上，背景必须完全透明而不是黑底。"""
        frame = self._render(["OF", "THE", "WORLD"], 0)
        self.assertEqual(frame.shape[2], 4)
        self.assertEqual(frame[0, 0, 3], 0)

    def test_highlight_colour_is_present_only_when_a_word_is_active(self):
        highlighted = self._render(["one", "two"], 0, highlight_color="#FF0000")
        plain = self._render(["one", "two"], -1, highlight_color="#FF0000")

        def has_red(frame):
            visible = frame[frame[..., 3] > 0]
            return bool(
                np.any(
                    (visible[:, 0] > 200) & (visible[:, 1] < 60) & (visible[:, 2] < 60)
                )
            )

        self.assertTrue(has_red(highlighted))
        self.assertFalse(has_red(plain))

    def test_highlight_moves_with_the_active_index(self):
        """高亮块必须跟着朗读位置走，否则强调的是错误的词。"""
        first = self._render(["AAA", "BBB", "CCC"], 0, highlight_color="#FF0000")
        last = self._render(["AAA", "BBB", "CCC"], 2, highlight_color="#FF0000")

        def red_center(frame):
            mask = (
                (frame[..., 0] > 200) & (frame[..., 1] < 60)
                & (frame[..., 2] < 60) & (frame[..., 3] > 0)
            )
            return mask.nonzero()[1].mean()

        self.assertLess(red_center(first), red_center(last))

    def test_uppercase_option_changes_the_rendering(self):
        lower = self._render(["word"], -1, uppercase=False)
        upper = self._render(["word"], -1, uppercase=True)
        self.assertFalse(np.array_equal(lower, upper))

    def test_long_words_wrap_instead_of_overflowing(self):
        """大字号下三个长单词放不进一行，必须折行而不是被裁掉。"""
        narrow = self._render(
            ["extraordinary", "circumstances", "everywhere"], 0, max_width=600
        )
        single = self._render(["short"], 0, max_width=600)
        self.assertGreater(narrow.shape[0], single.shape[0])

    def test_empty_input_does_not_crash(self):
        frame = subtitle_render.render_caption(
            words=[], active_index=0, font_path=FONT, font_size=80, max_width=900
        )
        self.assertEqual(frame.shape[2], 4)

    def test_content_stays_inside_the_canvas(self):
        """内容超出画布就会在成片里被裁掉，必须留在边界内。"""
        frame = self._render(["OF", "THE", "WORLD"], 2)
        columns = _opaque_columns(frame)
        self.assertTrue(columns.any())
        self.assertFalse(columns[-1], "content touches the right edge")


class LayoutTest(unittest.TestCase):
    def setUp(self):
        from PIL import ImageFont

        self.font = ImageFont.truetype(FONT, 80)
        self.draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    def test_words_that_fit_stay_on_one_line(self):
        lines = subtitle_render.layout_words(
            ["a", "b"], self.font, self.draw, 900, 6, 20
        )
        self.assertEqual(len(lines), 1)

    def test_every_word_is_kept_when_wrapping(self):
        words = ["alpha", "bravo", "charlie", "delta", "echo"]
        lines = subtitle_render.layout_words(
            words, self.font, self.draw, 400, 6, 20
        )
        flattened = [word for line in lines for word, _ in line]
        self.assertEqual(flattened, words)


class WordIntervalTest(unittest.TestCase):
    def test_intervals_cover_the_whole_span_without_gaps(self):
        intervals = subtitle_render.split_word_intervals(["a", "bb", "ccc"], 2.0, 5.0)
        self.assertEqual(intervals[0][0], 2.0)
        self.assertEqual(intervals[-1][1], 5.0)
        for previous, current in zip(intervals, intervals[1:]):
            self.assertEqual(previous[1], current[0])

    def test_longer_words_get_more_time(self):
        short, long = subtitle_render.split_word_intervals(["a", "abcdefgh"], 0.0, 1.0)
        self.assertLess(short[1] - short[0], long[1] - long[0])

    def test_empty_input_returns_no_interval(self):
        self.assertEqual(subtitle_render.split_word_intervals([], 0.0, 1.0), [])


if __name__ == "__main__":
    unittest.main()
