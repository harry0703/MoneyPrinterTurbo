import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

# add project root to python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models.schema import VideoParams
from app.services import cover
from app.services import task as cover_task
from app.utils import utils


resources_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")


class TestCoverService(unittest.TestCase):
    def setUp(self):
        self.task_id = "11111111-1111-1111-1111-111111111111"

    def tearDown(self):
        cover_path = os.path.join(utils.task_dir(self.task_id), "cover.png")
        if os.path.exists(cover_path):
            os.remove(cover_path)

    def test_generate_cover_image_from_local_material(self):
        params = VideoParams(
            video_subject="Chamán y medicina ancestral",
            video_script="Una guía visual sobre rituales, plantas sagradas y tradición espiritual.",
            video_terms=["ritual", "medicina ancestral", "espiritualidad"],
            video_aspect="9:16",
            font_name="MicrosoftYaHeiBold.ttc",
        )

        output_path = cover.generate_cover_image(
            task_id=self.task_id,
            params=params,
            video_script=params.video_script,
            video_terms=params.video_terms,
            material_paths=[os.path.join(resources_dir, "1.png")],
        )

        self.assertTrue(os.path.exists(output_path))
        with Image.open(output_path) as generated_cover:
            self.assertEqual(generated_cover.size, (1080, 1920))

    def test_generate_cover_image_uses_fallback_background_without_materials(self):
        params = VideoParams(
            video_subject="Portada sobre filosofía estoica",
            video_script="Explora disciplina, templanza y claridad mental.",
            video_terms=["estoicismo", "disciplina", "claridad mental"],
            video_aspect="16:9",
            font_name="missing-font.ttc",
        )

        output_path = cover.generate_cover_image(
            task_id=self.task_id,
            params=params,
            video_script=params.video_script,
            video_terms=params.video_terms,
            material_paths=[],
        )

        self.assertTrue(os.path.exists(output_path))
        with Image.open(output_path) as generated_cover:
            self.assertEqual(generated_cover.size, (1920, 1080))

    def test_resolve_cover_image_path_prefers_custom_cover(self):
        params = VideoParams(
            video_subject="Portada custom",
            video_script="Texto base",
            generate_cover=True,
        )

        with TemporaryDirectory() as tmp_dir:
            custom_cover_path = os.path.join(tmp_dir, "custom-cover.png")
            Image.new("RGB", (320, 180), color=(12, 34, 56)).save(custom_cover_path)
            params.custom_cover_file = custom_cover_path

            output_path = cover_task.resolve_cover_image_path(
                task_id=self.task_id,
                params=params,
                video_script=params.video_script,
                video_terms=[],
                material_paths=[],
            )

            self.assertEqual(output_path, custom_cover_path)


if __name__ == "__main__":
    unittest.main()