"""Resumable, fail-closed conversion from immutable Raw to Curated data."""

from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Literal

from pydantic import ValidationError

from .adapters.mediacrawler import (
    AdapterQuarantineError,
    CuratedPostDraft,
    MediaCrawlerContext,
    map_comment,
    map_post,
)
from .batch import BatchInputError, verify_raw_batch
from .canonical import canonical_json_bytes, load_unique_json
from .dedup import cluster_duplicates
from .models import CuratedComment, CuratedPost, QuerySpec, SourceFileBinding
from .privacy import PrivacyHasher, redact_text
from .storage import (
    DataLayout,
    PathSafetyError,
    assert_safe_directory,
    assert_safe_path_chain,
    assert_safe_regular_file,
)

EventHook = Callable[[str], None]
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REASON_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_CHUNK_FILES = frozenset(
    {"post-drafts.jsonl", "comments.jsonl", "quarantine.jsonl", "chunk-manifest.json"}
)
_FINAL_FILES = frozenset(
    {
        "chunks",
        "checkpoint.json",
        "posts.jsonl",
        "comments.jsonl",
        "quarantine.jsonl",
        "curated-manifest.json",
        "READY.json",
    }
)
_OUTPUT_SCHEMAS = {
    "posts.jsonl": "health_trend_post.v1",
    "comments.jsonl": "health_trend_comment.v1",
    "quarantine.jsonl": "health_trend_quarantine.v1",
}


class CurationError(ValueError):
    """A privacy-safe curation failure with a stable reason code."""

    __slots__ = ("reason_code",)

    def __init__(self, reason_code: str) -> None:
        if _REASON_CODE.fullmatch(reason_code) is None:
            reason_code = "invalid_state"
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class CurationCheckpoint:
    schema: Literal["health_trend_checkpoint.v1"]
    raw_manifest_sha256: str
    completed_source_sha256: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CuratedBatchResult:
    path: Path
    manifest_sha256: str
    raw_records: int
    curated_posts: int
    curated_comments: int
    duplicate_records: int
    quarantined_records: int
    pii_redacted_records: int


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    schema: Literal["health_trend_quarantine.v1"]
    source_sha256: str
    line_number: int
    reason_code: str
    platform: Literal["dy", "xhs"]

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.source_sha256) is None:
            raise ValueError("invalid source digest")
        if isinstance(self.line_number, bool) or not isinstance(self.line_number, int):
            raise TypeError("line number must be an integer")
        if self.line_number < 1:
            raise ValueError("line number must be positive")
        if _REASON_CODE.fullmatch(self.reason_code) is None:
            raise ValueError("invalid reason code")
        if self.platform not in {"dy", "xhs"}:
            raise ValueError("invalid platform")


def _emit(event_hook: EventHook | None, event: str) -> None:
    if event_hook is not None:
        event_hook(event)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_bytes(path: Path) -> bytes:
    try:
        assert_safe_regular_file(path)
        path_before = path.lstat()
        with path.open("rb") as stream:
            opened_before = os.fstat(stream.fileno())
            payload = stream.read()
            opened_after = os.fstat(stream.fileno())
        assert_safe_regular_file(path)
        path_after = path.lstat()
    except (OSError, PathSafetyError) as error:
        raise CurationError("artifact_unavailable") from error
    identities = {
        (
            status.st_dev,
            status.st_ino,
            status.st_size,
            status.st_mtime_ns,
            status.st_ctime_ns,
        )
        for status in (path_before, opened_before, opened_after, path_after)
    }
    if len(identities) != 1 or len(payload) != opened_before.st_size:
        raise CurationError("artifact_changed")
    return payload


def _read_canonical_json(path: Path) -> tuple[dict[str, Any], bytes]:
    payload = _read_bytes(path)
    try:
        value = load_unique_json(payload)
        if not isinstance(value, dict) or canonical_json_bytes(value) != payload:
            raise ValueError
    except (TypeError, ValueError) as error:
        raise CurationError("noncanonical_artifact") from error
    return value, payload


def _exclusive_write(path: Path, payload: bytes) -> None:
    try:
        assert_safe_path_chain(path)
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        assert_safe_regular_file(path)
    except (OSError, PathSafetyError) as error:
        raise CurationError("artifact_write_failed") from error


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f"{path.name}.tmp")
    if os.path.lexists(temporary):
        raise CurationError("unexpected_artifact")
    _exclusive_write(temporary, payload)
    try:
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except OSError as error:
        raise CurationError("checkpoint_write_failed") from error


def _directory_names(path: Path) -> set[str]:
    try:
        assert_safe_directory(path)
        return {entry.name for entry in path.iterdir()}
    except (OSError, PathSafetyError) as error:
        raise CurationError("directory_unavailable") from error


def _load_queries(layout: DataLayout, batch_id: str) -> tuple[QuerySpec, ...]:
    payload = _read_bytes(layout.raw / batch_id / "query-manifest.json")
    try:
        value = load_unique_json(payload)
        if not isinstance(value, list) or canonical_json_bytes(value) != payload:
            raise ValueError
        return tuple(QuerySpec.model_validate_json(canonical_json_bytes(item)) for item in value)
    except (TypeError, ValueError, ValidationError) as error:
        raise CurationError("query_manifest_invalid") from error


def _raw_manifest_payload(layout: DataLayout, batch_id: str) -> bytes:
    return _read_bytes(layout.raw / batch_id / "batch-manifest.json")


def _checkpoint_from_value(value: Mapping[str, Any]) -> CurationCheckpoint:
    if set(value) != {"schema", "raw_manifest_sha256", "completed_source_sha256"}:
        raise CurationError("checkpoint_invalid")
    completed = value["completed_source_sha256"]
    if not isinstance(completed, list) or any(not isinstance(item, str) for item in completed):
        raise CurationError("checkpoint_invalid")
    checkpoint = CurationCheckpoint(
        schema=value["schema"],  # type: ignore[arg-type]
        raw_manifest_sha256=value["raw_manifest_sha256"],  # type: ignore[arg-type]
        completed_source_sha256=tuple(completed),
    )
    if (
        checkpoint.schema != "health_trend_checkpoint.v1"
        or _SHA256.fullmatch(checkpoint.raw_manifest_sha256) is None
        or tuple(sorted(set(completed))) != checkpoint.completed_source_sha256
        or any(_SHA256.fullmatch(item) is None for item in completed)
    ):
        raise CurationError("checkpoint_invalid")
    return checkpoint


def _load_checkpoint(path: Path) -> tuple[CurationCheckpoint, bytes]:
    value, payload = _read_canonical_json(path)
    return _checkpoint_from_value(value), payload


def _checkpoint_bytes(checkpoint: CurationCheckpoint) -> bytes:
    return canonical_json_bytes(asdict(checkpoint))


def _line_values(payload: bytes) -> list[dict[str, Any]]:
    if not payload:
        return []
    if not payload.endswith(b"\n"):
        raise CurationError("jsonl_invalid")
    values: list[dict[str, Any]] = []
    for line in payload.splitlines(keepends=True):
        try:
            value = load_unique_json(line)
            if not isinstance(value, dict) or canonical_json_bytes(value) != line:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise CurationError("jsonl_invalid") from error
        values.append(value)
    return values


def _draft_dict(draft: CuratedPostDraft) -> dict[str, Any]:
    value = asdict(draft)
    value["published_at"] = draft.published_at.isoformat()
    value["snapshot_at"] = draft.snapshot_at.isoformat()
    return value


def _draft_from_value(value: Mapping[str, Any]) -> CuratedPostDraft:
    expected = {field.name for field in fields(CuratedPostDraft)}
    if set(value) != expected:
        raise CurationError("chunk_record_invalid")
    try:
        converted = dict(value)
        converted["published_at"] = datetime.fromisoformat(converted["published_at"])
        converted["snapshot_at"] = datetime.fromisoformat(converted["snapshot_at"])
        draft = CuratedPostDraft(**converted)  # type: ignore[arg-type]
        if draft.platform not in {"dy", "xhs"}:
            raise ValueError
        if draft.published_at.utcoffset() is None or draft.snapshot_at.utcoffset() is None:
            raise ValueError
        return draft
    except (TypeError, ValueError) as error:
        raise CurationError("chunk_record_invalid") from error


def _quarantine_from_value(value: Mapping[str, Any]) -> QuarantineRecord:
    if set(value) != {field.name for field in fields(QuarantineRecord)}:
        raise CurationError("quarantine_invalid")
    try:
        return QuarantineRecord(**value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise CurationError("quarantine_invalid") from error


def _jsonl_bytes(
    values: list[dict[str, Any]], stable_key: Callable[[dict[str, Any]], Any]
) -> bytes:
    return b"".join(canonical_json_bytes(value) for value in sorted(values, key=stable_key))


def _file_binding(payload: bytes, count: int, schema: str) -> dict[str, Any]:
    return {"bytes": len(payload), "records": count, "schema": schema, "sha256": _sha256(payload)}


def _choose_query(
    row: Mapping[str, Any], platform: str, queries: tuple[QuerySpec, ...]
) -> QuerySpec:
    candidates = [query for query in queries if query.platform == platform]
    keyword = row.get("source_keyword")
    if isinstance(keyword, str):
        candidates = [query for query in candidates if query.keyword == keyword]
    if len(candidates) != 1:
        raise AdapterQuarantineError("query_mismatch", "$.source_keyword")
    return candidates[0]


def _post_contains_redaction(row: Mapping[str, Any], platform: str) -> bool:
    if platform == "dy":
        title = row.get("title") or row.get("desc")
    else:
        parts = [row.get("title"), row.get("desc")]
        title = " ".join(part for part in parts if isinstance(part, str) and part.strip())
    return isinstance(title, str) and redact_text(title).contains_personal_data


def _source_path(layout: DataLayout, batch_id: str, binding: SourceFileBinding) -> Path:
    path = layout.raw / batch_id
    for component in binding.relative_path.split("/"):
        path = path / component
    return path


def _process_source(
    layout: DataLayout,
    batch_id: str,
    binding: SourceFileBinding,
    queries: tuple[QuerySpec, ...],
    hasher: PrivacyHasher,
    chunk_dir: Path,
    raw_manifest_sha256: str,
    query_manifest_sha256: str,
) -> None:
    if os.path.lexists(chunk_dir):
        raise CurationError("unexpected_chunk")
    try:
        chunk_dir.mkdir()
        assert_safe_directory(chunk_dir)
    except (OSError, PathSafetyError) as error:
        raise CurationError("chunk_write_failed") from error

    raw_payload = _read_bytes(_source_path(layout, batch_id, binding))
    raw_values = _line_values(raw_payload)
    drafts: list[dict[str, Any]] = []
    comments: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    pii_redacted = 0
    for line_number, row in enumerate(raw_values, start=1):
        try:
            query = _choose_query(row, binding.platform, queries)
            context = MediaCrawlerContext(
                platform=binding.platform,
                query_id=query.query_id,
                rank_in_query=line_number,
                snapshot_at=verify_raw_batch(layout, batch_id).snapshot_at,
            )
            if binding.record_kind == "posts":
                mapped = map_post(row, context, hasher)
                drafts.append(_draft_dict(mapped))
                pii_redacted += int(_post_contains_redaction(row, binding.platform))
            else:
                mapped_comment = map_comment(row, context, hasher)
                comments.append(mapped_comment.model_dump(mode="json"))
                pii_redacted += int(mapped_comment.contains_personal_data)
        except AdapterQuarantineError as error:
            quarantine.append(
                asdict(
                    QuarantineRecord(
                        schema="health_trend_quarantine.v1",
                        source_sha256=binding.sha256,
                        line_number=line_number,
                        reason_code=error.reason_code,
                        platform=binding.platform,
                    )
                )
            )
        except (TypeError, ValueError):
            quarantine.append(
                asdict(
                    QuarantineRecord(
                        schema="health_trend_quarantine.v1",
                        source_sha256=binding.sha256,
                        line_number=line_number,
                        reason_code="adapter_error",
                        platform=binding.platform,
                    )
                )
            )

    draft_payload = _jsonl_bytes(
        drafts,
        lambda value: (
            value["platform"],
            value["source_post_key"],
            value["query_id"],
            value["snapshot_at"],
            canonical_json_bytes(value),
        ),
    )
    comment_payload = _jsonl_bytes(
        comments,
        lambda value: (value["comment_key_hash"], canonical_json_bytes(value)),
    )
    quarantine_payload = _jsonl_bytes(
        quarantine,
        lambda value: (value["line_number"], value["reason_code"]),
    )
    payloads = {
        "post-drafts.jsonl": (draft_payload, len(drafts), "health_trend_post_draft.v1"),
        "comments.jsonl": (comment_payload, len(comments), "health_trend_comment.v1"),
        "quarantine.jsonl": (
            quarantine_payload,
            len(quarantine),
            "health_trend_quarantine.v1",
        ),
    }
    for name, (payload, _, _) in payloads.items():
        _exclusive_write(chunk_dir / name, payload)
    chunk_manifest = {
        "schema": "health_trend_chunk.v1",
        "raw_manifest_sha256": raw_manifest_sha256,
        "query_manifest_sha256": query_manifest_sha256,
        "source": {
            "bytes": binding.bytes,
            "platform": binding.platform,
            "record_kind": binding.record_kind,
            "records": binding.records,
            "relative_path": binding.relative_path,
            "sha256": binding.sha256,
        },
        "files": {
            name: _file_binding(payload, count, schema)
            for name, (payload, count, schema) in sorted(payloads.items())
        },
        "pii_redacted_records": pii_redacted,
    }
    _exclusive_write(chunk_dir / "chunk-manifest.json", canonical_json_bytes(chunk_manifest))


def _verify_bound_file(value: Any, payload: bytes, count: int, schema: str) -> None:
    expected = _file_binding(payload, count, schema)
    if value != expected:
        raise CurationError("file_binding_mismatch")


def _verify_chunk(
    chunk_dir: Path,
    binding: SourceFileBinding,
    raw_manifest_sha256: str,
    query_manifest_sha256: str,
) -> tuple[list[CuratedPostDraft], list[CuratedComment], list[QuarantineRecord], int, str]:
    if _directory_names(chunk_dir) != _CHUNK_FILES:
        raise CurationError("chunk_file_set_mismatch")
    manifest, manifest_payload = _read_canonical_json(chunk_dir / "chunk-manifest.json")
    expected_source = {
        "bytes": binding.bytes,
        "platform": binding.platform,
        "record_kind": binding.record_kind,
        "records": binding.records,
        "relative_path": binding.relative_path,
        "sha256": binding.sha256,
    }
    if (
        set(manifest)
        != {
            "schema",
            "raw_manifest_sha256",
            "query_manifest_sha256",
            "source",
            "files",
            "pii_redacted_records",
        }
        or manifest["schema"] != "health_trend_chunk.v1"
        or manifest["raw_manifest_sha256"] != raw_manifest_sha256
        or manifest["query_manifest_sha256"] != query_manifest_sha256
        or manifest["source"] != expected_source
        or set(manifest["files"]) != _CHUNK_FILES - {"chunk-manifest.json"}
        or isinstance(manifest["pii_redacted_records"], bool)
        or not isinstance(manifest["pii_redacted_records"], int)
        or not 0 <= manifest["pii_redacted_records"] <= binding.records
    ):
        raise CurationError("chunk_manifest_mismatch")

    draft_payload = _read_bytes(chunk_dir / "post-drafts.jsonl")
    comment_payload = _read_bytes(chunk_dir / "comments.jsonl")
    quarantine_payload = _read_bytes(chunk_dir / "quarantine.jsonl")
    drafts = [_draft_from_value(value) for value in _line_values(draft_payload)]
    try:
        comments = [
            CuratedComment.model_validate_json(canonical_json_bytes(value))
            for value in _line_values(comment_payload)
        ]
    except ValidationError as error:
        raise CurationError("chunk_record_invalid") from error
    quarantine = [_quarantine_from_value(value) for value in _line_values(quarantine_payload)]
    _verify_bound_file(
        manifest["files"]["post-drafts.jsonl"],
        draft_payload,
        len(drafts),
        "health_trend_post_draft.v1",
    )
    _verify_bound_file(
        manifest["files"]["comments.jsonl"],
        comment_payload,
        len(comments),
        "health_trend_comment.v1",
    )
    _verify_bound_file(
        manifest["files"]["quarantine.jsonl"],
        quarantine_payload,
        len(quarantine),
        "health_trend_quarantine.v1",
    )
    if len(drafts) + len(comments) + len(quarantine) != binding.records:
        raise CurationError("chunk_count_mismatch")
    if any(item.source_sha256 != binding.sha256 for item in quarantine):
        raise CurationError("quarantine_source_mismatch")
    if binding.record_kind == "posts" and comments:
        raise CurationError("chunk_kind_mismatch")
    if binding.record_kind == "comments" and drafts:
        raise CurationError("chunk_kind_mismatch")
    return (
        drafts,
        comments,
        quarantine,
        manifest["pii_redacted_records"],
        _sha256(manifest_payload),
    )


def _deduplicate_comments(comments: list[CuratedComment]) -> tuple[CuratedComment, ...]:
    grouped: dict[str, list[CuratedComment]] = defaultdict(list)
    for comment in comments:
        grouped[comment.comment_key_hash].append(comment)
    result: list[CuratedComment] = []
    for key in sorted(grouped):
        members = grouped[key]
        if len({item.text_redacted for item in members}) != 1:
            raise CurationError("comment_text_conflict")
        representative = max(
            members,
            key=lambda item: (
                item.created_at,
                canonical_json_bytes(item.model_dump(mode="json")),
            ),
        )
        result.append(representative)
    return tuple(result)


def _recompute_suspicious(
    posts: tuple[CuratedPost, ...],
) -> tuple[tuple[CuratedPost, ...], tuple[str, ...]]:
    by_platform: dict[str, list[CuratedPost]] = defaultdict(list)
    for post in posts:
        by_platform[post.platform].append(post)
    unavailable = False
    suspicious_keys: set[tuple[str, str]] = set()
    for platform_posts in by_platform.values():
        comparable = all(
            all(
                value is not None
                for value in (
                    post.like_count,
                    post.comment_count,
                    post.collect_count,
                    post.share_count,
                )
            )
            for post in platform_posts
        )
        if not comparable or len(platform_posts) < 5:
            unavailable = True
            continue
        totals = [
            post.like_count + post.comment_count + post.collect_count + post.share_count
            for post in platform_posts
            if post.like_count is not None
            and post.comment_count is not None
            and post.collect_count is not None
            and post.share_count is not None
        ]
        baseline = median(totals)
        if baseline <= 0:
            unavailable = True
            continue
        threshold = max(1000, baseline * 20)
        for post, total in zip(platform_posts, totals, strict=True):
            if total >= threshold:
                suspicious_keys.add((post.platform, post.source_post_key))
    updated = tuple(
        post.model_copy(
            update={
                "suspicious_engagement_signal": (
                    post.platform,
                    post.source_post_key,
                )
                in suspicious_keys
            }
        )
        for post in posts
    )
    warnings = ("suspicious_signal_unavailable",) if unavailable else ()
    return updated, warnings


def _collect_chunks(
    chunks_dir: Path,
    bindings: dict[str, SourceFileBinding],
    raw_manifest_sha256: str,
    query_manifest_sha256: str,
) -> tuple[
    list[CuratedPostDraft],
    list[CuratedComment],
    list[QuarantineRecord],
    int,
    dict[str, str],
]:
    if _directory_names(chunks_dir) != set(bindings):
        raise CurationError("chunk_set_mismatch")
    drafts: list[CuratedPostDraft] = []
    comments: list[CuratedComment] = []
    quarantine: list[QuarantineRecord] = []
    pii_redacted = 0
    chunk_hashes: dict[str, str] = {}
    for source_sha in sorted(bindings):
        values = _verify_chunk(
            chunks_dir / source_sha,
            bindings[source_sha],
            raw_manifest_sha256,
            query_manifest_sha256,
        )
        drafts.extend(values[0])
        comments.extend(values[1])
        quarantine.extend(values[2])
        pii_redacted += values[3]
        chunk_hashes[source_sha] = values[4]
    return drafts, comments, quarantine, pii_redacted, chunk_hashes


def _output_payloads(
    posts: tuple[CuratedPost, ...],
    comments: tuple[CuratedComment, ...],
    quarantine: list[QuarantineRecord],
) -> dict[str, tuple[bytes, int, str]]:
    post_values = [post.model_dump(mode="json") for post in posts]
    comment_values = [comment.model_dump(mode="json") for comment in comments]
    quarantine_values = [asdict(item) for item in quarantine]
    return {
        "posts.jsonl": (
            _jsonl_bytes(post_values, lambda value: (value["platform"], value["source_post_key"])),
            len(posts),
            _OUTPUT_SCHEMAS["posts.jsonl"],
        ),
        "comments.jsonl": (
            _jsonl_bytes(comment_values, lambda value: value["comment_key_hash"]),
            len(comments),
            _OUTPUT_SCHEMAS["comments.jsonl"],
        ),
        "quarantine.jsonl": (
            _jsonl_bytes(
                quarantine_values,
                lambda value: (value["source_sha256"], value["line_number"]),
            ),
            len(quarantine),
            _OUTPUT_SCHEMAS["quarantine.jsonl"],
        ),
    }


def _manifest_value(
    *,
    batch_id: str,
    raw_manifest_sha256: str,
    query_manifest_sha256: str,
    raw_records: int,
    payloads: dict[str, tuple[bytes, int, str]],
    duplicate_records: int,
    pii_redacted_records: int,
    warnings: tuple[str, ...],
    checkpoint_payload: bytes,
    chunk_hashes: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema": "health_trend_curated_manifest.v1",
        "batch_id": batch_id,
        "raw_manifest_sha256": raw_manifest_sha256,
        "query_manifest_sha256": query_manifest_sha256,
        "raw_records": raw_records,
        "curated_posts": payloads["posts.jsonl"][1],
        "curated_comments": payloads["comments.jsonl"][1],
        "duplicate_records": duplicate_records,
        "quarantined_records": payloads["quarantine.jsonl"][1],
        "pii_redacted_records": pii_redacted_records,
        "warnings": list(warnings),
        "checkpoint_sha256": _sha256(checkpoint_payload),
        "chunk_manifest_sha256": dict(sorted(chunk_hashes.items())),
        "files": {
            name: _file_binding(payload, count, schema)
            for name, (payload, count, schema) in sorted(payloads.items())
        },
    }


def _finalize(
    work_dir: Path,
    batch_id: str,
    raw_manifest_sha256: str,
    query_manifest_sha256: str,
    raw_records: int,
    bindings: dict[str, SourceFileBinding],
    checkpoint_payload: bytes,
    event_hook: EventHook | None,
) -> None:
    drafts, comment_rows, quarantine, pii_redacted, chunk_hashes = _collect_chunks(
        work_dir / "chunks", bindings, raw_manifest_sha256, query_manifest_sha256
    )
    posts, warnings = _recompute_suspicious(cluster_duplicates(drafts))
    comments = _deduplicate_comments(comment_rows)
    duplicate_records = raw_records - len(quarantine) - len(posts) - len(comments)
    if duplicate_records < 0:
        raise CurationError("count_mismatch")
    payloads = _output_payloads(posts, comments, quarantine)
    manifest = _manifest_value(
        batch_id=batch_id,
        raw_manifest_sha256=raw_manifest_sha256,
        query_manifest_sha256=query_manifest_sha256,
        raw_records=raw_records,
        payloads=payloads,
        duplicate_records=duplicate_records,
        pii_redacted_records=pii_redacted,
        warnings=warnings,
        checkpoint_payload=checkpoint_payload,
        chunk_hashes=chunk_hashes,
    )
    for name, (payload, _, _) in payloads.items():
        _exclusive_write(work_dir / name, payload)
    manifest_payload = canonical_json_bytes(manifest)
    _exclusive_write(work_dir / "curated-manifest.json", manifest_payload)
    ready = {
        "schema": "health_trend_curated_ready.v1",
        "batch_id": batch_id,
        "manifest_sha256": _sha256(manifest_payload),
    }
    _exclusive_write(work_dir / "READY.json", canonical_json_bytes(ready))
    _emit(event_hook, "ready_committed")


def _bindings_by_sha(
    manifest_sources: tuple[SourceFileBinding, ...],
) -> dict[str, SourceFileBinding]:
    bindings = {binding.sha256: binding for binding in manifest_sources}
    if len(bindings) != len(manifest_sources):
        raise CurationError("duplicate_source_sha256")
    return bindings


def curate_batch(
    layout: DataLayout,
    batch_id: str,
    hasher: PrivacyHasher,
    event_hook: EventHook | None = None,
) -> CuratedBatchResult:
    """Build or resume one deterministic Curated batch, publishing READY last."""

    if not isinstance(layout, DataLayout) or not isinstance(hasher, PrivacyHasher):
        raise TypeError("layout and hasher have invalid types")
    _emit(event_hook, "curation_started")
    try:
        raw_manifest = verify_raw_batch(layout, batch_id)
    except (BatchInputError, PathSafetyError, OSError, ValueError) as error:
        raise CurationError("raw_verification_failed") from error
    raw_manifest_sha256 = _sha256(_raw_manifest_payload(layout, batch_id))
    queries = _load_queries(layout, batch_id)
    bindings = _bindings_by_sha(raw_manifest.sources)
    final_dir = layout.curated / batch_id
    work_dir = layout.curated / f"{batch_id}.work"
    if os.path.lexists(final_dir):
        if os.path.lexists(work_dir):
            raise CurationError("destination_conflict")
        return verify_curated_batch(layout, batch_id)

    if not os.path.lexists(work_dir):
        try:
            work_dir.mkdir()
            (work_dir / "chunks").mkdir()
            assert_safe_directory(work_dir)
            assert_safe_directory(work_dir / "chunks")
        except (OSError, PathSafetyError) as error:
            raise CurationError("work_directory_failed") from error
        checkpoint = CurationCheckpoint(
            schema="health_trend_checkpoint.v1",
            raw_manifest_sha256=raw_manifest_sha256,
            completed_source_sha256=(),
        )
        _atomic_write(work_dir / "checkpoint.json", _checkpoint_bytes(checkpoint))

    root_names = _directory_names(work_dir)
    if "READY.json" in root_names:
        if root_names != _FINAL_FILES:
            raise CurationError("final_file_set_mismatch")
        verified_work = _verify_curated_path(layout, batch_id, work_dir)
        _emit(event_hook, "curation_completed")
        if os.path.lexists(final_dir):
            raise CurationError("destination_conflict")
        try:
            work_dir.rename(final_dir)
        except OSError as error:
            raise CurationError("finalize_move_failed") from error
        return replace(verified_work, path=final_dir)
    if root_names != {"chunks", "checkpoint.json"}:
        raise CurationError("unexpected_work_artifact")

    checkpoint, _ = _load_checkpoint(work_dir / "checkpoint.json")
    if checkpoint.raw_manifest_sha256 != raw_manifest_sha256:
        raise CurationError("checkpoint_raw_mismatch")
    if not set(checkpoint.completed_source_sha256) <= set(bindings):
        raise CurationError("checkpoint_unknown_source")
    chunks_dir = work_dir / "chunks"
    if _directory_names(chunks_dir) != set(checkpoint.completed_source_sha256):
        raise CurationError("checkpoint_chunk_mismatch")
    for source_sha in checkpoint.completed_source_sha256:
        _verify_chunk(
            chunks_dir / source_sha,
            bindings[source_sha],
            raw_manifest_sha256,
            raw_manifest.query_manifest_sha256,
        )

    completed = set(checkpoint.completed_source_sha256)
    for source_sha in sorted(set(bindings) - completed):
        _process_source(
            layout,
            batch_id,
            bindings[source_sha],
            queries,
            hasher,
            chunks_dir / source_sha,
            raw_manifest_sha256,
            raw_manifest.query_manifest_sha256,
        )
        completed.add(source_sha)
        checkpoint = CurationCheckpoint(
            schema="health_trend_checkpoint.v1",
            raw_manifest_sha256=raw_manifest_sha256,
            completed_source_sha256=tuple(sorted(completed)),
        )
        _atomic_write(work_dir / "checkpoint.json", _checkpoint_bytes(checkpoint))
        _emit(event_hook, "chunk_committed")

    checkpoint, checkpoint_payload = _load_checkpoint(work_dir / "checkpoint.json")
    if set(checkpoint.completed_source_sha256) != set(bindings):
        raise CurationError("checkpoint_incomplete")
    _emit(event_hook, "finalization_started")
    _finalize(
        work_dir,
        batch_id,
        raw_manifest_sha256,
        raw_manifest.query_manifest_sha256,
        sum(binding.records for binding in raw_manifest.sources),
        bindings,
        checkpoint_payload,
        event_hook,
    )
    verified_work = _verify_curated_path(layout, batch_id, work_dir)
    _emit(event_hook, "curation_completed")
    if os.path.lexists(final_dir):
        raise CurationError("destination_conflict")
    try:
        work_dir.rename(final_dir)
    except OSError as error:
        raise CurationError("finalize_move_failed") from error
    return replace(verified_work, path=final_dir)


def _verify_curated_path(layout: DataLayout, batch_id: str, path: Path) -> CuratedBatchResult:
    try:
        raw_manifest = verify_raw_batch(layout, batch_id)
    except (BatchInputError, PathSafetyError, OSError, ValueError) as error:
        raise CurationError("raw_verification_failed") from error
    raw_manifest_payload = _raw_manifest_payload(layout, batch_id)
    raw_manifest_sha256 = _sha256(raw_manifest_payload)
    bindings = _bindings_by_sha(raw_manifest.sources)
    if _directory_names(path) != _FINAL_FILES:
        raise CurationError("final_file_set_mismatch")

    checkpoint, checkpoint_payload = _load_checkpoint(path / "checkpoint.json")
    if checkpoint.raw_manifest_sha256 != raw_manifest_sha256 or set(
        checkpoint.completed_source_sha256
    ) != set(bindings):
        raise CurationError("checkpoint_mismatch")
    drafts, comment_rows, quarantine_chunks, pii_redacted, chunk_hashes = _collect_chunks(
        path / "chunks",
        bindings,
        raw_manifest_sha256,
        raw_manifest.query_manifest_sha256,
    )
    expected_posts, warnings = _recompute_suspicious(cluster_duplicates(drafts))
    expected_comments = _deduplicate_comments(comment_rows)

    post_payload = _read_bytes(path / "posts.jsonl")
    comment_payload = _read_bytes(path / "comments.jsonl")
    quarantine_payload = _read_bytes(path / "quarantine.jsonl")
    try:
        posts = tuple(
            CuratedPost.model_validate_json(canonical_json_bytes(value))
            for value in _line_values(post_payload)
        )
        comments = tuple(
            CuratedComment.model_validate_json(canonical_json_bytes(value))
            for value in _line_values(comment_payload)
        )
    except ValidationError as error:
        raise CurationError("curated_record_invalid") from error
    quarantine = [_quarantine_from_value(value) for value in _line_values(quarantine_payload)]
    expected_payloads = _output_payloads(expected_posts, expected_comments, quarantine_chunks)
    actual_payloads = {
        "posts.jsonl": (post_payload, len(posts), _OUTPUT_SCHEMAS["posts.jsonl"]),
        "comments.jsonl": (
            comment_payload,
            len(comments),
            _OUTPUT_SCHEMAS["comments.jsonl"],
        ),
        "quarantine.jsonl": (
            quarantine_payload,
            len(quarantine),
            _OUTPUT_SCHEMAS["quarantine.jsonl"],
        ),
    }
    if actual_payloads != expected_payloads:
        raise CurationError("curated_output_mismatch")

    raw_records = sum(binding.records for binding in raw_manifest.sources)
    duplicate_records = raw_records - len(quarantine) - len(posts) - len(comments)
    if duplicate_records < 0:
        raise CurationError("count_mismatch")
    expected_manifest = _manifest_value(
        batch_id=batch_id,
        raw_manifest_sha256=raw_manifest_sha256,
        query_manifest_sha256=raw_manifest.query_manifest_sha256,
        raw_records=raw_records,
        payloads=actual_payloads,
        duplicate_records=duplicate_records,
        pii_redacted_records=pii_redacted,
        warnings=warnings,
        checkpoint_payload=checkpoint_payload,
        chunk_hashes=chunk_hashes,
    )
    manifest, manifest_payload = _read_canonical_json(path / "curated-manifest.json")
    if manifest != expected_manifest:
        raise CurationError("curated_manifest_mismatch")
    manifest_sha256 = _sha256(manifest_payload)
    ready, _ = _read_canonical_json(path / "READY.json")
    if ready != {
        "schema": "health_trend_curated_ready.v1",
        "batch_id": batch_id,
        "manifest_sha256": manifest_sha256,
    }:
        raise CurationError("ready_mismatch")
    return CuratedBatchResult(
        path=path,
        manifest_sha256=manifest_sha256,
        raw_records=raw_records,
        curated_posts=len(posts),
        curated_comments=len(comments),
        duplicate_records=duplicate_records,
        quarantined_records=len(quarantine),
        pii_redacted_records=pii_redacted,
    )


def verify_curated_batch(layout: DataLayout, batch_id: str) -> CuratedBatchResult:
    """Independently re-open and verify all Curated and still-bound Raw bytes."""

    if not isinstance(layout, DataLayout):
        raise TypeError("layout must be DataLayout")
    path = layout.curated / batch_id
    if os.path.lexists(layout.curated / f"{batch_id}.work"):
        raise CurationError("unfinished_work_exists")
    return _verify_curated_path(layout, batch_id, path)
