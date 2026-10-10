"""Static WebP admission and native Pillow/MoviePy/FFmpeg rendering."""

import ast
import io
from pathlib import Path

import numpy as np
from PIL import Image
import pytest
from moviepy import VideoFileClip

from app.models import const
from app.services import material_upload, video


def _webui_extensions():
    source = Path(__file__).parents[2] / "webui" / "Main.py"
    node = next(node for node in ast.parse(source.read_text()).body
                if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "LOCAL_MATERIAL_EXTENSIONS"
                    for target in node.targets))
    namespace = {"material_upload_service": material_upload}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 str(source), "exec"), namespace)
    return namespace["LOCAL_MATERIAL_EXTENSIONS"]


def test_static_webp_upload_and_native_render(tmp_path, monkeypatch):
    source = io.BytesIO()
    Image.new("RGB", (64, 64), (30, 160, 220)).save(source, "WEBP", lossless=True)
    monkeypatch.setattr(material_upload, "uploaded_material_dir", lambda create=True: str(tmp_path))
    stored = material_upload.save_material_upload("photo.WEBP", source)
    assert "webp" in const.FILE_TYPE_IMAGES
    assert ".webp" in _webui_extensions()
    with Image.open(tmp_path / stored) as decoded:
        assert decoded.format == "WEBP"
        assert decoded.getpixel((32, 32)) == (30, 160, 220)
    output = video.render_image_zoom_video(str(tmp_path / stored), clip_duration=0.2)
    with VideoFileClip(output) as rendered:
        np.testing.assert_allclose(rendered.get_frame(0.1)[32, 32], [30, 160, 220], atol=5)
        assert rendered.duration >= 0.19


def test_animated_webp_is_rejected_as_static_material(tmp_path):
    source = tmp_path / "animated.webp"
    Image.new("RGB", (8, 8), "red").save(
        source, "WEBP", save_all=True,
        append_images=[Image.new("RGB", (8, 8), "blue")], duration=100, loop=0)
    with pytest.raises(material_upload.MaterialUploadError, match="static"):
        material_upload._validate_image(str(source), ".webp")


def test_renamed_png_is_not_accepted_as_webp(tmp_path):
    source = tmp_path / "renamed.webp"
    Image.new("RGB", (8, 8)).save(source, "PNG")
    with pytest.raises(material_upload.MaterialUploadError, match="extension"):
        material_upload._validate_image(str(source), ".webp")
