import threading
from unittest.mock import patch

from edge_tts import SubMaker

from app.config import config
from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.models.schema import VideoParams
from app.services import webui_task


def test_queued_generation_keeps_the_submitted_subtitle_timeline():
    manager = InMemoryTaskManager(max_concurrent_tasks=1)
    entered, release, complete = threading.Event(), threading.Event(), threading.Event()
    captured = {}
    timeline = SubMaker()
    timeline.feed({"type": "WordBoundary", "offset": 0, "duration": 10000000, "text": "original"})
    preview = {"audio_file": "preview.mp3", "sub_maker": timeline, "params": {"language": "en"}}

    def pipeline(task_id, **kwargs):
        if task_id == "first":
            entered.set()
            assert release.wait(5)
        else:
            captured.update(kwargs["voice_preview"])
            complete.set()
        return {"task_id": task_id}

    with patch.object(webui_task, "_task_manager", manager), patch.object(webui_task.tm, "start", side_effect=pipeline), patch.object(webui_task.sm.state, "update_task"):
        try:
            webui_task.submit_generation("first", VideoParams(video_subject="fixture"), capture_logs=False)
            assert entered.wait(5)
            webui_task.submit_generation("queued", VideoParams(video_subject="fixture"), capture_logs=False, voice_preview=preview)
            assert manager.queue_size() == 1
            timeline.cues[0].content = "changed by preview rerun"
            preview["params"]["language"] = "de"
            release.set()
            assert complete.wait(5)
            assert captured["sub_maker"].cues[0].content == "original"
            assert captured["params"]["language"] == "en"
            assert captured["audio_file"] == "preview.mp3"
        finally:
            release.set()


def test_queued_aigei_generation_stops_if_the_confirmed_key_changes(monkeypatch):
    monkeypatch.setitem(config.app, "aigei_api_key", "confirmed-key")
    with (
        patch.object(webui_task._task_manager, "add_task") as enqueue,
        patch.object(webui_task.tm, "start", return_value={}) as pipeline,
        patch.object(webui_task.sm.state, "update_task"),
        patch.object(webui_task.sm.state, "get_task", return_value=None),
    ):
        webui_task.submit_generation(
            "queued-aigei", VideoParams(video_subject="Fixture", video_source="aigei"),
            capture_logs=False,
        )
        monkeypatch.setitem(config.app, "aigei_api_key", "replacement-key")
        worker = enqueue.call_args.args[0]
        result = worker(**enqueue.call_args.kwargs)

    pipeline.assert_not_called()
    assert result["error_key"] == "aigei.charge_changed"
