"""Burned subtitles in the local renderer: ASS generation plus a native export."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from app.services.video_project import (
    ProjectError,
    RenderSettings,
    VideoProject,
    subtitle_document,
)


def _settings(**overrides):
    values = {"width": 64, "height": 64, "fps": 10}
    values.update(overrides)
    return RenderSettings.parse(values)


def test_document_times_every_line_end_to_end():
    document = subtitle_document(
        [("first line", 1.5), ("", 0.5), ("second line", 2.0)],
        _settings(subtitles=True, subtitle_font_size=30),
    )

    assert "PlayResX: 64" in document
    assert "PlayResY: 64" in document
    assert "Style: Default,Arial,30," in document
    assert "Dialogue: 0,0:00:00.00,0:00:01.50,Default,,0,0,0,,first line" in document
    # The silent scene keeps the timeline moving without emitting an event.
    assert "Dialogue: 0,0:00:01.50,0:00:02.00" not in document
    assert "Dialogue: 0,0:00:02.00,0:00:04.00,Default,,0,0,0,,second line" in document


def test_document_keeps_narration_out_of_override_blocks():
    document = subtitle_document(
        [("a {\\b1} b\nnext", 1.0)], _settings(subtitles=True)
    )

    dialogue = [line for line in document.splitlines() if line.startswith("Dialogue")][0]
    assert dialogue.endswith("a (\\b1) b next")
    assert "{\\" not in dialogue


@pytest.mark.parametrize(
    "settings",
    [
        {"subtitles": "yes"},
        {"subtitle_font": ""},
        {"subtitle_font": "Arial,60"},
        {"subtitle_font_size": 4},
        {"subtitle_font_size": True},
    ],
)
def test_invalid_subtitle_settings_are_rejected(settings):
    with pytest.raises(ProjectError):
        RenderSettings.parse(settings)


def _media(arguments):
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-threads",
            "1",
            *arguments,
        ],
        check=True,
    )


def _bottom_white_pixels(path):
    raw = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            "0.2",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "crop=64:20:0:44",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
    )
    return sum(
        1 for index in range(0, len(raw), 3) if min(raw[index : index + 3]) > 200
    )


def test_native_export_burns_narration_over_mixed_music(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("native FFmpeg/FFprobe required; no mocked rendering claim")
    _media(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=64x64:r=10:d=0.6",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(tmp_path / "red.mp4"),
        ]
    )
    for name, frequency in (("voice", 440), ("music", 220)):
        _media(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:sample_rate=48000:duration=0.6",
                str(tmp_path / f"{name}.wav"),
            ]
        )
    request = {
        "project_id": "lesson",
        "settings": {"width": 64, "height": 64, "fps": 10, "subtitles": True,
                     "subtitle_font_size": 30},
        "scenes": [
            {
                "id": "opening",
                "footage": "red.mp4",
                "audio": "voice.wav",
                "narration": "Original narration",
            }
        ],
        "bgm": "music.wav",
    }
    project = VideoProject(tmp_path / "subtitled")
    project.create_revision(request, relative_to=tmp_path)
    status = project.render()

    export = Path(status["export"]["path"])
    assert export.is_file()
    assert _bottom_white_pixels(export) > 0
    assert not (project.directory / ".work" / "subtitles.ass").exists()

    plain = dict(request)
    plain["project_id"] = "plain"
    plain["settings"] = {"width": 64, "height": 64, "fps": 10}
    plain.pop("bgm")
    plain_project = VideoProject(tmp_path / "plain")
    plain_project.create_revision(plain, relative_to=tmp_path)
    plain_export = Path(plain_project.render()["export"]["path"])
    assert _bottom_white_pixels(plain_export) == 0

    # Flipping subtitles off rebuilds only the export, not the scene media.
    spec_without = json.loads(json.dumps(request))
    spec_without["settings"].pop("subtitles")
    spec_without["settings"].pop("subtitle_font_size")
    project.create_revision(spec_without, relative_to=tmp_path)
    rebuilt = {stage["key"] for stage in project.plan() if stage["action"] == "build"}
    assert rebuilt == {"export"}
