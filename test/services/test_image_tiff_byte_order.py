import pytest
from PIL import Image
from moviepy import VideoFileClip

from app.models.schema import ImageMotion
from app.services.video import close_clip, render_image_zoom_video


@pytest.mark.parametrize('byte_order', ['little', 'big'])
@pytest.mark.parametrize('source_value,expected', [(0, 0), (16384, 64), (32768, 128), (65535, 255)])
def test_uint16_tiff_retains_brightness_in_native_render(
    tmp_path, byte_order, source_value, expected
):
    source = tmp_path / 'grayscale16.tiff'
    mode = 'I;16B' if byte_order == 'big' else 'I;16'
    Image.frombytes(
        mode, (32, 32), source_value.to_bytes(2, byte_order) * (32 * 32)
    ).save(source)
    output = render_image_zoom_video(str(source), 0.1, image_motion=ImageMotion.static)
    clip = VideoFileClip(output, audio=False)
    try:
        pixel = clip.get_frame(0)[16, 16]
        assert all(abs(int(channel) - expected) <= 5 for channel in pixel)
    finally:
        close_clip(clip)
