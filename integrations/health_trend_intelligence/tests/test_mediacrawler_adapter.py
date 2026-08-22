from __future__ import annotations

import json
from dataclasses import asdict, FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from health_trend_intelligence.adapters.mediacrawler import (
    AdapterQuarantineError,
    CuratedPostDraft,
    MediaCrawlerContext,
    map_comment,
    map_post,
)
from health_trend_intelligence.canonical import canonical_json_bytes
from health_trend_intelligence.privacy import PrivacyHasher, assert_no_sensitive_data

FIXTURES = Path(__file__).parent / "fixtures"
CHINA_TZ = timezone(timedelta(hours=8))
SNAPSHOT_AT = datetime(2026, 8, 18, 12, 0, tzinfo=CHINA_TZ)


def load_row(name: str) -> dict[str, object]:
    lines = (FIXTURES / name).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def serialize_draft(draft: CuratedPostDraft) -> bytes:
    payload = asdict(draft)
    payload["published_at"] = draft.published_at.isoformat()
    payload["snapshot_at"] = draft.snapshot_at.isoformat()
    return canonical_json_bytes(payload)


def context(platform: str) -> MediaCrawlerContext:
    query_id = "dy-sleep-v1" if platform == "dy" else "xhs-sleep-v1"
    return MediaCrawlerContext(
        platform=platform,  # type: ignore[arg-type]
        query_id=query_id,
        rank_in_query=1,
        snapshot_at=SNAPSHOT_AT,
    )


def test_context_and_draft_are_frozen_slotted_dataclasses() -> None:
    ctx = context("dy")
    draft = map_post(load_row("dy_posts.jsonl"), ctx, PrivacyHasher(b"test-key"))

    assert not hasattr(ctx, "__dict__")
    assert not hasattr(draft, "__dict__")
    with pytest.raises(FrozenInstanceError):
        ctx.rank_in_query = 2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        draft.rank_in_query = 2  # type: ignore[misc]
    assert isinstance(draft, CuratedPostDraft)
    assert not hasattr(draft, "model_dump")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"platform": "unknown"},
        {"query_id": ""},
        {"rank_in_query": 0},
        {"snapshot_at": datetime(2026, 8, 18, 12, 0)},
    ],
)
def test_context_rejects_invalid_platform_query_rank_and_naive_time(
    kwargs: dict[str, object]
) -> None:
    values: dict[str, object] = {
        "platform": "dy",
        "query_id": "dy-sleep-v1",
        "rank_in_query": 1,
        "snapshot_at": SNAPSHOT_AT,
    }
    values.update(kwargs)

    with pytest.raises(ValueError):
        MediaCrawlerContext(**values)  # type: ignore[arg-type]


def test_dy_mapping_is_exact_conservative_and_privacy_safe() -> None:
    row = load_row("dy_posts.jsonl")
    hasher = PrivacyHasher(b"test-key")
    draft = map_post(row, context("dy"), hasher)

    assert draft.platform == "dy"
    assert draft.source_post_key == hasher.identifier("dy-synthetic-001", domain="post")
    assert draft.source_url_restricted == "https://www.douyin.com/video/dy-synthetic-001"
    assert draft.published_at == datetime(2024, 1, 1, 8, 0, tzinfo=CHINA_TZ)
    assert draft.snapshot_at == SNAPSHOT_AT
    assert draft.author_key_hash == hasher.identifier("dy-user-synthetic-001", domain="author")
    assert draft.follower_band is None
    assert draft.view_count is None
    assert draft.like_count == 12_000
    assert draft.collect_count == 2_345
    assert draft.comment_count == 35_000
    assert draft.share_count == 7
    assert draft.topic_terms == ("睡眠", "健康科普")
    assert draft.query_id == "dy-sleep-v1"
    assert draft.rank_in_query == 1
    assert draft.ad_signal is True
    assert draft.medical_risk_signal is True
    assert draft.suspicious_engagement_signal is False
    assert draft.media_reuse_allowed is False
    assert draft.license_status == "unknown"
    assert_no_sensitive_data(asdict(draft))


def test_xhs_mapping_never_propagates_tokens_identity_or_media() -> None:
    row = load_row("xhs_posts.jsonl")
    draft = map_post(row, context("xhs"), PrivacyHasher(b"test-key"))
    encoded = serialize_draft(draft).decode("utf-8")

    for forbidden in (
        "xsec_token",
        "nickname",
        "xhs-user-synthetic-001",
        "image_list",
        "video_url",
        "13800138000",
        "synthetic.person",
        "synthetic_xhs_wx",
        "xhs_handle",
    ):
        assert forbidden not in encoded
    assert draft.source_url_restricted == "https://www.xiaohongshu.com/explore/note-synthetic-001"
    assert draft.published_at == datetime(2024, 1, 1, 8, 0, tzinfo=CHINA_TZ)
    assert draft.topic_terms == ("睡眠", "健康科普")
    assert draft.like_count == 9_876
    assert draft.collect_count == 12_500
    assert draft.media_reuse_allowed is False
    assert draft.license_status == "unknown"
    assert_no_sensitive_data(asdict(draft))


def test_mapping_uses_title_fallback_and_versioned_phrase_boundaries() -> None:
    row = load_row("dy_posts.jsonl")
    row.update(
        {
            "title": "这是下单元测试，也是研究根治机制的合成文本",
            "desc": "不应选择这个描述",
        }
    )

    draft = map_post(row, context("dy"), PrivacyHasher(b"test-key"))

    assert draft.title_redacted == "这是下单元测试,也是研究根治机制的合成文本"
    assert draft.ad_signal is False
    assert draft.medical_risk_signal is False


def test_mapping_redacts_unicode_handle_and_spaced_email_without_logging_originals(
    caplog: pytest.LogCaptureFixture,
) -> None:
    post_row = load_row("dy_posts.jsonl")
    post_row["title"] = "合成标题 联系＠张三 邮箱 Person ＠ Example.invalid"
    comment_row = load_row("dy_comments.jsonl")
    comment_row["content"] = "合成评论 联系＠李四 邮箱 Comment ＠ Example.invalid"

    draft = map_post(post_row, context("dy"), PrivacyHasher(b"test-key"))
    comment = map_comment(comment_row, context("dy"), PrivacyHasher(b"test-key"))

    assert "张三" not in draft.title_redacted
    assert "Person" not in draft.title_redacted
    assert "[REDACTED_HANDLE]" in draft.title_redacted
    assert "[REDACTED_EMAIL]" in draft.title_redacted
    assert "李四" not in comment.text_redacted
    assert "Comment" not in comment.text_redacted
    assert comment.contains_personal_data is True
    assert comment.excluded_reason == "personal_data_redacted"
    for original in ("张三", "Person", "李四", "Comment"):
        assert original not in caplog.text


def test_url_redaction_keeps_following_ad_and_medical_phrases_visible_to_signals(
    caplog: pytest.LogCaptureFixture,
) -> None:
    row = load_row("dy_posts.jsonl")
    row["title"] = (
        "前 https://example.invalid/a%2Fb?token=synthetic-url-secret，立即下单，保证根治。"
    )

    draft = map_post(row, context("dy"), PrivacyHasher(b"test-key"))

    assert draft.title_redacted == (
        "前 https://example.invalid/a%2Fb,立即下单,保证根治。"
    )
    assert draft.ad_signal is True
    assert draft.medical_risk_signal is True
    assert "synthetic-url-secret" not in caplog.text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0", 0),
        ("1,234", 1_234),
        ("1.2万", 12_000),
        ("0.125亿", 12_500_000),
        (2500, 2_500),
        (2500.0, 2_500),
    ],
)
def test_numeric_mapping_accepts_only_deterministic_nonnegative_counts(
    raw: object, expected: int
) -> None:
    row = load_row("dy_posts.jsonl")
    row["liked_count"] = raw

    assert map_post(row, context("dy"), PrivacyHasher(b"test-key")).like_count == expected


@pytest.mark.parametrize(
    "raw",
    [
        -1,
        -1.0,
        "-1",
        True,
        False,
        "NaN",
        "Infinity",
        "-Infinity",
        "1.2",
        "1,2",
        "12,34",
        "1,234,56",
        "一万",
        None,
    ],
)
def test_unknown_or_invalid_numeric_values_are_quarantined_not_coerced_to_zero(raw: object) -> None:
    row = load_row("dy_posts.jsonl")
    row["liked_count"] = raw

    with pytest.raises(AdapterQuarantineError, match="invalid_numeric") as caught:
        map_post(row, context("dy"), PrivacyHasher(b"test-key"))

    assert str(raw) not in str(caught.value) or raw in {None, True, False, -1, -1.0}


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"aweme_id": None}, "missing_field"),
        ({"liked_count": None}, "invalid_numeric"),
        ({"source_keyword": "未登记词"}, "query_mismatch"),
        ({"create_time": 4102444800}, "future_published_at"),
    ],
)
def test_missing_unknown_and_future_post_records_enter_explicit_quarantine(
    mutation: dict[str, object], reason: str
) -> None:
    row = load_row("dy_posts.jsonl")
    row.update(mutation)

    with pytest.raises(AdapterQuarantineError, match=reason):
        map_post(row, context("dy"), PrivacyHasher(b"test-key"))


def test_wrong_row_and_wrong_query_context_are_quarantined() -> None:
    with pytest.raises(AdapterQuarantineError, match="invalid_record"):
        map_post([], context("dy"), PrivacyHasher(b"test-key"))  # type: ignore[arg-type]

    row = load_row("dy_posts.jsonl")
    wrong = MediaCrawlerContext(
        platform="dy",
        query_id="xhs-sleep-v1",
        rank_in_query=1,
        snapshot_at=SNAPSHOT_AT,
    )
    with pytest.raises(AdapterQuarantineError, match="query_mismatch"):
        map_post(row, wrong, PrivacyHasher(b"test-key"))


@pytest.mark.parametrize(
    ("platform", "fixture", "raw_comment_id", "raw_post_id", "expected_likes"),
    [
        ("dy", "dy_comments.jsonl", "dy-comment-synthetic-001", "dy-synthetic-001", 1_234),
        (
            "xhs",
            "xhs_comments.jsonl",
            "xhs-comment-synthetic-001",
            "note-synthetic-001",
            25_000,
        ),
    ],
)
def test_comment_mapping_uses_correct_hash_domains_and_exclusion_semantics(
    platform: str,
    fixture: str,
    raw_comment_id: str,
    raw_post_id: str,
    expected_likes: int,
) -> None:
    hasher = PrivacyHasher(b"test-key")
    comment = map_comment(load_row(fixture), context(platform), hasher)
    encoded = canonical_json_bytes(comment.model_dump(mode="json")).decode("utf-8")

    assert comment.comment_key_hash == hasher.identifier(raw_comment_id, domain="comment")
    assert comment.source_post_key == hasher.identifier(raw_post_id, domain="post")
    assert comment.created_at.tzinfo == CHINA_TZ
    assert comment.like_count == expected_likes
    assert comment.need_cluster is None
    assert comment.objection_cluster is None
    assert comment.question_cluster is None
    assert comment.contains_personal_data is True
    assert comment.excluded_reason == "personal_data_redacted"
    for forbidden in (
        raw_comment_id,
        "user-synthetic",
        "合成评论昵称",
        "13800138000",
        "comment.person",
        "comment_handle",
        "synthetic_comment_wx",
        "synthetic_xhs_comment",
    ):
        assert forbidden not in encoded
    assert_no_sensitive_data(comment)


def test_clean_comment_is_retained_without_exclusion_reason() -> None:
    row = load_row("dy_comments.jsonl")
    row["content"] = "这是完全合成且不含个人信息的评论"

    comment = map_comment(row, context("dy"), PrivacyHasher(b"test-key"))

    assert comment.contains_personal_data is False
    assert comment.excluded_reason is None
    assert comment.text_redacted == "这是完全合成且不含个人信息的评论"


def test_adapter_logs_never_expose_fixture_text_identifiers_or_key(caplog: pytest.LogCaptureFixture) -> None:
    key = b"synthetic-secret-key-for-log-test"
    map_post(load_row("dy_posts.jsonl"), context("dy"), PrivacyHasher(key))
    map_comment(load_row("xhs_comments.jsonl"), context("xhs"), PrivacyHasher(key))
    captured = caplog.text

    for forbidden in (
        "13800138000",
        "synthetic_wx_01",
        "dy-user-synthetic-001",
        "xhs-comment-user-synthetic-001",
        key.decode("ascii"),
    ):
        assert forbidden not in captured
