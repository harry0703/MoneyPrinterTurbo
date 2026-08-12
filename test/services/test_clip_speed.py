import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models.schema import VideoParams
from app.utils import utils


class TestClipSpeed(unittest.TestCase):
    def test_video_params_uses_normal_speed_by_default(self):
        params = VideoParams(video_subject="test")

        self.assertEqual(params.video_clip_speed, 1.0)

    def test_normalize_clip_speed_clamps_valid_numbers(self):
        self.assertEqual(utils.normalize_clip_speed(0.1), 0.5)
        self.assertEqual(utils.normalize_clip_speed(1.3), 1.3)
        self.assertEqual(utils.normalize_clip_speed(5.0), 2.0)

    def test_normalize_clip_speed_rejects_invalid_values(self):
        for value in (None, "abc", 0, -2, math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                self.assertEqual(utils.normalize_clip_speed(value), 1.0)


if __name__ == "__main__":
    unittest.main()
