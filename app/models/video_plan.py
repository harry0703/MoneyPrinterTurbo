"""Versioned, validated scene-plan contracts for the opt-in scene pipeline."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCENE_PLAN_SCHEMA_VERSION = "1.0"
_SCENE_ID = re.compile(r"^scene-[0-9]{3,}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SceneTiming(StrictModel):
    estimated_duration_ms: int = Field(ge=0)
    actual_start_ms: int | None = Field(default=None, ge=0)
    actual_end_ms: int | None = Field(default=None, ge=0)
    confidence: float = Field(ge=0, le=1)
    source: Literal["estimated", "tts_aligned", "whisper_aligned", "manual"] = "estimated"

    @model_validator(mode="after")
    def validate_actual_interval(self):
        if (self.actual_start_ms is None) != (self.actual_end_ms is None):
            raise ValueError("actual_start_ms and actual_end_ms must be set together")
        if (
            self.actual_start_ms is not None
            and self.actual_end_ms is not None
            and self.actual_end_ms <= self.actual_start_ms
        ):
            raise ValueError("actual_end_ms must be greater than actual_start_ms")
        if self.source == "estimated" and self.actual_start_ms is not None:
            raise ValueError("estimated timing cannot contain an actual interval")
        return self


class VisualBrief(StrictModel):
    subject: list[str] = Field(min_length=1, max_length=12)
    action: str = Field(min_length=1, max_length=1000)
    context: str = Field(default="", max_length=2000)
    description: str = Field(min_length=1, max_length=4000)
    shot_type: str = Field(default="medium", min_length=1, max_length=64)
    visual_prompt: str = Field(min_length=1, max_length=4000)
    search_queries: list[str] = Field(min_length=1, max_length=8)
    recommended_material_type: list[
        Literal["stock_video", "generated_video", "generated_image", "local"]
    ] = Field(min_length=1)
    avoid: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("subject", "search_queries", "avoid")
    @classmethod
    def reject_empty_items(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("list entries cannot be empty")
        return values


class Shot(StrictModel):
    shot_id: str = Field(min_length=1, max_length=80)
    role: str = Field(default="primary", min_length=1, max_length=64)
    duration_share: float = Field(default=1.0, gt=0, le=1)


class Scene(StrictModel):
    scene_id: str
    order: int = Field(ge=0)
    narration_text: str = Field(min_length=1, max_length=8000)
    timing: SceneTiming
    visual: VisualBrief
    shots: list[Shot] = Field(min_length=1, max_length=8)

    @field_validator("scene_id")
    @classmethod
    def validate_scene_id(cls, value: str) -> str:
        if not _SCENE_ID.fullmatch(value):
            raise ValueError("scene_id must use the form scene-001")
        return value


class VideoPlan(StrictModel):
    schema_version: Literal["1.0"] = SCENE_PLAN_SCHEMA_VERSION
    plan_id: str = Field(default_factory=lambda: f"plan-{uuid4().hex}", min_length=8, max_length=80)
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    subject: str = Field(min_length=1, max_length=1000)
    language: str = Field(default="", max_length=64)
    scenes: list[Scene] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_scene_order_and_ids(self):
        ids = [scene.scene_id for scene in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("scene_id values must be unique")
        if [scene.order for scene in self.scenes] != list(range(len(self.scenes))):
            raise ValueError("scene order must be contiguous and start at zero")
        shot_ids = [shot.shot_id for scene in self.scenes for shot in scene.shots]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError("shot_id values must be unique within the plan")
        return self


def normalize_narration_text(value: str) -> str:
    """Normalize Unicode and whitespace without changing spoken punctuation or words."""
    normalized = unicodedata.normalize("NFC", value or "")
    return " ".join(normalized.split())


def validate_plan_script_coverage(script: str, plan: VideoPlan) -> None:
    """Require the ordered scene narration to reproduce the source script exactly."""
    source = normalize_narration_text(script)
    planned = normalize_narration_text(" ".join(scene.narration_text for scene in plan.scenes))
    if source != planned:
        raise ValueError("scene narration must cover the source script exactly and in order")
