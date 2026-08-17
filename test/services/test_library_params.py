import ast
import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models.schema import TaskVideoRequest, VideoParams


class TestPhotoLibraryParamDefaults(unittest.TestCase):
    def test_defaults_mean_library_disabled(self):
        params = VideoParams(video_subject="Coffee")

        self.assertEqual(params.photo_require, [])
        self.assertEqual(params.photo_prefer_tags, [])
        self.assertEqual(params.photo_only_tags, [])
        self.assertEqual(params.photo_exclude_tags, [])
        self.assertEqual(params.photo_max_duration, 8.0)

    def test_fields_reach_task_video_request(self):
        request = TaskVideoRequest(
            video_subject="Coffee",
            photo_require=["path:a.jpg", "tag:coffee"],
            photo_prefer_tags=["cozy"],
            photo_only_tags=["cafe"],
            photo_exclude_tags=["logo"],
            photo_max_duration=4.5,
        )

        self.assertEqual(request.photo_require, ["path:a.jpg", "tag:coffee"])
        self.assertEqual(request.photo_prefer_tags, ["cozy"])
        self.assertEqual(request.photo_only_tags, ["cafe"])
        self.assertEqual(request.photo_exclude_tags, ["logo"])
        self.assertEqual(request.photo_max_duration, 4.5)


class TestPhotoLibraryParamRedisRoundtrip(unittest.TestCase):
    def test_survives_str_literal_eval_roundtrip(self):
        params = VideoParams(
            video_subject="Coffee",
            photo_require=["path:a.jpg", "tag:coffee"],
            photo_prefer_tags=["cozy", "warm"],
            photo_only_tags=["cafe"],
            photo_exclude_tags=["logo"],
            photo_max_duration=4.5,
        )

        for field_name in (
            "photo_require",
            "photo_prefer_tags",
            "photo_only_tags",
            "photo_exclude_tags",
            "photo_max_duration",
        ):
            with self.subTest(field_name=field_name):
                original = getattr(params, field_name)
                roundtripped = ast.literal_eval(str(original))
                self.assertEqual(roundtripped, original)

    def test_default_empty_lists_survive_roundtrip(self):
        params = VideoParams(video_subject="Coffee")

        roundtripped = ast.literal_eval(str(params.photo_require))
        self.assertEqual(roundtripped, [])


class TestPhotoMaxDurationConstraints(unittest.TestCase):
    def test_accepts_value_within_bounds(self):
        params = VideoParams(video_subject="Coffee", photo_max_duration=1.0)

        self.assertEqual(params.photo_max_duration, 1.0)

    def test_rejects_value_below_minimum(self):
        with self.assertRaises(ValidationError):
            VideoParams(video_subject="Coffee", photo_max_duration=0.1)

    def test_rejects_value_above_maximum(self):
        with self.assertRaises(ValidationError):
            VideoParams(video_subject="Coffee", photo_max_duration=25.0)


if __name__ == "__main__":
    unittest.main()
