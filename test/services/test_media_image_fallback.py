from PIL import Image
from moviepy import VideoFileClip
import pytest

from app.models.schema import MaterialInfo
from app.services import video


@pytest.mark.parametrize("suffix", [".bin", ".mp4"])
def test_detected_image_is_rendered_even_with_nonimage_suffix(tmp_path, monkeypatch, suffix):
    source = tmp_path / ("picture" + suffix)
    Image.new("RGB", (720, 720), "green").save(source, format="PNG")
    monkeypatch.setattr(video.utils, "storage_dir", lambda *args, **kwargs: str(tmp_path))
    material = MaterialInfo(provider="local", url=str(source))

    result = video.preprocess_video([material], clip_duration=0.2)

    assert result == [material]
    assert material.url != str(source)
    assert material.url.endswith(".mp4")
    with VideoFileClip(material.url, audio=False) as clip:
        assert clip.duration >= 0.19
        assert clip.size == [720, 720]
