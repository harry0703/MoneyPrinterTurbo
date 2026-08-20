from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from health_trend_intelligence.batch import SourceSpec, register_batch
from health_trend_intelligence.canonical import canonical_json_bytes, load_unique_json
from health_trend_intelligence.cli import app
from health_trend_intelligence.curation import curate_batch
from health_trend_intelligence.exchange import (
    ApprovalRequired,
    ExchangeError,
    build_approved_exchange,
    verify_approved_exchange,
)
from health_trend_intelligence.models import ApprovedCandidate, ApprovedSelection
from health_trend_intelligence.privacy import PrivacyHasher
from health_trend_intelligence.storage import DataLayout

CHINA_TZ = timezone(timedelta(hours=8))
BATCH_ID = "HTI-20260818-01"
FIXTURE = Path(__file__).parent / "fixtures" / "approved-selection.json"
CANDIDATE_FIELDS = {
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


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_bytes(b"".join(canonical_json_bytes(record) for record in records))


def _curated_layout(root: Path) -> tuple[DataLayout, str]:
    layout = DataLayout.from_root(root)
    layout.initialize()
    staging = root / "synthetic"
    staging.mkdir()
    posts = staging / "dy_posts.jsonl"
    comments = staging / "dy_comments.jsonl"
    _write_jsonl(
        posts,
        [
            {
                "aweme_id": "synthetic-post",
                "title": "合成健康话题",
                "desc": "",
                "create_time": 1_776_398_400,
                "user_id": "synthetic-user",
                "source_keyword": "健康",
                "liked_count": 10,
                "comment_count": 1,
                "collected_count": 2,
                "share_count": 1,
                "hashtags": ["健康"],
            }
        ],
    )
    _write_jsonl(
        comments,
        [
            {
                "comment_id": "synthetic-comment",
                "aweme_id": "synthetic-post",
                "create_time": 1_776_402_000,
                "content": "这是合成问题",
                "like_count": 1,
            }
        ],
    )
    register_batch(
        layout,
        BATCH_ID,
        [
            {
                "query_id": "dy-health-v1",
                "platform": "dy",
                "keyword": "健康",
                "window_start": "2026-04-01T00:00:00+08:00",
                "window_end": "2026-04-30T23:59:59+08:00",
            }
        ],
        [SourceSpec(posts, "dy", "posts"), SourceSpec(comments, "dy", "comments")],
        datetime(2026, 4, 20, 12, tzinfo=CHINA_TZ),
    )
    curated = curate_batch(layout, BATCH_ID, PrivacyHasher(b"synthetic-test-key"))
    return layout, curated.manifest_sha256


def _selection_path(
    root: Path, curated_manifest_sha256: str, *, status: str = "approved"
) -> Path:
    value = load_unique_json(FIXTURE.read_bytes())
    value["curated_manifest_sha256"] = curated_manifest_sha256
    value["human_selection_status"] = status
    path = root / "selection.json"
    path.write_bytes(canonical_json_bytes(value))
    return path


def _selection_value(curated_manifest_sha256: str) -> dict[str, object]:
    value = load_unique_json(FIXTURE.read_bytes())
    value["curated_manifest_sha256"] = curated_manifest_sha256
    return value


def _write_selection(root: Path, value: dict[str, object], name: str = "selection.json") -> Path:
    path = root / name
    path.write_bytes(canonical_json_bytes(value))
    return path


def _rebind_payload(result, name: str, value: object) -> None:
    payload = canonical_json_bytes(value)
    (result.path / name).write_bytes(payload)
    manifest_path = result.path / "bundle-manifest.json"
    manifest = load_unique_json(manifest_path.read_bytes())
    for binding in manifest["files"]:
        if binding["relative_path"] == name:
            binding["bytes"] = len(payload)
            binding["sha256"] = hashlib.sha256(payload).hexdigest()
    manifest_path.write_bytes(canonical_json_bytes(manifest))


def _build_valid_exchange(root: Path):
    layout, manifest_sha256 = _curated_layout(root)
    selection = _selection_path(root, manifest_sha256)
    return build_approved_exchange(layout, BATCH_ID, selection)


def test_pending_selection_cannot_create_approved_directory(tmp_path: Path) -> None:
    root = tmp_path / "root"
    layout, manifest_sha256 = _curated_layout(root)
    selection = _selection_path(root, manifest_sha256, status="pending")

    with pytest.raises(ApprovalRequired):
        build_approved_exchange(layout, BATCH_ID, selection)

    assert not (root / "approved" / BATCH_ID).exists()


def test_approved_bundle_has_exact_files_and_no_restricted_data(tmp_path: Path) -> None:
    result = _build_valid_exchange(tmp_path / "root")

    assert sorted(path.name for path in result.path.iterdir()) == [
        "bundle-manifest.json",
        "evidence-summary.json",
        "top10.json",
    ]
    tree = b"".join(path.read_bytes() for path in result.path.iterdir() if path.is_file())
    for forbidden in (b"source_url_restricted", b"xsec_token", b"nickname", b"avatar", b"cookie"):
        assert forbidden not in tree.lower()


def test_models_are_strict_frozen_and_enforce_selection_invariants() -> None:
    value = _selection_value("a" * 64)
    selection = ApprovedSelection.model_validate_json(canonical_json_bytes(value))

    assert selection.model_config["extra"] == "forbid"
    assert selection.model_config["strict"] is True
    assert selection.model_config["frozen"] is True
    assert ApprovedCandidate.model_fields.keys() == CANDIDATE_FIELDS
    with pytest.raises(ValidationError):
        selection.batch_id = BATCH_ID
    with pytest.raises(ValidationError):
        ApprovedSelection.model_validate_json(
            canonical_json_bytes({**value, "unexpected": "field"})
        )
    with pytest.raises(ValidationError):
        ApprovedSelection.model_validate_json(
            canonical_json_bytes({**value, "candidates": value["candidates"][:-1]})
        )


@pytest.mark.parametrize("mutation", ["rank", "topic", "platform", "coverage"])
def test_selection_rejects_duplicate_or_incomplete_coverage(mutation: str) -> None:
    value = _selection_value("b" * 64)
    candidates = value["candidates"]
    assert isinstance(candidates, list)
    if mutation == "rank":
        candidates[1]["rank"] = 1
    elif mutation == "topic":
        candidates[1]["topic"] = "ｈｅｌｌｏ"
        candidates[0]["topic"] = "hello"
    elif mutation == "platform":
        candidates[0]["platform_rank_evidence"] = {}
    else:
        for candidate in candidates:
            candidate["platform_rank_evidence"] = {"dy": "合成排名区间"}

    with pytest.raises(ValidationError):
        ApprovedSelection.model_validate_json(canonical_json_bytes(value))


@pytest.mark.parametrize(
    ("field", "unsafe"),
    [
        ("growth_evidence", "h t t p s : / / example dot com / source"),
        ("growth_evidence", "h\u200bt\u200bt\u200bp\u200bs://10.0.0.1/source"),
        ("growth_evidence", "example [dot] com / source"),
        ("growth_evidence", "ftp://10.0.0.1/source"),
        ("growth_evidence", "example.dev/source"),
        ("growth_evidence", "httрs://example。com/source"),
        ("growth_evidence", "xsec＿token=supersecret"),
        ("growth_evidence", "access-token=supersecret"),
        ("growth_evidence", "coo\u2028kie=value"),
        ("growth_evidence", "me＿dia=value"),
        ("growth_evidence", "custom-scheme:opaque-value"),
        ("growth_evidence", "javascript:opaque-payload"),
        ("growth_evidence", "vbscript:opaque-payload"),
        ("growth_evidence", "data:text/plain,synthetic-secret"),
        ("growth_evidence", "file:C:/synthetic-secret"),
        ("growth_evidence", "about:blank"),
        ("growth_evidence", "blob:synthetic-payload"),
        ("growth_evidence", "chrome:settings"),
        ("growth_evidence", "chrome-extension:synthetic-payload"),
        ("growth_evidence", "resource:synthetic-payload"),
        ("growth_evidence", "intent:synthetic-payload"),
        ("growth_evidence", "market:synthetic-payload"),
        ("growth_evidence", "ms-appx:synthetic-payload"),
        ("growth_evidence", "ms-appdata:synthetic-payload"),
        ("growth_evidence", "view-source:synthetic-payload"),
        ("growth_evidence", "tel:+15551234567"),
        ("growth_evidence", "custom+hti://synthetic-host/source"),
        ("growth_evidence", "custom+hti://[2001:db8::1]/source"),
        ("growth_evidence", "localhost"),
        ("growth_evidence", "raw_record synthetic excerpt"),
        ("growth_evidence", "payload.exe"),
        ("growth_evidence", "secret=synthetic-secret"),
        ("growth_evidence", "sk_abcdefghijkl"),
        ("growth_evidence", "例子.健康/source"),
        ("growth_evidence", "avatar value"),
        ("user_questions", r"raw\HTI-20260818-01\posts.jsonl"),
        ("risk_flags", "待核对 nickname 字段"),
        ("missing_data", "clip.mp4 素材待补"),
    ],
)
def test_builder_rejects_recursive_restricted_values_without_echo(
    tmp_path: Path, field: str, unsafe: str
) -> None:
    root = tmp_path / "root"
    layout, manifest_sha256 = _curated_layout(root)
    value = _selection_value(manifest_sha256)
    candidates = value["candidates"]
    assert isinstance(candidates, list)
    candidates[0][field] = [unsafe] if isinstance(candidates[0][field], list) else unsafe
    selection = _write_selection(root, value)

    with pytest.raises(ExchangeError) as captured:
        build_approved_exchange(layout, BATCH_ID, selection)

    assert unsafe not in str(captured.value)
    assert not (layout.approved / BATCH_ID).exists()


def test_invalid_or_noncanonical_selection_fails_before_destination_creation(tmp_path: Path) -> None:
    root = tmp_path / "root"
    layout, manifest_sha256 = _curated_layout(root)
    value = _selection_value(manifest_sha256)
    value["batch_id"] = "HTI-20260818-02"
    selection = _write_selection(root, value)

    with pytest.raises(ExchangeError):
        build_approved_exchange(layout, BATCH_ID, selection)
    assert not (layout.approved / BATCH_ID).exists()

    selection.write_text('{"schema":"health_trend_selection.v1", "schema":"duplicate"}')
    with pytest.raises(ExchangeError):
        build_approved_exchange(layout, BATCH_ID, selection)
    assert not (layout.approved / BATCH_ID).exists()


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("growth_evidence", []),
        ("user_questions", []),
        ("user_needs", []),
        ("misunderstandings", []),
        ("objections", []),
        ("growth_evidence", ["NaN"]),
        ("growth_evidence", ["Ｎ／Ａ"]),
        ("growth_evidence", ["N - A"]),
        ("growth_evidence", ["N.A."]),
        ("growth_evidence", ["not applicable"]),
        ("growth_evidence", [" null "]),
        ("growth_evidence", ["NONE"]),
        ("growth_evidence", ["unknown"]),
        ("growth_evidence", ["未知"]),
        ("growth_evidence", ["不详"]),
        ("growth_evidence", ["暂无"]),
    ],
)
def test_required_evidence_rejects_empty_or_missing_sentinels_before_publication(
    tmp_path: Path, field: str, invalid: list[str]
) -> None:
    root = tmp_path / "root"
    layout, manifest_sha256 = _curated_layout(root)
    value = _selection_value(manifest_sha256)
    candidates = value["candidates"]
    assert isinstance(candidates, list)
    candidates[0][field] = invalid

    with pytest.raises(ExchangeError):
        build_approved_exchange(layout, BATCH_ID, _write_selection(root, value))

    assert not (layout.approved / BATCH_ID).exists()


def test_platform_rank_evidence_rejects_missing_sentinel_before_publication(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    layout, manifest_sha256 = _curated_layout(root)
    value = _selection_value(manifest_sha256)
    candidates = value["candidates"]
    assert isinstance(candidates, list)
    candidates[0]["platform_rank_evidence"] = {"dy": "unknown"}

    with pytest.raises(ExchangeError):
        build_approved_exchange(layout, BATCH_ID, _write_selection(root, value))

    assert not (layout.approved / BATCH_ID).exists()


def test_payloads_are_canonical_allowlisted_and_summary_is_aggregate_only(tmp_path: Path) -> None:
    result = _build_valid_exchange(tmp_path / "root")
    top10_payload = (result.path / "top10.json").read_bytes()
    summary_payload = (result.path / "evidence-summary.json").read_bytes()
    manifest_payload = (result.path / "bundle-manifest.json").read_bytes()
    top10 = load_unique_json(top10_payload)
    summary = load_unique_json(summary_payload)
    manifest = load_unique_json(manifest_payload)

    assert canonical_json_bytes(top10) == top10_payload
    assert canonical_json_bytes(summary) == summary_payload
    assert canonical_json_bytes(manifest) == manifest_payload
    assert isinstance(top10, list)
    assert [candidate["rank"] for candidate in top10] == list(range(1, 11))
    assert all(set(candidate) == CANDIDATE_FIELDS for candidate in top10)
    assert summary == {
        "batch_id": BATCH_ID,
        "candidate_count": 10,
        "confidence_counts": {"high": 4, "low": 3, "medium": 3},
        "evidence_item_counts": {
            "growth_evidence": 10,
            "misunderstandings": 10,
            "objections": 10,
            "user_needs": 10,
            "user_questions": 10,
        },
        "missing_data_candidate_count": 1,
        "missing_data_item_count": 1,
        "platform_coverage": {"both": 3, "dy": 7, "xhs": 6},
        "risk_flag_item_count": 11,
        "risk_flagged_candidate_count": 10,
        "schema": "health_trend_evidence_summary.v1",
    }
    for candidate in top10:
        for source_text in candidate["user_questions"] + candidate["growth_evidence"]:
            assert source_text not in summary_payload.decode("utf-8")
    assert manifest["generated_at"] == "2026-08-18T10:30:00+08:00"
    assert manifest["candidate_count"] == 10
    assert manifest["human_selection_status"] == "approved"
    assert manifest["schema"] == "health_trend_exchange.v1"
    assert manifest["version"] == "v01"


def test_manifest_binds_exact_payload_bytes_selection_and_curated_input(tmp_path: Path) -> None:
    root = tmp_path / "root"
    layout, curated_sha256 = _curated_layout(root)
    selection = _selection_path(root, curated_sha256)
    selection_payload = selection.read_bytes()
    result = build_approved_exchange(layout, BATCH_ID, selection)
    manifest_payload = (result.path / "bundle-manifest.json").read_bytes()
    manifest = load_unique_json(manifest_payload)

    assert result.manifest_sha256 == hashlib.sha256(manifest_payload).hexdigest()
    assert result.input_curated_manifest_sha256 == curated_sha256
    assert result.candidate_count == 10
    assert manifest["input_curated_manifest_sha256"] == curated_sha256
    assert manifest["selection_sha256"] == hashlib.sha256(selection_payload).hexdigest()
    assert [binding["relative_path"] for binding in manifest["files"]] == [
        "evidence-summary.json",
        "top10.json",
    ]
    for binding in manifest["files"]:
        payload = (result.path / binding["relative_path"]).read_bytes()
        assert binding["bytes"] == len(payload)
        assert binding["sha256"] == hashlib.sha256(payload).hexdigest()


def test_two_clean_roots_produce_identical_approved_bytes(tmp_path: Path) -> None:
    first = _build_valid_exchange(tmp_path / "first")
    second = _build_valid_exchange(tmp_path / "second")

    assert {
        path.name: path.read_bytes() for path in first.path.iterdir()
    } == {path.name: path.read_bytes() for path in second.path.iterdir()}
    tree = b"".join(path.read_bytes() for path in first.path.iterdir())
    assert str(tmp_path).encode() not in tree


def test_verifier_rejects_tampering_extra_file_and_bad_external_anchor(tmp_path: Path) -> None:
    result = _build_valid_exchange(tmp_path / "root")
    expected = result.manifest_sha256

    assert verify_approved_exchange(result.path, expected) == result
    with pytest.raises(ExchangeError):
        verify_approved_exchange(result.path, expected.upper())
    with pytest.raises(ExchangeError):
        verify_approved_exchange(result.path, "0" * 64)

    top10_path = result.path / "top10.json"
    original = top10_path.read_bytes()
    top10_path.write_bytes(original + b" ")
    with pytest.raises(ExchangeError):
        verify_approved_exchange(result.path)
    top10_path.write_bytes(original)

    extra = result.path / "extra.json"
    extra.write_bytes(b"{}")
    with pytest.raises(ExchangeError):
        verify_approved_exchange(result.path)
    extra.unlink()

    manifest_path = result.path / "bundle-manifest.json"
    manifest_original = manifest_path.read_bytes()
    manifest = load_unique_json(manifest_original)
    manifest["human_selection_status"] = "pending"
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    with pytest.raises(ExchangeError):
        verify_approved_exchange(result.path)
    manifest_path.write_bytes(manifest_original)


def test_verifier_rejects_semantic_leak_even_when_hashes_are_rebound(tmp_path: Path) -> None:
    result = _build_valid_exchange(tmp_path / "root")
    top10_path = result.path / "top10.json"
    top10 = load_unique_json(top10_path.read_bytes())
    top10[0]["growth_evidence"] = ["https[:]//example[.]com/source"]
    leaked_payload = canonical_json_bytes(top10)
    top10_path.write_bytes(leaked_payload)
    manifest_path = result.path / "bundle-manifest.json"
    manifest = load_unique_json(manifest_path.read_bytes())
    for binding in manifest["files"]:
        if binding["relative_path"] == "top10.json":
            binding["bytes"] = len(leaked_payload)
            binding["sha256"] = hashlib.sha256(leaked_payload).hexdigest()
    manifest_path.write_bytes(canonical_json_bytes(manifest))

    with pytest.raises(ExchangeError):
        verify_approved_exchange(result.path)


@pytest.mark.parametrize(
    "unsafe",
    [
        "ftp://10.0.0.1/source",
        "example.dev/source",
        "httрs://example。com/source",
        "xsec＿token=supersecret",
        "coo\u2028kie=value",
        "me＿dia=value",
        "custom-scheme:opaque-value",
        "javascript:opaque-payload",
        "vbscript:opaque-payload",
        "data:text/plain,synthetic-secret",
        "file:C:/synthetic-secret",
        "about:blank",
        "blob:synthetic-payload",
        "chrome:settings",
        "chrome-extension:synthetic-payload",
        "resource:synthetic-payload",
        "intent:synthetic-payload",
        "market:synthetic-payload",
        "ms-appx:synthetic-payload",
        "ms-appdata:synthetic-payload",
        "view-source:synthetic-payload",
        "tel:+15551234567",
        "custom+hti://synthetic-host/source",
        "custom+hti://[2001:db8::1]/source",
        "例子.健康/source",
        "access token=supersecret",
        "avatar value",
    ],
)
def test_verifier_rejects_review_leaks_after_semantically_rebound_hashes(
    tmp_path: Path, unsafe: str
) -> None:
    result = _build_valid_exchange(tmp_path / "root")
    top10 = load_unique_json((result.path / "top10.json").read_bytes())
    top10[0]["growth_evidence"] = [unsafe]
    _rebind_payload(result, "top10.json", top10)
    rebound_anchor = hashlib.sha256(
        (result.path / "bundle-manifest.json").read_bytes()
    ).hexdigest()

    with pytest.raises(ExchangeError) as captured:
        verify_approved_exchange(result.path, rebound_anchor)

    assert unsafe not in str(captured.value)


@pytest.mark.parametrize("candidate_count", [10.0, True])
def test_manifest_rejects_non_integer_candidate_count(
    tmp_path: Path, candidate_count: object
) -> None:
    result = _build_valid_exchange(tmp_path / "root")
    manifest_path = result.path / "bundle-manifest.json"
    manifest = load_unique_json(manifest_path.read_bytes())
    manifest["candidate_count"] = candidate_count
    manifest_path.write_bytes(canonical_json_bytes(manifest))

    with pytest.raises(ExchangeError):
        verify_approved_exchange(result.path)


@pytest.mark.parametrize("invalid_count", [4.0, True, -1])
def test_summary_rejects_non_integer_or_negative_counts(
    tmp_path: Path, invalid_count: object
) -> None:
    result = _build_valid_exchange(tmp_path / "root")
    summary = load_unique_json((result.path / "evidence-summary.json").read_bytes())
    summary["confidence_counts"]["high"] = invalid_count
    _rebind_payload(result, "evidence-summary.json", summary)

    with pytest.raises(ExchangeError):
        verify_approved_exchange(result.path)


@pytest.mark.parametrize("invalid_bytes", [1.0, True, -1])
def test_manifest_binding_rejects_non_integer_or_negative_bytes(
    tmp_path: Path, invalid_bytes: object
) -> None:
    result = _build_valid_exchange(tmp_path / "root")
    manifest_path = result.path / "bundle-manifest.json"
    manifest = load_unique_json(manifest_path.read_bytes())
    manifest["files"][0]["bytes"] = invalid_bytes
    manifest_path.write_bytes(canonical_json_bytes(manifest))

    with pytest.raises(ExchangeError):
        verify_approved_exchange(result.path)


def test_candidate_model_requires_batch_wide_unverified_medical_flag() -> None:
    value = _selection_value("a" * 64)
    candidates = value["candidates"]
    assert isinstance(candidates, list)
    for candidate in candidates:
        candidate["risk_flags"] = ["medical_claim_unverified"]
    candidates[0]["risk_flags"] = []

    with pytest.raises(ValidationError):
        ApprovedSelection.model_validate_json(canonical_json_bytes(value))


def test_candidate_model_requires_exactly_one_unverified_medical_status() -> None:
    value = _selection_value("a" * 64)
    candidates = value["candidates"]
    assert isinstance(candidates, list)
    candidates[0]["risk_flags"] = [
        "medical_claim_unverified",
        "medical_claim_unverified",
    ]

    with pytest.raises(ValidationError):
        ApprovedSelection.model_validate_json(canonical_json_bytes(value))


def test_builder_rejects_affirmative_medical_verification_but_allows_pending_forms(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    layout, manifest_sha256 = _curated_layout(root)
    affirmative = (
        "医学结论核验已完成",
        "医学核验顺利通过",
        "Clinical review is complete",
        "Medical claim verification passed",
        "The claim was medically verified",
    )
    incomplete = (
        "医学声明尚未通过验证",
        "医学声明待核验",
        "Medical claim verification is incomplete",
        "Medical claim verification has not yet passed",
        "Clinical review is pending",
    )
    conflicting_flags = (
        "medical_claim_verified",
        "clinical_review_approved",
        "health_claim_verification_passed",
        "medicine_claim_validated",
    )

    for index, flag in enumerate(conflicting_flags):
        value = _selection_value(manifest_sha256)
        candidates = value["candidates"]
        assert isinstance(candidates, list)
        candidates[0]["risk_flags"] = ["medical_claim_unverified", flag]
        with pytest.raises(ExchangeError, match="medical_verification_contradiction"):
            build_approved_exchange(
                layout,
                BATCH_ID,
                _write_selection(root, value, f"structured-{index}.json"),
            )
        assert not (layout.approved / BATCH_ID).exists()

    for index, statement in enumerate(affirmative):
        value = _selection_value(manifest_sha256)
        candidates = value["candidates"]
        assert isinstance(candidates, list)
        candidates[0]["growth_evidence"] = [statement]
        with pytest.raises(ExchangeError, match="medical_verification_contradiction"):
            build_approved_exchange(
                layout,
                BATCH_ID,
                _write_selection(root, value, f"affirmative-{index}.json"),
            )
        assert not (layout.approved / BATCH_ID).exists()

    for index, statement in enumerate(incomplete):
        value = _selection_value(manifest_sha256)
        candidates = value["candidates"]
        assert isinstance(candidates, list)
        candidates[0]["growth_evidence"] = [statement]
        result = build_approved_exchange(
            layout,
            BATCH_ID,
            _write_selection(root, value, f"incomplete-{index}.json"),
        )
        assert verify_approved_exchange(result.path, result.manifest_sha256).candidate_count == 10
        for child in result.path.iterdir():
            child.unlink()
        result.path.rmdir()


def test_builder_rejects_any_candidate_missing_batch_wide_risk_flag(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    layout, manifest_sha256 = _curated_layout(root)
    value = _selection_value(manifest_sha256)
    candidates = value["candidates"]
    assert isinstance(candidates, list)
    for candidate in candidates:
        candidate["risk_flags"] = ["medical_claim_unverified"]
    candidates[7]["risk_flags"] = []

    with pytest.raises(ExchangeError):
        build_approved_exchange(layout, BATCH_ID, _write_selection(root, value))

    assert not (layout.approved / BATCH_ID).exists()


def test_anchored_verifier_rejects_missing_batch_wide_flag_after_full_rebind(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    layout, manifest_sha256 = _curated_layout(root)
    value = _selection_value(manifest_sha256)
    candidates = value["candidates"]
    assert isinstance(candidates, list)
    for candidate in candidates:
        candidate["risk_flags"] = ["medical_claim_unverified"]
    result = build_approved_exchange(layout, BATCH_ID, _write_selection(root, value))
    top10 = load_unique_json((result.path / "top10.json").read_bytes())
    top10[7]["risk_flags"] = []
    _rebind_payload(result, "top10.json", top10)
    summary = load_unique_json((result.path / "evidence-summary.json").read_bytes())
    summary["risk_flagged_candidate_count"] = 9
    summary["risk_flag_item_count"] = 9
    _rebind_payload(result, "evidence-summary.json", summary)
    rebound_anchor = hashlib.sha256(
        (result.path / "bundle-manifest.json").read_bytes()
    ).hexdigest()

    with pytest.raises(ExchangeError):
        verify_approved_exchange(result.path, rebound_anchor)


@pytest.mark.parametrize(
    "statement",
    [
        "高血压患者应该减少盐摄入",
        "维生素C预防感冒",
        "熬夜会导致脱发",
        "吸烟可能引起肺部疾病",
        "高盐饮食会诱发高血压",
        "规律运动可以改善失眠",
        "这种疗法能治疗关节疼痛",
        "少盐可以降低高血压风险",
        "熬夜会增加脱发风险",
    ],
)
def test_unverified_medical_statement_requires_standard_risk_flag(
    tmp_path: Path, statement: str
) -> None:
    root = tmp_path / "root"
    layout, manifest_sha256 = _curated_layout(root)
    value = _selection_value(manifest_sha256)
    candidates = value["candidates"]
    assert isinstance(candidates, list)
    candidates[0]["narrative_gap"] = statement
    candidates[0]["risk_flags"] = []

    with pytest.raises(ExchangeError):
        build_approved_exchange(layout, BATCH_ID, _write_selection(root, value))

    assert not (layout.approved / BATCH_ID).exists()


@pytest.mark.parametrize(
    "statement",
    ["高血压患者应该减少盐摄入", "维生素C预防感冒", "熬夜会导致脱发", "少盐可以降低高血压风险"],
)
def test_standard_risk_flag_allows_unverified_statement_with_disclaimer(
    tmp_path: Path, statement: str
) -> None:
    root = tmp_path / "root"
    layout, manifest_sha256 = _curated_layout(root)
    value = _selection_value(manifest_sha256)
    candidates = value["candidates"]
    assert isinstance(candidates, list)
    candidates[0]["narrative_gap"] = statement
    candidates[0]["risk_flags"] = ["medical_claim_unverified"]
    result = build_approved_exchange(layout, BATCH_ID, _write_selection(root, value))

    verified = verify_approved_exchange(result.path, result.manifest_sha256)
    top10 = load_unique_json((result.path / "top10.json").read_bytes())
    assert verified.candidate_count == 10
    assert top10[0]["disclaimer"] == "该包只是选题情报，不是医学事实来源或可直接发布的脚本。"


def test_anchored_verifier_rejects_medical_statement_after_flag_is_removed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    layout, manifest_sha256 = _curated_layout(root)
    value = _selection_value(manifest_sha256)
    candidates = value["candidates"]
    assert isinstance(candidates, list)
    candidates[0]["narrative_gap"] = "熬夜会导致脱发"
    candidates[0]["risk_flags"] = ["medical_claim_unverified"]
    result = build_approved_exchange(layout, BATCH_ID, _write_selection(root, value))
    top10 = load_unique_json((result.path / "top10.json").read_bytes())
    top10[0]["risk_flags"] = []
    _rebind_payload(result, "top10.json", top10)
    summary = load_unique_json((result.path / "evidence-summary.json").read_bytes())
    summary["risk_flagged_candidate_count"] = 9
    summary["risk_flag_item_count"] = 10
    _rebind_payload(result, "evidence-summary.json", summary)
    rebound_anchor = hashlib.sha256(
        (result.path / "bundle-manifest.json").read_bytes()
    ).hexdigest()

    with pytest.raises(ExchangeError):
        verify_approved_exchange(result.path, rebound_anchor)


@pytest.mark.parametrize(
    ("field", "statement"),
    [
        ("growth_evidence", "Research question: compare public, aggregated trend signals"),
        ("growth_evidence", "研究问题：比较公开且聚合的趋势信号"),
        ("narrative_gap", "项目延期会导致交付计划调整"),
    ],
)
def test_safe_prose_with_colons_or_nonmedical_causality_builds_and_verifies(
    tmp_path: Path, field: str, statement: str
) -> None:
    root = tmp_path / "root"
    layout, manifest_sha256 = _curated_layout(root)
    value = _selection_value(manifest_sha256)
    candidates = value["candidates"]
    assert isinstance(candidates, list)
    candidates[0][field] = (
        [statement] if isinstance(candidates[0][field], list) else statement
    )
    result = build_approved_exchange(layout, BATCH_ID, _write_selection(root, value))

    verified = verify_approved_exchange(result.path, result.manifest_sha256)
    assert verified.candidate_count == 10


def test_existing_destination_is_never_overwritten(tmp_path: Path) -> None:
    root = tmp_path / "root"
    layout, curated_sha256 = _curated_layout(root)
    destination = layout.approved / BATCH_ID
    destination.mkdir()
    marker = destination / "owned.txt"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(ExchangeError):
        build_approved_exchange(layout, BATCH_ID, _selection_path(root, curated_sha256))

    assert marker.read_text(encoding="utf-8") == "preserve"


def test_selection_change_during_build_never_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from health_trend_intelligence import exchange

    root = tmp_path / "root"
    layout, curated_sha256 = _curated_layout(root)
    selection = _selection_path(root, curated_sha256)
    original_write = exchange._exclusive_write
    changed = False

    def mutate_after_first_write(path: Path, payload: bytes, **kwargs) -> None:
        nonlocal changed
        original_write(path, payload, **kwargs)
        if not changed:
            changed = True
            value = load_unique_json(selection.read_bytes())
            value["approved_at"] = "2026-08-18T11:30:00+08:00"
            selection.write_bytes(canonical_json_bytes(value))

    monkeypatch.setattr(exchange, "_exclusive_write", mutate_after_first_write)
    with pytest.raises(ExchangeError):
        build_approved_exchange(layout, BATCH_ID, selection)

    assert not (layout.approved / BATCH_ID).exists()


def test_change_after_manifest_write_leaves_no_consumable_work_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from health_trend_intelligence import exchange

    root = tmp_path / "root"
    layout, curated_sha256 = _curated_layout(root)
    selection = _selection_path(root, curated_sha256)
    original_write = exchange._exclusive_write
    writes = 0

    def mutate_after_manifest(path: Path, payload: bytes, **kwargs) -> None:
        nonlocal writes
        original_write(path, payload, **kwargs)
        writes += 1
        if writes == 3:
            value = load_unique_json(selection.read_bytes())
            value["approved_at"] = "2026-08-18T11:30:00+08:00"
            selection.write_bytes(canonical_json_bytes(value))

    monkeypatch.setattr(exchange, "_exclusive_write", mutate_after_manifest)
    with pytest.raises(ExchangeError):
        build_approved_exchange(layout, BATCH_ID, selection)

    work = layout.approved / f"{BATCH_ID}.work"
    assert not (layout.approved / BATCH_ID).exists()
    assert not (work / "bundle-manifest.json").exists()
    with pytest.raises(ExchangeError):
        verify_approved_exchange(work)


def test_verifier_rechecks_payload_bytes_after_semantic_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from health_trend_intelligence import exchange

    result = _build_valid_exchange(tmp_path / "root")
    original_read = exchange._read_stable_bytes
    changed = False

    def change_after_top10_read(path: Path) -> bytes:
        nonlocal changed
        payload = original_read(path)
        if path.name == "top10.json" and not changed:
            changed = True
            path.write_bytes(payload + b" ")
        return payload

    monkeypatch.setattr(exchange, "_read_stable_bytes", change_after_top10_read)
    with pytest.raises(ExchangeError):
        verify_approved_exchange(result.path)


def test_selection_replacement_during_open_handle_read_fails_before_work_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from health_trend_intelligence import exchange

    root = tmp_path / "root"
    layout, curated_sha256 = _curated_layout(root)
    selection = _selection_path(root, curated_sha256)
    original = exchange._opened_file_status
    replaced = False

    def replace_after_open(stream, path: Path):
        nonlocal replaced
        status = original(stream, path)
        if path == selection and not replaced:
            replaced = True
            moved = selection.with_suffix(".moved")
            selection.rename(moved)
            selection.write_bytes(moved.read_bytes())
        return status

    monkeypatch.setattr(exchange, "_opened_file_status", replace_after_open)
    with pytest.raises(ExchangeError):
        build_approved_exchange(layout, BATCH_ID, selection)

    assert not (layout.approved / f"{BATCH_ID}.work").exists()


def test_work_reparse_after_validation_receives_no_payload_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from health_trend_intelligence import exchange

    root = tmp_path / "root"
    layout, curated_sha256 = _curated_layout(root)
    selection = _selection_path(root, curated_sha256)
    outside = tmp_path / "outside"
    outside.mkdir()
    original = exchange._assert_write_boundary
    replaced = False

    def replace_after_first_check(*args, **kwargs):
        nonlocal replaced
        result = original(*args, **kwargs)
        if not replaced:
            work = layout.approved / f"{BATCH_ID}.work"
            work.rmdir()
            try:
                os.symlink(outside, work, target_is_directory=True)
            except OSError as error:
                if getattr(error, "winerror", None) == 1314:
                    pytest.skip("current account cannot create directory symlinks")
                raise
            replaced = True
        return result

    monkeypatch.setattr(exchange, "_assert_write_boundary", replace_after_first_check)
    with pytest.raises(ExchangeError):
        build_approved_exchange(layout, BATCH_ID, selection)

    outside_payload = outside / "top10.json"
    assert not outside_payload.exists() or outside_payload.read_bytes() == b""


def test_work_directory_identity_replacement_receives_no_payload_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from health_trend_intelligence import exchange

    root = tmp_path / "root"
    layout, curated_sha256 = _curated_layout(root)
    selection = _selection_path(root, curated_sha256)
    original = exchange._assert_write_boundary
    replaced = False

    def replace_with_new_directory(*args, **kwargs):
        nonlocal replaced
        result = original(*args, **kwargs)
        if not replaced:
            work = layout.approved / f"{BATCH_ID}.work"
            moved = layout.approved / f"{BATCH_ID}.moved"
            work.rename(moved)
            work.mkdir()
            replaced = True
        return result

    monkeypatch.setattr(exchange, "_assert_write_boundary", replace_with_new_directory)
    with pytest.raises(ExchangeError):
        build_approved_exchange(layout, BATCH_ID, selection)

    replacement_payload = layout.approved / f"{BATCH_ID}.work" / "top10.json"
    assert replacement_payload.is_file()
    assert replacement_payload.read_bytes() == b""


def test_cli_build_and_verify_use_safe_exit_codes_and_messages(tmp_path: Path) -> None:
    root = tmp_path / "root"
    layout, curated_sha256 = _curated_layout(root)
    selection = _selection_path(root, curated_sha256)
    runner = CliRunner()

    built = runner.invoke(
        app,
        ["build-approved", "--root", str(root), "--batch-id", BATCH_ID, "--selection", str(selection)],
    )
    assert built.exit_code == 0
    assert built.stdout.strip() == (
        f"built-approved {BATCH_ID} candidates=10 provenance=unanchored "
        "local-consistency-only content=not-medically-verified"
    )
    manifest_sha256 = hashlib.sha256(
        (layout.approved / BATCH_ID / "bundle-manifest.json").read_bytes()
    ).hexdigest()
    verified = runner.invoke(
        app,
        [
            "verify-approved",
            "--path",
            str(layout.approved / BATCH_ID),
            "--expected-manifest-sha256",
            manifest_sha256,
        ],
    )
    assert verified.exit_code == 0
    assert verified.stdout.strip() == (
        f"verified-approved {BATCH_ID} candidates=10 provenance=anchored "
        "content=not-medically-verified"
    )

    unanchored = runner.invoke(
        app,
        ["verify-approved", "--path", str(layout.approved / BATCH_ID)],
    )
    assert unanchored.exit_code == 0
    assert unanchored.stdout.strip() == (
        f"verified-approved {BATCH_ID} candidates=10 provenance=unanchored "
        "local-consistency-only content=not-medically-verified"
    )

    invalid = runner.invoke(
        app,
        [
            "build-approved",
            "--root",
            str(root),
            "--batch-id",
            "not-a-batch",
            "--selection",
            str(selection),
        ],
    )
    assert invalid.exit_code == 3
    assert invalid.stderr.strip() == "build-approved <invalid-batch> invalid_input"
    assert str(selection) not in invalid.stderr
