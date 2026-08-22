from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest

from health_trend_intelligence.batch import SourceSpec, register_batch
from health_trend_intelligence.canonical import canonical_json_bytes, load_unique_json
from health_trend_intelligence.curation import CuratedBatchResult, curate_batch
from health_trend_intelligence.exchange import (
    ApprovedExchangeResult,
    build_approved_exchange,
    verify_approved_exchange,
)
from health_trend_intelligence.privacy import PrivacyHasher
from health_trend_intelligence.storage import DataLayout

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MEDIA_CRAWLER_ROOT = PROJECT_ROOT.parents[2] / "MediaCrawler"
BOUNDARY_SCRIPT = (
    PROJECT_ROOT
    / "integrations"
    / "health_trend_intelligence"
    / "scripts"
    / "verify_boundaries.py"
)
BATCH_ID = "HTI-20260818-08"
MANUAL_DELETION_COUNT = 240
MANUAL_DELETION_SHA256 = (
    "391aa69f5238ab573788c248ced49824a51a5fa08b4c3c9477d9bbf2eda26db6"
)
SNAPSHOT = datetime(2026, 4, 20, 12, tzinfo=timezone(timedelta(hours=8)))
HASH_KEY = b"task8-completely-synthetic-hash-key-v1"
EXPECTED_DISCLAIMER = "该包只是选题情报，不是医学事实来源或可直接发布的脚本。"
EXPECTED_MEDICAL_RISK_FLAG = "medical_claim_unverified"


@dataclass(frozen=True, slots=True)
class SyntheticRun:
    layout: DataLayout
    curated: CuratedBatchResult
    approved: ApprovedExchangeResult
    imported_path: Path
    approved_manifest_sha256: str


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_bytes(b"".join(canonical_json_bytes(record) for record in records))


def _post(platform: str, index: int) -> dict[str, object]:
    post_id = f"{platform}-synthetic-{index:03d}"
    title = f"完全合成健康记录 {platform} {index:03d}"
    if index == 2:
        title = "完全合成近重复睡眠记录"
    if index == 3:
        title = "完全合成联系形状 13800138000 test.person@example.invalid @fake_handle"
    common: dict[str, object] = {
        "title": title,
        "desc": "完全合成离线测试",
        "liked_count": index + 10,
        "comment_count": 2,
        "collected_count": 3,
        "share_count": 1,
        "source_keyword": "睡眠",
    }
    if platform == "dy":
        return {
            **common,
            "aweme_id": post_id,
            "create_time": 1_776_398_400,
            "user_id": f"dy-author-{index:03d}",
            "hashtags": ["睡眠", "健康科普"],
        }
    return {
        **common,
        "note_id": post_id,
        "time": 1_776_398_400_000,
        "creator_hash": f"xhs-author-{index:03d}",
        "tag_list": [{"name": "睡眠"}, {"name": "健康科普"}],
    }


def _posts(platform: str) -> list[dict[str, object]]:
    records = [_post(platform, index) for index in range(150)]
    records[146] = deepcopy(records[0])
    records[147] = deepcopy(records[1])
    records[148]["title"] = "完全合成近重复睡眠记录。"
    records[149]["liked_count"] = "-1"
    return records


def _comment(platform: str, index: int) -> dict[str, object]:
    post_index = index % 140
    content = f"完全合成评论 {platform} {index:03d}"
    if index == 3:
        content = "完全合成联系形状 13900139000 comment@example.invalid @comment_fake"
    common: dict[str, object] = {
        "comment_id": f"{platform}-comment-{index:03d}",
        "content": content,
        "like_count": index + 1,
    }
    if platform == "dy":
        return {
            **common,
            "aweme_id": f"dy-synthetic-{post_index:03d}",
            "create_time": 1_776_402_000,
        }
    return {
        **common,
        "note_id": f"xhs-synthetic-{post_index:03d}",
        "create_time": 1_776_402_000_000,
    }


def _comments(platform: str) -> list[dict[str, object]]:
    records = [_comment(platform, index) for index in range(100)]
    records[98] = deepcopy(records[0])
    records[99]["like_count"] = "invalid-count"
    return records


def _selection(curated_manifest_sha256: str) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    for rank in range(1, 11):
        platform_evidence = {
            "dy": f"完全合成排名证据 {rank:02d}"
        } if rank % 2 else {"xhs": f"完全合成排名证据 {rank:02d}"}
        candidates.append(
            {
                "rank": rank,
                "topic": f"完全合成健康选题 {rank:02d}",
                "platform_rank_evidence": platform_evidence,
                "growth_evidence": [f"完全合成增长证据 {rank:02d}"],
                "user_questions": [f"完全合成问题类别 {rank:02d}"],
                "user_needs": [f"完全合成需求类别 {rank:02d}"],
                "misunderstandings": [f"完全合成误解类别 {rank:02d}"],
                "objections": [f"完全合成异议类别 {rank:02d}"],
                "homogeneity_pattern": f"完全合成同质化模式 {rank:02d}",
                "narrative_gap": f"完全合成叙事缺口 {rank:02d}",
                "original_visual_direction": f"完全合成原创视觉方向 {rank:02d}",
                "risk_flags": [EXPECTED_MEDICAL_RISK_FLAG],
                "confidence": ("low", "medium", "high")[(rank - 1) % 3],
                "missing_data": [],
                "disclaimer": EXPECTED_DISCLAIMER,
            }
        )
    return {
        "schema": "health_trend_selection.v1",
        "batch_id": BATCH_ID,
        "curated_manifest_sha256": curated_manifest_sha256,
        "human_selection_status": "approved",
        "approved_at": "2026-08-18T10:30:00+08:00",
        "candidates": candidates,
    }


def _fake_repo(path: Path) -> Path:
    path.mkdir()
    return path


def _load_task7_api() -> tuple[object, object]:
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from app.services.health_trend_exchange import (
            import_trend_exchange,
            verify_trend_exchange,
        )
    finally:
        sys.path.pop(0)
    return verify_trend_exchange, import_trend_exchange


def _load_boundary_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_hti_task8_boundary", BOUNDARY_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_synthetic_pipeline(path: Path) -> SyntheticRun:
    source_dir = path / "sources"
    source_dir.mkdir(parents=True)
    source_records = {
        "dy-posts.jsonl": _posts("dy"),
        "xhs-posts.jsonl": _posts("xhs"),
        "dy-comments.jsonl": _comments("dy"),
        "xhs-comments.jsonl": _comments("xhs"),
    }
    for name, records in source_records.items():
        _write_jsonl(source_dir / name, records)

    layout = DataLayout.from_root(path / "data-root")
    layout.initialize()
    queries = [
        {
            "query_id": f"{platform}-sleep-v1",
            "platform": platform,
            "keyword": "睡眠",
            "window_start": "2026-04-01T00:00:00+08:00",
            "window_end": "2026-04-20T12:00:00+08:00",
        }
        for platform in ("dy", "xhs")
    ]
    manifest = register_batch(
        layout,
        BATCH_ID,
        queries,
        [
            SourceSpec(source_dir / name, platform, kind)
            for name, platform, kind in (
                ("dy-posts.jsonl", "dy", "posts"),
                ("xhs-posts.jsonl", "xhs", "posts"),
                ("dy-comments.jsonl", "dy", "comments"),
                ("xhs-comments.jsonl", "xhs", "comments"),
            )
        ],
        SNAPSHOT,
    )
    assert sum(source.records for source in manifest.sources) == 500

    curated = curate_batch(layout, BATCH_ID, PrivacyHasher(HASH_KEY))
    selection_path = path / "synthetic-operator-selection.json"
    selection_path.write_bytes(canonical_json_bytes(_selection(curated.manifest_sha256)))
    approved = build_approved_exchange(layout, BATCH_ID, selection_path)
    manifest_sha256 = hashlib.sha256(
        (approved.path / "bundle-manifest.json").read_bytes()
    ).hexdigest()
    assert approved.manifest_sha256 == manifest_sha256
    verified = verify_approved_exchange(approved.path, manifest_sha256)

    verify_trend_exchange, import_trend_exchange = _load_task7_api()
    task7_verified = verify_trend_exchange(approved.path, manifest_sha256)
    imported = import_trend_exchange(
        approved.path,
        _fake_repo(path / "fake-moneyprinter-repo"),
        manifest_sha256,
    )
    imported_verified = verify_trend_exchange(imported, manifest_sha256)
    assert verified.candidate_count == task7_verified.candidate_count == 10
    assert imported_verified.manifest_sha256 == manifest_sha256
    return SyntheticRun(layout, curated, approved, imported, manifest_sha256)


def _tree_snapshot(path: Path) -> dict[str, tuple[int, str]]:
    return {
        child.relative_to(path).as_posix(): (
            len(payload := child.read_bytes()),
            hashlib.sha256(payload).hexdigest(),
        )
        for child in sorted(path.rglob("*"))
        if child.is_file()
    }


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [load_unique_json(line) for line in path.read_bytes().splitlines(keepends=True)]


def _boundary_command(
    run: SyntheticRun,
    *,
    audit_profile: str = "current-worktree-audit",
    repo_root: Path = PROJECT_ROOT,
) -> list[str]:
    return [
        sys.executable,
        str(BOUNDARY_SCRIPT),
        "--audit-profile",
        audit_profile,
        "--repo-root",
        str(repo_root),
        "--media-crawler-root",
        str(MEDIA_CRAWLER_ROOT),
        "--raw-path",
        str(run.layout.raw),
        "--curated-path",
        str(run.curated.path),
        "--approved-path",
        str(run.approved.path),
        "--imported-path",
        str(run.imported_path),
        "--external-manifest-sha256",
        run.approved_manifest_sha256,
    ]


def _contract_summary(candidates: list[dict[str, object]]) -> dict[str, object]:
    evidence_fields = (
        "growth_evidence",
        "misunderstandings",
        "objections",
        "user_needs",
        "user_questions",
    )
    return {
        "schema": "health_trend_evidence_summary.v1",
        "batch_id": BATCH_ID,
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
            for field in evidence_fields
        },
        "risk_flagged_candidate_count": sum(bool(candidate["risk_flags"]) for candidate in candidates),
        "risk_flag_item_count": sum(len(candidate["risk_flags"]) for candidate in candidates),
        "missing_data_candidate_count": sum(bool(candidate["missing_data"]) for candidate in candidates),
        "missing_data_item_count": sum(len(candidate["missing_data"]) for candidate in candidates),
    }


EXECUTABLE_CONFORMANCE_TEXT = {
    "executable_bat": "请勿上传 .bat 文件",
    "executable_cmd": "请勿上传 .cmd 文件",
    "executable_com": "请勿上传 .com 文件",
    "executable_dll": "请勿上传 .dll 文件",
    "executable_exe": "请勿上传 .exe 文件",
    "executable_js": "请勿上传 .js 文件",
    "executable_msi": "请勿上传 .msi 文件",
    "executable_ps1": "请勿上传 .ps1 文件",
    "executable_py": "请勿上传 .py 文件",
    "executable_scr": "请勿上传 .scr 文件",
    "executable_vbs": "请勿上传 .vbs 文件",
    "executable_uppercase": "请勿上传 .EXE 文件",
    "executable_fullwidth": "请勿上传 ．ＰＹ 文件",
    "executable_format_control": "请勿上传 ．Ｐ\u200bＳ１ 文件",
}


def _mutate_contract(value: dict[str, object], vector: str) -> None:
    candidates = value["candidates"]
    assert isinstance(candidates, list)
    if vector == "duplicate_risk_flag":
        candidates[0]["risk_flags"] = [EXPECTED_MEDICAL_RISK_FLAG] * 2
    elif vector == "conflicting_risk_flag":
        candidates[0]["risk_flags"] = [
            EXPECTED_MEDICAL_RISK_FLAG,
            "clinical_review_approved",
        ]
    elif vector == "affirmative_medical_text":
        candidates[0]["growth_evidence"] = ["Medical claim verification passed"]
    elif vector == "single_platform":
        for rank, candidate in enumerate(candidates, start=1):
            candidate["platform_rank_evidence"] = {"dy": f"完全合成排名证据 {rank:02d}"}
    elif vector == "missing_sentinel":
        candidates[0]["growth_evidence"] = ["unknown"]
    elif vector == "strict_numeric_type":
        candidates[0]["rank"] = True
    elif vector == "strict_list_type":
        candidates[0]["growth_evidence"] = "not-a-list"
    elif vector == "disclaimer":
        candidates[0]["disclaimer"] = "已完成医学核验。"
    elif vector == "extra_field":
        candidates[0]["unexpected"] = "synthetic"
    elif vector == "duplicate_topic":
        candidates[1]["topic"] = candidates[0]["topic"]
    elif vector == "schema":
        value["schema"] = "health_trend_selection.v2"
    elif vector == "localhost":
        candidates[0]["growth_evidence"] = ["localhost"]
    elif vector == "ssh_uri":
        candidates[0]["growth_evidence"] = ["ssh://host"]
    elif vector == "raw_record":
        candidates[0]["growth_evidence"] = ["raw_record synthetic excerpt"]
    elif vector == "secret_assignment":
        candidates[0]["growth_evidence"] = ["secret=synthetic-secret"]
    elif vector == "secret_token":
        candidates[0]["growth_evidence"] = ["sk_abcdefghijkl"]
    elif vector in EXECUTABLE_CONFORMANCE_TEXT:
        candidates[0]["growth_evidence"] = [EXECUTABLE_CONFORMANCE_TEXT[vector]]
    else:
        raise AssertionError(f"unknown conformance vector: {vector}")


def _rebound_contract_bundle(
    source: Path,
    root: Path,
    vector: str,
) -> tuple[Path, str]:
    destination = root / vector / BATCH_ID
    shutil.copytree(source, destination)
    top10_path = destination / "top10.json"
    manifest_path = destination / "bundle-manifest.json"
    top10 = load_unique_json(top10_path.read_bytes())
    assert isinstance(top10, list)
    wrapper: dict[str, object] = {"candidates": top10}
    _mutate_contract(wrapper, vector)
    manifest = load_unique_json(manifest_path.read_bytes())
    if vector == "schema":
        manifest["schema"] = "health_trend_exchange.v2"
    else:
        top10_payload = canonical_json_bytes(top10)
        summary_payload = canonical_json_bytes(_contract_summary(top10))
        top10_path.write_bytes(top10_payload)
        (destination / "evidence-summary.json").write_bytes(summary_payload)
        payloads = {
            "evidence-summary.json": summary_payload,
            "top10.json": top10_payload,
        }
        for binding in manifest["files"]:
            payload = payloads[binding["relative_path"]]
            binding["bytes"] = len(payload)
            binding["sha256"] = hashlib.sha256(payload).hexdigest()
    manifest_payload = canonical_json_bytes(manifest)
    manifest_path.write_bytes(manifest_payload)
    return destination, hashlib.sha256(manifest_payload).hexdigest()


def test_foundation_pipeline_is_reproducible_private_and_one_way(tmp_path: Path) -> None:
    first = _run_synthetic_pipeline(tmp_path / "first")
    second = _run_synthetic_pipeline(tmp_path / "second")

    assert first.curated.raw_records == second.curated.raw_records == 500
    assert first.curated.curated_posts + first.curated.curated_comments + first.curated.quarantined_records <= 500
    assert first.curated.quarantined_records == second.curated.quarantined_records == 10
    assert first.curated.duplicate_records == second.curated.duplicate_records == 6
    assert first.curated.pii_redacted_records == second.curated.pii_redacted_records == 4
    assert first.approved.candidate_count == second.approved.candidate_count == 10
    assert _tree_snapshot(first.curated.path) == _tree_snapshot(second.curated.path)
    assert _tree_snapshot(first.approved.path) == _tree_snapshot(second.approved.path)
    assert _tree_snapshot(first.imported_path) == _tree_snapshot(first.approved.path)

    curated_posts = _jsonl(first.curated.path / "posts.jsonl")
    assert len({post["platform"] for post in curated_posts}) == 2
    assert any(post["title_redacted"].endswith("睡眠记录。") for post in curated_posts)
    for platform in ("dy", "xhs"):
        near_duplicates = [
            post
            for post in curated_posts
            if post["platform"] == platform and "完全合成近重复睡眠记录" in post["title_redacted"]
        ]
        assert len(near_duplicates) == 2
        assert len({post["duplicate_cluster_id"] for post in near_duplicates}) == 1
    curated_payload = json.dumps(curated_posts, ensure_ascii=False)
    assert "13800138000" not in curated_payload
    assert "test.person@example.invalid" not in curated_payload
    quarantine = _jsonl(first.curated.path / "quarantine.jsonl")
    assert sum(item["reason_code"] == "invalid_numeric" for item in quarantine) == 4
    approved = load_unique_json((first.approved.path / "top10.json").read_bytes())
    assert all(
        candidate["risk_flags"] == [EXPECTED_MEDICAL_RISK_FLAG]
        for candidate in approved
    )
    assert all(candidate["disclaimer"] == EXPECTED_DISCLAIMER for candidate in approved)


def test_approved_contract_is_bidirectionally_conformant_across_runtimes(
    tmp_path: Path,
) -> None:
    run = _run_synthetic_pipeline(tmp_path / "contract")
    verify_trend_exchange, _ = _load_task7_api()
    assert verify_approved_exchange(
        run.approved.path, run.approved_manifest_sha256
    ).candidate_count == 10
    assert verify_trend_exchange(
        run.approved.path, run.approved_manifest_sha256
    ).candidate_count == 10
    baseline = tmp_path / "producer-valid" / BATCH_ID
    shutil.copytree(run.approved.path, baseline)
    shutil.rmtree(run.approved.path)
    safe_selection = _selection(run.curated.manifest_sha256)
    safe_candidates = safe_selection["candidates"]
    assert isinstance(safe_candidates, list)
    safe_candidates[0]["growth_evidence"] = [
        "请使用 .pythonic 和 .cmdlet 示例，版本号 1.2.3。"
    ]
    safe_selection_path = tmp_path / "selection-safe-extension-like-prose.json"
    safe_selection_path.write_bytes(canonical_json_bytes(safe_selection))
    safe_result = build_approved_exchange(run.layout, BATCH_ID, safe_selection_path)
    assert verify_approved_exchange(
        safe_result.path, safe_result.manifest_sha256
    ).candidate_count == 10
    assert verify_trend_exchange(
        safe_result.path, safe_result.manifest_sha256
    ).candidate_count == 10
    shutil.rmtree(safe_result.path)
    vectors = (
        "duplicate_risk_flag",
        "conflicting_risk_flag",
        "affirmative_medical_text",
        "single_platform",
        "missing_sentinel",
        "strict_numeric_type",
        "strict_list_type",
        "disclaimer",
        "extra_field",
        "duplicate_topic",
        "schema",
        "localhost",
        "ssh_uri",
        "raw_record",
        "secret_assignment",
        "secret_token",
        *EXECUTABLE_CONFORMANCE_TEXT,
    )

    for vector in vectors:
        selection = _selection(run.curated.manifest_sha256)
        _mutate_contract(selection, vector)
        selection_path = tmp_path / f"selection-{vector}.json"
        selection_path.write_bytes(canonical_json_bytes(selection))
        try:
            with pytest.raises(ValueError):
                build_approved_exchange(run.layout, BATCH_ID, selection_path)
        finally:
            if run.approved.path.exists():
                shutil.rmtree(run.approved.path)

        mutated_path, anchor = _rebound_contract_bundle(
            baseline,
            tmp_path / "consumer-vectors",
            vector,
        )
        with pytest.raises(ValueError):
            verify_approved_exchange(mutated_path, anchor)
        with pytest.raises(ValueError):
            verify_trend_exchange(mutated_path, anchor)

    noncanonical_path = tmp_path / "consumer-vectors" / "noncanonical" / BATCH_ID
    shutil.copytree(baseline, noncanonical_path)
    top10_path = noncanonical_path / "top10.json"
    top10 = load_unique_json(top10_path.read_bytes())
    top10_payload = json.dumps(top10, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    top10_path.write_bytes(top10_payload)
    manifest_path = noncanonical_path / "bundle-manifest.json"
    manifest = load_unique_json(manifest_path.read_bytes())
    manifest["files"][1]["bytes"] = len(top10_payload)
    manifest["files"][1]["sha256"] = hashlib.sha256(top10_payload).hexdigest()
    manifest_payload = canonical_json_bytes(manifest)
    manifest_path.write_bytes(manifest_payload)
    noncanonical_anchor = hashlib.sha256(manifest_payload).hexdigest()
    with pytest.raises(ValueError):
        verify_approved_exchange(noncanonical_path, noncanonical_anchor)
    with pytest.raises(ValueError):
        verify_trend_exchange(noncanonical_path, noncanonical_anchor)

    wrong_name = tmp_path / "consumer-vectors" / "wrong-approved-directory"
    shutil.copytree(baseline, wrong_name)
    anchor = hashlib.sha256((wrong_name / "bundle-manifest.json").read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        verify_approved_exchange(wrong_name, anchor)
    with pytest.raises(ValueError):
        verify_trend_exchange(wrong_name, anchor)


def test_boundary_cli_is_canonical_fail_closed_and_payload_safe(tmp_path: Path) -> None:
    run = _run_synthetic_pipeline(tmp_path / "boundary")
    completed = subprocess.run(
        _boundary_command(run),
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    report = load_unique_json(completed.stdout)
    assert completed.stdout == canonical_json_bytes(report)
    assert report == {
        "audit_profile": "current-worktree-audit",
        "approved_verified": True,
        "credentials_detected": False,
        "curated_verified": True,
        "manual_pack_deletion_status_unchanged": True,
        "media_crawler_commit": "d6f7c5bb906b6dac40ddf343ef9e26438a3de092",
        "media_crawler_modified": False,
        "media_detected": False,
        "moneyprinter_import_verified": True,
        "raw_in_git": False,
        "schema": "health_trend_foundation_qa.v1",
    }
    assert str(tmp_path).encode("utf-8") not in completed.stdout
    assert b"13800138000" not in completed.stdout

    missing = _boundary_command(run)
    missing[missing.index("--curated-path") + 1] = str(tmp_path / "missing-curated")
    rejected = subprocess.run(
        missing,
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert str(tmp_path).encode("utf-8") not in rejected.stdout + rejected.stderr


def test_boundary_cli_requires_explicit_audit_profile(tmp_path: Path) -> None:
    run = _run_synthetic_pipeline(tmp_path / "profile-required")
    command = _boundary_command(run)
    index = command.index("--audit-profile")
    del command[index : index + 2]

    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert completed.stdout == b""
    assert b"boundary_verification_failed" in completed.stderr


def test_clean_checkout_profile_passes_fresh_local_clone_without_git_config_mutation(
    tmp_path: Path,
) -> None:
    run = _run_synthetic_pipeline(tmp_path / "clean-profile-data")
    fresh_repo = tmp_path / "r"
    config_path = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={PROJECT_ROOT.as_posix()}",
            "-C",
            str(PROJECT_ROOT),
            "rev-parse",
            "--git-path",
            "config",
        ],
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8").strip()
    main_config = Path(config_path)
    if not main_config.is_absolute():
        main_config = PROJECT_ROOT / main_config
    config_before = main_config.read_bytes()
    source_git_dir = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={PROJECT_ROOT.as_posix()}",
            "-C",
            str(PROJECT_ROOT),
            "rev-parse",
            "--absolute-git-dir",
        ],
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8").strip()
    cloned = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={PROJECT_ROOT.as_posix()}",
            "-c",
            f"safe.directory={Path(source_git_dir).as_posix()}",
            "-c",
            "core.longpaths=true",
            "clone",
            "--no-hardlinks",
            "--quiet",
            str(PROJECT_ROOT),
            str(fresh_repo),
        ],
        capture_output=True,
        check=False,
    )
    assert cloned.returncode == 0, cloned.stderr.decode("utf-8", errors="replace")
    local_config = fresh_repo / "config.toml"
    local_config.write_text("synthetic-clean-profile-local-config=true\n", encoding="utf-8")
    clean_status = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={fresh_repo.as_posix()}",
            "-C",
            str(fresh_repo),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ],
        capture_output=True,
        check=True,
    )
    assert clean_status.stdout == b""

    completed = subprocess.run(
        _boundary_command(
            run,
            audit_profile="clean-checkout-validation",
            repo_root=fresh_repo,
        ),
        cwd=fresh_repo,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    report = load_unique_json(completed.stdout)
    assert completed.stdout == canonical_json_bytes(report)
    assert report["audit_profile"] == "clean-checkout-validation"
    assert report["manual_pack_deletion_status_unchanged"] is True
    assert b"synthetic-clean-profile-local-config" not in completed.stdout + completed.stderr
    assert main_config.read_bytes() == config_before


def test_profile_manual_deletion_contracts_fail_closed(
    boundary_module: ModuleType,
) -> None:
    boundary_module._assert_manual_deletion_contract(
        "current-worktree-audit",
        MANUAL_DELETION_COUNT,
        MANUAL_DELETION_SHA256,
    )
    boundary_module._assert_manual_deletion_contract(
        "clean-checkout-validation",
        0,
        hashlib.sha256(b"").hexdigest(),
    )
    with pytest.raises(boundary_module.BoundaryFailure):
        boundary_module._assert_manual_deletion_contract(
            "current-worktree-audit",
            MANUAL_DELETION_COUNT - 1,
            MANUAL_DELETION_SHA256,
        )
    with pytest.raises(boundary_module.BoundaryFailure):
        boundary_module._assert_manual_deletion_contract(
            "clean-checkout-validation",
            1,
            hashlib.sha256(b"synthetic\n").hexdigest(),
        )


def test_clean_profile_does_not_read_local_config_or_trust_legacy_cache_roots(
    boundary_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = tmp_path / "config.toml"
    legacy_raw = tmp_path / "integrations" / "health_trend_intelligence" / ".test-tmp-task5" / "raw"
    config.write_text("synthetic-local-config=true\n", encoding="utf-8")
    legacy_raw.mkdir(parents=True)
    (legacy_raw / "synthetic.json").write_text("{}\n", encoding="utf-8")
    original_open = Path.open

    def guarded_open(path: Path, *args: object, **kwargs: object):
        if path == config:
            raise AssertionError("clean profile read local config content")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    raw_found, protected = boundary_module._scan_repository_disk(
        tmp_path,
        frozenset(),
        frozenset(),
        "clean-checkout-validation",
    )

    assert raw_found
    assert not protected


def test_boundary_cli_hides_paths_when_runtime_dependencies_are_unavailable() -> None:
    completed = subprocess.run(
        [sys.executable, "-S", str(BOUNDARY_SCRIPT)],
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert completed.stdout == b""
    assert completed.stderr.replace(b"\r\n", b"\n") == b"boundary_verification_failed\n"
    assert str(PROJECT_ROOT).encode("utf-8") not in completed.stderr


@pytest.fixture(scope="module")
def boundary_run(tmp_path_factory: pytest.TempPathFactory) -> SyntheticRun:
    return _run_synthetic_pipeline(tmp_path_factory.mktemp("task8-boundary-attacks"))


@pytest.fixture(scope="module")
def boundary_module() -> ModuleType:
    return _load_boundary_module()


@pytest.mark.parametrize(
    "key",
    [
        "hmac_key",
        "HMAC-Key",
        "ＨＭＡＣ＿ＫＥＹ",
        "hmac_secret",
        "hash_key",
        "signing_key",
        "private_key",
        "secret_key",
        "encryption_key",
        "decryption_key",
        "access_key",
        "client_secret",
        "auth_key",
    ],
)
def test_boundary_credential_key_strategy_covers_keys_and_signing_material(
    boundary_module: ModuleType,
    key: str,
) -> None:
    assert boundary_module._credential_key(key)


@pytest.mark.parametrize(
    "key",
    [
        "hash",
        "sha256",
        "manifest_hash",
        "manifest_sha256",
        "content_hash",
        "file_sha256",
    ],
)
def test_boundary_credential_key_strategy_allows_digest_metadata(
    boundary_module: ModuleType,
    key: str,
) -> None:
    assert not boundary_module._credential_key(key)


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        (
            "boundary-extra.json",
            (
                b'{"outer":{"cookie" : "synthetic-secret",'
                b'"session_id":"synthetic-session",'
                b'"token":"synthetic-token",'
                b'"api-key":"synthetic-api-key",'
                b'"secret":"synthetic-value",'
                b'"password":"synthetic-password",'
                b'"proxy_credentials":"synthetic-proxy"}}\n'
            ),
        ),
        ("duplicate.json", b'{"safe":1,"safe":2}\n'),
        ("nfc-collision.jsonl", '{"é":1,"é":2}\n'.encode()),
        ("mp4-in-bin.bin", b"\x00\x00\x00\x18ftypmp42synthetic"),
        ("webm-in-data.data", b"\x1aE\xdf\xa3synthetic"),
        ("ogg-in-text.txt", b"OggSsynthetic"),
        ("mp3-in-json.data", b"ID3synthetic"),
        ("png-in-json.data", b"\x89PNG\r\n\x1a\nsynthetic"),
        ("jpeg-in-json.data", b"\xff\xd8\xffsynthetic"),
        ("gif-in-json.data", b"GIF89asynthetic"),
        ("riff-in-json.data", b"RIFF\x10\x00\x00\x00WAVEsynthetic"),
        ("media-by-extension.mp4", b"synthetic-non-media-payload"),
    ],
)
def test_boundary_cli_rejects_structured_secrets_and_disguised_media(
    boundary_run: SyntheticRun,
    name: str,
    payload: bytes,
) -> None:
    probe = boundary_run.layout.raw / name
    probe.write_bytes(payload)
    try:
        completed = subprocess.run(
            _boundary_command(boundary_run),
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
        )
    finally:
        probe.unlink()

    assert completed.returncode != 0
    assert completed.stdout == b""
    assert b"synthetic-secret" not in completed.stderr
    assert str(probe).encode("utf-8") not in completed.stderr


def test_boundary_cli_rejects_hmac_key_without_leaking_probe(
    boundary_run: SyntheticRun,
) -> None:
    probe = boundary_run.layout.raw / "hmac-probe.json"
    probe.write_bytes(b'{"hmac_key":"synthetic-test-only-value"}\n')
    try:
        completed = subprocess.run(
            _boundary_command(boundary_run),
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
        )
    finally:
        probe.unlink()

    assert completed.returncode != 0
    assert completed.stdout == b""
    assert b"synthetic-test-only-value" not in completed.stderr
    assert str(probe).encode("utf-8") not in completed.stderr


def test_boundary_cli_allows_hash_and_manifest_digest_metadata(
    boundary_run: SyntheticRun,
) -> None:
    probe = boundary_run.layout.raw / "synthetic-digest-metadata.json"
    probe.write_bytes(
        b'{"hash":"synthetic","sha256":"synthetic",'
        b'"manifest_hash":"synthetic","manifest_sha256":"synthetic",'
        b'"content_hash":"synthetic","file_sha256":"synthetic"}\n'
    )
    try:
        completed = subprocess.run(
            _boundary_command(boundary_run),
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
        )
    finally:
        probe.unlink()

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")


def test_boundary_cli_allows_synthetic_phone_and_email_shapes(
    boundary_run: SyntheticRun,
) -> None:
    probe = boundary_run.layout.raw / "synthetic-shapes.json"
    probe.write_bytes(
        b'{"note":"synthetic phone 13800138000 and test@example.invalid"}\n'
    )
    try:
        completed = subprocess.run(
            _boundary_command(boundary_run),
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
        )
    finally:
        probe.unlink()

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")


def test_boundary_cli_rejects_untracked_protected_config(
    boundary_run: SyntheticRun,
) -> None:
    probe = PROJECT_ROOT / "config.task8-boundary-probe.json"
    assert not probe.exists()
    probe.write_bytes(b'{"synthetic":true}\n')
    try:
        completed = subprocess.run(
            _boundary_command(boundary_run),
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
        )
    finally:
        probe.unlink()

    assert completed.returncode != 0
    assert completed.stdout == b""
    assert str(probe).encode("utf-8") not in completed.stderr


@pytest.mark.parametrize(
    "relative_path",
    [
        Path("app/config/config.task8-r2-probe.json"),
        Path("task8-r2-probe/dependencies/pyproject.toml"),
        Path("task8-r2-probe/dependencies/requirements-task8.txt"),
        Path("task8-r2-probe/dependencies/package-lock.json"),
    ],
)
def test_boundary_cli_rejects_recursive_untracked_protected_config(
    boundary_run: SyntheticRun,
    relative_path: Path,
) -> None:
    probe = PROJECT_ROOT / relative_path
    created_parents: list[Path] = []
    parent = probe.parent
    while parent != PROJECT_ROOT and not parent.exists():
        created_parents.append(parent)
        parent = parent.parent
    probe.parent.mkdir(parents=True, exist_ok=True)
    assert not probe.exists()
    probe.write_bytes(b'{"synthetic":true}\n')
    try:
        completed = subprocess.run(
            _boundary_command(boundary_run),
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
        )
    finally:
        probe.unlink()
        for directory in created_parents:
            directory.rmdir()

    assert completed.returncode != 0
    assert completed.stdout == b""
    assert str(probe).encode("utf-8") not in completed.stderr


@pytest.mark.parametrize(
    "relative_path",
    [
        Path("task8-r3-probe/opaque.uv-cache-hide/raw/synthetic.json"),
        Path("task8-r3-probe/.cache/raw/synthetic.json"),
        Path("app/config/.test-tmp-task8-r3/settings"),
        Path("app/config/task8-r3-nonskip/nested/settings"),
    ],
)
def test_boundary_cli_rejects_unknown_skip_like_raw_and_config_paths(
    boundary_run: SyntheticRun,
    relative_path: Path,
) -> None:
    probe = PROJECT_ROOT / relative_path
    created_parents: list[Path] = []
    parent = probe.parent
    while parent != PROJECT_ROOT and not parent.exists():
        created_parents.append(parent)
        parent = parent.parent
    probe.parent.mkdir(parents=True, exist_ok=True)
    assert not probe.exists()
    probe.write_bytes(b'{"synthetic":true}\n')
    try:
        completed = subprocess.run(
            _boundary_command(boundary_run),
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
        )
    finally:
        probe.unlink()
        for directory in created_parents:
            directory.rmdir()

    assert completed.returncode != 0
    assert completed.stdout == b""
    assert str(probe).encode("utf-8") not in completed.stderr


@pytest.mark.parametrize(
    "relative_path",
    [
        b"task8/.cache/raw/x.json",
        b"task8/.test-tmp-probe/Raw/x.json",
        b"task8/opaque.uv-cache-hide/\xef\xbc\xb2\xef\xbc\xa1\xef\xbc\xb7/x.json",
    ],
)
def test_raw_classifier_cannot_be_disabled_by_skip_like_names(
    boundary_module: ModuleType,
    relative_path: bytes,
) -> None:
    assert boundary_module._is_raw_repository_file(relative_path)


def test_exact_cache_root_does_not_expand_to_nested_same_name(
    boundary_module: ModuleType,
) -> None:
    assert boundary_module._is_exact_controlled_non_data_root((".cache",))
    assert boundary_module._is_exact_controlled_non_data_root((".CACHE",)) is (
        os.name == "nt"
    )
    assert boundary_module._is_under_exact_controlled_non_data_root(
        (".cache", "existing-synthetic-fixture")
    )
    for untrusted_parts in (
        ("task8", ".cache", "synthetic-probe"),
        (".cache-prefix",),
        ("opaque.cache",),
        (".ＣＡＣＨＥ",),
        (".uv-cachｅ-r3",),
    ):
        assert not boundary_module._is_exact_controlled_non_data_root(
            untrusted_parts
        )
        assert not boundary_module._is_under_exact_controlled_non_data_root(
            untrusted_parts
        )
        assert not boundary_module._is_under_exact_controlled_non_data_root(
            (*untrusted_parts, "synthetic-probe")
        )


def test_boundary_cli_rejects_compatibility_cache_root_raw(
    boundary_run: SyntheticRun,
) -> None:
    probe_root = PROJECT_ROOT / ".ＣＡＣＨＥ"
    raw_directory = probe_root / "raw"
    probe = raw_directory / "synthetic.json"
    assert not probe_root.exists()
    raw_directory.mkdir(parents=True)
    probe.write_bytes(b'{"synthetic":true}\n')
    try:
        completed = subprocess.run(
            _boundary_command(boundary_run),
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
        )
    finally:
        probe.unlink()
        raw_directory.rmdir()
        probe_root.rmdir()

    assert completed.returncode != 0
    assert completed.stdout == b""
    assert str(probe).encode("utf-8") not in completed.stderr


@pytest.mark.parametrize(
    "relative_path",
    [
        b"app/config/.cache/settings",
        b"app/config/.test-tmp-probe/settings",
        b"app/config/opaque.uv-cache-hide/settings",
    ],
)
def test_app_config_classifier_protects_extensionless_files_under_skip_like_names(
    boundary_module: ModuleType,
    relative_path: bytes,
) -> None:
    assert boundary_module._is_protected_repository_file(relative_path)


def test_repository_disk_scan_enumerates_unknown_skip_like_directories(
    boundary_module: ModuleType,
    tmp_path: Path,
) -> None:
    raw_probe = tmp_path / "opaque.uv-cache-hide" / "raw" / "synthetic.json"
    config_probe = tmp_path / "app" / "config" / ".test-tmp-probe" / "settings"
    raw_probe.parent.mkdir(parents=True)
    config_probe.parent.mkdir(parents=True)
    raw_probe.write_bytes(b'{"synthetic":true}\n')
    config_probe.write_bytes(b"synthetic=true\n")

    raw_found, protected_untracked = boundary_module._scan_repository_disk(
        tmp_path,
        frozenset(),
        frozenset(),
    )

    assert raw_found
    assert protected_untracked


def test_pinned_config_anchor_rejects_hard_link(
    boundary_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = b"synthetic-local-config\n"
    config = tmp_path / "config.toml"
    alias = tmp_path / "outside-alias.toml"
    config.write_bytes(payload)
    monkeypatch.setattr(boundary_module, "PINNED_LOCAL_CONFIG_BYTES", len(payload))
    monkeypatch.setattr(
        boundary_module,
        "PINNED_LOCAL_CONFIG_SHA256",
        hashlib.sha256(payload).hexdigest(),
    )
    assert boundary_module._matches_pinned_local_config(
        config,
        b"config.toml",
        config.lstat(),
    )

    os.link(config, alias)
    assert config.lstat().st_nlink == 2
    assert not boundary_module._matches_pinned_local_config(
        config,
        b"config.toml",
        config.lstat(),
    )


def test_boundary_cli_allows_untracked_business_json_outside_config_paths(
    boundary_run: SyntheticRun,
) -> None:
    probe_directory = PROJECT_ROOT / "task8-r2-probe" / "business"
    probe = probe_directory / "record.json"
    assert not probe_directory.parent.exists()
    probe_directory.mkdir(parents=True)
    probe.write_bytes(b'{"synthetic":true}\n')
    try:
        completed = subprocess.run(
            _boundary_command(boundary_run),
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
        )
    finally:
        probe.unlink()
        probe_directory.rmdir()
        probe_directory.parent.rmdir()

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")


def test_boundary_cli_rejects_repository_raw_even_when_untracked(
    boundary_run: SyntheticRun,
) -> None:
    raw_directory = PROJECT_ROOT / "integrations" / "health_trend_intelligence" / "raw"
    probe = raw_directory / "task8-boundary-probe.json"
    assert not raw_directory.exists()
    raw_directory.mkdir()
    probe.write_bytes(b'{"synthetic":true}\n')
    try:
        completed = subprocess.run(
            _boundary_command(boundary_run),
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
        )
    finally:
        probe.unlink()
        raw_directory.rmdir()

    assert completed.returncode != 0
    assert completed.stdout == b""
    assert str(probe).encode("utf-8") not in completed.stderr


@pytest.mark.parametrize("raw_component", ["raw", "Raw", "ＲＡＷ"])
def test_boundary_cli_rejects_repository_raw_at_arbitrary_depth(
    boundary_run: SyntheticRun,
    raw_component: str,
) -> None:
    probe_root = PROJECT_ROOT / "task8-r2-probe"
    raw_directory = probe_root / raw_component
    probe = raw_directory / "synthetic.json"
    assert not probe_root.exists()
    raw_directory.mkdir(parents=True)
    probe.write_bytes(b'{"synthetic":true}\n')
    try:
        completed = subprocess.run(
            _boundary_command(boundary_run),
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
        )
    finally:
        probe.unlink()
        raw_directory.rmdir()
        probe_root.rmdir()

    assert completed.returncode != 0
    assert completed.stdout == b""
    assert str(probe).encode("utf-8") not in completed.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction contract")
def test_boundary_cli_rejects_junction_in_original_argument_chain(
    boundary_run: SyntheticRun,
    tmp_path: Path,
) -> None:
    junction = tmp_path / "raw-junction"
    created = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(junction), str(boundary_run.layout.raw)],
        capture_output=True,
        check=False,
    )
    assert created.returncode == 0, created.stderr.decode("utf-8", errors="replace")
    command = _boundary_command(boundary_run)
    command[command.index("--raw-path") + 1] = str(junction)
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
        )
    finally:
        junction.rmdir()

    assert completed.returncode != 0
    assert completed.stdout == b""
    assert str(junction).encode("utf-8") not in completed.stderr


def test_boundary_cli_rejects_caller_selected_audit_anchors(
    boundary_run: SyntheticRun,
) -> None:
    command = _boundary_command(boundary_run)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    command.extend(
        [
            "--task8-base",
            head,
            "--expected-media-crawler-commit",
            "d6f7c5bb906b6dac40ddf343ef9e26438a3de092",
            "--expected-manual-deletion-count",
            str(MANUAL_DELETION_COUNT),
            "--expected-manual-deletion-sha256",
            MANUAL_DELETION_SHA256,
        ]
    )
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert completed.stdout == b""
