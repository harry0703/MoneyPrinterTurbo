import threading
from unittest.mock import patch

from moviepy import ImageClip, VideoFileClip
from PIL import Image

from app.services import video


def test_concurrent_same_stem_images_render_their_own_pixels(tmp_path):
    red = tmp_path / "scene.jpg"
    green = tmp_path / "scene.png"
    Image.new("RGB", (64, 64), "red").convert("CMYK").save(red)
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (64, 64), "lime").save(green, exif=exif)
    first_waiting, second_finished = threading.Event(), threading.Event()
    outputs, errors = {}, []
    calls = 0
    lock = threading.Lock()

    def delayed_decode(path, *args, **kwargs):
        nonlocal calls
        with lock:
            calls += 1
            first = calls == 1
        if first:
            first_waiting.set()
            assert second_finished.wait(10)
        return ImageClip(path, *args, **kwargs)

    def render_red():
        try:
            outputs["red"] = video.render_image_zoom_video(str(red), clip_duration=0.1)
        except Exception as error:
            errors.append(error)

    with patch.object(video, "ImageClip", side_effect=delayed_decode):
        thread = threading.Thread(target=render_red)
        thread.start()
        try:
            assert first_waiting.wait(5)
            outputs["green"] = video.render_image_zoom_video(str(green), clip_duration=0.1)
        finally:
            second_finished.set()
            thread.join(timeout=15)
        assert not thread.is_alive()
        assert not errors
    for name, channel in [("red", 0), ("green", 1)]:
        with VideoFileClip(outputs[name], audio=False) as clip:
            pixel = clip.get_frame(0)[32, 32]
            assert pixel[channel] > 200, (name, pixel)
            assert pixel[1 - channel] < 30, (name, pixel)
    with Image.open(red) as original:
        assert original.mode == "CMYK"
    with Image.open(green) as original:
        assert original.getexif()[274] == 6
