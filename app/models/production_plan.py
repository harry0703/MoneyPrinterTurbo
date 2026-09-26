"""Versioned, provider-neutral contract for scene-directed video production."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CandidateAsset(_StrictModel):
    provider: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    local_file: str = Field(min_length=1)
    source_page: str | None = None
    duration_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_public_source(self) -> CandidateAsset:
        if any(char in self.local_file for char in "/\\:\x00") or self.local_file in {
            ".",
            "..",
        }:
            raise ValueError("local_file must be a task-local basename")
        if self.source_page is not None:
            parsed = urlsplit(self.source_page)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "source_page must be a public URL without credentials or query"
                )
        return self


class ReviewFinding(_StrictModel):
    code: str = Field(min_length=1)
    severity: Literal["info", "warning", "error"]
    scene_id: str | None = None
    timestamp_seconds: float | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1)


class StageRecord(_StrictModel):
    stage: str = Field(min_length=1)
    status: Literal["pending", "complete", "failed", "needs_review"] = "pending"
    artifact_version: int = Field(default=1, ge=1)
    model_name: str | None = None
    prompt_version: str | None = None
    cost_usd: float | None = Field(default=None, ge=0)


class ScenePlan(_StrictModel):
    scene_id: str = Field(min_length=1)
    narration: str = Field(min_length=1)
    narration_start: int = Field(ge=0)
    narration_end: int = Field(gt=0)
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, gt=0)
    intent: str = Field(min_length=1)
    factual_claims: list[str] = Field(default_factory=list)
    visual_strategy: Literal["stock", "image", "diagram", "generated_video"] = "stock"
    search_queries: list[str] = Field(default_factory=list)
    candidate_assets: list[CandidateAsset] = Field(default_factory=list)
    selected_asset_id: str | None = None
    source_trim_start: float | None = Field(default=None, ge=0)
    source_trim_end: float | None = Field(default=None, gt=0)
    clip_speed: float = Field(default=1.0, ge=0.85, le=1.35)
    subtitle_text: str | None = None
    review_status: Literal["pending", "passed", "needs_review", "failed"] = "pending"

    @model_validator(mode="after")
    def validate_scene(self) -> ScenePlan:
        if self.narration_end <= self.narration_start:
            raise ValueError("narration_end must follow narration_start")
        if (self.start_seconds is None) != (self.end_seconds is None):
            raise ValueError(
                "scene timing must include both start_seconds and end_seconds"
            )
        if self.start_seconds is not None and self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must follow start_seconds")
        if (self.source_trim_start is None) != (self.source_trim_end is None):
            raise ValueError("source trim must include both start and end")
        if (
            self.source_trim_start is not None
            and self.source_trim_end <= self.source_trim_start
        ):
            raise ValueError("source trim end must follow start")
        asset_ids = [asset.asset_id for asset in self.candidate_assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("candidate asset IDs must be unique within a scene")
        if (
            self.selected_asset_id is not None
            and self.selected_asset_id not in asset_ids
        ):
            raise ValueError("selected_asset_id must reference a candidate asset")
        if any(not query.strip() for query in self.search_queries):
            raise ValueError("search queries cannot be blank")
        return self


class ProductionPlan(_StrictModel):
    version: Literal[1] = 1
    task_id: str = Field(min_length=1)
    narration_script: str = Field(min_length=1)
    scenes: list[ScenePlan] = Field(min_length=1)
    stages: list[StageRecord] = Field(default_factory=list)
    review_findings: list[ReviewFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scene_coverage(self) -> ProductionPlan:
        cursor = 0
        seen_ids: set[str] = set()
        previous_end_seconds: float | None = None
        for scene in self.scenes:
            if scene.scene_id in seen_ids:
                raise ValueError("scene IDs must be unique")
            seen_ids.add(scene.scene_id)
            if scene.narration_start != cursor:
                raise ValueError("scenes must cover narration without gaps or overlap")
            if (
                self.narration_script[scene.narration_start : scene.narration_end]
                != scene.narration
            ):
                raise ValueError(
                    "scene narration must match the spoken script verbatim"
                )
            if (
                previous_end_seconds is not None
                and scene.start_seconds is not None
                and scene.start_seconds < previous_end_seconds - 1e-6
            ):
                raise ValueError("scene timings cannot overlap")
            cursor = scene.narration_end
            previous_end_seconds = scene.end_seconds
        if cursor != len(self.narration_script):
            raise ValueError("scenes must cover the complete narration")
        if any(
            finding.scene_id not in seen_ids
            for finding in self.review_findings
            if finding.scene_id
        ):
            raise ValueError("review finding references an unknown scene")
        return self
