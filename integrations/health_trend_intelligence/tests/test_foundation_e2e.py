from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from health_trend_intelligence.batch import SourceSpec, register_batch
from health_trend_intelligence.canonical import canonical_json_bytes, load_unique_json
from health_trend_intelligence.curation import CuratedBatchResult, curate_batch
from health_trend_intelligence.exchange import (
    ApprovedExchangeResult,
    build_approved_exchange,
    verify_approved_exchange,
)
from health_trend_intelligence.models import (
    APPROVED_DISCLAIMER,
    APPROVED_MEDICAL_RISK_FLAG,
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
TASK8_BASE = "f5f6d900b78cc583272d3f29bb1c6e3976b1109e"
MANUAL_DELETION_COUNT = 240
MANUAL_DELETION_SHA256 = (
    "391aa69f5238ab573788c248ced49824a51a5fa08b4c3c9477d9bbf2eda26db6"
)
SNAPSHOT = datetime(2026, 4, 20, 12, tzinfo=timezone(timedelta(hours=8)))
HASH_KEY = b"task8-completely-synthetic-hash-key-v1"


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
                "risk_flags": [APPROVED_MEDICAL_RISK_FLAG],
                "confidence": ("low", "medium", "high")[(rank - 1) % 3],
                "missing_data": [],
                "disclaimer": APPROVED_DISCLAIMER,
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
            "window_end": "2026-04-30T23:59:59+08:00",
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
    verified = verify_approved_exchange(approved.path, approved.manifest_sha256)

    verify_trend_exchange, import_trend_exchange = _load_task7_api()
    task7_verified = verify_trend_exchange(approved.path, approved.manifest_sha256)
    imported = import_trend_exchange(
        approved.path,
        _fake_repo(path / "fake-moneyprinter-repo"),
        approved.manifest_sha256,
    )
    imported_verified = verify_trend_exchange(imported, approved.manifest_sha256)
    assert verified.candidate_count == task7_verified.candidate_count == 10
    assert imported_verified.manifest_sha256 == approved.manifest_sha256
    return SyntheticRun(layout, curated, approved, imported, approved.manifest_sha256)


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


def _boundary_command(run: SyntheticRun) -> list[str]:
    return [
        sys.executable,
        str(BOUNDARY_SCRIPT),
        "--repo-root",
        str(PROJECT_ROOT),
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
        "--task8-base",
        TASK8_BASE,
        "--expected-media-crawler-commit",
        "d6f7c5bb906b6dac40ddf343ef9e26438a3de092",
        "--expected-manual-deletion-count",
        str(MANUAL_DELETION_COUNT),
        "--expected-manual-deletion-sha256",
        MANUAL_DELETION_SHA256,
    ]


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
    assert all(candidate["risk_flags"] == [APPROVED_MEDICAL_RISK_FLAG] for candidate in approved)
    assert all(candidate["disclaimer"] == APPROVED_DISCLAIMER for candidate in approved)


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
