import os
import tempfile
import unittest

import numpy as np
from PIL import Image

from app.services import video as video_service
from app.services.utils import outro_render
from app.models.schema import VideoParams
from app.utils import utils

FONT = os.path.join(utils.font_dir(), "BeVietnamPro-Bold.ttf")


def _write_logo(directory: str, color="#0E2A47") -> str:
    path = os.path.join(directory, "logo.png")
    Image.new("RGB", (400, 400), color).save(path)
    return path


class OutroPoseTest(unittest.TestCase):
    """动画时间轴是最容易被"顺手调一下"改坏的部分，这里锁定它的性质。"""

    def test_logo_is_fully_visible_before_the_button_appears(self):
        pose = outro_render.outro_pose(0.20)
        self.assertGreater(pose.logo_alpha, 0.8)
        self.assertEqual(pose.pill_alpha, 0.0)

    def test_nothing_fades_out_at_the_end(self):
        """结尾淡出等于告诉观众"播完了"，会直接拉低完播与循环。"""
        pose = outro_render.outro_pose(1.0)
        self.assertEqual(pose.logo_alpha, 1.0)
        self.assertEqual(pose.pill_alpha, 1.0)

    def test_button_slides_up_into_place(self):
        self.assertGreater(outro_render.outro_pose(0.30).pill_rise, 0.0)
        self.assertEqual(outro_render.outro_pose(0.60).pill_rise, 0.0)

    def test_logo_overshoots_before_settling(self):
        scales = [outro_render.outro_pose(p / 100).logo_scale for p in range(0, 101)]
        self.assertGreater(max(scales), 1.0)
        self.assertAlmostEqual(scales[-1], 1.0, places=2)

    def test_progress_is_clamped(self):
        self.assertEqual(
            outro_render.outro_pose(-5.0).logo_alpha,
            outro_render.outro_pose(0.0).logo_alpha,
        )
        self.assertEqual(outro_render.outro_pose(9.0).logo_alpha, 1.0)


class ReadableTextColorTest(unittest.TestCase):
    def test_bright_accents_get_dark_text(self):
        """账号强调色里有亮黄和青色，白字在上面几乎看不见。"""
        self.assertEqual(outro_render.readable_text_color("#FACC15"), "#111111")
        self.assertEqual(outro_render.readable_text_color("#22D3EE"), "#111111")

    def test_dark_accents_get_white_text(self):
        self.assertEqual(outro_render.readable_text_color("#FF2E88"), "#FFFFFF")

    def test_unparsable_colour_falls_back_instead_of_raising(self):
        self.assertEqual(outro_render.readable_text_color("not-a-colour"), "#FFFFFF")


class RenderFramesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.logo = _write_logo(self.directory)

    def _frames(self, **kwargs):
        options = {
            "logo_path": self.logo,
            "handle": "@why.though101",
            "font_path": FONT,
            "logo_size": 200,
            "duration": 1.2,
            "fps": 25,
        }
        options.update(kwargs)
        return outro_render.render_outro_frames(**options)

    def test_frame_count_matches_duration_and_fps(self):
        self.assertEqual(len(self._frames(duration=1.2, fps=25)), 30)

    def test_every_frame_has_the_same_size(self):
        """ImageClip 序列拼在一起时尺寸必须一致，否则合成时会跳动。"""
        sizes = {frame.shape for frame in self._frames()}
        self.assertEqual(len(sizes), 1)

    def test_frames_are_rgba_with_a_transparent_background(self):
        frame = self._frames()[-1]
        self.assertEqual(frame.shape[2], 4)
        self.assertEqual(frame[0, 0, 3], 0)

    def test_first_frame_is_nearly_empty_and_last_is_full(self):
        frames = self._frames()
        self.assertLess(frames[0][..., 3].mean(), frames[-1][..., 3].mean())

    def test_animation_actually_moves(self):
        frames = self._frames()
        self.assertFalse(np.array_equal(frames[0], frames[len(frames) // 2]))
        self.assertFalse(np.array_equal(frames[len(frames) // 2], frames[-1]))

    def test_missing_logo_is_tolerated(self):
        """logo 缺失时仍应产出句柄与按钮，而不是让整条生成崩掉。"""
        frames = self._frames(logo_path=os.path.join(self.directory, "nope.png"))
        self.assertTrue(frames)
        self.assertGreater(frames[-1][..., 3].max(), 0)

    def test_handle_is_optional(self):
        frames = self._frames(handle="")
        self.assertTrue(frames)

    def test_content_stays_inside_the_canvas(self):
        frame = self._frames()[-1]
        self.assertEqual(frame[..., 3].max(axis=0)[-1], 0)
        self.assertEqual(frame[..., 3].max(axis=1)[-1], 0)


class CircularLogoTest(unittest.TestCase):
    def test_corners_are_transparent(self):
        source = Image.new("RGB", (100, 100), "#FF0000")
        circle = outro_render.circular_logo(source, 120, ring_width=6)
        self.assertEqual(circle.size, (120, 120))
        self.assertEqual(circle.getpixel((0, 0))[3], 0)
        self.assertEqual(circle.getpixel((60, 60))[3], 255)


class BuildOutroClipsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.logo = _write_logo(self.directory)

    def _params(self, **kwargs):
        fields = {
            "video_subject": "x",
            "outro_enabled": True,
            "outro_logo_path": self.logo,
            "outro_handle": "@why.though101",
            "outro_duration": 1.2,
        }
        fields.update(kwargs)
        return VideoParams(**fields)

    def _build(self, params, total_duration=30.0):
        return video_service.build_outro_clips(
            params=params,
            video_width=1080,
            video_height=1920,
            total_duration=total_duration,
            font_path=FONT,
        )

    def test_disabled_produces_nothing(self):
        self.assertEqual(self._build(self._params(outro_enabled=False)), [])

    def test_missing_logo_produces_nothing(self):
        params = self._params(outro_logo_path=os.path.join(self.directory, "nope.png"))
        self.assertEqual(self._build(params), [])

    def test_clips_cover_exactly_the_last_seconds(self):
        """角标必须贴着片尾结束，提前结束会留下一段没有提示的画面。"""
        clips = self._build(self._params(), total_duration=30.0)
        self.assertTrue(clips)
        self.assertAlmostEqual(clips[0].start, 28.8, places=2)
        self.assertAlmostEqual(clips[-1].end, 30.0, places=6)

    def test_clips_are_contiguous(self):
        clips = self._build(self._params())
        for previous, current in zip(clips, clips[1:]):
            self.assertAlmostEqual(previous.end, current.start, places=6)

    def test_total_duration_is_unchanged(self):
        """这是整个设计的前提：叠加而不是追加，成片时长不能变长。"""
        clips = self._build(self._params(), total_duration=30.0)
        self.assertLessEqual(max(clip.end for clip in clips), 30.0)

    def test_very_short_videos_are_skipped(self):
        self.assertEqual(self._build(self._params(), total_duration=2.0), [])

    def test_zero_duration_is_skipped(self):
        self.assertEqual(self._build(self._params(outro_duration=0.0)), [])


if __name__ == "__main__":
    unittest.main()
