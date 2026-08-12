"""Typed contracts shared by the campaign, story, and content-memory engines."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class LifecycleState(StrEnum):
    PLANNED = "planned"
    RESERVED = "reserved"
    GENERATING = "generating"
    GENERATED = "generated"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    REJECTED = "rejected"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class SourceStatus(StrEnum):
    SOURCE_NOT_REQUIRED = "source_not_required"
    SOURCE_RECOMMENDED = "source_recommended"
    SOURCE_REQUIRED = "source_required"
    SOURCE_VERIFIED = "source_verified"
    BLOCKED_PENDING_SOURCE = "blocked_pending_source"


class FeatureFlags(StrictModel):
    campaign_engine: bool = False
    story_engine: bool = False
    content_memory: bool = False
    structured_mpt_payload_adapter: bool = False
    automatic_daily_campaign_planning: bool = False
    memory_duplicate_blocking: bool = False
    memory_duplicate_warnings: bool = False


class PostingCadence(StrictModel):
    frequency: Literal["daily", "weekly"] = "daily"
    local_time: str = "09:00"
    days_of_week: list[int] = Field(default_factory=lambda: list(range(7)))

    @field_validator("local_time")
    @classmethod
    def validate_local_time(cls, value: str) -> str:
        try:
            hour, minute = (int(part) for part in value.split(":"))
        except (ValueError, TypeError) as exc:
            raise ValueError("local_time must be HH:MM") from exc
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("local_time must be HH:MM")
        return f"{hour:02d}:{minute:02d}"

    @field_validator("days_of_week")
    @classmethod
    def validate_days(cls, value: list[int]) -> list[int]:
        if not value or any(day < 0 or day > 6 for day in value):
            raise ValueError("days_of_week must contain values from 0 (Monday) to 6")
        return sorted(set(value))


class AudienceProfile(StrictModel):
    description: str
    problems: list[str]
    interests: list[str]
    motivations: list[str]


class ThemeConfig(StrictModel):
    id: str
    name: str
    weight: float = Field(default=1.0, gt=0)
    audience_goal: str


class ContentPillar(StrictModel):
    id: str
    name: str
    weight: float = Field(default=1.0, gt=0)
    audience_goals: list[str]
    themes: list[ThemeConfig]
    allowed_story_formats: list[str] = Field(default_factory=list)
    preferred_hooks: list[str] = Field(default_factory=list)
    preferred_ctas: list[str] = Field(default_factory=list)
    visual_treatments: list[str] = Field(default_factory=list)


class StoryFormatTemplate(StrictModel):
    id: str
    name: str
    weight: float = Field(default=1.0, ge=0)
    beat_structure: list[str]
    hook_patterns: list[str]
    constraints: list[str] = Field(default_factory=list)


class SeasonalRule(StrictModel):
    id: str
    start_month_day: str
    end_month_day: str
    eligible_seed_ids: list[str]
    weight_multiplier: float = Field(default=2.0, gt=0)


class SeedContent(StrictModel):
    id: str
    topic: str
    pillar_id: str
    theme_id: str
    weight: float = Field(default=1.0, gt=0)
    source_notes: list[str] = Field(default_factory=list)
    required_facts: list[str] = Field(default_factory=list)
    source_status: SourceStatus = SourceStatus.SOURCE_NOT_REQUIRED
    metadata: dict[str, Any] = Field(default_factory=dict)


class SeriesMetadata(StrictModel):
    series_id: str
    series_title: str
    episode_number: int = Field(ge=1)
    previous_episode: str | None = None
    next_episode: str | None = None
    recurring_format_allowance: bool = False
    continuity_requirements: list[str] = Field(default_factory=list)
    permitted_overlap: list[str] = Field(default_factory=list)
    completion_status: Literal["active", "complete", "cancelled"] = "active"


class CampaignConfig(StrictModel):
    schema_version: str
    campaign_id: str
    display_name: str
    description: str
    enabled: bool
    timezone: str
    enabled_platforms: list[str]
    default_content_type: str
    default_aspect_ratio: str
    min_duration_seconds: int = Field(ge=1)
    max_duration_seconds: int = Field(ge=1)
    posting_cadence: PostingCadence
    target_audience: AudienceProfile
    brand_positioning: str
    brand_voice: list[str]
    tone_constraints: list[str]
    content_pillars: list[ContentPillar]
    themes: list[str]
    story_formats: list[StoryFormatTemplate]
    allowed_formats: list[str]
    preferred_formats: list[str] = Field(default_factory=list)
    disallowed_formats: list[str] = Field(default_factory=list)
    hook_styles: list[str]
    calls_to_action: list[str]
    caption_styles: list[str]
    visual_styles: list[str]
    seasonal_rules: list[SeasonalRule] = Field(default_factory=list)
    content_exclusions: list[str]
    duplicate_cooldown_days: int = Field(ge=0)
    cooldowns: dict[str, int]
    safety_constraints: list[str]
    seed_content: list[SeedContent]
    stop_phrases: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> "CampaignConfig":
        if not self.schema_version.startswith("1."):
            raise ValueError("only campaign schema version 1.x is supported")
        if self.min_duration_seconds > self.max_duration_seconds:
            raise ValueError("min_duration_seconds cannot exceed max_duration_seconds")
        pillar_ids = {pillar.id for pillar in self.content_pillars}
        theme_ids = {
            theme.id for pillar in self.content_pillars for theme in pillar.themes
        }
        format_ids = {story_format.id for story_format in self.story_formats}
        if len(pillar_ids) != len(self.content_pillars):
            raise ValueError("content pillar IDs must be unique")
        if len({seed.id for seed in self.seed_content}) != len(self.seed_content):
            raise ValueError("seed IDs must be unique")
        for seed in self.seed_content:
            if seed.pillar_id not in pillar_ids or seed.theme_id not in theme_ids:
                raise ValueError(f"seed {seed.id!r} references an unknown pillar or theme")
        unknown_formats = set(self.allowed_formats) - format_ids
        if unknown_formats:
            raise ValueError(f"allowed formats are not defined: {sorted(unknown_formats)}")
        if set(self.allowed_formats) & set(self.disallowed_formats):
            raise ValueError("a format cannot be both allowed and disallowed")
        return self


class PlannedContentItem(StrictModel):
    planned_item_id: str
    campaign_id: str
    planned_local_date: date
    planned_utc_start: datetime
    planned_utc_end: datetime
    platform: str
    content_type: str
    content_pillar: str
    theme: str
    seed_id: str
    topic: str
    audience_objective: str
    story_format: str
    hook_style: str
    cta_style: str
    visual_style: str
    target_duration_seconds: int
    random_seed: int
    status: LifecycleState = LifecycleState.PLANNED
    created_at: datetime
    updated_at: datetime
    generation_metadata: dict[str, Any] = Field(default_factory=dict)
    series: SeriesMetadata | None = None


class PlanningDecision(StrictModel):
    local_date: date
    platform: str
    selected_seed_id: str | None
    score: float | None
    reasons: list[str]
    rejected: dict[str, list[str]] = Field(default_factory=dict)


class CampaignPlan(StrictModel):
    plan_id: str
    campaign_id: str
    start_date: date
    number_of_days: int
    target_platforms: list[str]
    random_seed: int
    planning_mode: str
    regeneration_policy: str
    created_at: datetime
    items: list[PlannedContentItem]
    decisions: list[PlanningDecision]


class SelectionOutcome(StrictModel):
    outcome: Literal[
        "selected",
        "already_completed_today",
        "already_reserved",
        "nothing_eligible",
        "campaign_disabled",
        "blocked_by_cooldown",
        "invalid_campaign",
        "invalid_plan",
        "selection_conflict",
    ]
    campaign_id: str
    local_date: date
    planned_item: PlannedContentItem | None = None
    reservation_id: str | None = None
    idempotent_replay: bool = False
    reasons: list[str] = Field(default_factory=list)
    memory_decisions: list["MemoryDecision"] = Field(default_factory=list)


class SimilarityEvidence(StrictModel):
    method: str
    score: float
    threshold: float
    compared_artifact: str


class MemoryDecision(StrictModel):
    decision: Literal[
        "allowed",
        "allowed_with_warning",
        "blocked",
        "exact_duplicate",
        "recent_topic",
        "recent_hook",
        "recent_script",
        "recent_media",
        "intentional_series_match",
        "insufficient_history",
        "comparison_error",
    ]
    reason: str
    matching_record_ids: list[str] = Field(default_factory=list)
    similarity: SimilarityEvidence | None = None
    cooldown_rule: str | None = None
    days_since_previous_use: int | None = None
    recommended_next_action: str
    blocking: bool = False


class MemoryRecord(StrictModel):
    memory_record_id: str
    campaign_id: str
    planned_item_id: str | None = None
    story_id: str | None = None
    story_version_id: str | None = None
    generation_run_id: str | None = None
    generation_task_id: str | None = None
    generation_artifact_sha256: str | None = None
    generation_completed_at: datetime | None = None
    generation_failed_at: datetime | None = None
    publication_run_id: str | None = None
    content_pillar: str | None = None
    theme: str | None = None
    original_seed: str | None = None
    normalized_topic: str | None = None
    fingerprints: dict[str, str] = Field(default_factory=dict)
    hook_text: str | None = None
    visual_prompt_fingerprints: list[str] = Field(default_factory=list)
    stock_search_term_fingerprints: list[str] = Field(default_factory=list)
    media_hashes: list[str] = Field(default_factory=list)
    platform: str | None = None
    planned_date: date | None = None
    generated_at: datetime | None = None
    approved_at: datetime | None = None
    published_at: datetime | None = None
    external_publication_id: str | None = None
    external_url: str | None = None
    status: LifecycleState
    rejection_reason: str | None = None
    failure_reason: str | None = None
    parent_version_id: str | None = None
    superseded: bool = False
    series: SeriesMetadata | None = None
    performance_metrics: dict[str, float | int | None] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)


class ValidationIssue(StrictModel):
    code: str
    severity: Literal["error", "warning"]
    stage: str
    message: str
    suggested_action: str


class StageMetadata(StrictModel):
    stage_id: str
    version: int = 1
    parent_stage_id: str | None = None
    provider: str
    random_seed: int
    created_at: datetime


class StoryBrief(StrictModel):
    story_id: str
    planned_item_id: str
    campaign_id: str
    content_pillar: str
    theme: str
    topic: str
    target_audience: str
    audience_objective: str
    core_message: str
    desired_emotional_response: str
    story_format: str
    tone: list[str]
    target_duration_seconds: int
    target_word_count: int
    platform: str
    cta_objective: str
    visual_style: str
    required_facts: list[str]
    source_notes: list[str]
    prohibited_claims: list[str]
    content_warnings: list[str]
    continuity_references: list[str]
    random_seed: int
    source_status: SourceStatus
    metadata: StageMetadata


class StoryConcept(StrictModel):
    concept_id: str
    working_title: str
    premise: str
    hook_idea: str
    emotional_arc: str
    story_format: str
    core_takeaway: str
    cta_direction: str
    estimated_duration_seconds: int
    novelty_notes: list[str]
    content_memory_warnings: list[str]
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    selection_score: float = 0
    selection_reasoning: list[str] = Field(default_factory=list)
    metadata: StageMetadata


class Hook(StrictModel):
    text: str
    hook_type: str
    intended_audience_response: str
    estimated_spoken_duration_seconds: float
    novelty_fingerprint: str
    risk_flags: list[str]
    alternatives: list[str]
    selection_reasoning: list[str]
    metadata: StageMetadata


class StoryBeat(StrictModel):
    beat_number: int
    beat_type: str
    purpose: str
    key_information: str
    emotional_function: str
    approximate_duration_seconds: float
    approximate_word_count: int
    visual_objective: str
    transition_guidance: str
    required_facts: list[str]
    supporting_details: list[str]
    metadata: StageMetadata


class NarrationSegment(StrictModel):
    segment_number: int
    beat_number: int
    text: str
    estimated_duration_seconds: float


class StructuredScript(StrictModel):
    title: str
    hook: str
    full_narration: str
    narration_segments: list[NarrationSegment]
    word_count: int
    estimated_spoken_duration_seconds: float
    estimate_method: str
    tone: list[str]
    reading_level: str | None = None
    pronunciation_notes: list[str]
    fact_references: list[str]
    cta: str
    closing_line: str
    script_fingerprint: str
    generation_metadata: StageMetadata
    validation_warnings: list[str]


class Scene(StrictModel):
    scene_number: int
    narration_segment: str
    start_time_seconds: float
    end_time_seconds: float
    intended_duration_seconds: float
    visual_objective: str
    subject: str
    setting: str
    action: str
    shot_type: str
    motion: str
    transition: str
    stock_search_terms: list[str]
    visual_prompt: dict[str, Any] | None = None
    continuity_requirements: list[str]
    safety_notes: list[str]
    scene_fingerprint: str
    metadata: StageMetadata


class CaptionPackage(StrictModel):
    primary_caption: str
    short_caption: str
    first_comment: str
    pinned_comment_suggestion: str
    community_question: str
    cta: str
    hashtag_suggestions: list[str]
    accessibility_description: str
    platform_variants: dict[str, str]
    caption_fingerprint: str
    metadata: StageMetadata


class StoryPackage(StrictModel):
    story_version_id: str
    parent_story_version_id: str | None = None
    brief: StoryBrief
    concept_candidates: list[StoryConcept]
    selected_concept_id: str
    hook: Hook
    beats: list[StoryBeat]
    script: StructuredScript
    scenes: list[Scene]
    caption: CaptionPackage
    validation_issues: list[ValidationIssue]
    created_at: datetime


class LegacyMptPayload(StrictModel):
    payload: dict[str, Any]
    field_sources: dict[str, str]
    warnings: list[str]


class PreparedCampaignContent(StrictModel):
    selection: SelectionOutcome
    memory_decision: MemoryDecision
    memory_decisions: list[MemoryDecision] = Field(default_factory=list)
    story_package: StoryPackage | None = None
    mpt_payload: LegacyMptPayload | None = None
    memory_record_id: str | None = None


class BridgeCampaignPreparation(StrictModel):
    """Versioned, provider-neutral contract consumed by the bridge."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract: Literal["mpt-campaign-v1"] = "mpt-campaign-v1"
    selection_outcome: str
    idempotent_replay: bool = False
    idempotency_key: str
    campaign_id: str
    planned_item_id: str
    story_id: str
    story_version_id: str
    memory_record_id: str
    generation_run_id: str
    mpt_payload: dict[str, Any]
    caption: CaptionPackage
