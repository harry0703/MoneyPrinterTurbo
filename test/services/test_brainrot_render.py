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


class PanelScheduleTest(unittest.TestCase):
    def test_one_instance_is_present_from_the_start(self):
        self.assertEqual(len(render.panel_schedule(0.0, 720, 1280, seed=1)), 1)

    def test_instances_accumulate_over_time(self):
        early = render.panel_schedule(0.5, 720, 1280, seed=1)
        late = render.panel_schedule(3.0, 720, 1280, seed=1)
        self.assertLess(len(early), len(late))

    def test_earlier_instances_keep_their_place(self):
        """实例是叠上去的，先出现的不能跟着重排——那样看起来是一段画面在乱跳。"""
        early = render.panel_schedule(0.5, 720, 1280, seed=1)
        late = render.panel_schedule(3.0, 720, 1280, seed=1)
        self.assertEqual(late[: len(early)], early)

    def test_each_instance_starts_one_interval_after_the_previous(self):
        panels = render.panel_schedule(2.0, 720, 1280, seed=1, interval=0.2)
        starts = [start for *_, start in panels]
        for previous, current in zip(starts, starts[1:]):
            self.assertAlmostEqual(current - previous, 0.2, places=6)

    def test_instance_count_is_capped(self):
        panels = render.panel_schedule(600.0, 720, 1280, seed=1)
        self.assertEqual(len(panels), render.MAX_PANELS)

    def test_panels_stay_inside_the_frame(self):
        """越界的矩形会被 paste 裁掉，表现为边缘出现半截色块。"""
        for x, y, width, height, _ in render.panel_schedule(3.4, 720, 1280, seed=3):
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + width, 720)
            self.assertLessEqual(y + height, 1280)

    def test_same_seed_gives_the_same_layout(self):
        self.assertEqual(
            render.panel_schedule(2.0, 720, 1280, seed=9),
            render.panel_schedule(2.0, 720, 1280, seed=9),
        )

    def test_different_seeds_give_different_layouts(self):
        self.assertNotEqual(
            render.panel_schedule(2.0, 720, 1280, seed=1),
            render.panel_schedule(2.0, 720, 1280, seed=2),
        )

    def test_nothing_before_the_invasion(self):
        self.assertEqual(render.panel_schedule(-1.0, 720, 1280, seed=1), [])


class LetterboxTest(unittest.TestCase):
    def test_landscape_source_keeps_its_aspect_and_gains_bars(self):
        """剪辑是 16:9，裁成竖屏会切掉两侧的构图，所以必须留黑边。"""
        frame = np.full((360, 640, 3), 255, dtype=np.uint8)
        result = render.letterbox(frame, 720, 1280)
        self.assertEqual(result.shape, (1280, 720, 3))
        self.assertEqual(int(result[0, 360, 0]), 0)      # 顶部黑边
        self.assertEqual(int(result[640, 360, 0]), 255)  # 中间是画面

    def test_visible_band_has_the_source_aspect_ratio(self):
        frame = np.full((360, 640, 3), 255, dtype=np.uint8)
        result = render.letterbox(frame, 720, 1280)
        rows = (result[..., 0].max(axis=1) > 0).nonzero()[0]
        band_height = rows.max() - rows.min() + 1
        self.assertAlmostEqual(720 / band_height, 640 / 360, delta=0.02)

    def test_matching_aspect_needs_no_bars(self):
        frame = np.full((1280, 720, 3), 255, dtype=np.uint8)
        result = render.letterbox(frame, 720, 1280)
        self.assertEqual(int(result[0, 0, 0]), 255)


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
