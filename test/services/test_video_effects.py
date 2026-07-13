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
