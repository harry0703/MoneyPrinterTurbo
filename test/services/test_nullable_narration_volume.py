import shutil
import subprocess

import numpy as np
import pytest

from app.models.schema import TaskVideoRequest
from app.services import video


@pytest.mark.parametrize("volume, audible", [(None, True), (1.0, True), (0.0, False)])
def test_valid_nullable_volume_renders_without_losing_mute(tmp_path, volume, audible):
    if not shutil.which("ffmpeg"):
        pytest.skip("native FFmpeg required")
    footage, speech, output = (tmp_path / name for name in ("input.mp4", "speech.wav", "final.mp4"))
    base = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-threads", "1"]
    subprocess.run([*base, "-f", "lavfi", "-i", "color=c=red:s=64x64:r=10:d=0.2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(footage)], check=True)
    subprocess.run([*base, "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2", str(speech)], check=True)
    request = TaskVideoRequest(video_subject="Narration", voice_volume=volume, subtitle_enabled=False, bgm_type="", n_threads=1)
    assert video.generate_video(str(footage), str(speech), "", str(output), request)
    decoded = subprocess.run([*base, "-i", str(output), "-map", "0:a:0", "-f", "f32le", "-acodec", "pcm_f32le", "-"], capture_output=True, check=True)
    peak = float(np.max(np.abs(np.frombuffer(decoded.stdout, dtype="<f4"))))
    if audible:
        assert peak > 0.02
    else:
        assert peak < 0.001
