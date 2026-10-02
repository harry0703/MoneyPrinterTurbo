from app.services.state import MemoryState

def test_update_task_snapshots_nested_input_values():
    state = MemoryState()
    result = {"platform": "youtube", "details": {"videos": ["first.mp4"]}}
    state.update_task("task-1", cross_post_results=[result])
    result["details"]["videos"].append("second.mp4")
    result["platform"] = "tiktok"
    assert state.get_task("task-1")["cross_post_results"] == [{"platform": "youtube", "details": {"videos": ["first.mp4"]}}]

def test_later_updates_snapshot_inputs_and_preserve_other_fields():
    state = MemoryState()
    state.update_task("task-1", video_subject="Coffee")
    videos = ["first.mp4"]
    state.update_task("task-1", progress=50, videos=videos)
    videos.clear()
    task = state.get_task("task-1")
    assert task["video_subject"] == "Coffee"
    assert task["videos"] == ["first.mp4"]
    assert task["progress"] == 50
