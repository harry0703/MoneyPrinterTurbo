"""Strict offline mapping for synthetic or registered MediaCrawler JSONL snapshots.

This module does not import, launch, authenticate to, or collect with MediaCrawler.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Literal

from health_trend_intelligence.models import CuratedComment
from health_trend_intelligence.privacy import PrivacyHasher, assert_no_sensitive_data, redact_text

Platform = Literal["dy", "xhs"]
CHINA_TZ = timezone(timedelta(hours=8))

# Query IDs are configuration, not values inferred from post text. Any new query
# requires a reviewed new table version.
REGISTERED_QUERY_KEYWORDS_V1: Mapping[str, tuple[Platform, str, str]] = MappingProxyType(
    {
        "dy-sleep-v1": ("dy", "睡眠", "睡眠"),
        "xhs-sleep-v1": ("xhs", "睡眠", "睡眠"),
        "dy-weight-v1": ("dy", "减脂", "减脂"),
        "xhs-weight-v1": ("xhs", "减脂", "减脂"),
        "dy-glucose-v1": ("dy", "控糖", "控糖"),
        "xhs-glucose-v1": ("xhs", "控糖", "控糖"),
    }
)
CANONICAL_PLATFORM_TAGS_V1: Mapping[str, str] = MappingProxyType(
    {
        "健康科普": "健康科普",
        "睡眠": "睡眠",
        "减脂": "减脂",
        "控糖": "控糖",
    }
)
AD_SIGNAL_PHRASES_V1 = ("立即下单", "点击购买", "领取优惠券", "合作推广")
MEDICAL_RISK_PHRASES_V1 = ("保证根治", "包治百病", "替代处方", "立即停药", "无需就医")

_SAFE_POST_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_COUNT = re.compile(
    r"(?:(?:0|[1-9]\d*)|(?:[1-9]\d{0,2}(?:,\d{3})+))"
    r"(?:\.\d+)?(?P<unit>万|亿)?\Z"
)
_MAX_COUNT = 10**18


class AdapterQuarantineError(ValueError):
    """A privacy-safe reason for routing one adapter record to quarantine."""

    __slots__ = ("field_path", "reason_code")

    def __init__(self, reason_code: str, field_path: str) -> None:
        self.reason_code = reason_code
        self.field_path = field_path
        super().__init__(f"adapter quarantine: {reason_code} at {field_path}")


@dataclass(frozen=True, slots=True)
class MediaCrawlerContext:
    platform: Literal["dy", "xhs"]
    query_id: str
    rank_in_query: int
    snapshot_at: datetime

    def __post_init__(self) -> None:
        if self.platform not in ("dy", "xhs"):
            raise ValueError("platform must be dy or xhs")
        if (
            not isinstance(self.query_id, str)
            or not self.query_id.strip()
            or unicodedata.normalize("NFC", self.query_id) != self.query_id
        ):
            raise ValueError("query_id must be non-empty NFC text")
        if isinstance(self.rank_in_query, bool) or not isinstance(self.rank_in_query, int):
            raise TypeError("rank_in_query must be an integer")
        if self.rank_in_query < 1:
            raise ValueError("rank_in_query must be at least 1")
        if not isinstance(self.snapshot_at, datetime) or self.snapshot_at.utcoffset() is None:
            raise ValueError("snapshot_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CuratedPostDraft:
    platform: Literal["dy", "xhs"]
    source_post_key: str
    source_url_restricted: str
    published_at: datetime
    snapshot_at: datetime
    author_key_hash: str
    follower_band: str | None
    title_redacted: str
    topic_terms: tuple[str, ...]
    view_count: int | None
    like_count: int | None
    comment_count: int | None
    collect_count: int | None
    share_count: int | None
    query_id: str
    rank_in_query: int
    ad_signal: bool
    suspicious_engagement_signal: bool
    medical_risk_signal: bool
    media_reuse_allowed: Literal[False]
    license_status: Literal["unknown"]


def map_post(
    row: Mapping[str, object], context: MediaCrawlerContext, hasher: PrivacyHasher
) -> CuratedPostDraft:
    """Map one already-registered post row without propagating raw identity or media."""

    _validate_inputs(row, context, hasher)
    registration = _query_registration(context)
    keyword = _required_text(row, "source_keyword")
    if keyword != registration[1]:
        raise AdapterQuarantineError("query_mismatch", "$.source_keyword")

    if context.platform == "dy":
        post_id = _safe_post_id(_required_text(row, "aweme_id"), "$.aweme_id")
        title = _dy_title(row)
        published_at = _epoch(row, "create_time", divisor=1)
        author_id = _first_identifier(row, ("user_id", "sec_uid", "creator_hash"))
        source_url = f"https://www.douyin.com/video/{post_id}"
    else:
        post_id = _safe_post_id(_required_text(row, "note_id"), "$.note_id")
        title = _xhs_title(row)
        published_at = _epoch(row, "time", divisor=1000)
        author_id = _first_identifier(row, ("creator_hash", "user_id"))
        source_url = f"https://www.xiaohongshu.com/explore/{post_id}"

    if published_at > context.snapshot_at.astimezone(CHINA_TZ):
        raise AdapterQuarantineError("future_published_at", "$.published_at")
    title_result = redact_text(title)
    if not title_result.text_redacted:
        raise AdapterQuarantineError("empty_redacted_text", "$.title")

    draft = CuratedPostDraft(
        platform=context.platform,
        source_post_key=hasher.identifier(post_id, domain="post"),
        source_url_restricted=source_url,
        published_at=published_at,
        snapshot_at=context.snapshot_at,
        author_key_hash=hasher.identifier(author_id, domain="author"),
        follower_band=None,
        title_redacted=title_result.text_redacted,
        topic_terms=_topic_terms(row, context.platform, registration[2]),
        view_count=None,
        like_count=_count(row, "liked_count"),
        comment_count=_count(row, "comment_count"),
        collect_count=_count(row, "collected_count"),
        share_count=_count(row, "share_count"),
        query_id=context.query_id,
        rank_in_query=context.rank_in_query,
        ad_signal=_has_phrase(title_result.text_redacted, AD_SIGNAL_PHRASES_V1),
        suspicious_engagement_signal=False,
        medical_risk_signal=_has_phrase(title_result.text_redacted, MEDICAL_RISK_PHRASES_V1),
        media_reuse_allowed=False,
        license_status="unknown",
    )
    assert_no_sensitive_data(asdict(draft))
    return draft


def map_comment(
    row: Mapping[str, object], context: MediaCrawlerContext, hasher: PrivacyHasher
) -> CuratedComment:
    """Map one comment to the strict Task 2 contract using only hashed identities."""

    _validate_inputs(row, context, hasher)
    _query_registration(context)
    if context.platform == "dy":
        comment_id = _required_text(row, "comment_id")
        post_id = _safe_post_id(_required_text(row, "aweme_id"), "$.aweme_id")
        created_at = _epoch(row, "create_time", divisor=1)
    else:
        comment_id = _required_text(row, "comment_id")
        post_id = _safe_post_id(_required_text(row, "note_id"), "$.note_id")
        created_at = _epoch(row, "create_time", divisor=1000)
    if created_at > context.snapshot_at.astimezone(CHINA_TZ):
        raise AdapterQuarantineError("future_created_at", "$.created_at")

    text = redact_text(_required_text(row, "content"))
    if not text.text_redacted:
        raise AdapterQuarantineError("empty_redacted_text", "$.content")
    comment = CuratedComment(
        schema="health_trend_comment.v1",
        comment_key_hash=hasher.identifier(comment_id, domain="comment"),
        source_post_key=hasher.identifier(post_id, domain="post"),
        created_at=created_at,
        text_redacted=text.text_redacted,
        like_count=_count(row, "like_count"),
        need_cluster=None,
        objection_cluster=None,
        question_cluster=None,
        contains_personal_data=text.contains_personal_data,
        excluded_reason="personal_data_redacted" if text.contains_personal_data else None,
    )
    assert_no_sensitive_data(comment)
    return comment


def _validate_inputs(
    row: Mapping[str, object], context: MediaCrawlerContext, hasher: PrivacyHasher
) -> None:
    if not isinstance(row, Mapping):
        raise AdapterQuarantineError("invalid_record", "$")
    if not isinstance(context, MediaCrawlerContext):
        raise TypeError("context must be MediaCrawlerContext")
    if not isinstance(hasher, PrivacyHasher):
        raise TypeError("hasher must be PrivacyHasher")


def _query_registration(context: MediaCrawlerContext) -> tuple[Platform, str, str]:
    registration = REGISTERED_QUERY_KEYWORDS_V1.get(context.query_id)
    if registration is None or registration[0] != context.platform:
        raise AdapterQuarantineError("query_mismatch", "$.context.query_id")
    return registration


def _required_text(row: Mapping[str, object], field: str) -> str:
    if field not in row or row[field] is None:
        raise AdapterQuarantineError("missing_field", f"$.{field}")
    value = row[field]
    if not isinstance(value, str):
        raise AdapterQuarantineError("invalid_type", f"$.{field}")
    normalized = unicodedata.normalize("NFC", value.strip())
    if not normalized:
        raise AdapterQuarantineError("missing_field", f"$.{field}")
    return normalized


def _optional_text(row: Mapping[str, object], field: str) -> str:
    if field not in row or row[field] is None:
        raise AdapterQuarantineError("missing_field", f"$.{field}")
    value = row[field]
    if not isinstance(value, str):
        raise AdapterQuarantineError("invalid_type", f"$.{field}")
    return unicodedata.normalize("NFC", value.strip())


def _first_identifier(row: Mapping[str, object], candidates: tuple[str, ...]) -> str:
    for field in candidates:
        value = row.get(field)
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            raise AdapterQuarantineError("invalid_type", f"$.{field}")
        normalized = unicodedata.normalize("NFC", value.strip())
        if normalized:
            return normalized
    raise AdapterQuarantineError("missing_field", "$.author_identifier")


def _dy_title(row: Mapping[str, object]) -> str:
    title = _optional_text(row, "title")
    if title:
        return title
    return _required_text(row, "desc")


def _xhs_title(row: Mapping[str, object]) -> str:
    title = _optional_text(row, "title")
    description = _optional_text(row, "desc")
    combined = " ".join(part for part in (title, description) if part)
    if not combined:
        raise AdapterQuarantineError("missing_field", "$.title")
    return combined


def _safe_post_id(value: str, field_path: str) -> str:
    if not _SAFE_POST_ID.fullmatch(value):
        raise AdapterQuarantineError("invalid_post_id", field_path)
    return value


def _epoch(row: Mapping[str, object], field: str, *, divisor: int) -> datetime:
    if field not in row or row[field] is None:
        raise AdapterQuarantineError("missing_field", f"$.{field}")
    value = row[field]
    if isinstance(value, bool):
        raise AdapterQuarantineError("invalid_timestamp", f"$.{field}")
    if isinstance(value, int):
        raw = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        raw = int(value)
    else:
        raise AdapterQuarantineError("invalid_timestamp", f"$.{field}")
    if raw < 0:
        raise AdapterQuarantineError("invalid_timestamp", f"$.{field}")
    try:
        return datetime.fromtimestamp(raw / divisor, tz=UTC).astimezone(CHINA_TZ)
    except (OSError, OverflowError, ValueError) as exc:
        raise AdapterQuarantineError("invalid_timestamp", f"$.{field}") from exc


def _count(row: Mapping[str, object], field: str) -> int:
    if field not in row:
        raise AdapterQuarantineError("missing_field", f"$.{field}")
    value = row[field]
    if isinstance(value, bool) or value is None:
        raise AdapterQuarantineError("invalid_numeric", f"$.{field}")
    if isinstance(value, int):
        result = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise AdapterQuarantineError("invalid_numeric", f"$.{field}")
        result = int(value)
    elif isinstance(value, str):
        compact = value.strip()
        match = _COUNT.fullmatch(compact)
        if match is None:
            raise AdapterQuarantineError("invalid_numeric", f"$.{field}")
        unit = match.group("unit")
        number_text = compact[:-1] if unit is not None else compact
        try:
            number = Decimal(number_text.replace(",", ""))
        except InvalidOperation as exc:
            raise AdapterQuarantineError("invalid_numeric", f"$.{field}") from exc
        multiplier = Decimal(10_000 if unit == "万" else 100_000_000)
        if unit is None:
            multiplier = Decimal(1)
        scaled = number * multiplier
        if scaled != scaled.to_integral_value():
            raise AdapterQuarantineError("invalid_numeric", f"$.{field}")
        result = int(scaled)
    else:
        raise AdapterQuarantineError("invalid_numeric", f"$.{field}")
    if result < 0 or result > _MAX_COUNT:
        raise AdapterQuarantineError("invalid_numeric", f"$.{field}")
    return result


def _topic_terms(row: Mapping[str, object], platform: Platform, query_term: str) -> tuple[str, ...]:
    field = "hashtags" if platform == "dy" else "tag_list"
    raw_tags = row.get(field, [])
    if not isinstance(raw_tags, list):
        raise AdapterQuarantineError("invalid_type", f"$.{field}")
    terms = [query_term]
    for index, item in enumerate(raw_tags):
        if isinstance(item, str):
            raw_name = item
        elif isinstance(item, Mapping) and isinstance(item.get("name"), str):
            raw_name = item["name"]
        else:
            raise AdapterQuarantineError("invalid_type", f"$.{field}[{index}]")
        normalized = unicodedata.normalize("NFKC", raw_name).strip()
        canonical = CANONICAL_PLATFORM_TAGS_V1.get(normalized)
        if canonical is not None and canonical not in terms:
            terms.append(canonical)
    return tuple(terms)


def _has_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return any(phrase.casefold() in normalized for phrase in phrases)
