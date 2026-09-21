import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import creative_segments


class TestPrepareShotSegment(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _asset(self, name, content=b"data"):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def test_empty_asset_returns_empty(self):
        self.assertEqual(creative_segments.prepare_shot_segment("", 4), "")

    def test_missing_asset_returns_empty(self):
        missing = os.path.join(self.root, "shot_001", "nope.mp4")
        self.assertEqual(creative_segments.prepare_shot_segment(missing, 4), "")

    def test_video_asset_returned_as_is(self):
        path = self._asset("shot_001/vid.mp4")
        result = creative_segments.prepare_shot_segment(path, 4)
        self.assertEqual(result, os.path.abspath(path))

    def test_image_asset_renders_zoom_video(self):
        path = self._asset("shot_002/generated_001.png")
        rendered = f"{path}.mp4"

        def fake_render(image, duration):
            with open(rendered, "wb") as f:
                f.write(b"fake-mp4")
            return rendered

        with mock.patch(
            "app.services.video.render_image_zoom_video",
            side_effect=fake_render,
        ) as stub:
            result = creative_segments.prepare_shot_segment(path, 4)

        self.assertEqual(result, rendered)
        stub.assert_called_once_with(path, 4)

    def test_existing_segment_reused(self):
        path = self._asset("shot_002/generated_001.png")
        rendered = f"{path}.mp4"
        with open(rendered, "wb") as f:
            f.write(b"fake-mp4")

        with mock.patch("app.services.video.render_image_zoom_video") as stub:
            result = creative_segments.prepare_shot_segment(path, 4)

        self.assertEqual(result, rendered)
        stub.assert_not_called()

    def test_empty_existing_segment_is_re_rendered(self):
        path = self._asset("shot_002/truncated.png")
        rendered = f"{path}.mp4"
        with open(rendered, "wb") as f:
            f.write(b"")

        def fake_render(image, duration):
            with open(rendered, "wb") as f:
                f.write(b"fake-mp4")
            return rendered

        with mock.patch(
            "app.services.video.render_image_zoom_video",
            side_effect=fake_render,
        ) as stub:
            result = creative_segments.prepare_shot_segment(path, 4)

        self.assertEqual(result, rendered)
        stub.assert_called_once_with(path, 4)

    def test_render_failure_returns_empty(self):
        path = self._asset("shot_002/broken.png")
        with mock.patch(
            "app.services.video.render_image_zoom_video",
            side_effect=RuntimeError("ffmpeg exploded"),
        ) as stub:
            result = creative_segments.prepare_shot_segment(path, 4)

        self.assertEqual(result, "")
        stub.assert_called_once_with(path, 4)

    def test_render_missing_output_returns_empty(self):
        path = self._asset("shot_002/ghost.png")
        with mock.patch(
            "app.services.video.render_image_zoom_video",
            return_value=f"{path}.mp4",
        ):
            result = creative_segments.prepare_shot_segment(path, 4)

        self.assertEqual(result, "")
