"""Native prepared-photo scenes in the opt-in revision renderer."""

import shutil

from PIL import Image
from moviepy import VideoFileClip
import numpy as np
import pytest

from app.services.video_project import VideoProject


@pytest.mark.parametrize("image_format", ["PNG", "JPEG", "BMP", "WEBP"])
def test_prepared_photo_scene_renders_and_reuses_native_export(tmp_path, image_format):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("native FFmpeg and FFprobe required")
    source = tmp_path / ("photo." + image_format.lower())
    Image.new("RGB", (64, 64), (30, 160, 220)).save(source, image_format)
    project = VideoProject(tmp_path / "project")
    revision = project.create_revision({
        "project_id": "photo-project",
        "settings": {"width": 64, "height": 64, "fps": 10},
        "scenes": [{"id": "photo", "footage": source.name, "duration": 0.4}],
    }, relative_to=tmp_path)
    result = project.render(revision["revision_id"])
    assert result["state"] == "succeeded"
    with VideoFileClip(result["export"]["path"]) as rendered:
        assert 0.35 <= rendered.duration <= 0.5
        np.testing.assert_allclose(rendered.get_frame(0.2)[32, 32], [30, 160, 220], atol=6)
    rerendered = project.render(revision["revision_id"])
    assert all(stage["reused"] for stage in rerendered["stages"].values())
    assert rerendered["export"]["sha256"] == result["export"]["sha256"]
