import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from moviepy import ImageClip

from app.models.schema import VideoTransitionMode
from app.services.utils import video_effects


def _gradient_clip(width=64, height=48, duration=1.0):
    # A non-uniform frame so zooming visibly changes pixel content.
    x = np.linspace(0, 255, width, dtype=np.uint8)
    y = np.linspace(0, 255, height, dtype=np.uint8)
    frame = np.stack(np.meshgrid(x, y), axis=-1).sum(axis=-1) % 256
    rgb = np.stack([frame] * 3, axis=-1).astype(np.uint8)
    return ImageClip(rgb).with_duration(duration)


class TestZoomTransitions(unittest.TestCase):
    def test_schema_has_zoom_members(self):
        self.assertEqual(VideoTransitionMode.zoom_in.value, "ZoomIn")
        self.assertEqual(VideoTransitionMode.zoom_out.value, "ZoomOut")

    def test_zoomin_preserves_geometry_and_zooms_over_time(self):
        clip = _gradient_clip()
        zoomed = video_effects.zoomin_transition(clip, 1)

        self.assertEqual(zoomed.size, clip.size)
        self.assertEqual(zoomed.duration, clip.duration)

        first = zoomed.get_frame(0)
        last = zoomed.get_frame(clip.duration - 0.01)
        original = clip.get_frame(0)

        self.assertEqual(first.shape, original.shape)
        self.assertEqual(first.dtype, np.uint8)
        # Zoom starts at scale 1: the first frame matches the source.
        np.testing.assert_allclose(first, original, atol=2)
        # By the end the frame is a scaled center crop, so it must differ.
        self.assertGreater(np.abs(last.astype(int) - original.astype(int)).max(), 2)

    def test_zoomout_starts_zoomed_and_returns_to_source(self):
        clip = _gradient_clip()
        zoomed = video_effects.zoomout_transition(clip, 1)

        self.assertEqual(zoomed.size, clip.size)

        first = zoomed.get_frame(0)
        # At t == duration the scale factor is exactly 1 again.
        last = zoomed.get_frame(clip.duration)
        original = clip.get_frame(0)

        self.assertGreater(np.abs(first.astype(int) - original.astype(int)).max(), 2)
        np.testing.assert_allclose(last, original, atol=2)


if __name__ == "__main__":
    unittest.main()
