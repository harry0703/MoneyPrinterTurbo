"""Versioned contracts for per-scene visual search and selection results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.scene_quality import MediaQualityReport


SCENE_MEDIA_SCHEMA_VERSION = "1.0"


class SceneMediaModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CandidateScores(SceneMediaModel):
    # Retrieval score describes query construction/ranking only. It is not a
    # visual match score and must never be used as a substitute for QA.
    retrieval: float = Field(ge=0, le=1)
    resolution: float = Field(ge=0, le=1)
    duration: float = Field(ge=0, le=1)
    aspect: float = Field(ge=0, le=1)
    semantic_relevance: float | None = Field(default=None, ge=0, le=1)
    visual_correspondence: float | None = Field(default=None, ge=0, le=1)
    technical_quality: float | None = Field(default=None, ge=0, le=1)
    visual_subject_match: float | None = Field(default=None, ge=0, le=1)
    action_match: float | None = Field(default=None, ge=0, le=1)
    context_match: float | None = Field(default=None, ge=0, le=1)
    assessment_confidence: float | None = Field(default=None, ge=0, le=1)
    validated_ranking: float | None = Field(default=None, ge=0, le=1)


class TemporalVisualObservation(SceneMediaModel):
    position: Literal["beginning", "middle", "end"]
    subject_visible: bool
    action_matches: bool
    context_matches: bool | None = None
    description: str = Field(min_length=1, max_length=2000)


class SceneVisualAssessment(SceneMediaModel):
    """Strict Pegasus answer; ambiguous or malformed outputs cannot select media."""

    subject_visible: bool
    action_matches: bool
    context_matches: bool | None = None
    confidence: float = Field(ge=0, le=1)
    description: str = Field(min_length=1, max_length=4000)
    mismatch_reasons: list[str] = Field(default_factory=list, max_length=12)
    observations: list[TemporalVisualObservation] = Field(default_factory=list, max_length=3)
    temporal_consistency: float | None = Field(default=None, ge=0, le=1)
    technical_quality: float | None = Field(default=None, ge=0, le=1)


class SceneMediaCandidate(SceneMediaModel):
    provider: str = Field(min_length=1, max_length=64)
    original_asset_id: str | None = Field(default=None, max_length=256)
    resource_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_page: str | None = Field(default=None, max_length=2048)
    local_path: str | None = Field(default=None, max_length=2048)
    material_type: Literal["stock_video", "generated_video", "generated_image"] = "stock_video"
    search_query: str = Field(min_length=1, max_length=500)
    matched_queries: list[str] = Field(default_factory=list, max_length=16)
    duration_seconds: float = Field(default=0, ge=0)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    scores: CandidateScores
    visual_validation: Literal[
        "not_requested", "unavailable", "passed", "mismatched", "failed"
    ] = "not_requested"
    visual_description: str | None = Field(default=None, max_length=4000)
    visual_assessment_key: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evaluation_result: Literal["accepted", "review", "rejected"] = "review"
    quality_report: MediaQualityReport | None = None
    duplicate_of: str | None = Field(default=None, max_length=256)
    selected: bool = False
    discard_reasons: list[str] = Field(default_factory=list, max_length=16)


class SceneMediaAssignment(SceneMediaModel):
    scene_id: str = Field(min_length=1, max_length=80)
    status: Literal["selected", "pending_review", "no_candidates", "failed"]
    search_queries: list[str] = Field(default_factory=list, max_length=16)
    selected_candidate: SceneMediaCandidate | None = None
    candidates: list[SceneMediaCandidate] = Field(default_factory=list, max_length=100)
    provider_errors: list[str] = Field(default_factory=list, max_length=30)
    warnings: list[str] = Field(default_factory=list, max_length=30)
    elapsed_ms: int = Field(default=0, ge=0)
    attempts: int = Field(default=1, ge=1)
    provider_search_requests: int = Field(default=0, ge=0)
    visual_validation_requests: int = Field(default=0, ge=0)
    visual_cache_hits: int = Field(default=0, ge=0)
    quality_cache_hits: int = Field(default=0, ge=0)
    download_attempts: int = Field(default=0, ge=0)
    search_history: list["SceneMediaAttempt"] = Field(default_factory=list, max_length=20)
    material_type: Literal["stock_video", "generated_video", "generated_image"] | None = None
    provider: str | None = Field(default=None, max_length=64)
    original_asset_id: str | None = Field(default=None, max_length=256)
    local_path: str | None = Field(default=None, max_length=2048)
    selected_search_query: str | None = Field(default=None, max_length=500)
    selected_scores: CandidateScores | None = None

    @model_validator(mode="after")
    def validate_selected_candidate(self):
        selected = [candidate for candidate in self.candidates if candidate.selected]
        if self.status == "selected":
            if self.selected_candidate is None or len(selected) != 1:
                raise ValueError("selected assignments must contain exactly one selected candidate")
            if self.selected_candidate.visual_validation != "passed":
                raise ValueError("selected candidate must pass strict visual validation")
        elif self.selected_candidate is not None or selected:
            raise ValueError("non-selected assignments cannot contain a selected candidate")
        return self


class SceneMediaAttempt(SceneMediaModel):
    attempted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["selected", "pending_review", "no_candidates", "failed"]
    search_queries: list[str] = Field(default_factory=list, max_length=16)
    candidates: list[SceneMediaCandidate] = Field(default_factory=list, max_length=100)
    selected_candidate: SceneMediaCandidate | None = None
    provider_errors: list[str] = Field(default_factory=list, max_length=30)
    warnings: list[str] = Field(default_factory=list, max_length=30)
    elapsed_ms: int = Field(default=0, ge=0)
    provider_search_requests: int = Field(default=0, ge=0)
    visual_validation_requests: int = Field(default=0, ge=0)
    visual_cache_hits: int = Field(default=0, ge=0)
    quality_cache_hits: int = Field(default=0, ge=0)
    download_attempts: int = Field(default=0, ge=0)


class SceneMediaManifest(SceneMediaModel):
    schema_version: Literal["1.0"] = SCENE_MEDIA_SCHEMA_VERSION
    plan_id: str = Field(min_length=8, max_length=80)
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    assignments: list[SceneMediaAssignment] = Field(default_factory=list, max_length=100)
    max_parallel_searches: int = Field(default=4, ge=1, le=16)
    total_provider_search_requests: int = Field(default=0, ge=0)
    total_visual_validation_requests: int = Field(default=0, ge=0)
    total_visual_cache_hits: int = Field(default=0, ge=0)
    total_quality_cache_hits: int = Field(default=0, ge=0)
    total_download_attempts: int = Field(default=0, ge=0)
    total_elapsed_ms: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_unique_scene_assignments(self):
        scene_ids = [assignment.scene_id for assignment in self.assignments]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("scene assignment IDs must be unique")
        return self
