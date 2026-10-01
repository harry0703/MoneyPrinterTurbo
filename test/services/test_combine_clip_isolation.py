from concurrent.futures import ThreadPoolExecutor
import shutil
import subprocess
import threading
import wave

import numpy as np

from app.models.schema import VideoAspect, VideoConcatMode
from app.services import video


def test_concurrent_combinations_own_intermediate_clips(tmp_path, monkeypatch):
    binary = video.utils.get_ffmpeg_binary()
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(24000)
        writer.writeframes(b"\0\0" * 4800)
    sources = []
    for color in ("red", "blue"):
        source = tmp_path / f"{color}.mp4"
        subprocess.run([binary, "-y", "-f", "lavfi", "-i", f"color=c={color}:s=64x64:r=10", "-t", "0.4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True, capture_output=True)
        sources.append(source)
    monkeypatch.setattr(VideoAspect, "to_resolution", lambda self: (64, 64))
    monkeypatch.setattr(video, "_get_configured_video_codec", lambda: "libx264")
    monkeypatch.setattr(video, "_get_effective_video_codec", lambda *args: "libx264")
    # Serialize the two real encodes, then hold both until they have completed.
    # This deterministically exposes a shared filename before either concat.
    encode_lock = threading.Lock()
    both_encoded = threading.Barrier(2)
    real_write = video._write_videofile_with_codec_fallback
    paths = []

    def encode(clip, target, **kwargs):
        with encode_lock:
            paths.append(target)
            real_write(clip, target, threads=1, **kwargs)
        both_encoded.wait(timeout=15)

    monkeypatch.setattr(video, "_write_videofile_with_codec_fallback", encode)
    foreign = tmp_path / "temp-clip-1.mp4"
    shutil.copyfile(sources[0], foreign)
    sentinel = foreign.read_bytes()

    def combine(index):
        output = tmp_path / f"output-{index}.mp4"
        video.combine_videos(str(output), [str(sources[index])], str(audio), video_concat_mode=VideoConcatMode.sequential, threads=1)
        return output

    with ThreadPoolExecutor(max_workers=2) as executor:
        outputs = list(executor.map(combine, range(2)))
    for index, output in enumerate(outputs):
        with video.VideoFileClip(str(output), audio=False) as clip:
            pixel = np.mean(clip.get_frame(0), axis=(0, 1))
            channel = 0 if index == 0 else 2
            assert pixel[channel] > 200
            assert pixel[2 if index == 0 else 0] < 30
    assert len(set(paths)) == 2
    assert foreign.read_bytes() == sentinel
    assert sorted(p.name for p in tmp_path.iterdir()) == ["audio.wav", "blue.mp4", "output-0.mp4", "output-1.mp4", "red.mp4", "temp-clip-1.mp4"]
