"""Select immutable revisions without discarding their artifacts or history."""

import json
import shutil
import subprocess
from unittest.mock import patch

import pytest

from app.services.video_project import ProjectError, VideoProject, main


@pytest.fixture
def revisions(tmp_path):
    media = tmp_path / "prepared.mp4"
    media.write_bytes(b"prepared snapshot fixture; no decoding claim")
    store = VideoProject(tmp_path / "project")
    request = {"project_id": "history", "scenes": [{"id": "one", "footage": str(media)}]}
    with patch("app.services.video_project._tool_version", return_value="fixture-v1"):
        before = store.create_revision(request)
        request["scenes"][0]["duration"] = 9
        after = store.create_revision(request)
    return store, request, before, after


def test_checkout_selects_existing_revision_without_rewriting_it(revisions):
    store, _, before, after = revisions
    revision_files = {
        p: p.read_bytes() for p in (store.directory / "revisions").rglob("*.json")
    }
    metadata_path = store.directory / "project.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["last_successful_export"] = {"revision_id": after["revision_id"], "path": "retained.mp4"}
    metadata_path.write_text(json.dumps(metadata))
    selected = store.checkout(before["revision_id"])
    assert selected["revision_id"] == before["revision_id"]
    assert store.revision()["scenes"][0]["duration"] == 5
    assert store.metadata()["last_successful_export"] == metadata["last_successful_export"]
    assert {p: p.read_bytes() for p in revision_files} == revision_files
    store.checkout(after["revision_id"])
    assert store.revision()["scenes"][0]["duration"] == 9


@pytest.mark.parametrize("revision", ["absent", "../outside", ""])
def test_invalid_checkout_does_not_move_current_revision(revisions, revision):
    store, _, _, after = revisions
    old = store.metadata()
    with pytest.raises((ProjectError, FileNotFoundError)):
        store.checkout(revision)
    assert store.metadata() == old
    assert store.revision()["revision_id"] == after["revision_id"]


def test_checked_out_revision_becomes_parent_of_next_edit(revisions):
    store, request, before, _ = revisions
    store.checkout(before["revision_id"])
    with patch("app.services.video_project._tool_version", return_value="fixture-v1"):
        edited = store.create_revision(request)
    assert edited["parent_revision"] == before["revision_id"]


def test_checkout_rejects_wrong_project_identity(revisions):
    store, _, before, after = revisions
    path = store.directory / "revisions" / before["revision_id"] / "spec.json"
    payload = json.loads(path.read_text())
    payload["project_id"] = "another"
    path.write_text(json.dumps(payload))
    with pytest.raises(ProjectError, match="project"):
        store.checkout(before["revision_id"])
    assert store.metadata()["current_revision"] == after["revision_id"]


def test_cli_checkout_returns_selected_revision(revisions, capsys):
    store, _, before, _ = revisions
    assert main(["--project", str(store.directory), "checkout", before["revision_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["revision_id"] == before["revision_id"]


def test_checkout_during_native_render_prevents_wrong_promotion_and_reuses_old_export(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("native FFmpeg and FFprobe required")
    media = tmp_path / "source.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
         "color=c=blue:s=64x64:r=10:d=0.3", "-c:v", "libx264", "-pix_fmt",
         "yuv420p", str(media)], check=True
    )
    store = VideoProject(tmp_path / "project")
    request = {"project_id": "native", "settings": {"width": 64, "height": 64, "fps": 10},
               "scenes": [{"id": "one", "footage": str(media), "duration": 0.3}]}
    original = store.create_revision(request)
    first = store.render()
    request["scenes"][0]["duration"] = 0.4
    newer = store.create_revision(request)
    switched = []

    def switch(stage, reused):
        if not switched:
            store.checkout(original["revision_id"])
            switched.append(True)

    finished = store.render(newer["revision_id"], on_stage=switch)
    assert not finished["promoted"]
    assert store.metadata()["current_revision"] == original["revision_id"]
    assert store.metadata()["last_successful_export"]["sha256"] == first["export"]["sha256"]
    restored = store.render()
    assert restored["promoted"]
    assert all(stage["reused"] for stage in restored["stages"].values())
    assert restored["export"]["sha256"] == first["export"]["sha256"]
