import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from moviepy import ImageClip

from app.models.schema import VideoTransitionMode
from app.services.utils import video_effects


def _gradient_clip(width=64, height=48, duration=1.0):
    """고르지 않은 그러데이션 화면을 만들어, 확대 전후의 픽셀 차이를 안정적으로 감지할 수 있게 한다."""
    x = np.linspace(0, 255, width, dtype=np.uint8)
    y = np.linspace(0, 255, height, dtype=np.uint8)
    frame = np.stack(np.meshgrid(x, y), axis=-1).sum(axis=-1) % 256
    rgb = np.stack([frame] * 3, axis=-1).astype(np.uint8)
    return ImageClip(rgb).with_duration(duration)


def _detail_frame(width=128, height=96):
    """고주파 디테일이 있는 RGB 프레임을 만들어, 서브픽셀 확대가 연속적으로 반응하는지 관찰한다."""
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
        """페이드 인·아웃은 호출자가 넘긴 길이를 그대로 MoviePy effect 에 전달해야 한다."""
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
        """슬라이드 인의 네 방향, 종료 위치, 알 수 없는 방향의 대비 동작이 모두 안정적이어야 한다."""
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
        슬라이드 아웃은 클립 끝부분에서야 움직이기 시작해야 한다. 네 방향, 종료 시각 초과, 길이 0 파라미터를
        모두 잘라 내, 0 으로 나누거나 소재가 미리 화면을 벗어나는 일이 없게 해야 한다.
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
        # 확대는 1 배에서 시작하므로 첫 프레임은 원본 화면과 같아야 한다.
        np.testing.assert_allclose(first, original, atol=2)
        # 마지막 프레임은 중앙을 잘라 확대한 영역이므로 원본 화면과 뚜렷이 달라야 한다.
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

        # 축소의 첫 프레임은 1.2 배 화면이고, 끝에서는 정확히 원본 비율로 돌아온다.
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

        # 이 두 비율은 예전 정수 크롭 알고리즘에서는 같은 크롭 크기로 떨어져 완전히 같은 프레임을 만들고,
        # 정수 경계를 넘는 순간 갑자기 튀었다. 서브픽셀 샘플링은 이런 미세한 비율 변화에도 반응해야 한다.
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
        # 홀수 폭·높이에는 정확한 중심 픽셀이 하나뿐이며, 확대 후에도 그 픽셀이 가로나 세로로 밀려서는 안 된다.
        np.testing.assert_allclose(
            zoomed[center_y, center_x],
            frame[center_y, center_x],
            atol=1,
        )


if __name__ == "__main__":
    unittest.main()
