"""Native FFmpeg scenarios plus deterministic storage/lifecycle checks."""

import copy
import json
from pathlib import Path
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.video_project import (
    ProjectError,
    RenderCancelled,
    RenderSettings,
    VideoProject,
    _atomic_json,
    main,
    stage_graph,
)


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


@pytest.fixture
def native(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("native FFmpeg/FFprobe required; no mocked rendering claim")
    for color in ("red", "blue", "green"):
        _media(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=64x64:r=10:d=0.6",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(tmp_path / f"{color}.mp4"),
            ]
        )
    for name, frequency, duration in (
        ("voice", 440, 0.6),
        ("voice2", 880, 0.9),
        ("music", 220, 0.6),
        ("music2", 330, 0.6),
    ):
        _media(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
                str(tmp_path / f"{name}.wav"),
            ]
        )
    request = {
        "project_id": "episode",
        "settings": {"width": 64, "height": 64, "fps": 10},
        "scenes": [
            {
                "id": "opening",
                "footage": "red.mp4",
                "audio": "voice.wav",
                "narration": "Original narration",
            },
            {"id": "closing", "footage": "blue.mp4", "duration": 0.6},
        ],
        "bgm": "music.wav",
    }
    project = VideoProject(tmp_path / "project's files")
    revision = project.create_revision(request, relative_to=tmp_path)
    return project, request, revision, tmp_path


def _builds(project):
    return {stage["key"] for stage in project.plan() if stage["action"] == "build"}


def _duration(path):
    return float(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            text=True,
        )
    )


def _pixel(path, second):
    raw = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(second),
            "-i",
            path,
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
    )
    return tuple(raw[:3])


def _audio(path):
    return subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            path,
            "-vn",
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-",
        ]
    )


def test_three_native_revision_scenarios(native):
    project, request, original, root = native
    first = project.render()
    initial_export = first["export"]["path"]
    assert 1.15 <= _duration(initial_export) <= 1.35
    assert _pixel(initial_export, 0.2)[0] > 200
    assert _pixel(initial_export, 0.9)[2] > 200
    assert any(_audio(initial_export))
    assert not _builds(project)

    footage = copy.deepcopy(request)
    footage["scenes"][0]["footage"] = "green.mp4"
    shot = project.create_revision(footage, relative_to=root)
    assert _builds(project) == {"opening:scene", "assembly", "export"}
    rendered = project.render()
    assert _pixel(rendered["export"]["path"], 0.2)[1] > 80
    assert _pixel(rendered["export"]["path"], 0.9)[2] > 200
    assert rendered["stages"]["opening:audio"]["reused"]
    assert rendered["stages"]["closing:scene"]["reused"]

    narration = copy.deepcopy(footage)
    narration["scenes"][0].update(audio="voice2.wav", narration="New narration")
    spoken = project.create_revision(narration, relative_to=root)
    assert _builds(project) == {
        "opening:audio",
        "opening:timing",
        "opening:scene",
        "assembly",
        "export",
    }
    narrated = project.render()
    assert 1.45 <= _duration(narrated["export"]["path"]) <= 1.65
    assert narrated["stages"]["closing:scene"]["reused"]
    assert _audio(narrated["export"]["path"]) != _audio(rendered["export"]["path"])

    music = copy.deepcopy(narration)
    music["bgm"] = "music2.wav"
    mixed = project.create_revision(music, relative_to=root)
    assert _builds(project) == {"export"}
    final = project.render()
    assert all(
        entry["reused"] for key, entry in final["stages"].items() if key != "export"
    )
    assert _audio(final["export"]["path"]) != _audio(narrated["export"]["path"])
    assert (
        project.metadata()["last_successful_export"]["revision_id"]
        == mixed["revision_id"]
    )
    assert Path(initial_export).is_file()  # Previous success was never overwritten.
    assert project.compare(shot["revision_id"], spoken["revision_id"])[0]["change"] in {
        "changed",
        "unchanged",
    }
    assert stage_graph(project.revision()) == stage_graph(project.revision())
    assert original["project_id"] == mixed["project_id"]


def test_integrity_and_source_snapshot(native):
    project, request, revision, root = native
    project.render()
    (root / "red.mp4").write_bytes(b"changed outside project")
    assert not _builds(project)  # Imports are snapshots, not mutable references.
    opening = next(
        stage for stage in stage_graph(revision) if stage.key == "opening:scene"
    )
    artifact = Path(project._cached(opening)["path"])
    artifact.write_bytes(b"corrupted")
    assert _builds(project) == {"opening:scene", "assembly", "export"}
    project.render()  # Repair stage from verified sources; final export remains verified.
    assert artifact.read_bytes() != b"corrupted"
    asset = project.directory / revision["scenes"][0]["footage"]["path"]
    asset.write_bytes(b"source damage")
    with pytest.raises(ProjectError, match="source snapshot"):
        project.plan()


def test_failed_retry_and_last_success(native):
    project, request, revision, root = native
    success = project.render()
    previous = project.metadata()["last_successful_export"]
    request["scenes"][0]["footage"] = "green.mp4"
    project.create_revision(request, relative_to=root)
    with pytest.raises(ProjectError, match="working.*required"):
        project.render(ffmpeg=str(root / "missing-command"))
    assert project.status()["state"] == "failed"
    assert project.metadata()["last_successful_export"] == previous
    with pytest.raises(ProjectError, match="explicit --retry"):
        project.render()
    assert project.render(retry=True)["state"] == "succeeded"
    assert Path(success["export"]["path"]).exists()


def test_cancel_then_explicit_retry(native):
    project, _, _, _ = native

    def cancel_scene(stage, reused):
        if stage.kind == "scene":
            project.cancel()

    with pytest.raises(RenderCancelled):
        project.render(on_stage=cancel_scene)
    assert project.status()["state"] == "cancelled"
    assert project.metadata()["last_successful_export"] is None
    with pytest.raises(ProjectError, match="explicit --retry"):
        project.render()
    assert project.render(retry=True)["state"] == "succeeded"
    assert project.status()["stages"]["opening:audio"]["reused"]


def test_stale_revision_cannot_promote(native):
    project, request, old, root = native
    advanced = False

    def next_revision(stage, reused):
        nonlocal advanced
        if not advanced:
            advanced = True
            request["bgm"] = "music2.wav"
            project.create_revision(request, relative_to=root)

    old_result = project.render(old["revision_id"], on_stage=next_revision)
    assert old_result["state"] == "succeeded" and not old_result["promoted"]
    assert project.metadata()["last_successful_export"] is None
    assert project.render()["promoted"]


def test_concurrent_revisions_share_immutable_verified_artifacts(native):
    project, request, old, root = native
    new = project.create_revision(request, relative_to=root)
    barrier = threading.Barrier(2)

    def render(revision):
        met = False

        def wait(stage, reused):
            nonlocal met
            if not met:
                met = True
                barrier.wait(timeout=10)

        return project.render(revision, on_stage=wait)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(render, [old["revision_id"], new["revision_id"]]))
    assert [result["promoted"] for result in results] == [False, True]
    assert results[0]["export"]["sha256"] == results[1]["export"]["sha256"]
    assert not _builds(project)


def test_interrupted_status_requires_retry(native):
    project, _, revision, _ = native
    _atomic_json(
        project._revision_path(revision["revision_id"]) / "status.json",
        {"state": "running", "stages": {}},
    )
    with pytest.raises(ProjectError, match="explicit --retry"):
        project.render()
    assert project.render(retry=True)["state"] == "succeeded"


@pytest.mark.parametrize(
    "settings",
    [
        {"api_key": "secret"},
        {"width": 63},
        {"fps": True},
        {"bgm_volume": float("nan")},
        {"height": -2},
    ],
)
def test_settings_validation(settings):
    with pytest.raises(ProjectError):
        RenderSettings.parse(settings)


def test_cli_presets_compare_and_path_validation(native, capsys):
    project, request, before, root = native
    manifest = root / "input.json"
    manifest.write_text(json.dumps(request))
    preset = root / "preset.json"
    prefix = ["--project", str(project.directory)]
    assert main(prefix + ["save-preset", str(preset)]) == 0
    assert "scenes" not in json.loads(preset.read_text())
    assert main(prefix + ["revise", str(manifest), "--preset", str(preset)]) == 0
    after = project.metadata()["current_revision"]
    assert main(prefix + ["compare", before["revision_id"], after]) == 0
    assert main(prefix + ["plan"]) == 0
    assert main(prefix + ["status"]) == 0
    with pytest.raises(ProjectError):
        project.revision("../../escape")
    request["api_key"] = "do not persist"
    with pytest.raises(ProjectError, match="unknown project fields"):
        project.create_revision(request, relative_to=root)
    assert "do not persist" not in (project.directory / "project.json").read_text()


def test_real_process_crash_recovers_completed_stages(native):
    import sys

    project, _, _, _ = native
    script = """import os,sys
from app.services.video_project import VideoProject
project=VideoProject(sys.argv[1])
def crash(stage,reused):
    if stage.kind=='scene': os._exit(37)
project.render(on_stage=crash)
"""
    crashed = subprocess.run(
        [sys.executable, "-c", script, str(project.directory)], timeout=20
    )
    assert crashed.returncode == 37
    assert project.status()["state"] == "running"
    assert "opening:audio" not in _builds(project)
    assert "opening:timing" not in _builds(project)
    assert project.metadata()["last_successful_export"] is None
    with pytest.raises(ProjectError, match="explicit --retry"):
        project.render()
    assert project.render(retry=True)["stages"]["opening:audio"]["reused"]


def test_command_deadline_and_active_cancellation(tmp_path):
    import sys
    import time

    project = VideoProject(tmp_path)
    cancellation = tmp_path / "cancel.json"
    before = time.monotonic()
    with pytest.raises(ProjectError, match="deadline"):
        project._run(
            [sys.executable, "-c", "import time; time.sleep(60)"], cancellation, 0.15
        )
    assert time.monotonic() - before < 3
    timer = threading.Timer(
        0.15, lambda: _atomic_json(cancellation, {"cancelled": True})
    )
    timer.start()
    try:
        with pytest.raises(RenderCancelled):
            project._run(
                [sys.executable, "-c", "import time; time.sleep(60)"], cancellation, 30
            )
    finally:
        timer.join(timeout=3)


def test_cli_native_render(native):
    import sys

    project, _, _, _ = native
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.services.video_project",
            "--project",
            str(project.directory),
            "render",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    report = json.loads(completed.stdout)
    assert report["state"] == "succeeded"
    assert Path(report["export"]["path"]).is_file()


def test_order_and_render_settings_invalidation(native):
    project, request, before, root = native
    project.render()
    reordered = copy.deepcopy(request)
    reordered["scenes"].reverse()
    project.create_revision(reordered, relative_to=root)
    assert _builds(project) == {"assembly", "export"}
    settings = copy.deepcopy(request)
    settings["settings"]["width"] = 128
    project.create_revision(settings, relative_to=root)
    assert _builds(project) == {"opening:scene", "closing:scene", "assembly", "export"}
    settings = copy.deepcopy(request)
    settings["settings"]["narration_volume"] = 0.5
    project.create_revision(settings, relative_to=root)
    assert _builds(project) == {
        "opening:audio",
        "opening:timing",
        "opening:scene",
        "closing:audio",
        "closing:timing",
        "closing:scene",
        "assembly",
        "export",
    }
    project.create_revision(request, relative_to=root)
    assert not _builds(project)
    changed = project.compare(
        before["revision_id"], project.metadata()["current_revision"]
    )
    assert all(row["change"] == "unchanged" for row in changed)


def test_no_cross_project_artifact_reuse(native):
    project, request, _, root = native
    project.render()
    other = VideoProject(root / "second-project")
    other.create_revision(request, relative_to=root)
    assert all(stage["action"] == "build" for stage in other.plan())


def test_commit_record_loss_is_not_success(native):
    project, request, before, root = native
    project.render()
    stage = stage_graph(before)[0]
    record = project.directory / "artifacts" / stage.fingerprint / "record.json"
    record.unlink()
    assert "opening:audio" in _builds(project)
    assert project.render()["state"] == "succeeded"
    # A source asset extension never controls output/cache paths.
    assert not list(project.directory.glob("*.mp4"))


def test_prepared_media_cannot_fetch_remote_playlist(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("native FFmpeg required")
    playlist = tmp_path / "unexpected-video.m3u8"
    playlist.write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nhttp://127.0.0.1:9/private.ts\n#EXT-X-ENDLIST\n"
    )
    project = VideoProject(tmp_path / "project")
    with pytest.raises(ProjectError, match="not on whitelist"):
        project._run(
            ["ffmpeg", "-v", "error", "-i", str(playlist), "-f", "null", "-"],
            tmp_path / "cancel.json",
            10,
        )


def test_silent_duration_change_renders_new_duration(native):
    project, request, original, root = native
    first = project.render()
    original_audio = project.status()["stages"]["closing:audio"]["fingerprint"]
    request["scenes"][1]["duration"] = 1.2
    project.create_revision(request, relative_to=root)
    assert _builds(project) == {
        "closing:audio",
        "closing:timing",
        "closing:scene",
        "assembly",
        "export",
    }
    second = project.render()
    assert 1.75 <= _duration(second["export"]["path"]) <= 1.95
    assert second["stages"]["closing:audio"]["fingerprint"] != original_audio
    assert (
        _duration(second["export"]["path"]) > _duration(first["export"]["path"]) + 0.5
    )


def test_different_silent_durations_do_not_collide(native):
    project, request, original, root = native
    request["scenes"][0] = {"id": "short", "footage": "red.mp4", "duration": 0.3}
    request["scenes"][1] = {"id": "long", "footage": "blue.mp4", "duration": 1.2}
    revision = project.create_revision(request, relative_to=root)
    stages = {stage.key: stage for stage in stage_graph(revision)}
    assert stages["short:audio"].fingerprint != stages["long:audio"].fingerprint
    rendered = project.render()
    short = Path(project._cached(stages["short:audio"])["path"])
    long = Path(project._cached(stages["long:audio"])["path"])
    assert abs(_duration(str(short)) - 0.3) < 0.02
    assert abs(_duration(str(long)) - 1.2) < 0.02
    assert 1.45 <= _duration(rendered["export"]["path"]) <= 1.65


def test_local_reference_playlist_rejected_as_prepared_footage(native):
    project, request, original, root = native
    segment = root / "mutable.ts"
    _media(["-i", str(root / "red.mp4"), "-c", "copy", "-f", "mpegts", str(segment)])
    playlist = root / "external.m3u8"
    playlist.write_text(
        f"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n#EXTINF:0.6,\n{segment}\n#EXT-X-ENDLIST\n"
    )
    request["scenes"][0]["footage"] = str(playlist)
    project.create_revision(request, relative_to=root)
    with pytest.raises(ProjectError, match="not on whitelist|Invalid data found"):
        project.render()
    assert project.status()["failed_stage"] == "opening:scene"
    assert project.metadata()["last_successful_export"] is None
    assert not list(project.directory.glob("artifacts/*/*.mp4"))


def test_dash_external_segments_cannot_escape_source_snapshot(native):
    import re

    project, request, original, root = native
    dash = root / "external.mpd"

    def segments(color):
        _media(
            [
                "-i",
                str(root / f"{color}.mp4"),
                "-c:v",
                "libx264",
                "-f",
                "dash",
                str(dash),
            ]
        )

    segments("red")
    text = dash.read_text()
    text = re.sub(
        r'(initialization|media)="([^"]+)"',
        lambda match: f'{match[1]}="{root / match[2]}"',
        text,
    )
    dash.write_text(text)
    request["scenes"][0]["footage"] = str(dash)
    revision = project.create_revision(request, relative_to=root)
    source_snapshot = project._asset_path(revision["scenes"][0]["footage"])
    unchanged_manifest = source_snapshot.read_bytes()
    segments(
        "blue"
    )  # External segments change while the hashed snapshot remains unchanged.
    assert source_snapshot.read_bytes() == unchanged_manifest
    with pytest.raises(ProjectError, match="not on whitelist"):
        project.render()
    assert project.status()["failed_stage"] == "opening:scene"
    assert project.metadata()["last_successful_export"] is None


@pytest.mark.parametrize("text", [
    "Jump to the recording.",
    "Jump to 00:01:23,456 in the recording.",
    "Show 00:01:23,456 --> 00:01:25,456 in the log.",
])
def test_final_caption_render_keeps_body_timecodes_and_duration(tmp_path, text):
    from moviepy import VideoFileClip

    from app.config import config
    from app.models.schema import VideoAspect, VideoParams
    from app.services import video
    from app.utils.subtitle_writer import write_subtitle_file

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("native FFmpeg executable is unavailable")
    font = Path(config.root_dir) / "resource/fonts/Charm-Regular.ttf"
    if not font.is_file():
        pytest.skip("native caption font is unavailable")

    base = [ffmpeg, "-nostdin", "-v", "error", "-y", "-threads", "1"]
    media = tmp_path / "white.mp4"
    audio = tmp_path / "narration.wav"
    subprocess.run([
        *base, "-f", "lavfi", "-i", "color=c=white:s=1080x1080:r=10:d=0.8",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(media),
    ], check=True, timeout=30)
    subprocess.run([
        *base, "-f", "lavfi", "-i", "sine=frequency=220:duration=0.8",
        "-ar", "44100", str(audio),
    ], check=True, timeout=30)
    artifact = tmp_path / "accepted.srt"
    assert write_subtitle_file(
        str(artifact), "1\n00:00:00,100 --> 00:00:00,700\n" + text + "\n\n"
    )
    output = tmp_path / "captioned.mp4"
    params = VideoParams(
        video_subject="owned-caption", video_aspect=VideoAspect.square,
        subtitle_enabled=True, subtitle_position="center",
        font_name="Charm-Regular.ttf", font_size=36,
        text_fore_color="#000000", stroke_width=0, text_background_color=False,
        bgm_type="", bgm_volume=0, voice_volume=1, n_threads=1,
    )
    previous = config.app.copy()
    try:
        config.app.update({"video_codec": "libx264", "video_clip_concurrency": 1})
        assert video.generate_video(
            str(media), str(audio), str(artifact), str(output), params
        )
        with VideoFileClip(str(output), audio=False) as rendered:
            assert 0.7 <= rendered.duration <= 0.9
            frame = rendered.get_frame(0.4)
            assert int((frame.mean(axis=2) < 180).sum()) > 100
    finally:
        config.app.clear()
        config.app.update(previous)


@pytest.mark.parametrize("field", ["narration_volume", "bgm_volume", "duration"])
@pytest.mark.parametrize("sign", [-1, 1])
def test_project_cli_rejects_large_json_numbers_without_traceback(
    tmp_path, field, sign
):
    import sys

    media = tmp_path / "footage.mp4"
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
            str(media),
        ]
    )
    manifest = tmp_path / "manifest.json"
    project = tmp_path / "project"
    request = {
        "project_id": "numbers",
        "scenes": [{"id": "opening", "footage": str(media), "duration": 0.6}],
    }
    manifest.write_text(json.dumps(request), encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "app.services.video_project",
        "--project",
        str(project),
        "revise",
        str(manifest),
    ]
    accepted = subprocess.run(command, text=True, capture_output=True, timeout=20)
    assert accepted.returncode == 0, accepted.stderr
    previous = (project / "project.json").read_bytes()
    if field == "duration":
        request["scenes"][0][field] = sign * 10**399
    else:
        request["settings"] = {field: sign * 10**399}
    manifest.write_text(json.dumps(request), encoding="utf-8")
    rejected = subprocess.run(command, text=True, capture_output=True, timeout=20)
    assert rejected.returncode == 1
    assert (project / "project.json").read_bytes() == previous
    assert rejected.stdout == ""
    assert "Traceback" not in rejected.stderr
    assert "video project:" in rejected.stderr
    assert ("scene duration" if field == "duration" else field) in rejected.stderr


@pytest.mark.parametrize(
    "field,number",
    [
        ("narration_volume", 4),
        ("bgm_volume", 4),
        ("duration", 3600),
        ("narration_volume", 5),
        ("bgm_volume", 5),
        ("duration", 3601),
    ],
)
def test_project_cli_numeric_bounds_controls(tmp_path, field, number):
    import sys

    media = tmp_path / "footage.mp4"
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
            str(media),
        ]
    )
    manifest = tmp_path / "manifest.json"
    project = tmp_path / "project"
    request = {
        "project_id": "numbers",
        "scenes": [{"id": "opening", "footage": str(media), "duration": 0.6}],
    }
    if field == "duration":
        request["scenes"][0][field] = number
    else:
        request["settings"] = {field: number}
    manifest.write_text(json.dumps(request), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.services.video_project",
            "--project",
            str(project),
            "revise",
            str(manifest),
        ],
        text=True,
        capture_output=True,
        timeout=20,
    )
    if number in (4, 3600):
        assert result.returncode == 0, result.stderr
        spec = json.loads(result.stdout)
        assert (
            spec["scenes"][0][field] if field == "duration" else spec["settings"][field]
        ) == number
        assert project.joinpath("project.json").is_file()
    else:
        assert result.returncode == 1
        assert "Traceback" not in result.stderr
        assert "video project:" in result.stderr
        assert ("scene duration" if field == "duration" else field) in result.stderr
        assert not project.joinpath("project.json").exists()
