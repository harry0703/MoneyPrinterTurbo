from PIL import Image, ImageOps
import numpy as np
import pytest
from app.services import video


@pytest.mark.parametrize("orientation", range(2, 9))
def test_native_image_clip_honors_camera_exif_orientation(tmp_path, orientation):
    source = tmp_path / "camera.png"
    pixels = np.zeros((60, 120, 3), dtype=np.uint8)
    pixels[:30, :60] = [255, 0, 0]
    pixels[:30, 60:] = [0, 255, 0]
    pixels[30:, :60] = [0, 0, 255]
    pixels[30:, 60:] = [255, 255, 0]
    image = Image.fromarray(pixels)
    exif = Image.Exif()
    exif[274] = orientation
    image.save(source, exif=exif)
    with Image.open(source) as original:
        expected = np.array(ImageOps.exif_transpose(original))
    clip, path = video._open_image_clip_with_fallback(str(source))
    try:
        assert clip.size == (expected.shape[1], expected.shape[0])
        np.testing.assert_array_equal(clip.get_frame(0), expected)
        with Image.open(source) as original:
            assert original.getexif()[274] == orientation
    finally:
        clip.close()


def test_native_image_clip_preserves_cmyk_photo_colors(tmp_path):
    source = tmp_path / "print-photo.jpg"
    Image.new("RGB", (120, 60), "blue").convert("CMYK").save(source)
    with Image.open(source) as original:
        expected = np.array(original.convert("RGB"))
    clip, _ = video._open_image_clip_with_fallback(str(source))
    try:
        np.testing.assert_array_equal(clip.get_frame(0), expected)
        assert clip.mask is None
    finally:
        clip.close()
