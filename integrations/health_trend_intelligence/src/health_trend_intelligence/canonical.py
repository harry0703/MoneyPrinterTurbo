"""Deterministic UTF-8 JSON encoders and strict JSON loading."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from typing import Any, TypeVar

T = TypeVar("T")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def load_unique_json(payload: bytes) -> Any:
    """Load UTF-8 JSON while rejecting duplicate keys and non-finite numbers."""

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("JSON must be UTF-8") from error
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_nonfinite)
    except json.JSONDecodeError as error:
        raise ValueError("invalid JSON") from error


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON cannot encode NaN or Infinity")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise ValueError(f"duplicate JSON key after NFC normalization: {normalized_key}")
            normalized[normalized_key] = _normalize(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Return compact, sorted, NFC-normalized UTF-8 JSON followed by one LF."""

    normalized = _normalize(value)
    try:
        encoded = json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("value is not canonical JSON") from error
    return encoded.encode("utf-8") + b"\n"


def canonical_jsonl_bytes(records: Iterable[T], *, stable_key: Callable[[T], Any]) -> bytes:
    """Return records ordered by a caller-provided stable key, one JSON object per line."""

    ordered_records = sorted(records, key=stable_key)
    if any(not isinstance(record, Mapping) for record in ordered_records):
        raise ValueError("JSONL records must be objects")
    return b"".join(canonical_json_bytes(record) for record in ordered_records)


def sha256_bytes(payload: bytes) -> str:
    """Return the lowercase SHA-256 digest of exact input bytes."""

    return hashlib.sha256(payload).hexdigest()
