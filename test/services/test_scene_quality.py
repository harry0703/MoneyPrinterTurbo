import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.models.scene_quality import MediaQualityReport
from app.services import scene_media, scene_quality

from test.services.test_scene_media import make_scene


class TestSceneQuality(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "frame.png"
        Image.new("RGB", (1280, 720), "navy").save(self.path)
        scene_quality.clear_quality_cache()
        scene_media._IMAGE_ASSESSMENT_CACHE.clear()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_image_assessment_requires_specific_visual_evidence(self):
        report = scene_quality.inspect_media_file(self.path)
        with patch.object(
            scene_media.twelvelabs,
            "analyze_images",
            return_value=(
                '{"subject_visible":true,"action_matches":true,"context_matches":true,'
                '"confidence":0.95,"description":"Saturn and its rings rotate in space."}'
            ),
        ) as analyze:
            result, returned_report = scene_media.evaluate_image_asset(make_scene(), self.path)
        self.assertEqual(returned_report.asset_sha256, report.asset_sha256)
        self.assertEqual(result["result"], "accepted")
        self.assertEqual(result["visual_correspondence"], 1.0)
        analyze.assert_called_once()

    def test_thematically_related_nebula_is_rejected_for_saturn_scene(self):
        accepted_report = MediaQualityReport(
            asset_sha256="a" * 64, media_type="image", result="accepted",
            duration_seconds=0,
            width=1280, height=720, resolution_score=1, aspect_score=1,
            technical_quality=1,
        )
        with patch.object(scene_media.scene_quality, "inspect_media_file", return_value=accepted_report), patch.object(
            scene_media.twelvelabs, "analyze_images",
            return_value=(
                '{"subject_visible":true,"action_matches":true,"context_matches":true,'
                '"confidence":0.99,"description":"A colorful nebula deep in space."}'
            ),
        ):
            result, _ = scene_media.evaluate_image_asset(make_scene(), self.path)
        self.assertEqual(result["result"], "rejected")
        self.assertEqual(result["visual_correspondence"], 0.6)

    def test_image_assessment_is_cached_by_content_and_scene_prompt(self):
        response = (
            '{"subject_visible":true,"action_matches":true,"context_matches":true,'
            '"confidence":0.95,"description":"Saturn and its rings are visible."}'
        )
        with patch.object(scene_media.twelvelabs, "analyze_images", return_value=response) as analyze:
            first, _ = scene_media.evaluate_image_asset(make_scene(), self.path)
            second, _ = scene_media.evaluate_image_asset(make_scene(), self.path)
        self.assertEqual(first, second)
        analyze.assert_called_once()

    def test_corrupt_media_is_reported(self):
        corrupt = Path(self.temp_dir.name) / "broken.mp4"
        corrupt.write_bytes(b"not a video")
        with self.assertRaises(ValueError):
            scene_quality.inspect_media_file(corrupt)


if __name__ == "__main__":
    unittest.main()
