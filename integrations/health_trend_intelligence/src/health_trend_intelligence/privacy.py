"""Privacy primitives for offline, already-registered snapshot data."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
import unicodedata
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

HashDomain = Literal["author", "comment", "post"]

_DOMAIN_PREFIXES: dict[HashDomain, bytes] = {
    "author": b"author\0",
    "comment": b"comment\0",
    "post": b"post\0",
}
_EMAIL = re.compile(
    r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])",
    re.IGNORECASE,
)
_PHONE = re.compile(r"(?<!\d)(?:\+?86[\s-]*)?1[3-9](?:[\s-]*\d){9}(?!\d)")
_URL_STOP = r"\s，。；、！？）》】\]"
_URL = re.compile(
    rf"(?P<base>https?://[^{_URL_STOP}?#]+)"
    rf"(?P<tail>(?:\?[^{_URL_STOP}#]*)?(?:#[^{_URL_STOP}]*)?)",
    re.IGNORECASE,
)
_WECHAT = re.compile(
    r"(?:微\s*信|[vV]\s*信|薇\s*信)\s*(?:号|id)?\s*[:：]?\s*"
    r"[A-Za-z][A-Za-z0-9_-]{5,31}",
    re.IGNORECASE,
)
_HANDLE = re.compile(r"(?<![\w@])@[A-Za-z0-9_][A-Za-z0-9_.-]{1,31}")
_BEARER = re.compile(r"\bbearer\s+[A-Za-z0-9._~+/-]{12,}\b", re.IGNORECASE)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")
_API_KEY = re.compile(r"\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{12,}\b", re.IGNORECASE)
_HEX_KEY = re.compile(r"[0-9A-Fa-f]+\Z")

_FORBIDDEN_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "avatar",
        "cookie",
        "creator_hash",
        "email",
        "image_list",
        "nickname",
        "open_id",
        "password",
        "phone",
        "raw_user_id",
        "refresh_token",
        "sec_uid",
        "session",
        "token",
        "user_id",
        "video_url",
        "wechat",
        "wxid",
        "xsec_token",
    }
)


class PrivacyConfigurationError(RuntimeError):
    """Raised for a missing or unsafe hashing-key configuration."""


class SensitiveDataError(ValueError):
    """Raised without echoing the sensitive value that caused rejection."""


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """Auditable redaction outcome that intentionally has no original-text field."""

    text_redacted: str
    contains_personal_data: bool
    redaction_kinds: tuple[str, ...]


class PrivacyHasher:
    """Keyed identifier hashing with fixed, separate HMAC domains."""

    __slots__ = ("_domain_bases",)

    def __init__(self, key: bytes) -> None:
        if not isinstance(key, bytes) or not key:
            raise ValueError("hash key must be non-empty bytes")
        self._domain_bases = {
            domain: hmac.new(key, prefix, hashlib.sha256)
            for domain, prefix in _DOMAIN_PREFIXES.items()
        }

    @classmethod
    def from_environment(cls) -> PrivacyHasher:
        """Read only ``HTI_HASH_KEY`` using explicit base64 or hexadecimal encoding."""

        configured = os.environ.get("HTI_HASH_KEY")
        if configured is None:
            raise PrivacyConfigurationError("HTI_HASH_KEY is required")
        try:
            encoded = configured.encode("ascii")
        except UnicodeEncodeError as exc:
            raise PrivacyConfigurationError(
                "HTI_HASH_KEY must use ASCII base64: or hex: encoding"
            ) from exc
        if b":" not in encoded:
            raise PrivacyConfigurationError("HTI_HASH_KEY must use base64: or hex: encoding")
        format_name, payload = encoded.split(b":", 1)
        try:
            if format_name == b"base64":
                decoded = base64.b64decode(payload, validate=True)
            elif format_name == b"hex" and payload and _HEX_KEY.fullmatch(payload.decode("ascii")):
                decoded = bytes.fromhex(payload.decode("ascii"))
            else:
                raise ValueError
        except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
            raise PrivacyConfigurationError("HTI_HASH_KEY encoding is invalid") from exc
        if len(decoded) < 32:
            raise PrivacyConfigurationError("HTI_HASH_KEY must decode to at least 32 bytes")
        return cls(decoded)

    def identifier(self, value: str, *, domain: HashDomain = "author") -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("identifier must not be empty")
        if domain not in _DOMAIN_PREFIXES:
            raise ValueError("unsupported identifier domain")
        normalized = unicodedata.normalize("NFC", value.strip())
        digest = self._domain_bases[domain].copy()
        digest.update(normalized.encode("utf-8"))
        return digest.hexdigest()

    def __repr__(self) -> str:
        return "PrivacyHasher(<redacted>)"


def redact_text(text: str) -> RedactionResult:
    """Conservatively remove common direct-contact identifiers from text."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    redacted = unicodedata.normalize("NFKC", text)
    kinds: set[str] = set()

    def replace(pattern: re.Pattern[str], marker: str, kind: str) -> None:
        nonlocal redacted
        redacted, count = pattern.subn(marker, redacted)
        if count:
            kinds.add(kind)

    replace(_EMAIL, "[REDACTED_EMAIL]", "email")
    replace(_PHONE, "[REDACTED_PHONE]", "phone")

    def redact_url(match: re.Match[str]) -> str:
        tail = match.group("tail")
        if not tail:
            return match.group(0)
        kinds.add("url")
        return match.group("base")

    redacted = _URL.sub(redact_url, redacted)
    replace(_WECHAT, "[REDACTED_WECHAT]", "wechat")
    replace(_HANDLE, "[REDACTED_HANDLE]", "handle")
    redacted = re.sub(r"\s+", " ", redacted).strip()
    ordered_kinds = tuple(sorted(kinds))
    return RedactionResult(
        text_redacted=redacted,
        contains_personal_data=bool(ordered_kinds),
        redaction_kinds=ordered_kinds,
    )


def assert_no_sensitive_data(payload: object) -> None:
    """Recursively reject raw identity fields and credential-shaped values."""

    visited: set[int] = set()

    def fail(path: str, reason: str) -> None:
        raise SensitiveDataError(f"sensitive data at {path}: {reason}")

    def scan(value: object, path: str) -> None:
        if isinstance(value, str):
            normalized = unicodedata.normalize("NFKC", value)
            if _BEARER.search(normalized) or _JWT.search(normalized) or _API_KEY.search(normalized):
                fail(path, "credential-shaped value")
            if redact_text(normalized).contains_personal_data:
                fail(path, "personal-data-shaped value")
            return
        if value is None or isinstance(value, (bool, int, float, bytes, date, datetime)):
            return

        identity = id(value)
        if identity in visited:
            return
        visited.add(identity)

        if isinstance(value, BaseModel):
            for name in type(value).model_fields:
                scan(getattr(value, name), f"{path}.{name}")
            return
        if is_dataclass(value) and not isinstance(value, type):
            for field in fields(value):
                scan(getattr(value, field.name), f"{path}.{field.name}")
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    fail(path, "non-text mapping key")
                normalized_key = unicodedata.normalize("NFKC", key).strip().casefold()
                if normalized_key in _FORBIDDEN_KEYS:
                    fail(path, "forbidden key")
                scan(item, f"{path}[{key!r}]")
            return
        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                scan(item, f"{path}[{index}]")
            return
        fail(path, "unsupported recursive value type")

    scan(payload, "$")
