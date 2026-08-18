"""Deterministic title fingerprinting and post duplicate clustering."""

from __future__ import annotations

import hashlib
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict

from .adapters.mediacrawler import CuratedPostDraft
from .canonical import canonical_json_bytes
from .models import CuratedPost

_UINT64_MAX = (1 << 64) - 1
# Optional CJK coordination particles are excluded as low-information tokens so
# punctuation-only rewrites and the reviewed "A和B" / "A、B" form stay close.
_CJK_CONNECTORS = frozenset("和与及")


def _tokens(text: str) -> tuple[str, ...]:
    if not isinstance(text, str):
        raise TypeError("title must be text")
    normalized = unicodedata.normalize("NFC", text).casefold()
    tokens: list[str] = []
    ascii_token: list[str] = []

    def flush_ascii() -> None:
        if ascii_token:
            tokens.append("".join(ascii_token))
            ascii_token.clear()

    for character in normalized:
        category = unicodedata.category(character)
        if character.isascii() and category[0] in {"L", "N"}:
            ascii_token.append(character)
            continue
        flush_ascii()
        if category[0] in {"L", "N"} and character not in _CJK_CONNECTORS:
            tokens.append(character)
    flush_ascii()
    if not tokens:
        raise ValueError("title must contain CJK or alphanumeric text")
    return tuple(tokens)


def _trigrams(text: str) -> tuple[str, ...]:
    token_stream = "".join(_tokens(text))
    if len(token_stream) < 3:
        return (token_stream,)
    return tuple(token_stream[index : index + 3] for index in range(len(token_stream) - 2))


def simhash64(text: str) -> int:
    """Return a stable unsigned 64-bit SimHash over normalized title trigrams."""

    scores = [0] * 64
    for trigram in _trigrams(text):
        digest = hashlib.sha256(b"hti-simhash-feature-v1\0" + trigram.encode("utf-8")).digest()
        bits = int.from_bytes(digest[:8], "big")
        for bit in range(64):
            scores[bit] += 1 if bits & (1 << bit) else -1
    result = 0
    for bit, score in enumerate(scores):
        if score >= 0:
            result |= 1 << bit
    return result


def hamming_distance(left: int, right: int) -> int:
    """Return bit distance between two unsigned 64-bit fingerprints."""

    for value in (left, right):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("fingerprint must be an integer")
        if not 0 <= value <= _UINT64_MAX:
            raise ValueError("fingerprint must be an unsigned 64-bit integer")
    return (left ^ right).bit_count()


def _source_key(draft: CuratedPostDraft) -> tuple[str, str]:
    if draft.platform not in {"dy", "xhs"}:
        raise ValueError("draft platform is invalid")
    if (
        not draft.source_post_key
        or "\0" in draft.source_post_key
        or unicodedata.normalize("NFC", draft.source_post_key) != draft.source_post_key
    ):
        raise ValueError("draft source key is invalid")
    return draft.platform, draft.source_post_key


def _draft_tiebreaker(draft: CuratedPostDraft) -> bytes:
    value = asdict(draft)
    value["published_at"] = draft.published_at.isoformat()
    value["snapshot_at"] = draft.snapshot_at.isoformat()
    return canonical_json_bytes(value)


def _merge_same_source(drafts: Iterable[CuratedPostDraft]) -> CuratedPost:
    members = tuple(drafts)
    representative = max(members, key=lambda item: (item.snapshot_at, _draft_tiebreaker(item)))
    query_ids = tuple(sorted({item.query_id for item in members}))
    best_rank = min(item.rank_in_query for item in members if item.rank_in_query > 0)
    topic_terms = tuple(sorted({term for item in members for term in item.topic_terms}))
    age_hours = (representative.snapshot_at - representative.published_at).total_seconds() / 3600
    return CuratedPost(
        schema="health_trend_post.v1",
        platform=representative.platform,
        source_post_key=representative.source_post_key,
        source_url_restricted=representative.source_url_restricted,
        published_at=representative.published_at,
        snapshot_at=representative.snapshot_at,
        age_hours=age_hours,
        author_key_hash=representative.author_key_hash,
        follower_band=representative.follower_band,
        title_redacted=representative.title_redacted,
        topic_terms=topic_terms,
        view_count=representative.view_count,
        like_count=representative.like_count,
        comment_count=representative.comment_count,
        collect_count=representative.collect_count,
        share_count=representative.share_count,
        query_ids=query_ids,
        best_rank_in_query=best_rank,
        duplicate_cluster_id="0" * 64,
        ad_signal=any(item.ad_signal for item in members),
        suspicious_engagement_signal=False,
        medical_risk_signal=any(item.medical_risk_signal for item in members),
        media_reuse_allowed=False,
        license_status="unknown",
    )


def _cluster_id(member_keys: tuple[tuple[str, str], ...]) -> str:
    serialized = b"\0".join(
        platform.encode("ascii") + b"\0" + source_key.encode("utf-8")
        for platform, source_key in sorted(member_keys)
    )
    return hashlib.sha256(b"hti-duplicate-v1\0" + serialized).hexdigest()


def cluster_duplicates(drafts: Iterable[CuratedPostDraft]) -> tuple[CuratedPost, ...]:
    """Merge exact source repeats and assign deterministic near-duplicate clusters."""

    grouped: dict[tuple[str, str], list[CuratedPostDraft]] = defaultdict(list)
    for draft in drafts:
        if not isinstance(draft, CuratedPostDraft):
            raise TypeError("drafts must contain CuratedPostDraft values")
        grouped[_source_key(draft)].append(draft)
    merged = {_source_key(items[0]): _merge_same_source(items) for items in grouped.values()}
    keys = tuple(sorted(merged))
    fingerprints = {key: simhash64(merged[key].title_redacted) for key in keys}

    parent = {key: key for key in keys}

    def find(key: tuple[str, str]) -> tuple[str, str]:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left: tuple[str, str], right: tuple[str, str]) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        low, high = sorted((left_root, right_root))
        parent[high] = low

    buckets: dict[tuple[int, int], list[tuple[str, str]]] = defaultdict(list)
    for key in keys:
        fingerprint = fingerprints[key]
        for bucket_index in range(4):
            bucket = (fingerprint >> (bucket_index * 16)) & 0xFFFF
            buckets[(bucket_index, bucket)].append(key)

    candidates: set[tuple[tuple[str, str], tuple[str, str]]] = set()
    for bucket_keys in buckets.values():
        ordered = sorted(bucket_keys)
        for left_index, left in enumerate(ordered):
            for right in ordered[left_index + 1 :]:
                candidates.add((left, right))
    for left, right in sorted(candidates):
        if hamming_distance(fingerprints[left], fingerprints[right]) <= 3:
            union(left, right)

    clusters: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for key in keys:
        clusters[find(key)].append(key)
    cluster_ids = {
        member: _cluster_id(tuple(members)) for members in clusters.values() for member in members
    }
    return tuple(
        merged[key].model_copy(update={"duplicate_cluster_id": cluster_ids[key]}) for key in keys
    )
