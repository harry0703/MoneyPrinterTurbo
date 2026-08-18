"""Immutable Raw batch registration, verification, and retention reporting."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import ValidationError

from .canonical import canonical_json_bytes, load_unique_json
from .models import BatchManifest, QuerySpec, SourceFileBinding
from .storage import (
    DataLayout,
    PathSafetyError,
    assert_safe_directory,
    assert_safe_path_chain,
    assert_safe_regular_file,
)

MEDIA_CRAWLER_COMMIT = "d6f7c5bb906b6dac40ddf343ef9e26438a3de092"
_BATCH_ID = re.compile(r"HTI-\d{8}-\d{2}\Z")
_FORBIDDEN = re.compile(
    r"cookie|token|secret|phone|mobile|profile|proxy|media|video|image|audio",
    re.IGNORECASE,
)


class BatchInputError(ValueError):
    """Raised for an unsafe, malformed, or unverifiable batch."""


@dataclass(frozen=True, slots=True)
class SourceSpec:
    path: Path
    platform: Literal["dy", "xhs"]
    record_kind: Literal["posts", "comments"]


@dataclass(frozen=True, slots=True)
class RetentionEntry:
    batch_id: str
    snapshot_at: datetime
    age_days: int
    eligible_for_manual_deletion: bool


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    device: int
    inode: int
    size: int
    modified_ns: int
    changed_ns: int


@dataclass(frozen=True, slots=True)
class _PreparedSource:
    spec: SourceSpec
    payload: bytes
    records: int
    identity: _FileIdentity


def _identity(status: os.stat_result) -> _FileIdentity:
    return _FileIdentity(
        device=status.st_dev,
        inode=status.st_ino,
        size=status.st_size,
        modified_ns=status.st_mtime_ns,
        changed_ns=status.st_ctime_ns,
    )


def _require_aware(value: datetime, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise BatchInputError(f"{field} must be timezone-aware")


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            _FORBIDDEN.search(key) is not None or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _validate_jsonl(payload: bytes) -> int:
    if not payload:
        raise BatchInputError("JSONL must contain at least one record")
    lines = payload.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    if not lines or any(not line.strip() for line in lines):
        raise BatchInputError("JSONL cannot contain empty lines")
    for line in lines:
        try:
            value = load_unique_json(line)
        except (TypeError, ValueError) as error:
            raise BatchInputError("source is not strict UTF-8 JSONL") from error
        if not isinstance(value, dict):
            raise BatchInputError("each JSONL record must be an object")
        if _contains_forbidden_key(value):
            raise BatchInputError("source contains a forbidden JSON key")
    return len(lines)


def _coerce_queries(query_manifest: object) -> tuple[QuerySpec, ...]:
    if not isinstance(query_manifest, Sequence) or isinstance(
        query_manifest, (str, bytes, bytearray)
    ):
        raise BatchInputError("query manifest must be a sequence")
    if not 1 <= len(query_manifest) <= 50:
        raise BatchInputError("query manifest must contain 1 to 50 queries")
    queries: list[QuerySpec] = []
    try:
        for value in query_manifest:
            if isinstance(value, QuerySpec):
                queries.append(value)
            elif isinstance(value, Mapping):
                queries.append(QuerySpec.model_validate_json(canonical_json_bytes(value)))
            else:
                raise BatchInputError("query entries must be QuerySpec objects")
    except (TypeError, ValueError, ValidationError) as error:
        raise BatchInputError("query manifest is invalid") from error
    identifiers = [item.query_id for item in queries]
    if len(set(identifiers)) != len(identifiers):
        raise BatchInputError("query IDs must be unique")
    return tuple(queries)


def _query_bytes(queries: tuple[QuerySpec, ...]) -> bytes:
    return canonical_json_bytes([item.model_dump(mode="json") for item in queries])


def _coerce_source(value: object) -> SourceSpec:
    if isinstance(value, SourceSpec):
        spec = value
    elif isinstance(value, Mapping):
        if set(value) != {"path", "platform", "record_kind"}:
            raise BatchInputError("source declarations have an invalid shape")
        path_value = value["path"]
        if not isinstance(path_value, (str, os.PathLike)):
            raise BatchInputError("source path is invalid")
        spec = SourceSpec(
            path=Path(path_value),
            platform=value["platform"],  # type: ignore[arg-type]
            record_kind=value["record_kind"],  # type: ignore[arg-type]
        )
    else:
        raise BatchInputError("source declarations are invalid")
    if spec.platform not in {"dy", "xhs"} or spec.record_kind not in {"posts", "comments"}:
        raise BatchInputError("source platform or record kind is invalid")
    return SourceSpec(path=Path(spec.path), platform=spec.platform, record_kind=spec.record_kind)


def _read_stable_source(path: Path) -> tuple[bytes, _FileIdentity]:
    assert_safe_regular_file(path)
    path_status_before = path.lstat()
    try:
        with path.open("rb") as stream:
            opened_before = os.fstat(stream.fileno())
            payload = stream.read()
            opened_after = os.fstat(stream.fileno())
    except OSError as error:
        raise BatchInputError("source could not be read safely") from error
    assert_safe_regular_file(path)
    path_status_after = path.lstat()
    identities = {
        _identity(path_status_before),
        _identity(opened_before),
        _identity(opened_after),
        _identity(path_status_after),
    }
    if len(identities) != 1 or len(payload) != opened_before.st_size:
        raise BatchInputError("source changed while being read")
    return payload, identities.pop()


def _prepare_source(value: object) -> _PreparedSource:
    spec = _coerce_source(value)
    path = spec.path
    if not path.is_absolute() or ".." in path.parts:
        raise BatchInputError("source paths must be absolute and traversal-free")
    if path.suffix.casefold() != ".jsonl" or _FORBIDDEN.search(path.name):
        raise BatchInputError("source filename is forbidden")
    try:
        payload, identity = _read_stable_source(path)
    except PathSafetyError as error:
        raise BatchInputError("source path is unsafe") from error
    records = _validate_jsonl(payload)
    return _PreparedSource(spec=spec, payload=payload, records=records, identity=identity)


def _read_for_copy(prepared: _PreparedSource) -> bytes:
    try:
        payload, identity = _read_stable_source(prepared.spec.path)
    except PathSafetyError as error:
        raise BatchInputError("source path became unsafe") from error
    if identity != prepared.identity or payload != prepared.payload:
        raise BatchInputError("source changed between validation and copy")
    return payload


def _exclusive_write(path: Path, payload: bytes) -> None:
    assert_safe_path_chain(path)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as error:
        raise BatchInputError("batch artifact could not be written exclusively") from error
    assert_safe_regular_file(path)


def _validate_batch_id(batch_id: str) -> None:
    if not isinstance(batch_id, str) or _BATCH_ID.fullmatch(batch_id) is None:
        raise BatchInputError("batch ID is invalid")


def register_batch(
    layout: DataLayout,
    batch_id: str,
    query_manifest: object,
    sources: object,
    snapshot_at: datetime,
) -> BatchManifest:
    """Register exact source bytes once, publishing the batch manifest last."""

    _validate_batch_id(batch_id)
    _require_aware(snapshot_at, "snapshot_at")
    try:
        layout.validate(initialized=True)
    except PathSafetyError as error:
        raise BatchInputError("data layout is unsafe or uninitialized") from error
    batch_dir = layout.raw / batch_id
    assert_safe_path_chain(batch_dir)
    if os.path.lexists(batch_dir):
        raise FileExistsError("batch already exists")
    queries = _coerce_queries(query_manifest)
    query_payload = _query_bytes(queries)
    if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes, bytearray)):
        raise BatchInputError("sources must be a sequence")
    if not sources:
        raise BatchInputError("at least one source is required")
    prepared = tuple(_prepare_source(item) for item in sources)
    names = [item.spec.path.name for item in prepared]
    if len({name.casefold() for name in names}) != len(names):
        raise BatchInputError("source destination names must be unique")

    inputs_dir = batch_dir / "inputs"
    manifest_path = batch_dir / "batch-manifest.json"
    try:
        batch_dir.mkdir()
        assert_safe_directory(batch_dir)
        inputs_dir.mkdir()
        assert_safe_directory(inputs_dir)
        bindings: list[SourceFileBinding] = []
        for item in prepared:
            payload = _read_for_copy(item)
            relative_path = PurePosixPath("inputs", item.spec.path.name).as_posix()
            destination = inputs_dir / item.spec.path.name
            _exclusive_write(destination, payload)
            copied, _ = _read_stable_source(destination)
            copied_records = _validate_jsonl(copied)
            if copied != payload or copied_records != item.records:
                raise BatchInputError("registered source verification failed")
            bindings.append(
                SourceFileBinding(
                    relative_path=relative_path,
                    record_kind=item.spec.record_kind,
                    platform=item.spec.platform,
                    sha256=hashlib.sha256(copied).hexdigest(),
                    bytes=len(copied),
                    records=copied_records,
                )
            )
        _exclusive_write(batch_dir / "query-manifest.json", query_payload)
        manifest = BatchManifest(
            schema="health_trend_batch.v1",
            batch_id=batch_id,
            created_at=snapshot_at,
            snapshot_at=snapshot_at,
            media_crawler_commit=MEDIA_CRAWLER_COMMIT,
            query_manifest_sha256=hashlib.sha256(query_payload).hexdigest(),
            sources=tuple(bindings),
            state="raw_registered",
        )
        _exclusive_write(manifest_path, canonical_json_bytes(manifest.model_dump(mode="json")))
        return verify_raw_batch(layout, batch_id)
    except (BatchInputError, PathSafetyError, OSError, ValidationError, ValueError):
        if manifest_path.is_file():
            try:
                manifest_path.unlink()
            except OSError:
                pass
        raise


def _safe_binding_path(batch_dir: Path, relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.as_posix() != relative_path
        or len(relative.parts) != 2
        or relative.parts[0] != "inputs"
        or not relative.name.casefold().endswith(".jsonl")
        or _FORBIDDEN.search(relative.name) is not None
    ):
        raise BatchInputError("manifest source path is unsafe")
    destination = batch_dir.joinpath(*relative.parts)
    try:
        assert_safe_regular_file(destination)
    except PathSafetyError as error:
        raise BatchInputError("manifest source path is unsafe") from error
    return destination


def _load_manifest(path: Path) -> BatchManifest:
    try:
        assert_safe_regular_file(path)
        payload = path.read_bytes()
        value = load_unique_json(payload)
        if canonical_json_bytes(value) != payload:
            raise BatchInputError("manifest is not canonical")
        return BatchManifest.model_validate_json(payload)
    except (OSError, PathSafetyError, TypeError, ValueError, ValidationError) as error:
        if isinstance(error, BatchInputError):
            raise
        raise BatchInputError("batch manifest is invalid") from error


def _verify_query_manifest(path: Path, expected_hash: str) -> None:
    try:
        assert_safe_regular_file(path)
        payload = path.read_bytes()
        value = load_unique_json(payload)
        queries = _coerce_queries(value)
        if _query_bytes(queries) != payload:
            raise BatchInputError("query manifest is not canonical")
        if hashlib.sha256(payload).hexdigest() != expected_hash:
            raise BatchInputError("query manifest hash does not match")
    except (OSError, PathSafetyError, TypeError, ValueError, ValidationError) as error:
        if isinstance(error, BatchInputError):
            raise
        raise BatchInputError("query manifest is invalid") from error


def verify_raw_batch(layout: DataLayout, batch_id: str) -> BatchManifest:
    """Re-open and verify every byte bound by a complete Raw manifest."""

    _validate_batch_id(batch_id)
    try:
        layout.validate(initialized=True)
        batch_dir = layout.raw / batch_id
        assert_safe_directory(batch_dir)
        inputs_dir = batch_dir / "inputs"
        assert_safe_directory(inputs_dir)
    except PathSafetyError as error:
        raise BatchInputError("raw batch path is unsafe or incomplete") from error
    manifest = _load_manifest(batch_dir / "batch-manifest.json")
    if manifest.batch_id != batch_id or manifest.state != "raw_registered":
        raise BatchInputError("batch manifest identity or state is invalid")
    _verify_query_manifest(batch_dir / "query-manifest.json", manifest.query_manifest_sha256)
    if len({binding.relative_path.casefold() for binding in manifest.sources}) != len(
        manifest.sources
    ):
        raise BatchInputError("batch manifest contains duplicate source paths")
    expected_names: set[str] = set()
    for binding in manifest.sources:
        path = _safe_binding_path(batch_dir, binding.relative_path)
        expected_names.add(path.name)
        try:
            payload, _ = _read_stable_source(path)
        except PathSafetyError as error:
            raise BatchInputError("registered source path is unsafe") from error
        records = _validate_jsonl(payload)
        if (
            len(payload) != binding.bytes
            or hashlib.sha256(payload).hexdigest() != binding.sha256
            or records != binding.records
        ):
            raise BatchInputError("registered source does not match its binding")
    try:
        actual_batch_entries = {path.name for path in batch_dir.iterdir()}
        actual_input_entries = {path.name for path in inputs_dir.iterdir()}
    except OSError as error:
        raise BatchInputError("batch directory cannot be inspected") from error
    if actual_batch_entries != {"inputs", "query-manifest.json", "batch-manifest.json"}:
        raise BatchInputError("raw batch contains unbound artifacts")
    if actual_input_entries != expected_names:
        raise BatchInputError("raw inputs contain unbound artifacts")
    return manifest


def build_retention_report(
    layout: DataLayout, as_of: datetime
) -> tuple[RetentionEntry, ...]:
    """Report complete batches older than 30 days without changing storage."""

    _require_aware(as_of, "as_of")
    try:
        layout.validate(initialized=True)
        children = tuple(layout.raw.iterdir())
    except (OSError, PathSafetyError) as error:
        raise BatchInputError("raw data layer cannot be inspected") from error
    entries: list[RetentionEntry] = []
    for child in children:
        if not child.is_dir() or not (child / "batch-manifest.json").is_file():
            continue
        manifest = verify_raw_batch(layout, child.name)
        age = as_of - manifest.snapshot_at
        if age > timedelta(days=30):
            entries.append(
                RetentionEntry(
                    batch_id=manifest.batch_id,
                    snapshot_at=manifest.snapshot_at,
                    age_days=age.days,
                    eligible_for_manual_deletion=True,
                )
            )
    return tuple(sorted(entries, key=lambda entry: entry.batch_id))
