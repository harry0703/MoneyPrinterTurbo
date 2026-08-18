from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from health_trend_intelligence.privacy import (
    PrivacyConfigurationError,
    PrivacyHasher,
    SensitiveDataError,
    assert_no_sensitive_data,
    redact_text,
)


def test_identifier_uses_stable_domain_separated_hmac_sha256() -> None:
    key = b"test-key"
    hasher = PrivacyHasher(key)

    expected = hmac.new(key, b"author\0same", hashlib.sha256).hexdigest()
    assert hasher.identifier("same") == expected
    assert hasher.identifier("same") == PrivacyHasher(key).identifier("same")
    assert hasher.identifier("same", domain="author") != hasher.identifier(
        "same", domain="comment"
    )
    assert hasher.identifier("same", domain="comment") != hasher.identifier(
        "same", domain="post"
    )
    assert hasher.identifier("same") != PrivacyHasher(b"different-key").identifier("same")


@pytest.mark.parametrize("value", ["", "   "])
def test_identifier_rejects_empty_identifiers_without_echoing_them(value: str) -> None:
    with pytest.raises(ValueError, match="identifier must not be empty") as caught:
        PrivacyHasher(b"test-key").identifier(value)
    assert value not in str(caught.value) or not value


def test_hasher_repr_never_contains_key_material() -> None:
    secret = b"synthetic-key-material-that-must-not-appear"
    rendered = repr(PrivacyHasher(secret))

    assert secret.decode("ascii") not in rendered
    assert "PrivacyHasher" in rendered


@pytest.mark.parametrize("prefix", ["base64", "hex"])
def test_hash_key_environment_accepts_only_explicit_32_byte_encodings(
    monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    key = bytes(range(32))
    encoded = base64.b64encode(key).decode("ascii") if prefix == "base64" else key.hex()
    monkeypatch.setenv("HTI_HASH_KEY", f"{prefix}:{encoded}")

    assert PrivacyHasher.from_environment().identifier("stable") == PrivacyHasher(key).identifier(
        "stable"
    )


def test_missing_hash_key_fails_without_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HTI_HASH_KEY", raising=False)

    with pytest.raises(PrivacyConfigurationError, match="HTI_HASH_KEY is required"):
        PrivacyHasher.from_environment()


@pytest.mark.parametrize(
    "configured",
    [
        "",
        "raw:abcdefghijklmnopqrstuvwxyz012345",
        "base64:@@not-base64@@",
        "base64:5pel5pys6Kqe",
        "hex:not-hex",
        "hex:00ff",
        "ｈｅｘ：" + "00" * 32,
    ],
)
def test_hash_key_environment_rejects_empty_short_invalid_and_unicode_values(
    monkeypatch: pytest.MonkeyPatch, configured: str
) -> None:
    monkeypatch.setenv("HTI_HASH_KEY", configured)

    with pytest.raises(PrivacyConfigurationError) as caught:
        PrivacyHasher.from_environment()

    if configured:
        assert configured not in str(caught.value)


def test_redaction_covers_unicode_whitespace_and_records_audit_kinds() -> None:
    result = redact_text(
        "  电话 １３８\u3000００１３ ８０００；邮箱 Person＠Example．invalid；"
        "微 信 号： synthetic_wx-01；＠synthetic_handle；"
        "https://example.invalid/path?token=secret#fragment  "
    )

    assert result.contains_personal_data is True
    assert result.redaction_kinds == ("email", "handle", "phone", "url", "wechat")
    assert "138" not in result.text_redacted
    assert "Person" not in result.text_redacted
    assert "synthetic_wx" not in result.text_redacted
    assert "synthetic_handle" not in result.text_redacted
    assert "token=" not in result.text_redacted
    assert "#fragment" not in result.text_redacted
    assert "https://example.invalid/path" in result.text_redacted
    assert "  " not in result.text_redacted
    assert not hasattr(result, "original_text")


def test_redaction_leaves_clean_normalized_text_auditable() -> None:
    result = redact_text("  合成的 睡眠\u3000经验  ")

    assert result.text_redacted == "合成的 睡眠 经验"
    assert result.contains_personal_data is False
    assert result.redaction_kinds == ()


@dataclass(frozen=True)
class NestedDataclass:
    values: tuple[dict[str, str], ...]


class NestedModel(BaseModel):
    payload: object


@pytest.mark.parametrize(
    ("payload", "safe_path"),
    [
        ({"outer": [{"ｘｓｅｃ＿ｔｏｋｅｎ": "hidden"}]}, "$['outer'][0]"),
        ({"outer": [{" USER_ID ": "hidden"}]}, "$['outer'][0]"),
        (NestedDataclass(({"nickname": "hidden"},)), "$.values[0]"),
        (NestedModel(payload={"safe": "Bearer synthetic-credential-123456"}), "$.payload['safe']"),
        ({"safe": "https://example.invalid/path?access_token=hidden"}, "$['safe']"),
        ({"safe": "eyJhbGciOiJIUzI1NiJ9.c3ludGhldGlj.c2lnbmF0dXJl"}, "$['safe']"),
    ],
)
def test_sensitive_scanner_recurses_and_reports_only_safe_path_and_reason(
    payload: object, safe_path: str
) -> None:
    with pytest.raises(SensitiveDataError) as caught:
        assert_no_sensitive_data(payload)

    message = str(caught.value)
    assert safe_path in message
    for forbidden_value in (
        "hidden",
        "synthetic-credential-123456",
        "access_token=hidden",
        "eyJhbGciOiJIUzI1NiJ9",
    ):
        assert forbidden_value not in message


def test_sensitive_scanner_accepts_curated_shapes_and_sha256_values() -> None:
    assert_no_sensitive_data(
        {
            "source_post_key": "a" * 64,
            "author_key_hash": "b" * 64,
            "query_ids": ("dy-sleep-v1",),
            "topic_terms": ["睡眠", "健康科普"],
            "source_url_restricted": "https://www.douyin.com/video/dy-synthetic-001",
        }
    )
