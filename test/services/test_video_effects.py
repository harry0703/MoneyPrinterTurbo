import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from moviepy import ImageClip

from app.models.schema import VideoTransitionMode
from app.services.utils import video_effects


def _gradient_clip(width=64, height=48, duration=1.0):
    """创建非均匀渐变画面，确保缩放前后的像素差异可以被可靠检测。"""
    x = np.linspace(0, 255, width, dtype=np.uint8)
    y = np.linspace(0, 255, height, dtype=np.uint8)
    frame = np.stack(np.meshgrid(x, y), axis=-1).sum(axis=-1) % 256
    rgb = np.stack([frame] * 3, axis=-1).astype(np.uint8)
    return ImageClip(rgb).with_duration(duration)


def _detail_frame(width=128, height=96):
    """创建包含高频细节的 RGB 帧，用于观察亚像素缩放是否连续响应。"""
    x = np.arange(width, dtype=np.int16)
    y = np.arange(height, dtype=np.int16)[:, None]
    return np.stack(
        (
            (x + y) % 256,
            (3 * x + y) % 256,
            (x + 3 * y) % 256,
        ),
        axis=-1,
    ).astype(np.uint8)


class TestFadeAndSlideTransitions(unittest.TestCase):
    def test_fade_transitions_apply_requested_duration(self):
        """淡入淡出必须把调用方传入的时长原样交给 MoviePy effect。"""
        clip = _gradient_clip()
        self.addCleanup(clip.close)

        fade_in = video_effects.fadein_transition(clip, 0.25)
        fade_out = video_effects.fadeout_transition(clip, 0.75)
        self.addCleanup(fade_in.close)
        self.addCleanup(fade_out.close)

        self.assertEqual(fade_in.duration, clip.duration)
        self.assertEqual(fade_out.duration, clip.duration)
        frame_difference = np.abs(
            fade_in.get_frame(0).astype(int) - clip.get_frame(0).astype(int)
        )
        self.assertGreater(
            frame_difference.max(),
            0,
        )
        np.testing.assert_allclose(
            fade_out.get_frame(0),
            clip.get_frame(0),
            atol=1,
        )

    def test_slidein_positions_cover_all_directions_and_unknown_side(self):
        """滑入动画的四个方向、结束位置和未知方向兜底都应保持稳定。"""
        clip = _gradient_clip(width=60, height=40, duration=2)
        self.addCleanup(clip.close)
        expected_starts = {
            "left": (-60, 0),
            "right": (60, 0),
            "top": (0, -40),
            "bottom": (0, 40),
            "unknown": (0, 0),
        }

        for side, expected_start in expected_starts.items():
            with self.subTest(side=side):
                transitioned = video_effects.slidein_transition(clip, 1, side)
                self.addCleanup(transitioned.close)
                moving_clip = transitioned.clips[1]
                self.assertEqual(moving_clip.pos(0), expected_start)
                self.assertEqual(moving_clip.pos(1), (0, 0))

    def test_slideout_positions_cover_timing_and_all_directions(self):
        """
        滑出应在片段尾部才开始运动；四个方向、超过结束时间和零时长参数
        都需要被夹紧，避免出现除零或素材提前离场。
        """
        clip = _gradient_clip(width=60, height=40, duration=2)
        self.addCleanup(clip.close)
        expected_ends = {
            "left": (-60, 0),
            "right": (60, 0),
            "top": (0, -40),
            "bottom": (0, 40),
            "unknown": (0, 0),
        }

        for side, expected_end in expected_ends.items():
            with self.subTest(side=side):
                transitioned = video_effects.slideout_transition(clip, 1, side)
                self.addCleanup(transitioned.close)
                moving_clip = transitioned.clips[1]
                self.assertEqual(moving_clip.pos(0.5), (0, 0))
                self.assertEqual(moving_clip.pos(2.5), expected_end)

        zero_duration = video_effects.slideout_transition(clip, 0, "right")
        self.addCleanup(zero_duration.close)
        self.assertEqual(zero_duration.clips[1].pos(2), (0, 0))
        self.assertEqual(zero_duration.clips[1].pos(2.1), (60, 0))


class TestZoomTransitions(unittest.TestCase):
    def test_schema_has_zoom_members(self):
        self.assertEqual(VideoTransitionMode.zoom_in.value, "ZoomIn")
        self.assertEqual(VideoTransitionMode.zoom_out.value, "ZoomOut")

    def test_zoomin_preserves_geometry_and_zooms_over_time(self):
        clip = _gradient_clip()
        zoomed = video_effects.zoomin_transition(clip, 1)
        self.addCleanup(zoomed.close)
        self.addCleanup(clip.close)

        self.assertEqual(zoomed.size, clip.size)
        self.assertEqual(zoomed.duration, clip.duration)

        first = zoomed.get_frame(0)
        last = zoomed.get_frame(clip.duration - 0.01)
        original = clip.get_frame(0)

        self.assertEqual(first.shape, original.shape)
        self.assertEqual(first.dtype, np.uint8)
        # 放大从 1 倍开始，因此首帧应与原始画面保持一致。
        np.testing.assert_allclose(first, original, atol=2)
        # 末帧来自中心裁剪并放大后的区域，应与原始画面存在明显差异。
        self.assertGreater(np.abs(last.astype(int) - original.astype(int)).max(), 2)

    def test_zoomout_starts_zoomed_and_returns_to_source(self):
        clip = _gradient_clip()
        zoomed = video_effects.zoomout_transition(clip, 1)
        self.addCleanup(zoomed.close)
        self.addCleanup(clip.close)

        self.assertEqual(zoomed.size, clip.size)

        first = zoomed.get_frame(0)
        last = zoomed.get_frame(clip.duration)
        original = clip.get_frame(0)

        # 缩小的首帧为 1.2 倍画面，结束时精确回到原始比例。
        self.assertGreater(np.abs(first.astype(int) - original.astype(int)).max(), 2)
        np.testing.assert_allclose(last, original, atol=2)

    def test_zoom_frame_rejects_invalid_scale_factor(self):
        frame = np.zeros((8, 8, 3), dtype=np.uint8)

        with self.assertRaisesRegex(ValueError, "scale_factor"):
            video_effects._zoom_frame(frame, 0)

    def test_zoom_frame_responds_to_subpixel_scale_changes(self):
        frame = _detail_frame()

        first = video_effects._zoom_frame(frame, 1.1)
        second = video_effects._zoom_frame(frame, 1.1001)

        # 这两个比例在旧的整数裁剪算法中会落入相同裁剪尺寸，产生完全相同的帧，
        # 随后在跨过整数边界时突然跳变。亚像素采样应当能响应这种微小比例变化。
        self.assertGreater(np.count_nonzero(first != second), 0)
        self.assertLessEqual(
            np.abs(first.astype(np.int16) - second.astype(np.int16)).max(),
            1,
        )

    def test_zoom_frame_keeps_center_stable_for_odd_resolution(self):
        width, height = 59, 75
        center_x, center_y = width // 2, height // 2
        x = np.arange(width, dtype=np.int16) - center_x
        y = np.arange(height, dtype=np.int16)[:, None] - center_y
        radial = np.clip(x**2 + y**2, 0, 255).astype(np.uint8)
        frame = np.stack((radial, radial, radial), axis=-1)

        zoomed = video_effects._zoom_frame(frame, 1.2)

        self.assertEqual(zoomed.shape, frame.shape)
        self.assertEqual(zoomed.dtype, frame.dtype)
        # 奇数宽高只有一个精确中心像素，缩放后该像素不应发生横向或纵向漂移。
        np.testing.assert_allclose(
            zoomed[center_y, center_x],
            frame[center_y, center_x],
            atol=1,
        )


if __name__ == "__main__":
    unittest.main()
