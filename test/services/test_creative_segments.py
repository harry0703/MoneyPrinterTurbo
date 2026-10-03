import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image, UnidentifiedImageError

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

    def test_unknown_motion_raises(self):
        path = self._asset("shot_002/generated_001.png")
        with self.assertRaises(ValueError):
            creative_segments.prepare_shot_segment(path, 4, motion="wobble")

    def test_default_motion_renders_smooth_segment(self):
        path = self._asset("shot_002/generated_001.png")
        rendered = f"{path}.smooth.mp4"

        def fake_smooth(image, duration):
            with open(rendered, "wb") as f:
                f.write(b"fake-mp4")
            return rendered

        with mock.patch.object(
            creative_segments, "render_smooth_zoom_video", side_effect=fake_smooth
        ) as stub:
            result = creative_segments.prepare_shot_segment(path, 4)

        self.assertEqual(result, rendered)
        stub.assert_called_once_with(path, 4)

    def test_standard_motion_uses_shared_renderer(self):
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
            result = creative_segments.prepare_shot_segment(
                path, 4, motion="standard"
            )

        self.assertEqual(result, rendered)
        stub.assert_called_once_with(path, 4)

    def test_smooth_existing_segment_reused(self):
        path = self._asset("shot_002/generated_001.png")
        rendered = f"{path}.smooth.mp4"
        with open(rendered, "wb") as f:
            f.write(b"fake-mp4")

        with mock.patch.object(creative_segments, "render_smooth_zoom_video") as stub:
            result = creative_segments.prepare_shot_segment(path, 4)

        self.assertEqual(result, rendered)
        stub.assert_not_called()

    def test_standard_existing_segment_reused(self):
        path = self._asset("shot_002/generated_001.png")
        rendered = f"{path}.mp4"
        with open(rendered, "wb") as f:
            f.write(b"fake-mp4")

        with mock.patch("app.services.video.render_image_zoom_video") as stub:
            result = creative_segments.prepare_shot_segment(path, 4, motion="standard")

        self.assertEqual(result, rendered)
        stub.assert_not_called()

    def test_smooth_empty_existing_segment_is_re_rendered(self):
        path = self._asset("shot_002/truncated.png")
        rendered = f"{path}.smooth.mp4"
        with open(rendered, "wb") as f:
            f.write(b"")

        def fake_smooth(image, duration):
            with open(rendered, "wb") as f:
                f.write(b"fake-mp4")
            return rendered

        with mock.patch.object(
            creative_segments, "render_smooth_zoom_video", side_effect=fake_smooth
        ) as stub:
            result = creative_segments.prepare_shot_segment(path, 4)

        self.assertEqual(result, rendered)
        stub.assert_called_once_with(path, 4)

    def test_render_failure_returns_empty(self):
        path = self._asset("shot_002/broken.png")
        with mock.patch.object(
            creative_segments,
            "render_smooth_zoom_video",
            side_effect=RuntimeError("ffmpeg exploded"),
        ) as stub:
            result = creative_segments.prepare_shot_segment(path, 4)

        self.assertEqual(result, "")
        stub.assert_called_once_with(path, 4)

    def test_render_missing_output_returns_empty(self):
        path = self._asset("shot_002/ghost.png")
        with mock.patch.object(
            creative_segments,
            "render_smooth_zoom_video",
            return_value=f"{path}.smooth.mp4",
        ):
            result = creative_segments.prepare_shot_segment(path, 4)

        self.assertEqual(result, "")


class TestRenderSmoothZoomVideo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _image(self, name, size=(160, 90)):
        w, h = size
        xs = np.linspace(0, 255, w, dtype=np.uint8)
        ys = np.linspace(0, 255, h, dtype=np.uint8)
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        arr[..., 0] = xs[None, :]
        arr[..., 1] = ys[:, None]
        arr[..., 2] = ((xs[None, :].astype(int) + ys[:, None].astype(int)) // 2).astype(np.uint8)
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Image.fromarray(arr).save(path)
        return path

    def test_real_render_produces_readable_mp4(self):
        from moviepy import VideoFileClip

        path = self._image("real.png")
        out = creative_segments.render_smooth_zoom_video(path, 2)
        try:
            self.assertTrue(os.path.isfile(out))
            self.assertGreater(os.path.getsize(out), 0)
            self.assertFalse(os.path.exists(f"{out}.tmp.mp4"))
            clip = VideoFileClip(out)
            try:
                self.assertEqual(list(clip.size), [160, 90])
                self.assertAlmostEqual(clip.duration, 2.0, delta=0.25)
            finally:
                clip.close()
        finally:
            if os.path.exists(out):
                os.remove(out)

    def test_invalid_image_raises(self):
        path = os.path.join(self.root, "not_an_image.png")
        with open(path, "wb") as f:
            f.write(b"definitely not a png")
        with self.assertRaises(UnidentifiedImageError):
            creative_segments.render_smooth_zoom_video(path, 2)


class TestVideoSegmentTrims(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _video(self, name, duration):
        from moviepy import ColorClip

        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        clip = ColorClip(size=(64, 36), color=(20, 40, 60), duration=duration)
        clip.write_videofile(path, fps=10, logger=None)
        clip.close()
        return path

    def test_video_longer_than_duration_is_trimmed(self):
        path = self._video("shot_001/long.mp4", 4.0)
        result = creative_segments.prepare_shot_segment(path, 2)
        self.assertEqual(result, f"{os.path.abspath(path)}.trim2s.mp4")
        self.assertTrue(os.path.isfile(result))
        self.assertTrue(os.path.isfile(path))
        self.assertFalse(os.path.exists(f"{result}.tmp.mp4"))
        self.assertAlmostEqual(
            creative_segments.get_video_duration(result), 2.0, delta=0.25
        )

    def test_trim_is_reused_on_second_prepare(self):
        path = self._video("shot_001/long.mp4", 4.0)
        first = creative_segments.prepare_shot_segment(path, 2)
        with mock.patch.object(
            creative_segments, "render_trimmed_segment"
        ) as stub:
            second = creative_segments.prepare_shot_segment(path, 2)
        self.assertEqual(first, second)
        stub.assert_not_called()

    def test_video_shorter_than_duration_returns_asset(self):
        path = self._video("shot_001/short.mp4", 1.0)
        self.assertEqual(
            creative_segments.prepare_shot_segment(path, 3),
            os.path.abspath(path),
        )

    def test_unreadable_video_duration_returns_none(self):
        path = os.path.join(self.root, "shot_001/garbage.mp4")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"not a video")
        self.assertIsNone(creative_segments.get_video_duration(path))

    def test_trim_failure_returns_empty(self):
        path = self._video("shot_001/long.mp4", 4.0)
        with mock.patch.object(
            creative_segments,
            "render_trimmed_segment",
            side_effect=RuntimeError("ffmpeg exploded"),
        ) as stub:
            result = creative_segments.prepare_shot_segment(path, 2)
        self.assertEqual(result, "")
        self.assertTrue(os.path.isfile(path))
        stub.assert_called_once_with(path, 2)
