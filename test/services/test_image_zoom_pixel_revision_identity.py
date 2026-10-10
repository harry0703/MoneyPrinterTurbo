import shutil
from pathlib import Path

import pytest
from moviepy import VideoFileClip
from PIL import Image

from app.services import video


def test_updated_image_does_not_replace_previous_rendered_pixels(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("native FFmpeg required")
    source = tmp_path / "scene.png"
    Image.new("RGB", (64, 64), "red").save(source)
    first = video.render_image_zoom_video(str(source), clip_duration=0.1)
    first_bytes = Path(first).read_bytes()
    Image.new("RGB", (64, 64), "blue").save(source)
    second = video.render_image_zoom_video(str(source), clip_duration=0.1)
    assert first != second
    assert Path(first).read_bytes() == first_bytes
    for output, channel in [(first, 0), (second, 2)]:
        with VideoFileClip(output, audio=False) as rendered:
            assert rendered.get_frame(0)[32, 32, channel] > 200
