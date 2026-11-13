import pytest
from PIL import Image
from moviepy import VideoFileClip

from app.services.video import close_clip, render_image_zoom_video


@pytest.mark.parametrize("mode,pixel", [("LA", (180, 128)), ("RGBA", (180, 180, 180, 128))])
def test_alpha_image_preserves_partial_opacity_in_native_render(tmp_path, mode, pixel):
    source = tmp_path / "gray-alpha.png"
    Image.new(mode, (32, 32), pixel).save(source)
    output = render_image_zoom_video(str(source), 0.1)
    clip = VideoFileClip(output, audio=False)
    try:
        pixel = clip.get_frame(0)[16, 16]
        # Half-opacity gray180 over the renderer's black canvas is gray90.
        assert all(abs(int(channel) - 90) <= 5 for channel in pixel)
    finally:
        close_clip(clip)
