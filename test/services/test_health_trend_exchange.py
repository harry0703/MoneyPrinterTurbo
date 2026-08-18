from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.services import health_trend_exchange as exchange
from app.services.health_trend_exchange import (
    TrendExchangeError,
    import_trend_exchange,
    verify_trend_exchange,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLI = PROJECT_ROOT / "09_泛健康日更" / "scripts" / "import_trend_intelligence.py"
DISCLAIMER = "该包只是选题情报，不是医学事实来源或可直接发布的脚本。"
SHA_ZERO = "0" * 64


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _candidate(rank: int) -> dict[str, object]:
    platform = {"dy": f"合成排名区间 {rank:02d}"}
    if rank % 2 == 0:
        platform = {"xhs": f"合成排名区间 {rank:02d}"}
    if rank % 3 == 0:
        platform = {
            "dy": f"合成排名区间 {rank:02d}",
            "xhs": f"合成排名区间 {rank:02d}",
        }
    return {
        "rank": rank,
        "topic": f"合成选题 {rank:02d}",
        "platform_rank_evidence": platform,
        "growth_evidence": [f"合成增长信号 {rank:02d}"],
        "user_questions": [f"合成问题类别 {rank:02d}"],
        "user_needs": [f"合成需求类别 {rank:02d}"],
        "misunderstandings": [f"合成误解类别 {rank:02d}"],
        "objections": [f"合成异议类别 {rank:02d}"],
        "homogeneity_pattern": f"合成同质化模式 {rank:02d}",
        "narrative_gap": f"合成叙事缺口 {rank:02d}",
        "original_visual_direction": f"合成原创视觉方向 {rank:02d}",
        "risk_flags": ["medical_claim_unverified"],
        "confidence": ("low", "medium", "high")[(rank - 1) % 3],
        "missing_data": [],
        "disclaimer": DISCLAIMER,
    }


def _summary(batch_id: str, candidates: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema": "health_trend_evidence_summary.v1",
        "batch_id": batch_id,
        "candidate_count": 10,
        "platform_coverage": {"dy": 6, "xhs": 7, "both": 3},
        "confidence_counts": {"low": 4, "medium": 3, "high": 3},
        "evidence_item_counts": {
            "growth_evidence": 10,
            "user_questions": 10,
            "user_needs": 10,
            "misunderstandings": 10,
            "objections": 10,
        },
        "risk_flagged_candidate_count": sum(bool(c["risk_flags"]) for c in candidates),
        "risk_flag_item_count": sum(len(c["risk_flags"]) for c in candidates),
        "missing_data_candidate_count": 0,
        "missing_data_item_count": 0,
    }


def _write_bundle(
    root: Path,
    *,
    batch_id: str = "HTI-20260818-01",
    mutate: Callable[[list[dict[str, object]], Any], tuple[object, object, dict[str, object]]]
    | None = None,
) -> tuple[Path, str]:
    source = root / batch_id
    source.mkdir(parents=True)
    candidates = [_candidate(rank) for rank in range(1, 11)]
    top10: object = candidates
    summary: object = _summary(batch_id, candidates)
    manifest_overrides: dict[str, object] = {}
    if mutate is not None:
        top10, summary, manifest_overrides = mutate(candidates, summary)
    payloads = {
        "evidence-summary.json": _json_bytes(summary),
        "top10.json": _json_bytes(top10),
    }
    manifest = {
        "schema": "health_trend_exchange.v1",
        "version": "v01",
        "batch_id": batch_id,
        "generated_at": "2026-08-18T10:30:00+08:00",
        "input_curated_manifest_sha256": SHA_ZERO,
        "selection_sha256": "1" * 64,
        "human_selection_status": "approved",
        "candidate_count": 10,
        "disclaimer": DISCLAIMER,
        "files": [
            {
                "relative_path": name,
                "bytes": len(payloads[name]),
                "sha256": hashlib.sha256(payloads[name]).hexdigest(),
            }
            for name in ("evidence-summary.json", "top10.json")
        ],
    }
    manifest.update(manifest_overrides)
    manifest_bytes = _json_bytes(manifest)
    for name, payload in payloads.items():
        (source / name).write_bytes(payload)
    (source / "bundle-manifest.json").write_bytes(manifest_bytes)
    return source, hashlib.sha256(manifest_bytes).hexdigest()


def _fake_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    return repo


@pytest.mark.parametrize("anchor", ["", "A" * 64, "0" * 63, "z" * 64, None])
def test_verify_requires_exact_external_lowercase_sha256_anchor(
    tmp_path: Path, anchor: str | None
) -> None:
    source, _ = _write_bundle(tmp_path)

    with pytest.raises(TrendExchangeError, match="expected_manifest_anchor_invalid"):
        verify_trend_exchange(source, anchor)  # type: ignore[arg-type]


def test_verify_rejects_wrong_manifest_anchor(tmp_path: Path) -> None:
    source, _ = _write_bundle(tmp_path)

    with pytest.raises(TrendExchangeError, match="manifest_anchor_mismatch"):
        verify_trend_exchange(source, "f" * 64)


def test_verify_accepts_exact_task6_bundle_and_public_research_text(tmp_path: Path) -> None:
    def mutate(candidates: list[dict[str, object]], summary: object):
        candidates[0]["topic"] = "Public health research overview"
        return candidates, summary, {}

    source, anchor = _write_bundle(tmp_path, mutate=mutate)

    verified = verify_trend_exchange(source, anchor)

    assert verified.batch_id == "HTI-20260818-01"
    assert verified.version == "v01"
    assert verified.manifest_sha256 == anchor
    assert verified.candidate_count == 10


@pytest.mark.parametrize(
    ("target", "value"),
    [
        ("manifest.schema", "health_trend_exchange.v2"),
        ("manifest.version", "v02"),
        ("manifest.human_selection_status", "pending"),
        ("manifest.candidate_count", True),
        ("manifest.generated_at", "2026-08-18T10:30:00"),
        ("summary.schema", "health_trend_evidence_summary.v2"),
        ("summary.candidate_count", 10.0),
        ("candidate.rank", 1.0),
        ("candidate.disclaimer", "已完成医学核验。"),
        ("candidate.risk_flags", ["medical_claim_verified"]),
    ],
)
def test_verify_rejects_schema_status_type_rank_disclaimer_and_risk_changes(
    tmp_path: Path, target: str, value: object
) -> None:
    def mutate(candidates: list[dict[str, object]], summary: dict[str, object]):
        manifest: dict[str, object] = {}
        scope, field = target.split(".")
        if scope == "manifest":
            manifest[field] = value
        elif scope == "summary":
            summary[field] = value
        else:
            candidates[0][field] = value
        return candidates, summary, manifest

    source, anchor = _write_bundle(tmp_path, mutate=mutate)

    with pytest.raises(TrendExchangeError):
        verify_trend_exchange(source, anchor)


def test_verify_rejects_duplicate_and_nfc_colliding_json_keys(tmp_path: Path) -> None:
    source, _ = _write_bundle(tmp_path)
    top10 = source / "top10.json"
    original = top10.read_bytes()
    top10.write_bytes(b'{"schema":"a","schema":"b"}\n')
    manifest = source / "bundle-manifest.json"
    manifest_value = json.loads(manifest.read_text("utf-8"))
    manifest_value["files"][1]["bytes"] = top10.stat().st_size
    manifest_value["files"][1]["sha256"] = hashlib.sha256(top10.read_bytes()).hexdigest()
    manifest_bytes = _json_bytes(manifest_value)
    manifest.write_bytes(manifest_bytes)

    with pytest.raises(TrendExchangeError, match="duplicate_json_key"):
        verify_trend_exchange(source, hashlib.sha256(manifest_bytes).hexdigest())

    top10.write_bytes(b'{"\xc3\xa9":1,"e\xcc\x81":2}\n')
    manifest_value["files"][1]["bytes"] = top10.stat().st_size
    manifest_value["files"][1]["sha256"] = hashlib.sha256(top10.read_bytes()).hexdigest()
    manifest_bytes = _json_bytes(manifest_value)
    manifest.write_bytes(manifest_bytes)
    with pytest.raises(TrendExchangeError, match="nfc_json_key_collision"):
        verify_trend_exchange(source, hashlib.sha256(manifest_bytes).hexdigest())
    assert original


@pytest.mark.parametrize(
    "injected",
    [
        "https：//example．com/file",
        "hтtp://example.com/file",
        "example [dot] com / download",
        "http://127.0.0.1/private",
        "file:///curated/records.jsonl",
        "raw_record synthetic excerpt",
        "mobile 13800138000",
        "cookie=synthetic-secret",
        "Bearer synthetic-token",
        "download/clip.mp4",
        "payload.exe",
    ],
)
def test_verify_recursively_rejects_urls_secrets_layers_media_and_executables(
    tmp_path: Path, injected: str
) -> None:
    def mutate(candidates: list[dict[str, object]], summary: object):
        candidates[0]["topic"] = injected
        return candidates, summary, {}

    source, anchor = _write_bundle(tmp_path, mutate=mutate)

    with pytest.raises(TrendExchangeError, match="restricted_exchange_content"):
        verify_trend_exchange(source, anchor)


def test_verify_rejects_extra_file_and_symlink_source_file(tmp_path: Path) -> None:
    source, anchor = _write_bundle(tmp_path)
    (source / "extra.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(TrendExchangeError, match="source_file_set_invalid"):
        verify_trend_exchange(source, anchor)
    (source / "extra.txt").unlink()

    payload = source / "top10.json"
    replacement = tmp_path / "outside.json"
    replacement.write_bytes(payload.read_bytes())
    payload.unlink()
    try:
        payload.symlink_to(replacement)
    except OSError as error:
        pytest.skip(f"current account cannot create symlink: {error}")
    with pytest.raises(TrendExchangeError, match="source_file_invalid"):
        verify_trend_exchange(source, anchor)


def test_import_is_exact_versioned_byte_identical_and_no_overwrite(tmp_path: Path) -> None:
    source, anchor = _write_bundle(tmp_path / "source")
    repo = _fake_repo(tmp_path)

    target = import_trend_exchange(source, repo, anchor)

    assert target == (
        repo
        / "09_泛健康日更"
        / "data"
        / "trend-intelligence"
        / "HTI-20260818-01"
        / "v01"
    )
    assert {path.name for path in target.iterdir()} == {
        "top10.json",
        "evidence-summary.json",
        "bundle-manifest.json",
    }
    for name in ("top10.json", "evidence-summary.json", "bundle-manifest.json"):
        assert (target / name).read_bytes() == (source / name).read_bytes()
    with pytest.raises(FileExistsError):
        import_trend_exchange(source, repo, anchor)


def test_import_rejects_reparse_repo_parent(tmp_path: Path) -> None:
    source, anchor = _write_bundle(tmp_path / "source")
    outside = tmp_path / "outside"
    outside.mkdir()
    repo = tmp_path / "repo-link"
    try:
        repo.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"current account cannot create directory symlink: {error}")

    with pytest.raises(TrendExchangeError, match="destination_boundary_invalid"):
        import_trend_exchange(source, repo, anchor)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction test")
def test_import_rejects_windows_junction_repo_parent(tmp_path: Path) -> None:
    source, anchor = _write_bundle(tmp_path / "source")
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = tmp_path / "repo-junction"
    created = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip("current account cannot create a directory junction")

    with pytest.raises(TrendExchangeError, match="destination_boundary_invalid"):
        import_trend_exchange(source, junction, anchor)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction test")
def test_verify_rejects_windows_junction_source(tmp_path: Path) -> None:
    real_source, anchor = _write_bundle(tmp_path / "real")
    junction = tmp_path / "source-junction"
    created = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(real_source)],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip("current account cannot create a source junction")

    with pytest.raises(TrendExchangeError, match="source_directory_invalid"):
        verify_trend_exchange(junction, anchor)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction test")
def test_import_rejects_junction_inside_destination_parent_chain(tmp_path: Path) -> None:
    source, anchor = _write_bundle(tmp_path / "source")
    repo = _fake_repo(tmp_path)
    outside = tmp_path / "outside-parent"
    outside.mkdir()
    junction = repo / "09_泛健康日更"
    created = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip("current account cannot create a destination-parent junction")

    with pytest.raises(TrendExchangeError, match="destination_boundary_invalid"):
        import_trend_exchange(source, repo, anchor)


def test_cli_success_and_rejection_are_payload_safe(tmp_path: Path) -> None:
    source, anchor = _write_bundle(tmp_path / "source")
    secret = "synthetic-secret-that-must-not-appear"
    verified = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "verify",
            "--source",
            str(source),
            "--expected-manifest-sha256",
            anchor,
        ],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr
    assert "HTI-20260818-01" in verified.stdout
    assert str(source) not in verified.stdout + verified.stderr

    rejected = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "verify",
            "--source",
            secret,
            "--expected-manifest-sha256",
            "bad-anchor",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert rejected.returncode == 3
    assert secret not in rejected.stdout + rejected.stderr


def test_cli_argument_errors_exit_three_without_echoing_values() -> None:
    secret = "synthetic-secret-argument"
    rejected = subprocess.run(
        [sys.executable, str(CLI), "verify", "--source", secret],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert rejected.returncode == 3
    assert secret not in rejected.stdout + rejected.stderr


def test_import_failure_never_leaves_manifest_completion_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, anchor = _write_bundle(tmp_path / "source")
    repo = _fake_repo(tmp_path)
    original_fsync = os.fsync
    calls = 0

    def fail_second_payload_sync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic fsync failure")
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_second_payload_sync)
    with pytest.raises(TrendExchangeError):
        import_trend_exchange(source, repo, anchor)

    target = (
        repo
        / "09_泛健康日更"
        / "data"
        / "trend-intelligence"
        / "HTI-20260818-01"
        / "v01"
    )
    assert not (target / "bundle-manifest.json").exists()


def test_import_rejects_same_byte_source_identity_replacement_during_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, anchor = _write_bundle(tmp_path / "source")
    repo = _fake_repo(tmp_path)
    original_read = exchange._read_regular_file
    top10_reads = 0

    def replace_on_copy(path: Path):
        nonlocal top10_reads
        if path == source / "top10.json":
            top10_reads += 1
            if top10_reads == 3:
                replacement = source / "replacement.tmp"
                replacement.write_bytes(path.read_bytes())
                os.replace(replacement, path)
        return original_read(path)

    monkeypatch.setattr(exchange, "_read_regular_file", replace_on_copy)
    with pytest.raises(TrendExchangeError, match="source_changed_during_import"):
        import_trend_exchange(source, repo, anchor)

    target = (
        repo
        / "09_泛健康日更"
        / "data"
        / "trend-intelligence"
        / "HTI-20260818-01"
        / "v01"
    )
    assert not (target / "bundle-manifest.json").exists()


def test_post_manifest_verification_failure_removes_completion_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, anchor = _write_bundle(tmp_path / "source")
    repo = _fake_repo(tmp_path)
    original_verify = exchange._verify_snapshot

    def fail_target_verification(path: Path, expected: str):
        if Path(path).name == "v01":
            raise TrendExchangeError("synthetic_post_manifest_failure")
        return original_verify(path, expected)

    monkeypatch.setattr(exchange, "_verify_snapshot", fail_target_verification)
    with pytest.raises(TrendExchangeError, match="synthetic_post_manifest_failure"):
        import_trend_exchange(source, repo, anchor)

    target = (
        repo
        / "09_泛健康日更"
        / "data"
        / "trend-intelligence"
        / "HTI-20260818-01"
        / "v01"
    )
    assert not (target / "bundle-manifest.json").exists()
