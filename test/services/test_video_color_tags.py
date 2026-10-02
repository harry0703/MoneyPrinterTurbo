import re
import subprocess

import numpy as np
from PIL import Image

from app.services import video

# A saturated green: BT.601 encodes decoded as BT.709 lose the most here.
SOURCE_RGB = (40, 180, 60)


def _stream_color(binary, path):
    # ffprobe is not bundled with imageio-ffmpeg; ffmpeg's own stream line carries the same tags.
    result = subprocess.run([binary, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    match = re.search(r"Video: h264.*?, (yuv420p\([^)]*\))", result.stderr)
    assert match, result.stderr
    return match.group(1)


def _decode_as_player(binary, path):
    # Decode the way players and YouTube treat HD: BT.709, limited range.
    raw = subprocess.run(
        [binary, "-v", "error", "-i", str(path), "-frames:v", "1",
         "-vf", "scale=in_color_matrix=bt709:in_range=tv,format=rgb24,crop=2:2", "-f", "rawvideo", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(2, 2, 3)[0, 0].astype(int)


def _assert_bt709(binary, path):
    assert _stream_color(binary, path).startswith("yuv420p(tv, bt709")
    # Each 4:2:0 limited-range generation rounds by a level or two; a BT.601 encode is ~20 off.
    assert np.abs(_decode_as_player(binary, path) - SOURCE_RGB).max() <= 8


def test_clip_concat_and_image_renders_are_bt709(tmp_path, monkeypatch):
    binary = video.utils.get_ffmpeg_binary()
    monkeypatch.setattr(video, "_get_effective_video_codec", lambda *args: "libx264")
    image = tmp_path / "still.png"
    Image.new("RGB", (64, 64), SOURCE_RGB).save(image)

    # Stock footage arrives tagged BT.709.
    source = tmp_path / "source.mp4"
    subprocess.run(
        [binary, "-y", "-loop", "1", "-framerate", "10", "-i", str(image), "-t", "0.4",
         "-vf", video._BT709_VIDEO_FILTER, "-c:v", "libx264", str(source)],
        check=True, capture_output=True,
    )
    clip_file = tmp_path / "clip.mp4"
    with video.VideoFileClip(str(source), audio=False) as clip:
        video._write_videofile_with_codec_fallback(clip, str(clip_file), codec="libx264", logger=None, fps=10)
    _assert_bt709(binary, clip_file)

    combined = tmp_path / "combined.mp4"
    video.concat_video_clips_with_ffmpeg([str(clip_file)], str(combined), 1, str(tmp_path))
    _assert_bt709(binary, combined)

    _assert_bt709(binary, video.render_image_zoom_video(str(image), clip_duration=1))
