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
_HORIZONTAL_SPACE = r"[^\S\r\n]*"
_EMAIL = re.compile(
    rf"(?<![\w.+-])[A-Z0-9_%+-]+"
    rf"(?:{_HORIZONTAL_SPACE}\.{_HORIZONTAL_SPACE}[A-Z0-9_%+-]+)*"
    rf"{_HORIZONTAL_SPACE}@{_HORIZONTAL_SPACE}[A-Z0-9-]+"
    rf"(?:{_HORIZONTAL_SPACE}\.{_HORIZONTAL_SPACE}[A-Z0-9-]+)+(?![\w.-])",
    re.IGNORECASE,
)
_PHONE = re.compile(r"(?<!\d)(?:\+?86[\s-]*)?1[3-9](?:[\s-]*\d){9}(?!\d)")
_URL_STOP = r"\s" + re.escape(",;!?，。；！？、()（）[]{}<>《》【】\"'“”‘’")
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
_HANDLE = re.compile(r"(?<!@)@[\w](?:[\w.-]{0,29}[\w])(?![\w.-])")
_BEARER = re.compile(r"\bbearer\s+[A-Za-z0-9._~+/-]{12,}\b", re.IGNORECASE)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")
_API_KEY = re.compile(r"\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{12,}\b", re.IGNORECASE)
_HEX_KEY = re.compile(r"[0-9A-Fa-f]+\Z")
_SAFE_FIELD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

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


def _stable_sort_token(value: object) -> bytes:
    """Return an internal deterministic token without rendering values in errors."""

    if value is None:
        return b"none"
    if isinstance(value, bool):
        return b"bool:" + str(value).encode("ascii")
    if isinstance(value, str):
        return b"str:" + unicodedata.normalize("NFKC", value).encode("utf-8")
    if isinstance(value, bytes):
        return b"bytes:" + value
    if isinstance(value, int):
        return b"int:" + str(value).encode("ascii")
    if isinstance(value, float):
        return b"float:" + value.hex().encode("ascii")
    if isinstance(value, (date, datetime)):
        return b"date:" + value.isoformat().encode("ascii")
    if isinstance(value, tuple):
        return b"tuple:" + b"\0".join(_stable_sort_token(item) for item in value)
    if isinstance(value, frozenset):
        return b"frozenset:" + b"\0".join(sorted(_stable_sort_token(item) for item in value))
    if isinstance(value, BaseModel):
        parts = []
        for name in type(value).model_fields:
            parts.append(name.encode("utf-8") + b"=" + _stable_sort_token(getattr(value, name)))
        return b"model:" + b"\0".join(parts)
    if is_dataclass(value) and not isinstance(value, type):
        parts = [
            field.name.encode("utf-8") + b"=" + _stable_sort_token(getattr(value, field.name))
            for field in fields(value)
        ]
        return b"dataclass:" + b"\0".join(parts)
    type_name = f"{type(value).__module__}.{type(value).__qualname__}"
    return b"unsupported:" + type_name.encode("utf-8")


def assert_no_sensitive_data(payload: object) -> None:
    """Recursively reject raw identity fields and credential-shaped values."""

    visited: set[int] = set()

    def fail(path: str, reason: str) -> None:
        raise SensitiveDataError(f"sensitive data at {path}: {reason}")

    def text_reason(value: str) -> str | None:
        normalized = unicodedata.normalize("NFKC", value)
        if _BEARER.search(normalized) or _JWT.search(normalized) or _API_KEY.search(normalized):
            return "credential-shaped value"
        if redact_text(normalized).contains_personal_data:
            return "personal-data-shaped value"
        return None

    def check_name(name: str, path: str) -> None:
        normalized = unicodedata.normalize("NFKC", name).strip()
        if normalized.casefold() in _FORBIDDEN_KEYS:
            fail(path, "forbidden key")
        reason = text_reason(normalized)
        if reason is not None:
            fail(path, reason.removesuffix(" value") + " key")

    def model_field_path(parent: str, name: str, index: int) -> str:
        if _SAFE_FIELD_NAME.fullmatch(name):
            return f"{parent}.{name}"
        return f"{parent}.<field:{index}>"

    def check_mapping_collisions(value: dict[object, object], path: str) -> None:
        nfc_names: set[str] = set()
        nfkc_names: set[str] = set()
        for key in value:
            if not isinstance(key, str):
                continue
            nfc_name = unicodedata.normalize("NFC", key).strip()
            nfkc_name = unicodedata.normalize("NFKC", key).strip().casefold()
            if nfc_name in nfc_names or nfkc_name in nfkc_names:
                fail(path, "normalized key collision")
            nfc_names.add(nfc_name)
            nfkc_names.add(nfkc_name)

    def scan(value: object, path: str) -> None:
        if isinstance(value, str):
            reason = text_reason(value)
            if reason is not None:
                fail(path, reason)
            return
        if value is None or isinstance(value, (bool, int, float, bytes, date, datetime)):
            return

        identity = id(value)
        if identity in visited:
            return
        visited.add(identity)

        if isinstance(value, BaseModel):
            for index, (name, field_info) in enumerate(type(value).model_fields.items()):
                safe_path = model_field_path(path, name, index)
                check_name(name, f"{path}.<field:{index}>")
                if isinstance(field_info.alias, str) and field_info.alias != name:
                    check_name(field_info.alias, f"{path}.<field:{index}>")
                scan(getattr(value, name), safe_path)
            return
        if is_dataclass(value) and not isinstance(value, type):
            for index, field in enumerate(fields(value)):
                safe_path = model_field_path(path, field.name, index)
                check_name(field.name, f"{path}.<field:{index}>")
                scan(getattr(value, field.name), safe_path)
            return
        if isinstance(value, dict):
            check_mapping_collisions(value, path)
            ordered_items = sorted(value.items(), key=lambda pair: _stable_sort_token(pair[0]))
            for index, (key, item) in enumerate(ordered_items):
                safe_path = f"{path}[{index}]"
                if not isinstance(key, str):
                    fail(safe_path, "non-text mapping key")
                check_name(key, safe_path)
                scan(item, safe_path)
            return
        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                scan(item, f"{path}[{index}]")
            return
        if isinstance(value, (set, frozenset)):
            for index, item in enumerate(sorted(value, key=_stable_sort_token)):
                scan(item, f"{path}[{index}]")
            return
        fail(path, "unsupported recursive value type")

    scan(payload, "$")
