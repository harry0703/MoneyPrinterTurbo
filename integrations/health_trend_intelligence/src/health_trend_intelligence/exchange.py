"""Fail-closed construction and verification of human-approved exchange packages."""

from __future__ import annotations

import hashlib
import html
import os
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from pydantic import ValidationError

from .canonical import canonical_json_bytes, load_unique_json
from .curation import CurationError, verify_curated_batch
from .models import APPROVED_DISCLAIMER, ApprovedCandidate, ApprovedSelection
from .privacy import SensitiveDataError, assert_no_sensitive_data
from .storage import (
    DataLayout,
    PathSafetyError,
    assert_safe_directory,
    assert_safe_regular_file,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_BATCH_ID = re.compile(r"HTI-\d{8}-\d{2}\Z")
_EXPECTED_FILES = frozenset({"bundle-manifest.json", "evidence-summary.json", "top10.json"})
_PAYLOAD_FILES = ("evidence-summary.json", "top10.json")
_CANDIDATE_FIELDS = frozenset(ApprovedCandidate.model_fields)
_SUMMARY_FIELDS = frozenset(
    {
        "batch_id",
        "candidate_count",
        "confidence_counts",
        "evidence_item_counts",
        "missing_data_candidate_count",
        "missing_data_item_count",
        "platform_coverage",
        "risk_flag_item_count",
        "risk_flagged_candidate_count",
        "schema",
    }
)
_MANIFEST_FIELDS = frozenset(
    {
        "batch_id",
        "candidate_count",
        "disclaimer",
        "files",
        "generated_at",
        "human_selection_status",
        "input_curated_manifest_sha256",
        "schema",
        "selection_sha256",
        "version",
    }
)
_BINDING_FIELDS = frozenset({"bytes", "relative_path", "sha256"})
_SELECTION_FIELDS = frozenset(ApprovedSelection.model_fields)
_ALLOWED_KEYS = frozenset().union(
    _CANDIDATE_FIELDS,
    _SUMMARY_FIELDS,
    _MANIFEST_FIELDS,
    _BINDING_FIELDS,
    _SELECTION_FIELDS,
    {"both", "dy", "high", "low", "medium", "xhs"},
)
_URL = re.compile(r"(?:https?|hxxps?)//|www\.|wwwdot", re.IGNORECASE)
_DOMAIN = re.compile(
    r"\b[a-z0-9-]{2,}\s*(?:\.|\[\.\]|\(\.\)|dot)\s*(?:cn|co|com|io|net|org)\b",
    re.IGNORECASE,
)
_COMPACT_DOMAIN = re.compile(r"[a-z0-9-]{2,}(?:dot|\.)(?:cn|co|com|io|net|org)\b")
_RAW_PATH = re.compile(r"(?:^|[\\/])(?:raw|curated)(?:[\\/]|$)", re.IGNORECASE)
_IDENTITY_OR_MEDIA = re.compile(
    r"\b(?:avatar|bearer|cookie|credential|identifier|media|nickname|source[_ -]?url|token|url|user[_ -]?id|video|audio|image|id)\b",
    re.IGNORECASE,
)
_MEDIA_EXTENSION = re.compile(
    r"\.(?:aac|avi|gif|jpeg|jpg|m4a|mkv|mov|mp3|mp4|mpeg|png|svg|wav|webm)\b",
    re.IGNORECASE,
)
_RAW_EXCERPT = re.compile(r"raw\s*excerpt|原文|原句|摘录|全文", re.IGNORECASE)
_CHINESE_RESTRICTED = re.compile(r"昵称|头像|凭据|令牌|媒体|身份")
_MEDICAL_CLAIM = re.compile(
    r"(?:一定|保证|必然|可以|能够).{0,16}(?:治愈|根治|确诊|治疗|预防疾病)"
    r"|包治|药到病除|经医学证实|医学事实"
)


class ExchangeError(ValueError):
    """A privacy-safe exchange failure carrying only a stable reason code."""

    __slots__ = ("reason_code",)

    def __init__(self, reason_code: str) -> None:
        safe = reason_code if re.fullmatch(r"[a-z0-9_]+", reason_code) else "invalid_exchange"
        self.reason_code = safe
        super().__init__(safe)


class ApprovalRequired(ExchangeError):
    """Raised before filesystem publication when explicit approval is absent."""

    def __init__(self) -> None:
        super().__init__("approval_required")


@dataclass(frozen=True, slots=True)
class ApprovedExchangeResult:
    path: Path
    batch_id: str
    manifest_sha256: str
    candidate_count: int
    input_curated_manifest_sha256: str


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_stable_bytes(path: Path) -> bytes:
    try:
        assert_safe_regular_file(path)
        first = path.read_bytes()
        assert_safe_regular_file(path)
        second = path.read_bytes()
    except (OSError, PathSafetyError) as error:
        raise ExchangeError("input_unavailable") from error
    if first != second or _sha256(first) != _sha256(second):
        raise ExchangeError("input_changed")
    return first


def _load_canonical_object(payload: bytes, reason_code: str) -> dict[str, Any]:
    try:
        value = load_unique_json(payload)
        if not isinstance(value, dict) or canonical_json_bytes(value) != payload:
            raise ValueError
    except (TypeError, ValueError) as error:
        raise ExchangeError(reason_code) from error
    return value


def _load_canonical_value(payload: bytes, reason_code: str) -> Any:
    try:
        value = load_unique_json(payload)
        if canonical_json_bytes(value) != payload:
            raise ValueError
    except (TypeError, ValueError) as error:
        raise ExchangeError(reason_code) from error
    return value


def _decoded_text(value: str) -> str:
    decoded = unicodedata.normalize("NFKC", html.unescape(value)).casefold()
    for _ in range(3):
        expanded = unquote(decoded)
        if expanded == decoded:
            break
        decoded = expanded
    return "".join(
        character
        for character in decoded
        if not unicodedata.category(character).startswith("C")
    )


def _assert_safe_text(value: str) -> None:
    if value == APPROVED_DISCLAIMER:
        return
    decoded = _decoded_text(value)
    compact = re.sub(r"[\s\[\](){}<>:'\"`]+", "", decoded)
    if (
        _URL.search(compact)
        or _DOMAIN.search(decoded)
        or _COMPACT_DOMAIN.search(compact)
        or _RAW_PATH.search(decoded)
        or _IDENTITY_OR_MEDIA.search(decoded)
        or _MEDIA_EXTENSION.search(decoded)
        or _RAW_EXCERPT.search(decoded)
        or _CHINESE_RESTRICTED.search(decoded)
        or _MEDICAL_CLAIM.search(decoded)
    ):
        raise ExchangeError("restricted_approved_content")


def _assert_approved_content(payload: object) -> None:
    """Apply both the shared privacy scanner and the narrower Approved allowlist."""

    try:
        assert_no_sensitive_data(payload)
    except SensitiveDataError as error:
        raise ExchangeError("restricted_approved_content") from error

    def scan(value: object) -> None:
        if isinstance(value, str):
            _assert_safe_text(value)
            return
        if value is None or isinstance(value, (bool, int, float, datetime)):
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                if not isinstance(key, str) or key not in _ALLOWED_KEYS:
                    raise ExchangeError("undeclared_approved_field")
                _assert_safe_text(key)
                scan(item)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                scan(item)
            return
        raise ExchangeError("unsupported_approved_value")

    scan(payload)


def _exclusive_write(path: Path, payload: bytes) -> None:
    try:
        with path.open("xb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as error:
        raise ExchangeError("destination_conflict") from error
    except OSError as error:
        raise ExchangeError("write_failed") from error


def _remove_completion_marker(path: Path) -> None:
    if not os.path.lexists(path):
        return
    try:
        assert_safe_regular_file(path)
        path.unlink()
    except (OSError, PathSafetyError) as error:
        raise ExchangeError("completion_marker_cleanup_failed") from error


def _directory_names(path: Path) -> frozenset[str]:
    try:
        assert_safe_directory(path)
        names = frozenset(item.name for item in path.iterdir())
    except (OSError, PathSafetyError) as error:
        raise ExchangeError("approved_directory_invalid") from error
    return names


def _summary_value(batch_id: str, candidates: tuple[ApprovedCandidate, ...]) -> dict[str, Any]:
    return {
        "schema": "health_trend_evidence_summary.v1",
        "batch_id": batch_id,
        "candidate_count": len(candidates),
        "platform_coverage": {
            "dy": sum("dy" in candidate.platform_rank_evidence for candidate in candidates),
            "xhs": sum("xhs" in candidate.platform_rank_evidence for candidate in candidates),
            "both": sum(
                set(candidate.platform_rank_evidence) == {"dy", "xhs"}
                for candidate in candidates
            ),
        },
        "confidence_counts": {
            level: sum(candidate.confidence == level for candidate in candidates)
            for level in ("low", "medium", "high")
        },
        "evidence_item_counts": {
            field: sum(len(getattr(candidate, field)) for candidate in candidates)
            for field in (
                "growth_evidence",
                "user_questions",
                "user_needs",
                "misunderstandings",
                "objections",
            )
        },
        "risk_flagged_candidate_count": sum(bool(candidate.risk_flags) for candidate in candidates),
        "risk_flag_item_count": sum(len(candidate.risk_flags) for candidate in candidates),
        "missing_data_candidate_count": sum(bool(candidate.missing_data) for candidate in candidates),
        "missing_data_item_count": sum(len(candidate.missing_data) for candidate in candidates),
    }


def _file_binding(name: str, payload: bytes) -> dict[str, object]:
    return {"relative_path": name, "bytes": len(payload), "sha256": _sha256(payload)}


def _assert_inputs_unchanged(
    layout: DataLayout,
    batch_id: str,
    curated_manifest_payload: bytes,
    selection_path: Path,
    selection_payload: bytes,
) -> None:
    try:
        verified = verify_curated_batch(layout, batch_id)
    except (CurationError, OSError, PathSafetyError, TypeError, ValueError) as error:
        raise ExchangeError("curated_input_changed") from error
    current_curated = _read_stable_bytes(verified.path / "curated-manifest.json")
    current_selection = _read_stable_bytes(selection_path)
    if (
        current_curated != curated_manifest_payload
        or _sha256(current_curated) != verified.manifest_sha256
        or current_selection != selection_payload
        or _sha256(current_selection) != _sha256(selection_payload)
    ):
        raise ExchangeError("input_changed")


def _selection_from_payload(payload: bytes) -> ApprovedSelection:
    value = _load_canonical_object(payload, "selection_invalid")
    if value.get("human_selection_status") != "approved":
        raise ApprovalRequired
    try:
        selection = ApprovedSelection.model_validate_json(payload)
    except ValidationError as error:
        raise ExchangeError("selection_invalid") from error
    _assert_approved_content(selection.model_dump(mode="json"))
    return selection


def build_approved_exchange(
    layout: DataLayout, batch_id: str, selection_path: Path
) -> ApprovedExchangeResult:
    """Publish one deterministic exchange only from a verified Curated batch and approval."""

    if not isinstance(layout, DataLayout) or not isinstance(batch_id, str):
        raise ExchangeError("invalid_input")
    if _BATCH_ID.fullmatch(batch_id) is None:
        raise ExchangeError("invalid_batch_id")
    try:
        curated = verify_curated_batch(layout, batch_id)
    except (CurationError, OSError, PathSafetyError, TypeError, ValueError) as error:
        raise ExchangeError("curated_verification_failed") from error
    curated_manifest_payload = _read_stable_bytes(curated.path / "curated-manifest.json")
    if _sha256(curated_manifest_payload) != curated.manifest_sha256:
        raise ExchangeError("curated_manifest_changed")

    selection_file = Path(selection_path)
    selection_payload = _read_stable_bytes(selection_file)
    selection = _selection_from_payload(selection_payload)
    if selection.batch_id != batch_id:
        raise ExchangeError("selection_batch_mismatch")
    if selection.curated_manifest_sha256 != curated.manifest_sha256:
        raise ExchangeError("selection_curated_mismatch")

    destination = layout.approved / batch_id
    work = layout.approved / f"{batch_id}.work"
    if os.path.lexists(destination) or os.path.lexists(work):
        raise ExchangeError("destination_conflict")
    try:
        work.mkdir()
    except FileExistsError as error:
        raise ExchangeError("destination_conflict") from error
    except OSError as error:
        raise ExchangeError("write_failed") from error

    candidates = tuple(sorted(selection.candidates, key=lambda candidate: candidate.rank))
    top10_value = [candidate.model_dump(mode="json") for candidate in candidates]
    summary_value = _summary_value(batch_id, candidates)
    _assert_approved_content(top10_value)
    _assert_approved_content(summary_value)
    top10_payload = canonical_json_bytes(top10_value)
    summary_payload = canonical_json_bytes(summary_value)
    _exclusive_write(work / "top10.json", top10_payload)
    _exclusive_write(work / "evidence-summary.json", summary_payload)

    _assert_inputs_unchanged(
        layout,
        batch_id,
        curated_manifest_payload,
        selection_file,
        selection_payload,
    )
    manifest_value = {
        "schema": "health_trend_exchange.v1",
        "version": "v01",
        "batch_id": batch_id,
        "generated_at": selection.approved_at.isoformat(),
        "input_curated_manifest_sha256": curated.manifest_sha256,
        "selection_sha256": _sha256(selection_payload),
        "human_selection_status": "approved",
        "candidate_count": len(candidates),
        "disclaimer": APPROVED_DISCLAIMER,
        "files": [
            _file_binding("evidence-summary.json", summary_payload),
            _file_binding("top10.json", top10_payload),
        ],
    }
    manifest_payload = canonical_json_bytes(manifest_value)
    work_manifest = work / "bundle-manifest.json"
    _exclusive_write(work_manifest, manifest_payload)
    manifest_sha256 = _sha256(manifest_payload)
    published = False
    try:
        _verify_approved_exchange(work, manifest_sha256, allow_work=True)
        _assert_inputs_unchanged(
            layout,
            batch_id,
            curated_manifest_payload,
            selection_file,
            selection_payload,
        )
        if os.path.lexists(destination):
            raise ExchangeError("destination_conflict")
        work.rename(destination)
        published = True
        return verify_approved_exchange(destination, manifest_sha256)
    except OSError as error:
        _remove_completion_marker(work_manifest)
        raise ExchangeError("publish_failed") from error
    except ExchangeError:
        completion_marker = (
            destination / "bundle-manifest.json" if published else work_manifest
        )
        _remove_completion_marker(completion_marker)
        raise


def _validate_manifest(value: dict[str, Any]) -> None:
    if set(value) != _MANIFEST_FIELDS:
        raise ExchangeError("manifest_fields_invalid")
    if (
        value.get("schema") != "health_trend_exchange.v1"
        or value.get("version") != "v01"
        or value.get("human_selection_status") != "approved"
        or value.get("candidate_count") != 10
        or value.get("disclaimer") != APPROVED_DISCLAIMER
        or not isinstance(value.get("batch_id"), str)
        or _BATCH_ID.fullmatch(value["batch_id"]) is None
        or not isinstance(value.get("input_curated_manifest_sha256"), str)
        or _SHA256.fullmatch(value["input_curated_manifest_sha256"]) is None
        or not isinstance(value.get("selection_sha256"), str)
        or _SHA256.fullmatch(value["selection_sha256"]) is None
    ):
        raise ExchangeError("manifest_invalid")
    try:
        generated_at = datetime.fromisoformat(value["generated_at"])
    except (TypeError, ValueError) as error:
        raise ExchangeError("manifest_invalid") from error
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ExchangeError("manifest_invalid")
    files = value.get("files")
    if not isinstance(files, list) or len(files) != 2:
        raise ExchangeError("manifest_files_invalid")
    for expected_name, binding in zip(_PAYLOAD_FILES, files, strict=True):
        if not isinstance(binding, dict) or set(binding) != _BINDING_FIELDS:
            raise ExchangeError("manifest_files_invalid")
        if (
            binding.get("relative_path") != expected_name
            or isinstance(binding.get("bytes"), bool)
            or not isinstance(binding.get("bytes"), int)
            or binding["bytes"] < 0
            or not isinstance(binding.get("sha256"), str)
            or _SHA256.fullmatch(binding["sha256"]) is None
        ):
            raise ExchangeError("manifest_files_invalid")


def verify_approved_exchange(
    path: Path, expected_manifest_sha256: str | None = None
) -> ApprovedExchangeResult:
    """Re-open and semantically verify every exact byte in an Approved exchange."""

    return _verify_approved_exchange(path, expected_manifest_sha256, allow_work=False)


def _verify_approved_exchange(
    path: Path,
    expected_manifest_sha256: str | None,
    *,
    allow_work: bool,
) -> ApprovedExchangeResult:

    if expected_manifest_sha256 is not None and (
        not isinstance(expected_manifest_sha256, str)
        or _SHA256.fullmatch(expected_manifest_sha256) is None
    ):
        raise ExchangeError("expected_manifest_anchor_invalid")
    approved_path = Path(path)
    if _directory_names(approved_path) != _EXPECTED_FILES:
        raise ExchangeError("approved_file_set_mismatch")
    manifest_payload = _read_stable_bytes(approved_path / "bundle-manifest.json")
    manifest_sha256 = _sha256(manifest_payload)
    if expected_manifest_sha256 is not None and manifest_sha256 != expected_manifest_sha256:
        raise ExchangeError("manifest_anchor_mismatch")
    manifest = _load_canonical_object(manifest_payload, "manifest_noncanonical")
    _validate_manifest(manifest)
    expected_directory_name = (
        f"{manifest['batch_id']}.work" if allow_work else manifest["batch_id"]
    )
    if approved_path.name != expected_directory_name:
        raise ExchangeError("approved_path_batch_mismatch")

    payloads: dict[str, bytes] = {}
    for binding in manifest["files"]:
        name = binding["relative_path"]
        payload = _read_stable_bytes(approved_path / name)
        if len(payload) != binding["bytes"] or _sha256(payload) != binding["sha256"]:
            raise ExchangeError("payload_binding_mismatch")
        payloads[name] = payload

    top10 = _load_canonical_value(payloads["top10.json"], "top10_noncanonical")
    if not isinstance(top10, list) or len(top10) != 10:
        raise ExchangeError("top10_invalid")
    try:
        candidates = tuple(
            ApprovedCandidate.model_validate_json(canonical_json_bytes(candidate))
            for candidate in top10
        )
        ApprovedSelection.model_validate_json(
            canonical_json_bytes(
                {
                    "schema": "health_trend_selection.v1",
                    "batch_id": manifest["batch_id"],
                    "curated_manifest_sha256": manifest["input_curated_manifest_sha256"],
                    "human_selection_status": manifest["human_selection_status"],
                    "approved_at": manifest["generated_at"],
                    "candidates": top10,
                }
            )
        )
    except ValidationError as error:
        raise ExchangeError("top10_invalid") from error
    if tuple(candidate.rank for candidate in candidates) != tuple(range(1, 11)):
        raise ExchangeError("top10_order_invalid")

    summary = _load_canonical_object(payloads["evidence-summary.json"], "summary_noncanonical")
    if set(summary) != _SUMMARY_FIELDS or summary != _summary_value(manifest["batch_id"], candidates):
        raise ExchangeError("summary_invalid")
    _assert_approved_content(top10)
    _assert_approved_content(summary)
    _assert_approved_content(manifest)
    if _directory_names(approved_path) != _EXPECTED_FILES:
        raise ExchangeError("approved_file_set_changed")
    if _read_stable_bytes(approved_path / "bundle-manifest.json") != manifest_payload:
        raise ExchangeError("manifest_changed")
    for name, payload in payloads.items():
        if _read_stable_bytes(approved_path / name) != payload:
            raise ExchangeError("payload_changed")
    return ApprovedExchangeResult(
        path=approved_path,
        batch_id=manifest["batch_id"],
        manifest_sha256=manifest_sha256,
        candidate_count=manifest["candidate_count"],
        input_curated_manifest_sha256=manifest["input_curated_manifest_sha256"],
    )
