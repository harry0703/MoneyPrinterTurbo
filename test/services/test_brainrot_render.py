import os
import unittest

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.services.utils import brainrot_render as render
from app.utils import utils

FONT = os.path.join(utils.font_dir(), "BeVietnamPro-Bold.ttf")


class TextCardTest(unittest.TestCase):
    def _card(self, text, **kwargs):
        options = {"font_path": FONT, "font_size": 48, "max_width": 660}
        options.update(kwargs)
        return render.render_text_card(text=text, **options)

    def test_card_is_rgba_with_transparent_corners(self):
        """卡片是圆角的，四角必须透明，否则会在画面上留下白色直角。"""
        card = self._card("hello")
        self.assertEqual(card.shape[2], 4)
        self.assertEqual(card[0, 0, 3], 0)

    def test_card_centre_is_opaque_white(self):
        card = self._card("hello")
        centre = card[card.shape[0] // 2, card.shape[1] // 2]
        self.assertEqual(centre[3], 255)
        self.assertGreater(int(centre[0]), 200)

    def test_long_text_wraps_and_grows_taller_not_wider(self):
        short = self._card("one line")
        long = self._card("how it feels to check the mail on a saturday morning alone")
        self.assertGreater(long.shape[0], short.shape[0])
        self.assertLessEqual(long.shape[1], 660)

    def test_card_never_exceeds_the_requested_width(self):
        card = self._card("a" * 200, max_width=500)
        self.assertLessEqual(card.shape[1], 500)

    def test_empty_text_does_not_crash(self):
        self.assertEqual(self._card("   ").shape[2], 4)


class WrapLinesTest(unittest.TestCase):
    def setUp(self):
        self.font = ImageFont.truetype(FONT, 48)
        self.draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    def test_every_word_is_kept(self):
        words = "the quick brown fox jumps over the lazy dog".split()
        lines = render.wrap_lines(" ".join(words), self.font, self.draw, 300)
        self.assertEqual(" ".join(lines).split(), words)

    def test_a_word_wider_than_the_box_is_split(self):
        """卡片宽度由最长的一行决定，放任超宽的词会把卡片撑出画面。"""
        lines = render.wrap_lines("hi supercalifragilistic", self.font, self.draw, 200)
        self.assertGreater(len(lines), 2)
        self.assertEqual("".join(lines).replace(" ", ""), "hisupercalifragilistic")
        for line in lines:
            self.assertLessEqual(self.draw.textlength(line, font=self.font), 200)

    def test_empty_input_returns_no_lines(self):
        self.assertEqual(render.wrap_lines("", self.font, self.draw, 300), [])


class PanelRectsTest(unittest.TestCase):
    def test_nothing_before_the_invasion_starts(self):
        self.assertEqual(render.panel_rects(0.0, 720, 1280, seed=1), [])

    def test_panel_count_grows_with_progress(self):
        early = len(render.panel_rects(0.15, 720, 1280, seed=1))
        late = len(render.panel_rects(1.0, 720, 1280, seed=1))
        self.assertLess(early, late)
        self.assertEqual(late, render.MAX_PANELS)

    def test_panels_stay_inside_the_frame(self):
        """越界的矩形会被 paste 裁掉，表现为边缘出现半截色块。"""
        for progress in (0.2, 0.6, 1.0):
            for x, y, width, height in render.panel_rects(progress, 720, 1280, seed=3):
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x + width, 720)
                self.assertLessEqual(y + height, 1280)

    def test_same_seed_gives_the_same_panels(self):
        """同一刷新槽位内必须完全一致，否则逐帧抖动会变成噪点而不是闪跳。"""
        self.assertEqual(
            render.panel_rects(0.5, 720, 1280, seed=9),
            render.panel_rects(0.5, 720, 1280, seed=9),
        )

    def test_different_seeds_give_different_panels(self):
        self.assertNotEqual(
            render.panel_rects(0.5, 720, 1280, seed=1),
            render.panel_rects(0.5, 720, 1280, seed=2),
        )

    def test_progress_is_clamped(self):
        self.assertEqual(
            render.panel_rects(4.0, 720, 1280, seed=1),
            render.panel_rects(1.0, 720, 1280, seed=1),
        )


class PanelSeedTest(unittest.TestCase):
    def test_frames_within_one_refresh_slot_share_a_seed(self):
        self.assertEqual(render.panel_seed(0.01), render.panel_seed(0.14))

    def test_slots_advance_over_time(self):
        self.assertLess(render.panel_seed(0.1), render.panel_seed(0.9))


class CropToAspectTest(unittest.TestCase):
    def test_landscape_source_becomes_portrait(self):
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        self.assertEqual(render.crop_to_aspect(frame, 720, 1280).shape, (1280, 720, 3))

    def test_crop_is_centred_rather_than_stretched(self):
        """左右两侧应被裁掉，中间的内容保持原比例，不能被压扁。"""
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        frame[:, 300:340] = 255  # 居中的白色竖条
        result = render.crop_to_aspect(frame, 720, 1280)
        columns = result[..., 0].max(axis=0) > 128
        centre = columns.nonzero()[0].mean()
        self.assertAlmostEqual(centre, 360, delta=40)

    def test_portrait_source_is_returned_at_the_target_size(self):
        frame = np.zeros((1920, 1080, 3), dtype=np.uint8)
        self.assertEqual(render.crop_to_aspect(frame, 720, 1280).shape, (1280, 720, 3))


if __name__ == "__main__":
    unittest.main()
