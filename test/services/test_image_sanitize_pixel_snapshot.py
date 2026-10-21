import threading
from unittest.mock import patch

from moviepy import ImageClip, VideoFileClip
from PIL import Image

from app.services import video


def test_inflight_sanitized_image_keeps_pixels_when_source_is_replaced(tmp_path):
    source = tmp_path / "scene.jpg"
    Image.new("RGB", (64, 64), "red").convert("CMYK").save(source)
    first_waiting = threading.Event()
    second_finished = threading.Event()
    outputs, errors = {}, []
    calls = [0]

    def delayed_decode(path, *args, **kwargs):
        calls[0] += 1
        if calls[0] == 1:
            first_waiting.set()
            assert second_finished.wait(10)
        return ImageClip(path, *args, **kwargs)

    def first_render():
        try:
            outputs["first"] = video.render_image_zoom_video(str(source), clip_duration=0.1)
        except Exception as exc:
            errors.append(exc)

    with patch.object(video, "ImageClip", side_effect=delayed_decode):
        worker = threading.Thread(target=first_render)
        worker.start()
        try:
            assert first_waiting.wait(5)
            Image.new("RGB", (64, 64), "blue").convert("CMYK").save(source)
            # A different duration keeps the two final output paths independent.
            outputs["second"] = video.render_image_zoom_video(str(source), clip_duration=0.2)
        finally:
            second_finished.set()
            worker.join(15)
    assert not worker.is_alive()
    assert errors == []
    with VideoFileClip(outputs["first"], audio=False) as rendered:
        pixel = rendered.get_frame(0)[32, 32]
        assert pixel[0] > 200 and pixel[2] < 30
    with VideoFileClip(outputs["second"], audio=False) as rendered:
        pixel = rendered.get_frame(0)[32, 32]
        assert pixel[2] > 200 and pixel[0] < 30
