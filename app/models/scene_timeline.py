"""Validated, scene-linked render timeline contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SCENE_TIMELINE_SCHEMA_VERSION = "1.0"


class TimelineModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TimelineItem(TimelineModel):
    scene_id: str = Field(min_length=1, max_length=80)
    asset_path: str = Field(min_length=1, max_length=2048)
    material_type: Literal["stock_video", "generated_video", "generated_image"]
    provider: str = Field(min_length=1, max_length=64)
    original_asset_id: str | None = Field(default=None, max_length=256)
    timeline_start: float = Field(ge=0)
    timeline_end: float = Field(gt=0)
    source_start: float = Field(default=0, ge=0)
    source_end: float = Field(gt=0)
    entry_transition: Literal["cut", "fade"] = "cut"
    exit_transition: Literal["cut", "fade"] = "cut"
    fit_mode: Literal["cover", "contain"] = "cover"
    image_motion: Literal["static", "zoom"] = "zoom"
    synchronization: Literal["subtitle_aligned", "tts_aligned", "estimated"]
    narration_text: str = Field(min_length=1, max_length=8000)
    shot_id: str = Field(min_length=1, max_length=80)
    scene_label: str | None = Field(default=None, max_length=160)

    @property
    def duration(self) -> float:
        return self.timeline_end - self.timeline_start

    @property
    def source_duration(self) -> float:
        return self.source_end - self.source_start


class SceneTimeline(TimelineModel):
    schema_version: Literal["1.0"] = SCENE_TIMELINE_SCHEMA_VERSION
    plan_id: str = Field(min_length=8, max_length=80)
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    audio_duration: float = Field(gt=0)
    alignment_source: Literal["subtitles", "tts_cues", "estimated"]
    synchronization: Literal["subtitle_aligned", "tts_aligned", "estimated"]
    fps: int = Field(default=30, ge=1, le=120)
    items: list[TimelineItem] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_timeline(self):
        if abs(self.items[0].timeline_start) > 0.025:
            raise ValueError("timeline must start at zero")
        previous_end = 0.0
        scene_ids = set()
        for item in self.items:
            if item.scene_id in scene_ids:
                raise ValueError("timeline must contain exactly one item per scene")
            scene_ids.add(item.scene_id)
            if abs(item.timeline_start - previous_end) > 0.025:
                raise ValueError("timeline items must be contiguous without gaps or overlaps")
            if item.timeline_end <= item.timeline_start:
                raise ValueError("timeline item duration must be positive")
            if item.source_end <= item.source_start:
                raise ValueError("source interval duration must be positive")
            if item.material_type != "generated_image" and item.source_duration + 0.025 < item.duration:
                raise ValueError("video source is shorter than its assigned timeline interval")
            previous_end = item.timeline_end
        if abs(previous_end - self.audio_duration) > 0.05:
            raise ValueError("timeline must end at the narration audio duration")
        return self
