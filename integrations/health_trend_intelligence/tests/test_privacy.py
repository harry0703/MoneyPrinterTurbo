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


def test_redaction_removes_unicode_handle_and_only_locally_deobfuscates_email() -> None:
    result = redact_text(
        "前文 联系＠张三；邮箱 Person . alias ＠ Example . invalid；普通 A B 保持分开"
    )

    assert result.contains_personal_data is True
    assert result.redaction_kinds == ("email", "handle")
    assert result.text_redacted == (
        "前文 联系[REDACTED_HANDLE];邮箱 [REDACTED_EMAIL];普通 A B 保持分开"
    )
    assert "张三" not in result.text_redacted
    assert "Person" not in result.text_redacted
    assert "A B" in result.text_redacted


@pytest.mark.parametrize(
    "boundary",
    ["，", "；", "！", "？", ",", ";", "!", "?", "（", "(", "“", '"', "\n"],
)
def test_url_redaction_stops_at_normalized_prose_boundaries_and_preserves_path(
    boundary: str,
) -> None:
    result = redact_text(
        f"前 https://example.invalid/a%2Fb/path?token=synthetic-secret#part{boundary}后文保留"
    )

    assert result.contains_personal_data is True
    assert result.redaction_kinds == ("url",)
    assert "https://example.invalid/a%2Fb/path" in result.text_redacted
    assert "synthetic-secret" not in result.text_redacted
    assert "#part" not in result.text_redacted
    assert "后文保留" in result.text_redacted


@dataclass(frozen=True)
class NestedDataclass:
    values: tuple[dict[str, str], ...]


class NestedModel(BaseModel):
    payload: object


@dataclass(frozen=True)
class SensitiveFieldDataclass:
    user_id: str


class SensitiveFieldModel(BaseModel):
    user_id: str


@pytest.mark.parametrize(
    ("payload", "safe_path"),
    [
        ({"outer": [{"ｘｓｅｃ＿ｔｏｋｅｎ": "hidden"}]}, "$[0][0][0]"),
        ({"outer": [{" USER_ID ": "hidden"}]}, "$[0][0][0]"),
        (NestedDataclass(({"nickname": "hidden"},)), "$.values[0][0]"),
        (NestedModel(payload={"safe": "Bearer synthetic-credential-123456"}), "$.payload[0]"),
        ({"safe": "https://example.invalid/path?access_token=hidden"}, "$[0]"),
        ({"safe": "eyJhbGciOiJIUzI1NiJ9.c3ludGhldGlj.c2lnbmF0dXJl"}, "$[0]"),
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


@pytest.mark.parametrize(
    ("secret_key", "safe_value"),
    [
        ("Bearer synthetic-mapping-secret-123456", "clean"),
        ("Person ＠ Example . invalid", "clean"),
        ("Bearer synthetic-mapping-secret-123456", "Person ＠ Example . invalid"),
    ],
)
def test_sensitive_mapping_keys_fail_before_values_without_echoing_or_logging(
    secret_key: str,
    safe_value: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(SensitiveDataError) as caught:
        assert_no_sensitive_data({secret_key: safe_value})

    rendered = f"{caught.value!s}\n{caught.value!r}\n{caplog.text}"
    assert "$[0]" in rendered
    assert "key" in rendered
    for secret_part in ("synthetic-mapping-secret-123456", "Person", "Example"):
        assert secret_part not in rendered


@pytest.mark.parametrize(
    "payload",
    [
        {"e\u0301": "first", "é": "second"},
        {"Ａ": "first", "a": "second"},
    ],
)
def test_mapping_key_normalization_collisions_fail_closed_without_key_echo(
    payload: dict[str, str],
) -> None:
    with pytest.raises(SensitiveDataError, match="normalized key collision") as caught:
        assert_no_sensitive_data(payload)

    message = str(caught.value)
    assert message == "sensitive data at $: normalized key collision"
    assert "first" not in message
    assert "second" not in message


@pytest.mark.parametrize(
    "payload",
    [
        {"safe": "clean"},
        ["clean"],
        ("clean",),
        {"clean", "also-clean"},
        frozenset({"clean", "also-clean"}),
        NestedModel(payload="clean"),
        NestedDataclass(({"safe": "clean"},)),
    ],
)
def test_sensitive_scanner_accepts_all_declared_recursive_container_types(payload: object) -> None:
    assert_no_sensitive_data(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"safe": "Bearer synthetic-container-secret-123456"},
        ["Bearer synthetic-container-secret-123456"],
        ("Bearer synthetic-container-secret-123456",),
        {"clean", "Bearer synthetic-container-secret-123456"},
        frozenset({"clean", "Bearer synthetic-container-secret-123456"}),
        NestedModel(payload="Bearer synthetic-container-secret-123456"),
        NestedDataclass(({"safe": "Bearer synthetic-container-secret-123456"},)),
    ],
)
def test_sensitive_scanner_recurses_stably_without_element_repr(payload: object) -> None:
    messages: set[str] = set()
    for _ in range(10):
        with pytest.raises(SensitiveDataError, match="credential-shaped value") as caught:
            assert_no_sensitive_data(payload)
        messages.add(str(caught.value))

    assert len(messages) == 1
    message = messages.pop()
    assert "synthetic-container-secret-123456" not in message
    assert "Bearer" not in message


@pytest.mark.parametrize(
    "payload",
    [SensitiveFieldDataclass(user_id="clean"), SensitiveFieldModel(user_id="clean")],
)
def test_model_and_dataclass_field_names_use_same_forbidden_key_guard(payload: object) -> None:
    with pytest.raises(SensitiveDataError, match="forbidden key") as caught:
        assert_no_sensitive_data(payload)

    assert "clean" not in str(caught.value)
    assert "user_id" not in str(caught.value)


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
