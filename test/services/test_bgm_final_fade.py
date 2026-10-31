import shutil
import subprocess

import numpy as np
import pytest

from app.models.schema import TaskVideoRequest
from app.services import video


def test_looped_background_music_fades_only_at_final_video_end(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("native FFmpeg required")
    footage, speech, music, output = (tmp_path / name for name in ("input.mp4", "speech.wav", "music.wav", "final.mp4"))
    base = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-threads", "1"]
    subprocess.run([*base, "-f", "lavfi", "-i", "color=c=red:s=64x64:r=10:d=8", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(footage)], check=True)
    subprocess.run([*base, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "8", str(speech)], check=True)
    subprocess.run([*base, "-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(music)], check=True)
    request = TaskVideoRequest(video_subject="Music", subtitle_enabled=False, bgm_type="custom", bgm_file=str(music), bgm_volume=1.0, n_threads=1)
    from unittest.mock import patch
    with patch.object(video, "get_bgm_file", return_value=str(music)):
        assert video.generate_video(str(footage), str(speech), "", str(output), request)
    decoded = subprocess.run([*base, "-i", str(output), "-map", "0:a:0", "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "1", "-ar", "44100", "-"], capture_output=True, check=True)
    samples = np.frombuffer(decoded.stdout, dtype="<f4")
    def rms(start, end):
        window = samples[int(start * 44100):int(end * 44100)]
        return float(np.sqrt(np.mean(window * window)))
    initial = rms(0.2, 0.4)
    assert initial > 0.02
    # An interior point close to the first source's end must remain at full gain.
    assert rms(1.7, 1.9) > initial * 0.85
    assert rms(3.7, 3.9) > initial * 0.85
    # Only the final three seconds fade; the endpoint is quieter than its start.
    assert rms(7.7, 7.9) < initial * 0.15
