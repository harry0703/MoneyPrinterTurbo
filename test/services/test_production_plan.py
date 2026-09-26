import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.models.production_plan import (
    CandidateAsset,
    ProductionPlan,
    ReviewFinding,
    ScenePlan,
)
from app.models.schema import TaskStatusData
from app.services import task_artifacts


def _plan() -> ProductionPlan:
    return ProductionPlan(
        task_id="task-123",
        narration_script="Hello world. Next scene.",
        scenes=[
            ScenePlan(
                scene_id="scene-001",
                narration="Hello world. ",
                narration_start=0,
                narration_end=13,
                start_seconds=0.0,
                end_seconds=1.8,
                intent="hook",
                search_queries=["planet earth aerial", "earth from space"],
            ),
            ScenePlan(
                scene_id="scene-002",
                narration="Next scene.",
                narration_start=13,
                narration_end=24,
                start_seconds=1.8,
                end_seconds=3.6,
                intent="explain",
                candidate_assets=[
                    CandidateAsset(
                        provider="pexels",
                        asset_id="123",
                        local_file="video-123.mp4",
                        source_page="https://example.org/video/123",
                        duration_seconds=7.0,
                    )
                ],
                selected_asset_id="123",
                source_trim_start=0.5,
                source_trim_end=3.2,
                clip_speed=1.2,
                review_status="passed",
            ),
        ],
        review_findings=[
            ReviewFinding(
                code="crop_risk",
                severity="warning",
                scene_id="scene-002",
                timestamp_seconds=2.0,
                reason="Subject may be cropped in portrait mode.",
            )
        ],
    )


def test_plan_round_trips_with_stable_ids(tmp_path: Path):
    plan = _plan()
    with patch.object(task_artifacts.utils, "task_dir", return_value=str(tmp_path)):
        task_artifacts.write_production_plan("task-123", plan)
        loaded = task_artifacts.read_production_plan("task-123")

    assert loaded == plan
    assert [scene.scene_id for scene in loaded.scenes] == ["scene-001", "scene-002"]
    assert (
        json.loads((tmp_path / "production-plan-v1.json").read_text(encoding="utf-8"))[
            "version"
        ]
        == 1
    )
    assert list(tmp_path.glob(".production-plan-v1.json.*.tmp")) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"narration_start": 1},
        {"narration_end": 12},
        {"narration": "Changed words. "},
        {"scene_id": "scene-002"},
    ],
)
def test_plan_rejects_gaps_overlap_changed_script_and_duplicate_ids(changes):
    payload = _plan().model_dump()
    payload["scenes"][0].update(changes)
    with pytest.raises(ValidationError):
        ProductionPlan.model_validate(payload)


@pytest.mark.parametrize("speed", [0.84, 1.36])
def test_scene_rejects_out_of_bounds_clip_speed(speed):
    payload = _plan().model_dump()
    payload["scenes"][0]["clip_speed"] = speed
    with pytest.raises(ValidationError):
        ProductionPlan.model_validate(payload)


def test_plan_rejects_invalid_timing_and_selected_asset():
    payload = _plan().model_dump()
    payload["scenes"][1]["start_seconds"] = 1.0
    payload["scenes"][1]["selected_asset_id"] = "missing"
    with pytest.raises(ValidationError):
        ProductionPlan.model_validate(payload)


def test_read_rejects_unsupported_version_and_corruption(tmp_path: Path):
    with patch.object(task_artifacts.utils, "task_dir", return_value=str(tmp_path)):
        target = tmp_path / "production-plan-v1.json"
        target.write_text('{"version": 2}', encoding="utf-8")
        with pytest.raises(
            task_artifacts.ProductionPlanArtifactError, match="production_plan"
        ):
            task_artifacts.read_production_plan("task-123")
        target.write_text("{broken", encoding="utf-8")
        with pytest.raises(
            task_artifacts.ProductionPlanArtifactError, match="production_plan"
        ):
            task_artifacts.read_production_plan("task-123")


def test_write_rejects_task_mismatch_without_clobbering_existing_file(tmp_path: Path):
    with patch.object(task_artifacts.utils, "task_dir", return_value=str(tmp_path)):
        task_artifacts.write_production_plan("task-123", _plan())
        original = (tmp_path / "production-plan-v1.json").read_bytes()
        with pytest.raises(task_artifacts.ProductionPlanArtifactError, match="task_id"):
            task_artifacts.write_production_plan("other-task", _plan())
        assert (tmp_path / "production-plan-v1.json").read_bytes() == original


def test_plan_artifact_is_idempotent_but_cannot_be_replaced(tmp_path: Path):
    with patch.object(task_artifacts.utils, "task_dir", return_value=str(tmp_path)):
        plan = _plan()
        task_artifacts.write_production_plan("task-123", plan)
        original = (tmp_path / "production-plan-v1.json").read_bytes()
        task_artifacts.write_production_plan("task-123", plan)
        changed = plan.model_copy(deep=True)
        changed.scenes[0].intent = "different"
        with pytest.raises(
            task_artifacts.ProductionPlanArtifactError, match="already exists"
        ):
            task_artifacts.write_production_plan("task-123", changed)
        assert (tmp_path / "production-plan-v1.json").read_bytes() == original


def test_write_revalidates_mutated_model_before_persisting(tmp_path: Path):
    with patch.object(task_artifacts.utils, "task_dir", return_value=str(tmp_path)):
        plan = _plan()
        plan.scenes[0].narration = "Different words. "
        with pytest.raises(task_artifacts.ProductionPlanArtifactError, match="invalid"):
            task_artifacts.write_production_plan("task-123", plan)
        assert not (tmp_path / "production-plan-v1.json").exists()


def test_legacy_task_status_stays_valid_with_new_plan_version_field():
    old_task = TaskStatusData(task_id="old-task", state=1, progress=100)
    assert old_task.production_plan_version is None
    new_task = TaskStatusData(
        task_id="new-task", state=4, progress=50, production_plan_version=1
    )
    assert new_task.production_plan_version == 1


@pytest.mark.parametrize(
    "asset_changes",
    [
        {"local_file": "../other-task/secret.mp4"},
        {"local_file": "C:\\secret.mp4"},
        {"local_file": "video.mp4:stream"},
        {"local_file": "video\x00.mp4"},
        {"source_page": "https://example.org/video?token=secret"},
        {"source_page": "https://user:password@example.org/video"},
    ],
)
def test_candidate_asset_rejects_unsafe_paths_and_private_urls(asset_changes):
    payload = _plan().model_dump()
    payload["scenes"][1]["candidate_assets"][0].update(asset_changes)
    with pytest.raises(ValidationError):
        ProductionPlan.model_validate(payload)


def test_plan_rejects_review_reference_to_missing_scene():
    payload = _plan().model_dump()
    payload["review_findings"][0]["scene_id"] = "missing"
    with pytest.raises(ValidationError):
        ProductionPlan.model_validate(payload)


def test_plan_rejects_nonfinite_timing_and_cost():
    payload = _plan().model_dump()
    payload["scenes"][0]["end_seconds"] = float("nan")
    with pytest.raises(ValidationError):
        ProductionPlan.model_validate(payload)
