"""Strict, immutable contracts for health-trend data."""

from __future__ import annotations

import math
import re
import unicodedata
import warnings
from datetime import datetime
from typing import ClassVar, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

_BATCH_ID = re.compile(r"HTI-\d{8}-\d{2}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

# The externally versioned JSON field is necessarily named ``schema``. Pydantic
# retains a deprecated BaseModel method with that name, so silence only this
# unavoidable class-construction warning.
warnings.filterwarnings(
    "ignore",
    message=r'Field name "schema" in ".+" shadows an attribute in parent "StrictModel"',
    category=UserWarning,
)


class StrictModel(BaseModel):
    """Base for public contracts: no coercion, mutation, or unknown fields."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    _text_fields: ClassVar[tuple[str, ...]] = ()

    @field_validator("*", mode="after")
    @classmethod
    def validate_text_and_datetime(cls, value: object, info: object) -> object:
        field_name = getattr(info, "field_name", "")
        if isinstance(value, str) and field_name in cls._text_fields:
            if not value.strip():
                raise ValueError("text must not be empty")
            if unicodedata.normalize("NFC", value) != value:
                raise ValueError("text must be NFC-normalized")
        if isinstance(value, datetime) and value.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")
        return value


class QuerySpec(StrictModel):
    query_id: str
    platform: Literal["dy", "xhs"]
    keyword: str
    window_start: AwareDatetime
    window_end: AwareDatetime

    _text_fields = ("query_id", "keyword")

    @model_validator(mode="after")
    def validate_window(self) -> QuerySpec:
        if self.window_start > self.window_end:
            raise ValueError("window_start must be no later than window_end")
        return self


class SourceFileBinding(StrictModel):
    relative_path: str
    record_kind: Literal["posts", "comments"]
    platform: Literal["dy", "xhs"]
    sha256: str
    bytes: int = Field(ge=0)
    records: int = Field(ge=0)

    _text_fields = ("relative_path",)

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("must be a lowercase SHA-256 hex digest")
        return value


class BatchManifest(StrictModel):
    schema: Literal["health_trend_batch.v1"]
    batch_id: str
    created_at: AwareDatetime
    snapshot_at: AwareDatetime
    media_crawler_commit: Literal["d6f7c5bb906b6dac40ddf343ef9e26438a3de092"]
    query_manifest_sha256: str
    sources: tuple[SourceFileBinding, ...]
    state: Literal["raw_registered", "curating", "curated_ready", "approved_ready"]

    _text_fields = ("batch_id",)

    @field_validator("batch_id")
    @classmethod
    def validate_batch_id(cls, value: str) -> str:
        if not _BATCH_ID.fullmatch(value):
            raise ValueError("must match HTI-YYYYMMDD-NN")
        return value

    @field_validator("query_manifest_sha256")
    @classmethod
    def validate_query_manifest_sha256(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("must be a lowercase SHA-256 hex digest")
        return value


class CuratedPost(StrictModel):
    schema: Literal["health_trend_post.v1"]
    platform: Literal["dy", "xhs"]
    source_post_key: str
    source_url_restricted: str
    published_at: AwareDatetime
    snapshot_at: AwareDatetime
    age_hours: float = Field(ge=0)
    author_key_hash: str
    follower_band: str | None
    title_redacted: str
    topic_terms: tuple[str, ...]
    view_count: int | None = Field(default=None, ge=0)
    like_count: int | None = Field(default=None, ge=0)
    comment_count: int | None = Field(default=None, ge=0)
    collect_count: int | None = Field(default=None, ge=0)
    share_count: int | None = Field(default=None, ge=0)
    query_ids: tuple[str, ...]
    best_rank_in_query: int = Field(ge=1)
    duplicate_cluster_id: str
    ad_signal: bool
    suspicious_engagement_signal: bool
    medical_risk_signal: bool
    media_reuse_allowed: Literal[False]
    license_status: Literal["unknown"]

    _text_fields = (
        "source_post_key",
        "source_url_restricted",
        "follower_band",
        "title_redacted",
        "duplicate_cluster_id",
    )

    @field_validator("author_key_hash")
    @classmethod
    def validate_author_key_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("must be a lowercase SHA-256 hex digest")
        return value

    @field_validator("age_hours")
    @classmethod
    def validate_age_hours(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("must be finite")
        return value

    @field_validator("topic_terms", "query_ids")
    @classmethod
    def validate_normalized_terms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("must not be empty")
        for value in values:
            if not value.strip() or unicodedata.normalize("NFC", value) != value:
                raise ValueError("items must be non-empty NFC-normalized text")
        return values

    @model_validator(mode="after")
    def validate_curated_derivations(self) -> CuratedPost:
        if self.published_at > self.snapshot_at:
            raise ValueError("published_at must be no later than snapshot_at")
        expected_age = (self.snapshot_at - self.published_at).total_seconds() / 3600
        if not math.isclose(self.age_hours, expected_age, rel_tol=0, abs_tol=1e-9):
            raise ValueError("age_hours must match the snapshot interval")
        if self.query_ids != tuple(sorted(set(self.query_ids))):
            raise ValueError("query_ids must be sorted and unique")
        return self


class CuratedComment(StrictModel):
    schema: Literal["health_trend_comment.v1"]
    comment_key_hash: str
    source_post_key: str
    created_at: AwareDatetime
    text_redacted: str
    like_count: int = Field(ge=0)
    need_cluster: str | None
    objection_cluster: str | None
    question_cluster: str | None
    contains_personal_data: bool
    excluded_reason: str | None

    _text_fields = (
        "source_post_key",
        "text_redacted",
        "need_cluster",
        "objection_cluster",
        "question_cluster",
        "excluded_reason",
    )

    @field_validator("comment_key_hash")
    @classmethod
    def validate_comment_key_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("must be a lowercase SHA-256 hex digest")
        return value


APPROVED_DISCLAIMER = "该包只是选题情报，不是医学事实来源或可直接发布的脚本。"
_MISSING_TEXT_SENTINELS = frozenset(
    {
        "missing",
        "na",
        "nan",
        "none",
        "notapplicable",
        "notavailable",
        "null",
        "tbd",
        "unknown",
        "不详",
        "暂无",
        "无",
        "未知",
        "缺失",
    }
)


class ApprovedCandidate(StrictModel):
    """One human-ranked topic containing only the Approved interchange allowlist."""

    rank: int = Field(ge=1, le=10)
    topic: str
    platform_rank_evidence: dict[Literal["dy", "xhs"], str] = Field(
        min_length=1, max_length=2
    )
    growth_evidence: tuple[str, ...] = Field(min_length=1)
    user_questions: tuple[str, ...] = Field(min_length=1)
    user_needs: tuple[str, ...] = Field(min_length=1)
    misunderstandings: tuple[str, ...] = Field(min_length=1)
    objections: tuple[str, ...] = Field(min_length=1)
    homogeneity_pattern: str
    narrative_gap: str
    original_visual_direction: str
    risk_flags: tuple[str, ...]
    confidence: Literal["low", "medium", "high"]
    missing_data: tuple[str, ...]
    disclaimer: Literal[APPROVED_DISCLAIMER]

    _text_fields = (
        "topic",
        "homogeneity_pattern",
        "narrative_gap",
        "original_visual_direction",
    )

    @field_validator(
        "growth_evidence",
        "user_questions",
        "user_needs",
        "misunderstandings",
        "objections",
        "risk_flags",
        "missing_data",
    )
    @classmethod
    def validate_text_items(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if not value.strip() or unicodedata.normalize("NFC", value) != value:
                raise ValueError("items must be non-empty NFC-normalized text")
            normalized = unicodedata.normalize("NFKC", value).strip().casefold()
            sentinel = "".join(character for character in normalized if character.isalnum())
            if sentinel in _MISSING_TEXT_SENTINELS:
                raise ValueError("missing sentinel is not evidence")
        return values

    @field_validator("platform_rank_evidence")
    @classmethod
    def validate_platform_evidence(
        cls, value: dict[Literal["dy", "xhs"], str]
    ) -> dict[Literal["dy", "xhs"], str]:
        if any(
            not item.strip() or unicodedata.normalize("NFC", item) != item
            for item in value.values()
        ):
            raise ValueError("platform evidence must be non-empty NFC-normalized text")
        return value


class ApprovedSelection(StrictModel):
    """Canonical, human-authored approval bound to exactly one Curated manifest."""

    schema: Literal["health_trend_selection.v1"]
    batch_id: str
    curated_manifest_sha256: str
    human_selection_status: Literal["approved"]
    approved_at: AwareDatetime
    candidates: tuple[ApprovedCandidate, ...] = Field(min_length=10, max_length=10)

    _text_fields = ("batch_id",)

    @field_validator("batch_id")
    @classmethod
    def validate_batch_id(cls, value: str) -> str:
        if not _BATCH_ID.fullmatch(value):
            raise ValueError("must match HTI-YYYYMMDD-NN")
        return value

    @field_validator("curated_manifest_sha256")
    @classmethod
    def validate_curated_manifest_sha256(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("must be a lowercase SHA-256 hex digest")
        return value

    @model_validator(mode="after")
    def validate_candidate_set(self) -> ApprovedSelection:
        if {candidate.rank for candidate in self.candidates} != set(range(1, 11)):
            raise ValueError("candidate ranks must be the complete unique set 1..10")
        topics = {
            unicodedata.normalize("NFKC", " ".join(candidate.topic.split())).casefold()
            for candidate in self.candidates
        }
        if "" in topics or len(topics) != 10:
            raise ValueError("candidate topics must be unique after normalization")
        covered_platforms = {
            platform for candidate in self.candidates for platform in candidate.platform_rank_evidence
        }
        if covered_platforms != {"dy", "xhs"}:
            raise ValueError("selection must contain rank evidence for both supported platforms")
        return self
