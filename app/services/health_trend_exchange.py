"""Fail-closed verification and one-way import of approved trend exchanges."""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import math
import ntpath
import os
import re
import stat
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_BATCH_ID = re.compile(r"HTI-\d{8}-\d{2}\Z")
_EXPECTED_FILES = frozenset(
    {"bundle-manifest.json", "evidence-summary.json", "top10.json"}
)
_PAYLOAD_FILES = ("evidence-summary.json", "top10.json")
_DISCLAIMER = "该包只是选题情报，不是医学事实来源或可直接发布的脚本。"
_MEDICAL_RISK = "medical_claim_unverified"
_CANDIDATE_FIELDS = frozenset(
    {
        "confidence",
        "disclaimer",
        "growth_evidence",
        "homogeneity_pattern",
        "missing_data",
        "misunderstandings",
        "narrative_gap",
        "objections",
        "original_visual_direction",
        "platform_rank_evidence",
        "rank",
        "risk_flags",
        "topic",
        "user_needs",
        "user_questions",
    }
)
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
_TEXT_LIST_FIELDS = (
    "growth_evidence",
    "user_questions",
    "user_needs",
    "misunderstandings",
    "objections",
)
_ALL_TEXT_LIST_FIELDS = (*_TEXT_LIST_FIELDS, "risk_flags", "missing_data")
_DECLARED_FILE_NAMES = frozenset(_EXPECTED_FILES)
_REPARSE_ATTRIBUTE = 0x400
_CONFUSABLE_ASCII = str.maketrans(
    {
        "Α": "a",
        "Β": "b",
        "Ε": "e",
        "Ι": "i",
        "Κ": "k",
        "Ο": "o",
        "Ρ": "p",
        "Τ": "t",
        "Χ": "x",
        "α": "a",
        "β": "b",
        "ε": "e",
        "ι": "i",
        "κ": "k",
        "ο": "o",
        "ρ": "p",
        "τ": "t",
        "χ": "x",
        "А": "a",
        "В": "b",
        "Е": "e",
        "К": "k",
        "М": "m",
        "Н": "h",
        "О": "o",
        "Р": "p",
        "С": "c",
        "Т": "t",
        "Х": "x",
        "а": "a",
        "в": "b",
        "е": "e",
        "і": "i",
        "ј": "j",
        "к": "k",
        "м": "m",
        "н": "h",
        "о": "o",
        "р": "p",
        "с": "c",
        "т": "t",
        "х": "x",
    }
)
_URL_SCHEME = re.compile(
    r"(?<![a-z0-9])(?:https?|ftp|file|data|javascript|vbscript|blob):\s*[\\/]{0,2}",
    re.IGNORECASE,
)
_DOMAIN = re.compile(r"(?<![\w-])(?:[a-z0-9-]{1,63}\.)+[a-z]{2,63}(?![\w-])", re.I)
_IP = re.compile(
    r"(?<![\w])(?:\[[0-9a-f:.%]+\]|(?:\d{1,3}\.){3}\d{1,3}|[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){2,})(?![\w])",
    re.I,
)
_RAW_OR_CURATED_PATH = re.compile(r"(?:^|[\\/])(?:raw|curated)(?:[\\/]|$)", re.I)
_RAW_OR_CURATED_RECORD = re.compile(
    r"(?<![a-z0-9])(?:raw|curated)[_ -]?(?:data|record|excerpt|payload)(?![a-z0-9])",
    re.I,
)
_MEDIA_OR_EXECUTABLE = re.compile(
    r"\.(?:aac|avi|bat|cmd|com|dll|exe|gif|jpeg|jpg|js|m4a|mkv|mov|mp3|mp4|mpeg|msi|png|ps1|py|scr|svg|vbs|wav|webm)(?:\b|$)",
    re.I,
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?:api[_ -]?key|authorization|bearer|cookie|credential|password|proxy[_ -]?(?:key|password)|secret|session|token|xsec[_ -]?token)\s*(?:=|:|\s)\s*\S+",
    re.I,
)
_SECRET_TOKEN = re.compile(
    r"(?<![a-z0-9])(?:(?:sk|pk)_[a-z0-9_-]{12,}|(?:sk|pk)-[a-z0-9_-]{12,})",
    re.I,
)
_PHONE_NUMBER = re.compile(r"(?<!\d)(?:\+?86[ -]?)?1[3-9]\d{9}(?!\d)")
_ENGLISH_MEDICAL_CONTEXT = (
    r"(?:medical(?:ly)?|medicine|clinical(?:ly)?|health[ _-]+claim)"
)
_ENGLISH_VERIFIED_STATE = (
    r"(?:verified|verification.{0,12}(?:complete(?:d)?|done|finished|passed))"
)
_CONTRADICTORY_MEDICAL_ENGLISH = (
    re.compile(
        rf"\b{_ENGLISH_MEDICAL_CONTEXT}\b.{{0,48}}\b{_ENGLISH_VERIFIED_STATE}\b",
        re.I,
    ),
    re.compile(
        rf"\b{_ENGLISH_VERIFIED_STATE}\b.{{0,48}}\b{_ENGLISH_MEDICAL_CONTEXT}\b",
        re.I,
    ),
)
_CONTRADICTORY_MEDICAL_CHINESE = (
    re.compile(
        r"(?:医学|医疗|临床|健康(?:结论|声明)).{0,24}"
        r"(?:已|已经|完成|通过|成功).{0,10}(?:核验|验证|确认|审查)"
    ),
    re.compile(
        r"(?:已|已经|完成|通过|成功).{0,10}"
        r"(?:医学|医疗|临床).{0,10}(?:核验|验证|确认|审查)"
    ),
)


class TrendExchangeError(ValueError):
    """A rejection with a stable, payload-free reason code."""

    __slots__ = ("reason_code",)

    def __init__(self, reason_code: str) -> None:
        safe = reason_code if re.fullmatch(r"[a-z0-9_]+", reason_code) else "invalid_exchange"
        self.reason_code = safe
        super().__init__(safe)


@dataclass(frozen=True, slots=True)
class VerifiedTrendExchange:
    source: Path
    batch_id: str
    version: Literal["v01"]
    manifest_sha256: str
    candidate_count: int


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    payload: bytes
    identity: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class _VerifiedSnapshot:
    result: VerifiedTrendExchange
    files: dict[str, _FileSnapshot]


def _is_reparse(status: os.stat_result) -> bool:
    return bool(getattr(status, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE)


def _identity(status: os.stat_result) -> tuple[int, int, int, int]:
    return (status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns)


def _directory_identity(status: os.stat_result) -> tuple[int, int]:
    return (status.st_dev, status.st_ino)


def _absolute_without_resolving(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _validate_local_absolute_path(path: Path, reason: str) -> Path:
    raw = os.fspath(path)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise TrendExchangeError(reason)
    if os.name == "nt":
        if raw.startswith(("\\\\", "//")):
            raise TrendExchangeError(reason)
        drive, tail = ntpath.splitdrive(raw)
        if (
            re.fullmatch(r"[A-Za-z]:", drive) is None
            or not tail.startswith(("\\", "/"))
            or ".." in Path(raw).parts
            or ":" in tail
        ):
            raise TrendExchangeError(reason)
        try:
            drive_status = Path(f"{drive}\\").lstat()
        except OSError as error:
            raise TrendExchangeError(reason) from error
        if not stat.S_ISDIR(drive_status.st_mode) or _is_reparse(drive_status):
            raise TrendExchangeError(reason)
    elif not raw.startswith("/") or raw.startswith("//") or ".." in Path(raw).parts:
        raise TrendExchangeError(reason)
    return _absolute_without_resolving(Path(raw))


def _assert_safe_directory(path: Path, reason: str) -> tuple[int, int]:
    absolute = _absolute_without_resolving(path)
    chain = [absolute, *absolute.parents]
    for component in reversed(chain):
        try:
            status = component.lstat()
        except OSError as error:
            raise TrendExchangeError(reason) from error
        if _is_reparse(status) or stat.S_ISLNK(status.st_mode):
            raise TrendExchangeError(reason)
    try:
        status = absolute.lstat()
    except OSError as error:
        raise TrendExchangeError(reason) from error
    if not stat.S_ISDIR(status.st_mode) or _is_reparse(status):
        raise TrendExchangeError(reason)
    return _directory_identity(status)


def _read_regular_file(path: Path) -> _FileSnapshot:
    try:
        path_before = path.lstat()
        if (
            _is_reparse(path_before)
            or stat.S_ISLNK(path_before.st_mode)
            or not stat.S_ISREG(path_before.st_mode)
        ):
            raise TrendExchangeError("source_file_invalid")
        with path.open("rb") as handle:
            opened_before = os.fstat(handle.fileno())
            if _is_reparse(opened_before) or not stat.S_ISREG(opened_before.st_mode):
                raise TrendExchangeError("source_file_invalid")
            if _identity(path_before) != _identity(opened_before):
                raise TrendExchangeError("source_file_changed")
            payload = handle.read()
            opened_after = os.fstat(handle.fileno())
        path_after = path.lstat()
    except TrendExchangeError:
        raise
    except OSError as error:
        raise TrendExchangeError("source_file_invalid") from error
    if not (
        _identity(path_before)
        == _identity(opened_before)
        == _identity(opened_after)
        == _identity(path_after)
    ):
        raise TrendExchangeError("source_file_changed")
    if len(payload) != opened_after.st_size:
        raise TrendExchangeError("source_file_changed")
    return _FileSnapshot(payload=payload, identity=_identity(opened_after))


def _parse_constant(_: str) -> None:
    raise TrendExchangeError("non_finite_json_number")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    normalized_keys: set[str] = set()
    for key, value in pairs:
        if key in result:
            raise TrendExchangeError("duplicate_json_key")
        normalized = unicodedata.normalize("NFC", key)
        if normalized in normalized_keys:
            raise TrendExchangeError("nfc_json_key_collision")
        if normalized != key:
            raise TrendExchangeError("json_text_not_nfc")
        result[key] = value
        normalized_keys.add(normalized)
    return result


def _assert_json_values(value: object) -> None:
    if isinstance(value, str):
        if unicodedata.normalize("NFC", value) != value:
            raise TrendExchangeError("json_text_not_nfc")
        return
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise TrendExchangeError("non_finite_json_number")
        return
    if isinstance(value, list):
        for item in value:
            _assert_json_values(item)
        return
    if isinstance(value, dict):
        for item in value.values():
            _assert_json_values(item)
        return
    raise TrendExchangeError("unsupported_json_value")


def _load_json(payload: bytes) -> object:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise TrendExchangeError("json_utf8_invalid") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_parse_constant,
        )
    except TrendExchangeError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise TrendExchangeError("json_invalid") from error
    _assert_json_values(value)
    return value


def _require_object(value: object, fields: frozenset[str], reason: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise TrendExchangeError(reason)
    return value


def _require_sha(value: object, reason: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise TrendExchangeError(reason)
    return value


def _require_nonempty_text(value: object, reason: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrendExchangeError(reason)
    return value


def _require_count(value: object, reason: str, maximum: int | None = None) -> int:
    if type(value) is not int or value < 0 or (maximum is not None and value > maximum):
        raise TrendExchangeError(reason)
    return value


def _validate_manifest(value: object) -> dict[str, Any]:
    manifest = _require_object(value, _MANIFEST_FIELDS, "manifest_fields_invalid")
    if (
        manifest.get("schema") != "health_trend_exchange.v1"
        or manifest.get("version") != "v01"
        or manifest.get("human_selection_status") != "approved"
        or manifest.get("disclaimer") != _DISCLAIMER
        or type(manifest.get("candidate_count")) is not int
        or manifest["candidate_count"] != 10
        or not isinstance(manifest.get("batch_id"), str)
        or _BATCH_ID.fullmatch(manifest["batch_id"]) is None
    ):
        raise TrendExchangeError("manifest_invalid")
    _require_sha(manifest.get("input_curated_manifest_sha256"), "manifest_invalid")
    _require_sha(manifest.get("selection_sha256"), "manifest_invalid")
    try:
        generated_at = datetime.fromisoformat(manifest["generated_at"])
    except (TypeError, ValueError) as error:
        raise TrendExchangeError("manifest_invalid") from error
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise TrendExchangeError("manifest_invalid")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != 2:
        raise TrendExchangeError("manifest_files_invalid")
    for expected_name, raw_binding in zip(_PAYLOAD_FILES, files, strict=True):
        binding = _require_object(raw_binding, _BINDING_FIELDS, "manifest_files_invalid")
        if (
            binding.get("relative_path") != expected_name
            or type(binding.get("bytes")) is not int
            or binding["bytes"] < 0
        ):
            raise TrendExchangeError("manifest_files_invalid")
        _require_sha(binding.get("sha256"), "manifest_files_invalid")
    return manifest


def _validate_text_list(value: object, *, allow_empty: bool, reason: str) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise TrendExchangeError(reason)
    for item in value:
        _require_nonempty_text(item, reason)
    return value


def _validate_candidates(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != 10:
        raise TrendExchangeError("top10_invalid")
    candidates: list[dict[str, Any]] = []
    topics: set[str] = set()
    for expected_rank, raw_candidate in enumerate(value, start=1):
        candidate = _require_object(raw_candidate, _CANDIDATE_FIELDS, "candidate_fields_invalid")
        if type(candidate.get("rank")) is not int or candidate["rank"] != expected_rank:
            raise TrendExchangeError("candidate_rank_invalid")
        if candidate.get("disclaimer") != _DISCLAIMER:
            raise TrendExchangeError("candidate_disclaimer_invalid")
        if candidate.get("confidence") not in {"low", "medium", "high"}:
            raise TrendExchangeError("candidate_confidence_invalid")
        for field in ("topic", "homogeneity_pattern", "narrative_gap", "original_visual_direction"):
            _require_nonempty_text(candidate.get(field), "candidate_text_invalid")
        for field in _ALL_TEXT_LIST_FIELDS:
            _validate_text_list(
                candidate.get(field),
                allow_empty=field == "missing_data",
                reason="candidate_list_invalid",
            )
        if candidate["risk_flags"].count(_MEDICAL_RISK) != 1:
            raise TrendExchangeError("medical_claim_unverified")
        for risk_flag in candidate["risk_flags"]:
            compact_risk_flag = "".join(
                character
                for character in unicodedata.normalize("NFKC", risk_flag).casefold()
                if character.isalnum()
            )
            has_medical_context = any(
                context in compact_risk_flag for context in ("clinical", "medical")
            )
            has_positive_verified_state = (
                "verified" in compact_risk_flag
                and "unverified" not in compact_risk_flag
                and "notverified" not in compact_risk_flag
                and "neververified" not in compact_risk_flag
            )
            if has_medical_context and has_positive_verified_state:
                raise TrendExchangeError("medical_verification_contradiction")
        platform = candidate.get("platform_rank_evidence")
        if (
            not isinstance(platform, dict)
            or not 1 <= len(platform) <= 2
            or not set(platform) <= {"dy", "xhs"}
        ):
            raise TrendExchangeError("candidate_platform_invalid")
        for evidence in platform.values():
            _require_nonempty_text(evidence, "candidate_platform_invalid")
        topic_key = unicodedata.normalize("NFKC", " ".join(candidate["topic"].split())).casefold()
        if not topic_key or topic_key in topics:
            raise TrendExchangeError("candidate_topic_invalid")
        topics.add(topic_key)
        candidates.append(candidate)
    return candidates


def _summary_for(batch_id: str, candidates: list[dict[str, Any]]) -> dict[str, object]:
    return {
        "schema": "health_trend_evidence_summary.v1",
        "batch_id": batch_id,
        "candidate_count": 10,
        "platform_coverage": {
            "dy": sum("dy" in candidate["platform_rank_evidence"] for candidate in candidates),
            "xhs": sum("xhs" in candidate["platform_rank_evidence"] for candidate in candidates),
            "both": sum(
                set(candidate["platform_rank_evidence"]) == {"dy", "xhs"}
                for candidate in candidates
            ),
        },
        "confidence_counts": {
            level: sum(candidate["confidence"] == level for candidate in candidates)
            for level in ("low", "medium", "high")
        },
        "evidence_item_counts": {
            field: sum(len(candidate[field]) for candidate in candidates)
            for field in _TEXT_LIST_FIELDS
        },
        "risk_flagged_candidate_count": sum(bool(candidate["risk_flags"]) for candidate in candidates),
        "risk_flag_item_count": sum(len(candidate["risk_flags"]) for candidate in candidates),
        "missing_data_candidate_count": sum(bool(candidate["missing_data"]) for candidate in candidates),
        "missing_data_item_count": sum(len(candidate["missing_data"]) for candidate in candidates),
    }


def _validate_summary(
    value: object, batch_id: str, candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    summary = _require_object(value, _SUMMARY_FIELDS, "summary_fields_invalid")
    if (
        summary.get("schema") != "health_trend_evidence_summary.v1"
        or summary.get("batch_id") != batch_id
        or type(summary.get("candidate_count")) is not int
        or summary["candidate_count"] != 10
    ):
        raise TrendExchangeError("summary_invalid")
    expected_nested = {
        "platform_coverage": ({"both", "dy", "xhs"}, 10),
        "confidence_counts": ({"high", "low", "medium"}, 10),
        "evidence_item_counts": (set(_TEXT_LIST_FIELDS), None),
    }
    for field, (keys, maximum) in expected_nested.items():
        counts = summary.get(field)
        if not isinstance(counts, dict) or set(counts) != keys:
            raise TrendExchangeError("summary_invalid")
        for count in counts.values():
            _require_count(count, "summary_invalid", maximum=maximum)
    for field in (
        "risk_flagged_candidate_count",
        "risk_flag_item_count",
        "missing_data_candidate_count",
        "missing_data_item_count",
    ):
        _require_count(summary.get(field), "summary_invalid")
    if summary != _summary_for(batch_id, candidates):
        raise TrendExchangeError("summary_invalid")
    return summary


def _normalized_security_text(value: str) -> str:
    normalized = value
    for _ in range(3):
        decoded = unquote(html.unescape(normalized))
        if decoded == normalized:
            break
        normalized = decoded
    normalized = unicodedata.normalize("NFKC", normalized).translate(_CONFUSABLE_ASCII)
    return "".join(
        character for character in normalized if unicodedata.category(character) != "Cf"
    ).casefold()


def _contains_ip(value: str) -> bool:
    for match in _IP.finditer(value):
        candidate = match.group(0).strip("[]").split("%", 1)[0]
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            continue
        return True
    return False


def _assert_safe_text(value: str) -> None:
    if value == _DISCLAIMER or value in _DECLARED_FILE_NAMES:
        return
    normalized = _normalized_security_text(value)
    medical_claim_text = re.sub(r"[_-]+", " ", normalized)
    medical_claim_text = re.sub(
        r"\b(?:(?:has|have|is|was|were)\s+)?(?:not|never)\s+(?:been\s+)?verified\b",
        "unverified",
        medical_claim_text,
    )
    if any(
        pattern.search(medical_claim_text)
        for pattern in (*_CONTRADICTORY_MEDICAL_ENGLISH, *_CONTRADICTORY_MEDICAL_CHINESE)
    ):
        raise TrendExchangeError("medical_verification_contradiction")
    defanged = re.sub(
        r"\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\bdot\b)\s*",
        ".",
        normalized,
    )
    compact = re.sub(r"[\s\[\](){}<>:'\"`]+", "", normalized)
    if (
        _URL_SCHEME.search(normalized)
        or re.search(r"(?:https?|ftp)\s*:\s*[\\/]\s*[\\/]", normalized)
        or re.search(r"(?:https?|ftp):[\\/]{2}", compact)
        or _DOMAIN.search(defanged)
        or _contains_ip(normalized)
        or "localhost" in normalized
        or _RAW_OR_CURATED_PATH.search(normalized)
        or _RAW_OR_CURATED_RECORD.search(normalized)
        or _MEDIA_OR_EXECUTABLE.search(normalized)
        or _SECRET_ASSIGNMENT.search(normalized)
        or _SECRET_TOKEN.search(normalized)
        or _PHONE_NUMBER.search(normalized)
    ):
        raise TrendExchangeError("restricted_exchange_content")


def _assert_safe_content(value: object) -> None:
    if isinstance(value, str):
        _assert_safe_text(value)
    elif value is None or type(value) in (bool, int, float):
        return
    elif isinstance(value, list):
        for item in value:
            _assert_safe_content(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _assert_safe_text(key)
            _assert_safe_content(item)
    else:
        raise TrendExchangeError("unsupported_exchange_content")


def _directory_names(path: Path) -> frozenset[str]:
    try:
        return frozenset(item.name for item in path.iterdir())
    except OSError as error:
        raise TrendExchangeError("source_directory_invalid") from error


def _verify_snapshot(source: Path, expected_manifest_sha256: str) -> _VerifiedSnapshot:
    if not isinstance(expected_manifest_sha256, str) or _SHA256.fullmatch(
        expected_manifest_sha256
    ) is None:
        raise TrendExchangeError("expected_manifest_anchor_invalid")
    source = _validate_local_absolute_path(Path(source), "source_path_invalid")
    directory_identity = _assert_safe_directory(source, "source_directory_invalid")
    if _directory_names(source) != _EXPECTED_FILES:
        raise TrendExchangeError("source_file_set_invalid")
    files = {name: _read_regular_file(source / name) for name in _EXPECTED_FILES}
    manifest_snapshot = files["bundle-manifest.json"]
    manifest_sha256 = hashlib.sha256(manifest_snapshot.payload).hexdigest()
    if manifest_sha256 != expected_manifest_sha256:
        raise TrendExchangeError("manifest_anchor_mismatch")
    manifest = _validate_manifest(_load_json(manifest_snapshot.payload))
    for binding in manifest["files"]:
        name = binding["relative_path"]
        payload = files[name].payload
        if len(payload) != binding["bytes"] or hashlib.sha256(payload).hexdigest() != binding["sha256"]:
            raise TrendExchangeError("payload_binding_mismatch")
    candidates = _validate_candidates(_load_json(files["top10.json"].payload))
    summary = _validate_summary(
        _load_json(files["evidence-summary.json"].payload), manifest["batch_id"], candidates
    )
    _assert_safe_content(manifest)
    _assert_safe_content(candidates)
    _assert_safe_content(summary)
    if _directory_names(source) != _EXPECTED_FILES:
        raise TrendExchangeError("source_file_set_changed")
    if _assert_safe_directory(source, "source_directory_invalid") != directory_identity:
        raise TrendExchangeError("source_directory_changed")
    for name, snapshot in files.items():
        current = _read_regular_file(source / name)
        if current != snapshot:
            raise TrendExchangeError("source_file_changed")
    return _VerifiedSnapshot(
        result=VerifiedTrendExchange(
            source=source,
            batch_id=manifest["batch_id"],
            version="v01",
            manifest_sha256=manifest_sha256,
            candidate_count=manifest["candidate_count"],
        ),
        files=files,
    )


def verify_trend_exchange(
    source: Path, expected_manifest_sha256: str
) -> VerifiedTrendExchange:
    """Verify an Approved three-file bundle against an operator-supplied anchor."""

    return _verify_snapshot(source, expected_manifest_sha256).result


def _ensure_destination_parent(repo_root: Path, batch_id: str) -> Path:
    root = _validate_local_absolute_path(repo_root, "destination_path_invalid")
    _assert_safe_directory(root, "destination_boundary_invalid")
    if _BATCH_ID.fullmatch(batch_id) is None:
        raise TrendExchangeError("destination_batch_invalid")
    parent = root
    for name in ("09_泛健康日更", "data", "trend-intelligence", batch_id):
        parent_identity = _assert_safe_directory(parent, "destination_boundary_invalid")
        child = parent / name
        try:
            child.mkdir()
        except FileExistsError:
            pass
        except OSError as error:
            raise TrendExchangeError("destination_create_failed") from error
        if _assert_safe_directory(parent, "destination_boundary_invalid") != parent_identity:
            raise TrendExchangeError("destination_boundary_changed")
        _assert_safe_directory(child, "destination_boundary_invalid")
        try:
            if os.path.commonpath((os.fspath(root), os.fspath(child))) != os.fspath(root):
                raise TrendExchangeError("destination_escape")
        except ValueError as error:
            raise TrendExchangeError("destination_escape") from error
        parent = child
    return parent


def _exclusive_write(path: Path, payload: bytes) -> None:
    try:
        with path.open("xb") as handle:
            opened_before = os.fstat(handle.fileno())
            if _is_reparse(opened_before) or not stat.S_ISREG(opened_before.st_mode):
                raise TrendExchangeError("destination_file_invalid")
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            opened_after = os.fstat(handle.fileno())
        path_after = path.lstat()
    except FileExistsError:
        raise
    except TrendExchangeError:
        raise
    except OSError as error:
        raise TrendExchangeError("destination_write_failed") from error
    if (
        not (
            _directory_identity(opened_before)
            == _directory_identity(opened_after)
            == _directory_identity(path_after)
        )
        or _identity(opened_after) != _identity(path_after)
        or opened_after.st_size != len(payload)
    ):
        raise TrendExchangeError("destination_file_changed")


def _cleanup_owned_exchange_directory(
    path: Path, expected_identity: tuple[int, int]
) -> None:
    if not os.path.lexists(path):
        return
    try:
        if (
            _assert_safe_directory(path, "transaction_cleanup_failed")
            != expected_identity
        ):
            raise TrendExchangeError("transaction_cleanup_failed")
        names = frozenset(item.name for item in path.iterdir())
        if not names <= _EXPECTED_FILES:
            raise TrendExchangeError("transaction_cleanup_failed")
        for name in names:
            status = (path / name).lstat()
            if (
                _is_reparse(status)
                or stat.S_ISLNK(status.st_mode)
                or not stat.S_ISREG(status.st_mode)
            ):
                raise TrendExchangeError("transaction_cleanup_failed")
        for name in ("bundle-manifest.json", *_PAYLOAD_FILES):
            candidate = path / name
            if os.path.lexists(candidate):
                if (
                    _assert_safe_directory(path, "transaction_cleanup_failed")
                    != expected_identity
                ):
                    raise TrendExchangeError("transaction_cleanup_failed")
                candidate.unlink()
        if (
            _assert_safe_directory(path, "transaction_cleanup_failed")
            != expected_identity
        ):
            raise TrendExchangeError("transaction_cleanup_failed")
        path.rmdir()
    except TrendExchangeError:
        raise
    except OSError as error:
        raise TrendExchangeError("transaction_cleanup_failed") from error


def _assert_same_source_snapshot(
    source: Path, anchor: str, expected: _VerifiedSnapshot
) -> _VerifiedSnapshot:
    current = _verify_snapshot(source, anchor)
    if current.files != expected.files or current.result != expected.result:
        raise TrendExchangeError("source_changed_during_import")
    return current


def import_trend_exchange(
    source: Path,
    repo_root: Path,
    expected_manifest_sha256: str,
) -> Path:
    """Copy one verified bundle to its sole versioned repository destination."""

    source_snapshot = _verify_snapshot(source, expected_manifest_sha256)
    destination_parent = _ensure_destination_parent(
        Path(repo_root), source_snapshot.result.batch_id
    )
    target = destination_parent / "v01"
    if os.path.lexists(target):
        raise FileExistsError("destination_exists")
    parent_identity = _assert_safe_directory(
        destination_parent, "destination_boundary_invalid"
    )
    try:
        staging = Path(
            tempfile.mkdtemp(prefix=".v01-import-", dir=destination_parent)
        )
    except OSError as error:
        raise TrendExchangeError("destination_create_failed") from error
    if (
        _assert_safe_directory(destination_parent, "destination_boundary_invalid")
        != parent_identity
    ):
        raise TrendExchangeError("destination_boundary_changed")
    staging_identity = _assert_safe_directory(
        staging, "destination_boundary_invalid"
    )
    published = False
    try:
        for name in _PAYLOAD_FILES:
            current = _read_regular_file(source_snapshot.result.source / name)
            if current != source_snapshot.files[name]:
                raise TrendExchangeError("source_changed_during_import")
            _exclusive_write(staging / name, current.payload)
            if (
                _assert_safe_directory(staging, "destination_boundary_invalid")
                != staging_identity
            ):
                raise TrendExchangeError("destination_boundary_changed")
        _assert_same_source_snapshot(
            source_snapshot.result.source, expected_manifest_sha256, source_snapshot
        )
        manifest = source_snapshot.files["bundle-manifest.json"].payload
        _exclusive_write(staging / "bundle-manifest.json", manifest)
        if (
            _assert_safe_directory(staging, "destination_boundary_invalid")
            != staging_identity
        ):
            raise TrendExchangeError("destination_boundary_changed")
        staging_snapshot = _verify_snapshot(staging, expected_manifest_sha256)
        if any(
            staging_snapshot.files[name].payload
            != source_snapshot.files[name].payload
            for name in _EXPECTED_FILES
        ):
            raise TrendExchangeError("destination_bytes_mismatch")
        _assert_same_source_snapshot(
            source_snapshot.result.source, expected_manifest_sha256, source_snapshot
        )
        if os.path.lexists(target):
            raise FileExistsError("destination_exists")
        if (
            _assert_safe_directory(destination_parent, "destination_boundary_invalid")
            != parent_identity
        ):
            raise TrendExchangeError("destination_boundary_changed")
        try:
            staging.rename(target)
        except FileExistsError:
            raise
        except OSError as error:
            if os.path.lexists(target):
                raise FileExistsError("destination_exists") from error
            raise TrendExchangeError("destination_publish_failed") from error
        published = True
        if (
            _assert_safe_directory(target, "destination_boundary_invalid")
            != staging_identity
        ):
            raise TrendExchangeError("destination_boundary_changed")
        _assert_same_source_snapshot(
            source_snapshot.result.source, expected_manifest_sha256, source_snapshot
        )
        target_snapshot = _verify_snapshot(target, expected_manifest_sha256)
        if any(
            target_snapshot.files[name].payload != source_snapshot.files[name].payload
            for name in _EXPECTED_FILES
        ):
            raise TrendExchangeError("destination_bytes_mismatch")
        return target
    except BaseException:
        if not published and os.path.lexists(target):
            try:
                published = (
                    _assert_safe_directory(target, "transaction_cleanup_failed")
                    == staging_identity
                )
            except TrendExchangeError:
                published = False
        cleanup_path = target if published else staging
        _cleanup_owned_exchange_directory(cleanup_path, staging_identity)
        raise
