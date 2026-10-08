import random
import shutil
import subprocess

import pytest
from moviepy import VideoFileClip

from app.models.schema import VideoAspect, VideoConcatMode, VideoTransitionMode
from app.services import video


@pytest.mark.parametrize(
    "duration,speed,transition,measure",
    [
        (0.4, 1.0, None, "first"),
        (0.4, 1.0, VideoTransitionMode.fade_out, "first"),
        (0.4, 1.0, VideoTransitionMode.fade_in, "late"),
        (0.4, 1.0, VideoTransitionMode.slide_out, "slide_out"),
        (0.4, 1.0, VideoTransitionMode.slide_in, "slide_in"),
        (0.8, 2.0, VideoTransitionMode.fade_out, "first"),
        (0.4, 1.0, VideoTransitionMode.shuffle, "late"),
        (1.2, 1.0, VideoTransitionMode.fade_out, "first"),
    ],
)
def test_combined_short_footage_completes_its_transition(
    tmp_path, monkeypatch, duration, speed, transition, measure
):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("native FFmpeg required")
    source, speech, output = (tmp_path / name for name in ("source.mp4", "speech.wav", "combined.mp4"))
    base = [ffmpeg, "-nostdin", "-v", "error", "-y", "-threads", "1"]
    subprocess.run([
        *base, "-f", "lavfi", "-i", f"color=c=white:s=64x64:r=30:d={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
    ], check=True)
    subprocess.run([
        *base, "-f", "lavfi", "-i", "sine=frequency=220:duration=0.9",
        "-ar", "44100", str(speech),
    ], check=True)
    monkeypatch.setitem(video.config.app, "video_codec", "libx264")
    monkeypatch.setitem(video.config.app, "video_clip_concurrency", 1)
    state = random.getstate()
    try:
        # The ordinary shuffle selection chooses FadeIn with this seed.
        random.seed(2)
        video.combine_videos(
            str(output), [str(source)], str(speech), video_aspect=VideoAspect.square,
            video_concat_mode=VideoConcatMode.sequential, video_transition_mode=transition,
            threads=1, clip_speed=speed,
        )
    finally:
        random.setstate(state)
    with VideoFileClip(str(output), audio=False) as rendered:
        assert rendered.duration == pytest.approx(0.9, abs=0.04)
        frame = rendered.get_frame(0 if measure == "first" else 0.35)
        if measure == "slide_out":
            assert (frame.mean(axis=2) > 80).mean() < 0.25
        elif measure == "slide_in":
            assert (frame.mean(axis=2) > 80).mean() > 0.75
        else:
            threshold = 220 if measure == "first" else 200
            assert frame[rendered.h // 2, rendered.w // 2].mean() > threshold
    assert not list(tmp_path.glob("temp-clip-*.mp4"))
    assert not list(tmp_path.glob("ffmpeg-concat-*.txt"))
