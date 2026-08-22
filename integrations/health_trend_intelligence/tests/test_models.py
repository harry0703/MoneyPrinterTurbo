from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from health_trend_intelligence.models import (
    BatchManifest,
    CuratedComment,
    CuratedPost,
    QuerySpec,
    SourceFileBinding,
)


NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
SHA256 = "a" * 64

VALID_SOURCE = {
    "relative_path": "dy/posts.jsonl",
    "record_kind": "posts",
    "platform": "dy",
    "sha256": SHA256,
    "bytes": 1,
    "records": 1,
}
VALID_MANIFEST = {
    "schema": "health_trend_batch.v1",
    "batch_id": "HTI-20260818-01",
    "created_at": NOW,
    "snapshot_at": NOW,
    "media_crawler_commit": "d6f7c5bb906b6dac40ddf343ef9e26438a3de092",
    "query_manifest_sha256": SHA256,
    "sources": (VALID_SOURCE,),
    "state": "raw_registered",
}
VALID_POST = {
    "schema": "health_trend_post.v1",
    "platform": "dy",
    "source_post_key": "dy:post:1",
    "source_url_restricted": "restricted://dy/post/1",
    "published_at": NOW - timedelta(hours=1),
    "snapshot_at": NOW,
    "age_hours": 1.0,
    "author_key_hash": SHA256,
    "follower_band": None,
    "title_redacted": "健康话题",
    "topic_terms": ("睡眠",),
    "view_count": 1,
    "like_count": 1,
    "comment_count": 0,
    "collect_count": None,
    "share_count": None,
    "query_ids": ("query-1",),
    "best_rank_in_query": 1,
    "duplicate_cluster_id": "cluster-1",
    "ad_signal": False,
    "suspicious_engagement_signal": False,
    "medical_risk_signal": False,
    "media_reuse_allowed": False,
    "license_status": "unknown",
}
VALID_COMMENT = {
    "schema": "health_trend_comment.v1",
    "comment_key_hash": SHA256,
    "source_post_key": "dy:post:1",
    "created_at": NOW,
    "text_redacted": "我也想知道",
    "like_count": 0,
    "need_cluster": None,
    "objection_cluster": None,
    "question_cluster": None,
    "contains_personal_data": False,
    "excluded_reason": None,
}


def test_curated_post_rejects_extra_fields_and_negative_counts() -> None:
    with pytest.raises(ValidationError):
        CuratedPost.model_validate({**VALID_POST, "nickname": "不得保留"})
    with pytest.raises(ValidationError):
        CuratedPost.model_validate({**VALID_POST, "like_count": -1})


def test_manifest_rejects_naive_datetime_and_bad_batch_id() -> None:
    with pytest.raises(ValidationError):
        BatchManifest.model_validate({**VALID_MANIFEST, "batch_id": "batch1"})
    with pytest.raises(ValidationError):
        BatchManifest.model_validate({**VALID_MANIFEST, "snapshot_at": "2026-08-18T12:00:00"})


def test_models_are_frozen_and_reject_coercion() -> None:
    post = CuratedPost.model_validate(VALID_POST)
    with pytest.raises(ValidationError):
        post.like_count = 2
    with pytest.raises(ValidationError):
        SourceFileBinding.model_validate({**VALID_SOURCE, "bytes": "1"})


@pytest.mark.parametrize("field", ["view_count", "like_count", "comment_count", "collect_count", "share_count"])
def test_curated_post_rejects_negative_optional_counts(field: str) -> None:
    with pytest.raises(ValidationError):
        CuratedPost.model_validate({**VALID_POST, field: -1})


def test_curated_comment_rejects_negative_count_and_non_normalized_text() -> None:
    with pytest.raises(ValidationError):
        CuratedComment.model_validate({**VALID_COMMENT, "like_count": -1})
    with pytest.raises(ValidationError):
        CuratedComment.model_validate({**VALID_COMMENT, "text_redacted": "e\u0301"})


def test_hashes_and_nonempty_text_are_validated() -> None:
    with pytest.raises(ValidationError):
        SourceFileBinding.model_validate({**VALID_SOURCE, "sha256": "A" * 64})
    with pytest.raises(ValidationError):
        CuratedPost.model_validate({**VALID_POST, "title_redacted": " "})


def test_query_window_must_be_ordered_and_timezone_aware() -> None:
    valid = {
        "query_id": "query-1",
        "platform": "xhs",
        "keyword": "睡眠",
        "window_start": NOW - timedelta(days=1),
        "window_end": NOW,
    }
    assert QuerySpec.model_validate(valid).window_end == NOW
    with pytest.raises(ValidationError):
        QuerySpec.model_validate({**valid, "window_start": NOW + timedelta(seconds=1)})
    with pytest.raises(ValidationError):
        QuerySpec.model_validate({**valid, "window_end": datetime(2026, 8, 18, 12, 0)})
