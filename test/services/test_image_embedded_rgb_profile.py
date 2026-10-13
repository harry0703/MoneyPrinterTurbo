import io
import struct

import numpy as np
import pytest
from PIL import Image, ImageCms, ImageOps

from app.services import video


def _synthetic_rgb_profile():
    # Generate our own ICC bytes: change the transfer curve of Pillow's sRGB
    # profile. No system/vendor profile redistribution or external fixture.
    data = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    count = struct.unpack_from(">I", data, 128)[0]
    for index in range(count):
        tag, offset, _size = struct.unpack_from(">4sII", data, 132 + 12 * index)
        if tag in {b"rTRC", b"gTRC", b"bTRC"}:
            assert data[offset:offset + 4] == b"para"
            struct.pack_into(">i", data, offset + 12, int(1.8 * 65536))
    return bytes(data)


@pytest.mark.parametrize("orientation", [1, 6])
def test_native_image_clip_applies_embedded_rgb_color_profile(tmp_path, orientation):
    source = tmp_path / "profile-photo.png"
    profile = _synthetic_rgb_profile()
    exif = Image.Exif()
    exif[274] = orientation
    Image.new("RGB", (120, 60), (100, 150, 200)).save(source, icc_profile=profile, exif=exif)
    before = source.read_bytes()
    with Image.open(source) as image:
        upright = ImageOps.exif_transpose(image)
        expected = np.asarray(ImageCms.profileToProfile(
            upright, ImageCms.ImageCmsProfile(io.BytesIO(profile)),
            ImageCms.createProfile("sRGB"), outputMode="RGB",
        ))
    assert tuple(expected[0, 0]) != (100, 150, 200)
    clip, _path = video._open_image_clip_with_fallback(str(source))
    try:
        np.testing.assert_array_equal(clip.get_frame(0), expected)
        assert clip.size == (expected.shape[1], expected.shape[0])
        assert source.read_bytes() == before
    finally:
        clip.close()


def test_native_rgba_profile_preserves_opacity_mask(tmp_path):
    source = tmp_path / "alpha.png"
    profile = _synthetic_rgb_profile()
    image = Image.new("RGBA", (64, 64), (100, 150, 200, 128))
    image.save(source, icc_profile=profile)
    expected = np.asarray(ImageCms.profileToProfile(
        image, ImageCms.ImageCmsProfile(io.BytesIO(profile)),
        ImageCms.createProfile("sRGB"), outputMode="RGBA",
    ))
    clip, _path = video._open_image_clip_with_fallback(str(source))
    try:
        np.testing.assert_array_equal(clip.get_frame(0), expected[:, :, :3])
        np.testing.assert_allclose(clip.mask.get_frame(0), 128 / 255)
    finally:
        clip.close()


@pytest.mark.parametrize("profile", [None, b"invalid-profile"])
def test_untagged_and_invalid_profile_images_remain_usable(tmp_path, profile):
    source = tmp_path / "ordinary.png"
    image = Image.new("RGB", (64, 64), (100, 150, 200))
    image.save(source, icc_profile=profile)
    clip, _path = video._open_image_clip_with_fallback(str(source))
    try:
        np.testing.assert_array_equal(clip.get_frame(0), np.asarray(image))
    finally:
        clip.close()
