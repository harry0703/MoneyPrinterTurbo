import pytest
from PIL import Image
from moviepy import VideoFileClip

from app.services.video import close_clip, render_image_zoom_video


@pytest.mark.parametrize("extension", ["png", "bmp"])
def test_bilevel_white_pixels_remain_white_in_native_render(tmp_path, extension):
    source = tmp_path / f"bilevel.{extension}"
    Image.new("1", (32, 32), 1).save(source)
    output = render_image_zoom_video(str(source), 0.1)
    clip = VideoFileClip(output, audio=False)
    try:
        pixel = clip.get_frame(0)[16, 16]
        assert all(int(channel) >= 245 for channel in pixel)
    finally:
        close_clip(clip)
