import os
import random
import shutil
import subprocess

import pytest
from moviepy import VideoFileClip

from app.config import config
from app.models.schema import VideoAspect, VideoConcatMode
from app.services import video


@pytest.mark.parametrize("directory", ["ordinary", "مرحبا-O'Brien", r"back\slash"])
def test_combination_preserves_native_output_directory(tmp_path, directory):
    if os.name == "nt" and "\\" in directory:
        pytest.skip("Windows does not permit a literal backslash in a path component")
    binary = video.utils.get_ffmpeg_binary()
    if not shutil.which(binary):
        pytest.skip("FFmpeg is required for native media rendering")

    source = tmp_path / "source.mp4"
    audio = tmp_path / "narration.wav"
    output_dir = tmp_path / directory
    output_dir.mkdir()
    output = output_dir / "combined.mp4"
    base = [binary, "-nostdin", "-v", "error", "-y", "-threads", "1"]
    subprocess.run(
        [*base, "-f", "lavfi", "-i", "color=c=white:s=64x64:r=30:d=0.4",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)],
        check=True, capture_output=True,
    )
    subprocess.run(
        [*base, "-f", "lavfi", "-i", "sine=frequency=220:duration=0.3",
         "-ar", "44100", str(audio)],
        check=True, capture_output=True,
    )

    previous_config = config.app.copy()
    previous_random = random.getstate()
    config.app.update({"video_codec": "libx264", "video_clip_concurrency": 1})
    try:
        returned = video.combine_videos(
            str(output), [str(source)], str(audio),
            video_aspect=VideoAspect.square,
            video_concat_mode=VideoConcatMode.sequential,
            video_transition_mode=None, threads=1,
        )
        assert returned == str(output)
        with VideoFileClip(str(output), audio=False) as rendered:
            assert 0.25 <= rendered.duration <= 0.4
            assert rendered.get_frame(0.1).mean() > 200
        assert list(output_dir.iterdir()) == [output]
    finally:
        config.app.clear()
        config.app.update(previous_config)
        random.setstate(previous_random)
