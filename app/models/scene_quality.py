"""Persistable technical quality results for scene media and final renders."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MediaQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: Literal["image", "video"]
    result: Literal["accepted", "review", "rejected"]
    duration_seconds: float = Field(ge=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    resolution_score: float = Field(ge=0, le=1)
    aspect_score: float = Field(ge=0, le=1)
    technical_quality: float = Field(ge=0, le=1)
    black_duration_ratio: float = Field(default=0, ge=0, le=1)
    freeze_events: list[dict[str, float]] = Field(default_factory=list, max_length=100)
    audio_video_delta_seconds: float | None = None
    elapsed_ms: int = Field(default=0, ge=0)
    cache_hit: bool = False
    issues: list[str] = Field(default_factory=list, max_length=30)
