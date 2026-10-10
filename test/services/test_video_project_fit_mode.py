"""Native framing, validation and revision cache checks."""

import copy
import shutil
import subprocess

import pytest

from app.services.video_project import ProjectError, VideoProject


def _frame(path):
    return subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    )


def _pixel(frame, x, y):
    offset = (y * 64 + x) * 3
    return tuple(frame[offset:offset + 3])


@pytest.fixture
def project(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("native FFmpeg and FFprobe required")
    footage = tmp_path / "wide.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
         "color=c=red:s=128x64:r=10:d=0.3", "-c:v", "libx264", "-pix_fmt",
         "yuv420p", str(footage)], check=True
    )
    request = {
        "project_id": "framing", "settings": {"width": 64, "height": 64, "fps": 10},
        "scenes": [{"id": "one", "footage": str(footage), "duration": 0.3},
                   {"id": "two", "footage": str(footage), "duration": 0.3}],
    }
    return VideoProject(tmp_path / "project"), request


def test_contain_keeps_full_frame_and_reuses_other_scene(project):
    store, request = project
    original = store.create_revision(request)
    initial = store.render()
    frame = _frame(initial["export"]["path"])
    assert _pixel(frame, 32, 3)[0] > 200  # Default remains full-canvas cover.
    change = copy.deepcopy(request)
    change["scenes"][0]["fit_mode"] = "contain"
    revised = store.create_revision(change)
    assert {r["key"] for r in store.plan() if r["action"] == "build"} == {
        "one:scene", "assembly", "export"
    }
    result = store.render()
    frame = _frame(result["export"]["path"])
    assert max(_pixel(frame, 32, 3)) < 10  # Actual encoded letterbox bar.
    assert _pixel(frame, 32, 32)[0] > 200
    assert result["stages"]["one:audio"]["reused"]
    assert result["stages"]["two:scene"]["reused"]
    assert store.revision(original["revision_id"])["scenes"][0].get("fit_mode", "cover") == "cover"
    assert store.revision(revised["revision_id"])["scenes"][0]["fit_mode"] == "contain"
    assert all(r["action"] == "reuse" for r in store.plan())


def test_explicit_cover_matches_default_cache(project):
    store, request = project
    store.create_revision(request)
    store.render()
    request["scenes"][0]["fit_mode"] = "cover"
    store.create_revision(request)
    assert all(r["action"] == "reuse" for r in store.plan())


@pytest.mark.parametrize("value", ["stretch", "", None, True, 1, ["contain"]])
def test_unknown_modes_fail_before_creating_revision(project, value):
    store, request = project
    original = store.create_revision(request)
    request["scenes"][0]["fit_mode"] = value
    with pytest.raises(ProjectError, match="fit_mode"):
        store.create_revision(request)
    assert store.metadata()["current_revision"] == original["revision_id"]


@pytest.mark.parametrize("sar,bar", [("2", (32, 3)), ("1/2", (3, 32))])
def test_contain_uses_display_aspect_ratio_for_anamorphic_source(project, tmp_path, sar, bar):
    store, request = project
    footage = tmp_path / "anamorphic.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
        "color=c=red:s=64x64:r=10:d=0.3", "-vf", f"setsar={sar}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(footage),
    ], check=True)
    store.create_revision(request)
    store.render()
    request["scenes"][0].update(footage=str(footage), fit_mode="contain")
    store.create_revision(request)
    result = store.render()
    frame = _frame(result["export"]["path"])
    assert max(_pixel(frame, *bar)) < 10
    assert _pixel(frame, 32, 32)[0] > 200
    assert result["stages"]["one:audio"]["reused"]
    assert result["stages"]["two:scene"]["reused"]


def test_display_geometry_contract_retains_cover_and_invalidates_old_contain():
    from app.services.video_project import stage_graph

    # These fingerprints were captured from the pre-SAR-correction renderer.
    spec = {"settings": {}, "toolchain": {"ffmpeg": "fixture-v1", "ffprobe": "fixture-v1"},
            "scenes": [{"id": "one", "narration": "", "audio": None, "duration": 0.5,
                        "footage": {"sha256": "a" * 64, "path": "assets/" + "a" * 64}}],
            "bgm": None}
    assert next(s.fingerprint for s in stage_graph(spec) if s.key == "one:scene") == "012d726bb2b0e2def4e649cbdce55dd685334cc36299bbbf3b83b70e165f8734"
    spec["scenes"][0]["fit_mode"] = "contain"
    assert next(s.fingerprint for s in stage_graph(spec) if s.key == "one:scene") != "e07115b6bb0c28ecc44ed9606cc3f70b6c6e843f38713d1ebd425e806a0dc4c1"
