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
    best_rank_in_query: int = Field(ge=0)
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
