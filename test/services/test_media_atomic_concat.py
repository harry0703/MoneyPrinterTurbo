from pathlib import Path
import subprocess

import pytest

from app.services import video


@pytest.mark.parametrize("previous", [None, b"previous complete video"])
@pytest.mark.parametrize("error", [RuntimeError("encode failed"), TimeoutError("encoder timed out")])
def test_concat_failure_never_publishes_partial_video(tmp_path, monkeypatch, previous, error):
    output = tmp_path / "combined.mp4"
    if previous is not None:
        output.write_bytes(previous)
    monkeypatch.setattr(video, "_get_effective_video_codec", lambda: "libx264")

    def failed_encode(command, reported_output):
        Path(command[-1]).write_bytes(b"partial encoding")
        raise error

    monkeypatch.setattr(video, "_run_concat_with_heartbeat", failed_encode)
    with pytest.raises(type(error)):
        video.concat_video_clips_with_ffmpeg(["input.mp4"], str(output), 1, str(tmp_path))
    if previous is None:
        assert not output.exists()
    else:
        assert output.read_bytes() == previous
    assert sorted(p.name for p in tmp_path.iterdir()) == ([output.name] if previous is not None else [])


def test_concat_success_publishes_real_ffmpeg_video(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    output = tmp_path / "combined.mp4"
    binary = video.utils.get_ffmpeg_binary()
    subprocess.run(
        [binary, "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=10",
         "-t", "0.2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)],
        check=True, capture_output=True,
    )
    output.write_bytes(b"old video")
    monkeypatch.setattr(video, "_get_effective_video_codec", lambda: "libx264")
    assert video.concat_video_clips_with_ffmpeg([str(source)], str(output), 1, str(tmp_path)) == "libx264"
    with video.VideoFileClip(str(output), audio=False) as clip:
        assert clip.duration >= 0.19
        assert clip.size == [64, 64]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["combined.mp4", "source.mp4"]
