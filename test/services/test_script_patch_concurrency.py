import json
import threading
from app.services import task_artifacts


def test_concurrent_real_manifest_updates_preserve_both_fields(tmp_path, monkeypatch):
    target = tmp_path / "script.json"
    target.write_text('{"video_script": "preserve original"}', encoding="utf-8")
    monkeypatch.setattr(task_artifacts, "_script_file", lambda task_id: target)
    first_read = threading.Event()
    release_read = threading.Event()
    second_finished = threading.Event()
    original_load = json.load

    def controlled_load(source):
        payload = original_load(source)
        if threading.current_thread().name == "first":
            first_read.set()
            assert release_read.wait(2)
        return payload

    monkeypatch.setattr(task_artifacts.json, "load", controlled_load)
    outcomes = []

    def first():
        outcomes.append(
            task_artifacts.patch_script_data("task", material_sources=["clip"])
        )

    def second():
        outcomes.append(
            task_artifacts.patch_script_data("task", experiment_id="experiment")
        )
        second_finished.set()

    a = threading.Thread(target=first, name="first")
    b = threading.Thread(target=second, name="second")
    a.start()
    assert first_read.wait(2)
    b.start()
    # The old implementation lets the second update commit while the first
    # still holds stale JSON. A serialized implementation waits instead.
    second_finished.wait(0.05)
    release_read.set()
    a.join(2)
    b.join(2)
    assert not a.is_alive() and not b.is_alive()
    assert outcomes == [True, True]
    assert json.loads(target.read_text()) == {
        "video_script": "preserve original",
        "material_sources": ["clip"],
        "experiment_id": "experiment",
    }
