from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from health_trend_intelligence.adapters.mediacrawler import CuratedPostDraft
from health_trend_intelligence.dedup import (
    cluster_duplicates,
    hamming_distance,
    simhash64,
)

CHINA_TZ = timezone(timedelta(hours=8))


def draft(
    *,
    source_post_key: str,
    title: str = "合成睡眠建议",
    query_id: str = "dy-sleep-v1",
    rank: int = 4,
    snapshot_at: datetime | None = None,
    like_count: int = 10,
) -> CuratedPostDraft:
    captured_at = snapshot_at or datetime(2026, 8, 18, 12, tzinfo=CHINA_TZ)
    return CuratedPostDraft(
        platform="dy",
        source_post_key=source_post_key,
        source_url_restricted=f"https://www.douyin.com/video/{source_post_key}",
        published_at=datetime(2026, 8, 17, 12, tzinfo=CHINA_TZ),
        snapshot_at=captured_at,
        author_key_hash="a" * 64,
        follower_band=None,
        title_redacted=title,
        topic_terms=("睡眠",),
        view_count=None,
        like_count=like_count,
        comment_count=3,
        collect_count=2,
        share_count=1,
        query_id=query_id,
        rank_in_query=rank,
        ad_signal=False,
        suspicious_engagement_signal=False,
        medical_risk_signal=False,
        media_reuse_allowed=False,
        license_status="unknown",
    )


def test_near_duplicate_titles_share_deterministic_cluster() -> None:
    a = "午后总犯困，先看昨晚睡眠和午餐节奏"
    b = "午后总犯困 先看昨晚睡眠、午餐节奏"

    assert hamming_distance(simhash64(a), simhash64(b)) <= 3


def test_simhash_normalizes_nfc_case_and_punctuation() -> None:
    assert simhash64("CAFÉ－睡眠") == simhash64("cafe\u0301 睡眠")


def test_same_post_seen_by_two_queries_merges_without_double_counting() -> None:
    first = draft(source_post_key="1" * 64, query_id="dy-sleep-02", rank=7)
    second = replace(first, query_id="dy-sleep-01", rank_in_query=2)

    posts = cluster_duplicates([first, second])

    assert len(posts) == 1
    assert posts[0].query_ids == ("dy-sleep-01", "dy-sleep-02")
    assert posts[0].best_rank_in_query == 2


def test_same_source_key_keeps_latest_snapshot_metrics() -> None:
    old = draft(source_post_key="2" * 64, query_id="dy-sleep-01", like_count=10)
    new = replace(
        old,
        snapshot_at=old.snapshot_at + timedelta(hours=1),
        like_count=99,
        query_id="dy-sleep-02",
    )

    post = cluster_duplicates([new, old])[0]

    assert post.snapshot_at == new.snapshot_at
    assert post.like_count == 99
    assert post.query_ids == ("dy-sleep-01", "dy-sleep-02")


def test_cluster_result_and_ids_ignore_input_order() -> None:
    first = draft(
        source_post_key="3" * 64,
        title="午后总犯困，先看昨晚睡眠和午餐节奏",
    )
    second = draft(
        source_post_key="4" * 64,
        title="午后总犯困 先看昨晚睡眠、午餐节奏",
    )

    forward = cluster_duplicates([first, second])
    reverse = cluster_duplicates([second, first])

    assert forward == reverse
    assert forward[0].duplicate_cluster_id == forward[1].duplicate_cluster_id
    expected = hashlib.sha256(
        b"hti-duplicate-v1\0" + b"dy\0" + b"3" * 64 + b"\0" + b"dy\0" + b"4" * 64
    ).hexdigest()
    assert {item.duplicate_cluster_id for item in forward} == {expected}


def test_unrelated_titles_do_not_share_cluster() -> None:
    first = draft(source_post_key="5" * 64, title="晚上固定时间关灯睡觉")
    second = draft(source_post_key="6" * 64, title="力量训练后如何安排蛋白质")

    posts = cluster_duplicates([first, second])

    assert posts[0].duplicate_cluster_id != posts[1].duplicate_cluster_id


def test_hamming_distance_rejects_values_outside_uint64() -> None:
    for invalid in (-1, 1 << 64, True):
        try:
            hamming_distance(invalid, 0)
        except (TypeError, ValueError):
            pass
        else:
            raise AssertionError("invalid uint64 accepted")
