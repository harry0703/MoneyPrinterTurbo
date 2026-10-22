import numpy as np
import pytest
from PIL import Image
from moviepy import VideoFileClip

from app.services.video import close_clip, render_image_zoom_video


@pytest.mark.parametrize('source_value,expected', [(16384, 64), (32768, 128)])
def test_uint16_grayscale_retains_brightness_in_native_render(tmp_path, source_value, expected):
    source = tmp_path / 'grayscale16.png'
    Image.fromarray(np.full((32, 32), source_value, dtype=np.uint16)).save(source)
    output = render_image_zoom_video(str(source), 0.1)
    clip = VideoFileClip(output, audio=False)
    try:
        pixel = clip.get_frame(0)[16, 16]
        assert all(abs(int(channel) - expected) <= 5 for channel in pixel)
    finally:
        close_clip(clip)
