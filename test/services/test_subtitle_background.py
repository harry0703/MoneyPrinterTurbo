"""Focused tests for the opt-in subtitle background styling.

Guarantees the default stays the original solid, fully opaque rectangle and
that the opt-in path produces a configurable translucent / rounded background.
"""

import unittest

import numpy as np

from app.models.schema import VideoParams
from app.services.video import build_subtitle_background_rgba, hex_to_rgb


class SubtitleBackgroundDefaultsTest(unittest.TestCase):
    def test_defaults_preserve_original_behavior(self):
        # New fields must default to the original solid, opaque rectangle.
        p = VideoParams(video_subject="x")
        self.assertFalse(p.subtitle_background_rounded)
        self.assertEqual(p.subtitle_background_opacity, 100)


class HexToRgbTest(unittest.TestCase):
    def test_valid_and_invalid(self):
        self.assertEqual(hex_to_rgb("#000000"), (0, 0, 0))
        self.assertEqual(hex_to_rgb("#FF8040"), (255, 128, 64))
        self.assertEqual(hex_to_rgb("nonsense"), (0, 0, 0))
        self.assertEqual(hex_to_rgb("#GGGGGG"), (0, 0, 0))


class SubtitleBackgroundRenderTest(unittest.TestCase):
    W, H = 200, 80

    def _arr(self, alpha, radius):
        return build_subtitle_background_rgba(self.W, self.H, (0, 0, 0), alpha, radius)

    def test_shape_is_rgba(self):
        arr = self._arr(255, 0)
        self.assertEqual(arr.shape, (self.H, self.W, 4))

    def test_opaque_square_default(self):
        # opacity=255, radius=0 -> fully opaque everywhere (the default look).
        arr = self._arr(255, 0)
        self.assertEqual(int(arr[0, 0, 3]), 255)  # corner opaque
        self.assertEqual(int(arr[self.H // 2, self.W // 2, 3]), 255)  # centre opaque

    def test_translucent_center(self):
        # opacity ~55% -> centre alpha 140, still opaque corners when square.
        arr = self._arr(140, 0)
        self.assertEqual(int(arr[self.H // 2, self.W // 2, 3]), 140)
        self.assertEqual(int(arr[0, 0, 3]), 140)

    def test_rounded_corners_are_transparent(self):
        # With a radius the extreme corner pixel is outside the rounded shape.
        arr = self._arr(255, 24)
        self.assertEqual(int(arr[0, 0, 3]), 0)  # corner cut away -> transparent
        self.assertEqual(int(arr[self.H // 2, self.W // 2, 3]), 255)  # centre filled


if __name__ == "__main__":
    unittest.main()
