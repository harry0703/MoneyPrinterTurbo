from __future__ import annotations

import hashlib
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
        ("user_questions", r"raw\HTI-20260818-01\posts.jsonl"),
        ("risk_flags", "待核对 nickname 字段"),
        ("missing_data", "clip.mp4 素材待补"),
        ("narrative_gap", "每天执行这个方法一定能治愈所有疾病"),
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
        "risk_flag_item_count": 1,
        "risk_flagged_candidate_count": 1,
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
    import health_trend_intelligence.exchange as exchange

    root = tmp_path / "root"
    layout, curated_sha256 = _curated_layout(root)
    selection = _selection_path(root, curated_sha256)
    original_write = exchange._exclusive_write
    changed = False

    def mutate_after_first_write(path: Path, payload: bytes) -> None:
        nonlocal changed
        original_write(path, payload)
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
    import health_trend_intelligence.exchange as exchange

    root = tmp_path / "root"
    layout, curated_sha256 = _curated_layout(root)
    selection = _selection_path(root, curated_sha256)
    original_write = exchange._exclusive_write
    writes = 0

    def mutate_after_manifest(path: Path, payload: bytes) -> None:
        nonlocal writes
        original_write(path, payload)
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
    import health_trend_intelligence.exchange as exchange

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
    assert built.stdout.strip() == f"built-approved {BATCH_ID} candidates=10"
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
    assert verified.stdout.strip() == f"verified-approved {BATCH_ID} candidates=10"

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
