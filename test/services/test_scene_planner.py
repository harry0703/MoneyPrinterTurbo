from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import scene_planner


def test_scene_plan_preserves_spoken_script_and_stable_scene_ids():
    script = "EUV uses 13.5 nm light. Why does it matter? Next step!"
    plan = scene_planner.build_scene_plan(
        task_id="task-1", script=script, audio_duration=6.0, subtitle_items=[]
    )

    assert plan.narration_script == script
    assert [scene.scene_id for scene in plan.scenes] == [
        "scene-001",
        "scene-002",
        "scene-003",
    ]
    assert "".join(scene.narration for scene in plan.scenes) == script
    assert plan.scenes[0].narration.startswith("EUV uses 13.5 nm light.")
    assert plan.scenes[-1].end_seconds == 6.0
    assert all(scene.review_status == "needs_review" for scene in plan.scenes)
    assert plan.review_findings[0].code == "timing_estimated"


def test_scene_timing_follows_matching_subtitle_cues():
    cues = [
        (1, "00:00:00,300 --> 00:00:01,500", "First sentence."),
        (2, "00:00:02,000 --> 00:00:03,700", "Second sentence."),
    ]
    plan = scene_planner.build_scene_plan(
        task_id="task-2",
        script="First sentence. Second sentence.",
        audio_duration=4.0,
        subtitle_items=cues,
    )

    assert [(scene.start_seconds, scene.end_seconds) for scene in plan.scenes] == [
        (0.0, 2.0),
        (2.0, 4.0),
    ]
    assert all(scene.timing_source == "subtitle" for scene in plan.scenes)
    assert plan.review_findings == []


@pytest.mark.parametrize(
    "cues",
    [
        [(1, "00:00:00,000 --> 00:00:01,000", "Unrelated words")],
        [(1, "broken time", "First sentence. Second sentence.")],
    ],
)
def test_scene_planner_marks_unmatched_or_bad_subtitles_for_review(cues):
    plan = scene_planner.build_scene_plan(
        task_id="task-3",
        script="First sentence. Second sentence.",
        audio_duration=4.0,
        subtitle_items=cues,
    )

    assert len(plan.scenes) == 2
    assert all(scene.timing_source == "estimated" for scene in plan.scenes)
    assert all(scene.review_status == "needs_review" for scene in plan.scenes)
    assert any(finding.code == "timing_estimated" for finding in plan.review_findings)


def test_custom_audio_requires_review_even_when_subtitles_match():
    plan = scene_planner.build_scene_plan(
        task_id="task-4",
        script="Hello world.",
        audio_duration=2.0,
        subtitle_items=[(1, "00:00:00,100 --> 00:00:01,700", "Hello world.")],
        custom_audio=True,
    )

    assert plan.scenes[0].timing_source == "subtitle"
    assert plan.scenes[0].review_status == "needs_review"
    assert any(
        finding.code == "custom_audio_alignment_review"
        for finding in plan.review_findings
    )


def test_pause_tags_are_removed_before_scene_coverage():
    script = "Hello [pause: 1s] world."
    plan = scene_planner.build_scene_plan(
        task_id="task-5", script=script, audio_duration=2.0, subtitle_items=[]
    )
    assert "break" not in plan.narration_script
    assert "".join(scene.narration for scene in plan.scenes) == plan.narration_script


def test_director_mode_writes_plan_before_materials_and_skips_auto_upload(
    tmp_path: Path,
):
    from app.models.schema import VideoParams
    from app.services import task as tm

    params = VideoParams(video_subject="EUV", director_mode=True)
    plan_path = tmp_path / "production-plan-v1.json"
    with (
        patch.object(tm.utils, "check_ffmpeg_ready", return_value=True),
        patch.object(
            tm, "generate_script", return_value="First sentence. Second sentence."
        ),
        patch.object(tm, "generate_terms", return_value=["EUV"]),
        patch.object(tm, "save_script_data"),
        patch.object(tm, "generate_audio", return_value=("audio.mp3", 4.0, object())),
        patch.object(tm, "generate_subtitle", return_value=""),
        patch.object(tm, "get_video_materials", return_value=["clip.mp4"]) as materials,
        patch.object(
            tm,
            "generate_final_videos",
            return_value=(["final.mp4"], ["combined.mp4"], []),
        ),
        patch.object(
            tm.upload_post.upload_post_service, "is_configured", return_value=True
        ),
        patch.dict(tm.config.app, {"upload_post_auto_upload": True}),
        patch.object(tm.upload_post, "cross_post_video") as upload,
        patch.object(tm, "_schedule_cross_post") as schedule,
        patch.object(tm.sm.state, "update_task"),
        patch.object(tm.task_artifacts.utils, "task_dir", return_value=str(tmp_path)),
    ):
        result = tm.start("task-6", params)

    assert plan_path.exists()
    assert result["production_plan_version"] == 1
    assert result["cross_post_state"] is None
    assert {warning["code"] for warning in result["warnings"]} == {
        "director_mode_preview_legacy_render"
    }
    materials.assert_called_once()
    upload.assert_not_called()
    schedule.assert_not_called()


def test_director_mode_does_not_fetch_materials_when_scene_plan_fails():
    from app.models.schema import VideoParams
    from app.services import task as tm

    params = VideoParams(video_subject="EUV", director_mode=True)
    with (
        patch.object(tm.utils, "check_ffmpeg_ready", return_value=True),
        patch.object(tm, "generate_script", return_value="EUV script."),
        patch.object(tm, "generate_terms", return_value=["EUV"]),
        patch.object(tm, "save_script_data"),
        patch.object(tm, "generate_audio", return_value=("audio.mp3", 2.0, object())),
        patch.object(tm, "generate_subtitle", return_value=""),
        patch.object(
            tm.scene_planner, "build_scene_plan", side_effect=ValueError("bad scene")
        ),
        patch.object(tm, "get_video_materials") as materials,
        patch.object(tm.sm.state, "update_task"),
    ):
        result = tm.start("task-bad-scene", params)

    assert result["state"] == tm.const.TASK_STATE_FAILED
    assert result["failed_stage"] == "scene_plan"
    materials.assert_not_called()


def test_director_mode_is_explicit_opt_in():
    from app.models.schema import TaskVideoRequest, VideoParams

    assert VideoParams(video_subject="EUV").director_mode is False
    assert (
        TaskVideoRequest(video_subject="EUV", director_mode=True).director_mode is True
    )


def test_materials_stage_reports_saved_scene_plan_version(tmp_path: Path):
    from app.models.schema import VideoParams
    from app.services import task as tm

    params = VideoParams(video_subject="EUV", director_mode=True)
    with (
        patch.object(tm.utils, "check_ffmpeg_ready", return_value=True),
        patch.object(tm, "generate_script", return_value="First sentence."),
        patch.object(tm, "generate_terms", return_value=["EUV"]),
        patch.object(tm, "save_script_data"),
        patch.object(tm, "generate_audio", return_value=("audio.mp3", 2.0, object())),
        patch.object(tm, "generate_subtitle", return_value=""),
        patch.object(tm, "get_video_materials", return_value=["clip.mp4"]),
        patch.object(tm, "generate_final_videos") as render,
        patch.object(tm.sm.state, "update_task") as update_task,
        patch.object(tm.task_artifacts.utils, "task_dir", return_value=str(tmp_path)),
    ):
        result = tm.start("task-materials", params, stop_at="materials")

    assert result == {"materials": ["clip.mp4"], "production_plan_version": 1}
    assert update_task.call_args.kwargs["production_plan_version"] == 1
    render.assert_not_called()
