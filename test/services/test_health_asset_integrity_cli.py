from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import subprocess
import sys
from dataclasses import fields, replace
from pathlib import Path

import pytest

import app.services.health_asset_integrity as integrity
from app.services.health_asset_integrity import DeletedAsset, GitInspectionError, GitInspector
from test.services.health_asset_audit_fixtures import (
    REMOTE_NAME,
    REMOTE_REF,
    create_deleted_pack_repo,
    repo_with_one_manual_pack,
    repository_fingerprint,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLI = PROJECT_ROOT / "09_泛健康日更" / "scripts" / "audit_health_assets.py"
BUNDLE_FILES = {
    "audit.json",
    "deleted-assets.csv",
    "audit-summary.md",
    "bundle-manifest.json",
}


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def _audit_args(repo: Path, output_parent: Path, audit_id: str) -> tuple[str, ...]:
    return (
        "audit",
        "--repo",
        str(repo),
        "--output-parent",
        str(output_parent),
        "--audit-id",
        audit_id,
    )


def _complete_report(tmp_path: Path):
    repo = create_deleted_pack_repo(tmp_path)
    return integrity.audit_health_assets(
        GitInspector(repo), remote=REMOTE_NAME, remote_ref=REMOTE_REF
    )


def test_cli_rejects_output_inside_audited_repo(tmp_path: Path):
    repo = create_deleted_pack_repo(tmp_path)

    result = _run(*_audit_args(repo, repo / "reports", "HCAS-TEST-01"))

    assert result.returncode == 3
    assert "outside audited repository" in result.stdout
    assert not (repo / "reports").exists()


def test_cli_rejects_output_equal_to_repo_and_normalized_descendant(tmp_path: Path):
    repo = create_deleted_pack_repo(tmp_path)

    equal = _run(*_audit_args(repo, repo, "HCAS-TEST-01"))
    descendant = _run(
        *_audit_args(repo, repo / "child" / ".." / "reports", "HCAS-TEST-02")
    )

    assert equal.returncode == 3
    assert descendant.returncode == 3
    assert not (repo / "reports").exists()


@pytest.mark.parametrize(
    "audit_id",
    [
        ".",
        "..",
        "../escape",
        r"..\escape",
        "nested/id",
        r"nested\id",
        "/absolute",
        "HCAS-TEST-01\nINJECT",
    ],
)
def test_cli_rejects_traversal_and_audit_id_injection(tmp_path: Path, audit_id: str):
    repo = create_deleted_pack_repo(tmp_path)
    output_parent = tmp_path / "evidence"

    result = _run(*_audit_args(repo, output_parent, audit_id))

    assert result.returncode == 3
    assert "invalid audit id" in result.stdout
    assert not output_parent.exists()


def test_cli_rejects_symlink_or_reparse_component_in_output_chain(tmp_path: Path):
    repo = create_deleted_pack_repo(tmp_path / "audit")
    real_output = tmp_path / "real-output"
    real_output.mkdir()
    linked_output = tmp_path / "linked-output"
    try:
        linked_output.symlink_to(real_output, target_is_directory=True)
    except OSError:
        junction = subprocess.run(
            [
                "cmd.exe",
                "/d",
                "/c",
                "mklink",
                "/J",
                str(linked_output),
                str(real_output),
            ],
            capture_output=True,
            check=False,
        )
        if junction.returncode != 0:
            pytest.skip("directory symlinks and junctions are unavailable")

    result = _run(*_audit_args(repo, linked_output / "child", "HCAS-TEST-01"))

    assert result.returncode == 3
    assert "symlink or reparse point" in result.stdout
    assert list(real_output.iterdir()) == []


def test_cli_writes_new_bundle_without_mutating_repo(tmp_path: Path):
    repo = create_deleted_pack_repo(tmp_path)
    output_parent = tmp_path / "evidence"
    before = repository_fingerprint(repo)

    result = _run(*_audit_args(repo, output_parent, "HCAS-TEST-01"))

    assert result.returncode == 0, result.stdout
    bundle = output_parent / "HCAS-TEST-01"
    assert {path.name for path in bundle.iterdir()} == BUNDLE_FILES
    assert repository_fingerprint(repo) == before
    response = json.loads(result.stdout)
    assert response == {"status": "complete", "bundle": str(bundle.resolve())}


def test_real_lfs_probe_fails_closed_before_unconfigured_repo_mutation(tmp_path: Path):
    repo = repo_with_one_manual_pack(tmp_path)
    before = repository_fingerprint(repo)

    report = integrity.audit_health_assets(
        GitInspector(repo), remote=None, remote_ref=None
    )

    assert report.summary["audit_complete"] is False
    assert "repository format" in report.lfs["error"]
    assert repository_fingerprint(repo) == before


@pytest.mark.parametrize("format_output", [b"0\n\n", b"0\r\r\n", b"00\n", b"0 injected\n"])
def test_lfs_probe_rejects_non_exact_local_format_records_before_lfs_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    format_output: bytes,
):
    inspector = GitInspector(repo_with_one_manual_pack(tmp_path))
    calls: list[tuple[list[str], dict]] = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, format_output, b"")

    monkeypatch.setattr(integrity.subprocess, "run", fake_run)

    with pytest.raises(GitInspectionError, match="repository format"):
        integrity._run_lfs_readonly(inspector, ("ls-files", "--all", "-n"))

    assert len(calls) == 1
    assert calls[0][0][-4:] == [
        "config",
        "--local",
        "--get",
        "lfs.repositoryformatversion",
    ]
    assert calls[0][1]["env"]["GIT_OPTIONAL_LOCKS"] == "0"


def test_bundle_manifest_binds_hash_and_size_of_every_payload(tmp_path: Path):
    repo = create_deleted_pack_repo(tmp_path)
    output_parent = tmp_path / "evidence"

    result = _run(*_audit_args(repo, output_parent, "HCAS-TEST-01"))

    assert result.returncode == 0, result.stdout
    bundle = output_parent / "HCAS-TEST-01"
    manifest = json.loads((bundle / "bundle-manifest.json").read_text("utf-8"))
    assert manifest["schema"] == "health-asset-integrity-bundle-v1"
    assert manifest["audit_id"] == "HCAS-TEST-01"
    assert manifest["report_schema"] == "health_asset_integrity.v1"
    assert list(manifest["files"]) == [
        "audit.json",
        "deleted-assets.csv",
        "audit-summary.md",
    ]
    for name in manifest["files"]:
        payload = (bundle / name).read_bytes()
        assert manifest["files"][name] == {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        }


def test_deleted_asset_csv_has_fixed_columns_and_deterministic_path_order(tmp_path: Path):
    report = _complete_report(tmp_path)
    reversed_report = replace(report, deleted_assets=tuple(reversed(report.deleted_assets)))

    rendered = integrity.render_deleted_assets_csv(reversed_report)
    rows = list(csv.DictReader(io.StringIO(rendered.decode("utf-8"))))

    assert tuple(rows[0]) == tuple(field.name for field in fields(DeletedAsset))
    assert [row["path"] for row in rows] == sorted(row["path"] for row in rows)
    assert rendered.endswith(b"\n")
    assert b"\r\n" not in rendered


def test_summary_contains_required_evidence_without_blob_contents(tmp_path: Path):
    report = _complete_report(tmp_path)

    summary = integrity.render_audit_summary(report).decode("utf-8")

    assert "24" in summary
    assert "HC20260810-001" in summary
    assert "refs/heads/feature/health-content-system" in summary
    assert "git-lfs/" in summary
    assert "Mutation guard" in summary
    assert "restore_exact_from_head" in summary
    assert "regenerate_outside_repo_and_compare" in summary
    assert "keep_deletions" in summary
    assert "S01 prompt" not in summary
    assert "\x89PNG" not in summary


def test_cli_refuses_existing_audit_id_without_rewrite(tmp_path: Path):
    repo = create_deleted_pack_repo(tmp_path)
    output_parent = tmp_path / "evidence"
    first = _run(*_audit_args(repo, output_parent, "HCAS-TEST-01"))
    assert first.returncode == 0, first.stdout
    bundle = output_parent / "HCAS-TEST-01"
    before = {path.name: path.read_bytes() for path in bundle.iterdir()}

    second = _run(*_audit_args(repo, output_parent, "HCAS-TEST-01"))

    assert second.returncode == 3
    assert "already exists" in second.stdout
    assert {path.name: path.read_bytes() for path in bundle.iterdir()} == before


def test_write_failure_preserves_non_consumable_staging_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    report = _complete_report(tmp_path / "fixture")
    output_parent = tmp_path / "evidence"
    original_write = integrity._write_exclusive
    calls = 0

    def fail_second_write(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected write failure")
        original_write(path, payload)

    monkeypatch.setattr(integrity, "_write_exclusive", fail_second_write)

    with pytest.raises(GitInspectionError, match="injected write failure"):
        integrity.write_report_bundle(output_parent, "HCAS-TEST-01", report)

    staging = output_parent / ".HCAS-TEST-01.staging"
    assert staging.is_dir()
    assert {path.name for path in staging.iterdir()} == {"audit.json"}
    assert not (staging / "bundle-manifest.json").exists()
    assert not (output_parent / "HCAS-TEST-01").exists()


def test_publish_race_never_overwrites_existing_target_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    report = _complete_report(tmp_path / "fixture")
    output_parent = tmp_path / "evidence"
    original_rename = os.rename

    def create_competing_target(source: Path, target: Path) -> None:
        target.mkdir()
        (target / "owner.txt").write_bytes(b"pre-existing owner bytes")
        original_rename(source, target)

    monkeypatch.setattr(integrity.os, "rename", create_competing_target)

    with pytest.raises(GitInspectionError, match="already exists"):
        integrity.write_report_bundle(output_parent, "HCAS-TEST-01", report)

    target = output_parent / "HCAS-TEST-01"
    assert {path.name: path.read_bytes() for path in target.iterdir()} == {
        "owner.txt": b"pre-existing owner bytes"
    }
    assert (output_parent / ".HCAS-TEST-01.staging").is_dir()


def test_cli_incomplete_remote_evidence_writes_bundle_and_exits_four(tmp_path: Path):
    repo = create_deleted_pack_repo(tmp_path)
    output_parent = tmp_path / "evidence"

    result = _run(
        *_audit_args(repo, output_parent, "HCAS-TEST-01"),
        "--remote",
        "missing-remote",
    )

    assert result.returncode == 4, result.stdout
    response = json.loads(result.stdout)
    assert response["status"] == "incomplete"
    report = json.loads((output_parent / "HCAS-TEST-01" / "audit.json").read_text("utf-8"))
    assert report["summary"]["audit_complete"] is False
    assert report["remote"]["tree_comparison"] == "unavailable"
    assert all("preferred" not in option for option in report["decision_options"])


def test_cli_default_requests_exact_local_fixture_remote_evidence(tmp_path: Path):
    repo = create_deleted_pack_repo(tmp_path)
    output_parent = tmp_path / "evidence"

    result = _run(*_audit_args(repo, output_parent, "HCAS-TEST-01"))

    assert result.returncode == 0, result.stdout
    report = json.loads((output_parent / "HCAS-TEST-01" / "audit.json").read_text("utf-8"))
    assert report["summary"]["audit_complete"] is True
    assert report["remote"] == {
        "requested": True,
        "name": REMOTE_NAME,
        "ref": REMOTE_REF,
        "oid": report["head_sha"],
        "object_available_locally": True,
        "tree_comparison": "identical",
        "error": None,
    }
