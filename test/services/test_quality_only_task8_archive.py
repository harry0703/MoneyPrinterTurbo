import csv
import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORK_ROOT = Path("09_泛健康日更/work")
ARCHIVE_ROOT = WORK_ROOT / "HC20260810-B01-task8-qa/archive_v00/external-review-superseded"
MANIFEST_PATH = ARCHIVE_ROOT / "ARCHIVE-MANIFEST.csv"
SUPERSEDED_PATH = ARCHIVE_ROOT / "SUPERSEDED.md"

HANDOFF_IDS = tuple(f"HC20260810-{number:03d}" for number in range(1, 11))
SOURCE_HANDOFFS = {
    content_id: WORK_ROOT
    / content_id
    / "production/v01/01_evidence/review-handoff-v01.md"
    for content_id in HANDOFF_IDS
}
SOURCE_BATCH = WORK_ROOT / "HC20260810-B01-review-index.md"
SOURCE_TOOLS = (
    WORK_ROOT / "HC20260810-B01-task8-qa/build-review-handoffs.py",
    WORK_ROOT / "HC20260810-B01-task8-qa/probe-review-transaction.py",
)
RESULT_KEYS = frozenset({"reviewer", "reviewed_at", "decision", "signatures", "signature", "private_key"})
FORBIDDEN_IDENTIFIERS = ("胡秋生", "陈晓亮", "2026-08-17T15:30:00+08:00")
CANONICAL_PAYLOAD_PATTERN = re.compile(
    r"<!-- canonical-payload-start -->\s*\n(.*?)\n<!-- canonical-payload-end -->",
    re.DOTALL,
)
RESULT_HEADING_PATTERN = re.compile(
    r"(?:审核结果|审批结果|外审|review\s*(?:result|decision)?|approval|result|decision|结论)",
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archive_relative_files(archive_root: Path) -> set[str]:
    return {path.relative_to(archive_root).as_posix() for path in archive_root.rglob("*") if path.is_file()}


def _expected_archive_files() -> set[str]:
    return {
        "ARCHIVE-MANIFEST.csv",
        "SUPERSEDED.md",
        "batch/HC20260810-B01-review-index.md",
        "tools/build-review-handoffs.py",
        "tools/probe-review-transaction.py",
        *(f"handoffs/{content_id}-review-handoff-v01.md" for content_id in HANDOFF_IDS),
    }


def _canonical_payload(markdown: str, artifact: Path) -> dict:
    payload_match = CANONICAL_PAYLOAD_PATTERN.search(markdown)
    assert payload_match is not None, f"canonical payload is missing from {artifact}"
    payload = json.loads(payload_match.group(1))
    assert isinstance(payload, dict), f"canonical payload must be an object in {artifact}"
    return payload


def _assert_no_result_keys(payload: dict, artifact: Path) -> None:
    unexpected = RESULT_KEYS.intersection(payload)
    assert not unexpected, f"canonical payload has result keys in {artifact}: {sorted(unexpected)}"


def _assert_non_tool_archive_metadata_is_not_result(archive_root: Path) -> None:
    for relative_path in sorted(_archive_relative_files(archive_root) - {"tools/build-review-handoffs.py", "tools/probe-review-transaction.py"}):
        artifact = archive_root / relative_path
        text = artifact.read_text(encoding="utf-8")
        for heading in re.finditer(r"^##+\s+(.+?)\s*$", text, re.MULTILINE):
            assert not RESULT_HEADING_PATTERN.search(heading.group(1)), f"result heading in {artifact}: {heading.group(1)}"
        for forbidden_identifier in FORBIDDEN_IDENTIFIERS:
            assert forbidden_identifier not in text, f"forbidden review identity or timestamp in {artifact}"
        if "<!-- canonical-payload-start -->" in text:
            _assert_no_result_keys(_canonical_payload(text, artifact), artifact)


def _assert_handoff_payloads_are_awaiting_real_review(archive_root: Path) -> None:
    for content_id in HANDOFF_IDS:
        artifact = archive_root / "handoffs" / f"{content_id}-review-handoff-v01.md"
        payload = _canonical_payload(artifact.read_text(encoding="utf-8"), artifact)
        assert payload.get("status") == "awaiting_real_review", f"handoff status changed in {artifact}"
        _assert_no_result_keys(payload, artifact)


def _temporary_archive_environment(monkeypatch, tmp_path):
    temporary_repo = tmp_path / "repo"
    temporary_archive = temporary_repo / ARCHIVE_ROOT
    shutil.copytree(REPO_ROOT / ARCHIVE_ROOT, temporary_archive)
    monkeypatch.chdir(temporary_repo)
    monkeypatch.setitem(globals(), "REPO_ROOT", temporary_repo)
    return temporary_archive


def _update_manifest_record(archive_root: Path, archive_file: Path) -> None:
    manifest_path = archive_root / "ARCHIVE-MANIFEST.csv"
    with manifest_path.open(newline="", encoding="utf-8") as manifest_file:
        rows = list(csv.DictReader(manifest_file))
        fieldnames = list(rows[0])
    archive_relative = archive_file.relative_to(archive_root).as_posix()
    for row in rows:
        if row["archive_path"].endswith(archive_relative):
            row["bytes"] = str(archive_file.stat().st_size)
            row["sha256"] = _sha256(archive_file)
            break
    else:
        raise AssertionError(f"manifest row missing for {archive_relative}")
    with manifest_path.open("w", newline="", encoding="utf-8") as manifest_file:
        writer = csv.DictWriter(manifest_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_task8_evidence_is_archived_hash_preserved_and_not_live():
    expected_originals = {
        *(path.as_posix() for path in SOURCE_HANDOFFS.values()),
        SOURCE_BATCH.as_posix(),
        *(path.as_posix() for path in SOURCE_TOOLS),
    }
    expected_archives = {
        **{
            source.as_posix(): (ARCHIVE_ROOT / "handoffs" / f"{content_id}-review-handoff-v01.md").as_posix()
            for content_id, source in SOURCE_HANDOFFS.items()
        },
        SOURCE_BATCH.as_posix(): (ARCHIVE_ROOT / "batch/HC20260810-B01-review-index.md").as_posix(),
        SOURCE_TOOLS[0].as_posix(): (ARCHIVE_ROOT / "tools/build-review-handoffs.py").as_posix(),
        SOURCE_TOOLS[1].as_posix(): (ARCHIVE_ROOT / "tools/probe-review-transaction.py").as_posix(),
    }

    archive_root = REPO_ROOT / ARCHIVE_ROOT
    assert _archive_relative_files(archive_root) == _expected_archive_files(), "archive inventory changed"
    assert MANIFEST_PATH.is_file(), "the archive manifest records each pre-move artifact"
    with MANIFEST_PATH.open(newline="", encoding="utf-8") as manifest_file:
        rows = list(csv.DictReader(manifest_file))
    assert set(rows[0]) == {"original_path", "archive_path", "bytes", "sha256"}
    assert len(rows) == 13
    assert {row["original_path"] for row in rows} == expected_originals
    assert {row["archive_path"] for row in rows} == set(expected_archives.values())

    for row in rows:
        original = REPO_ROOT / row["original_path"]
        archived = REPO_ROOT / row["archive_path"]
        assert row["archive_path"] == expected_archives[row["original_path"]]
        assert not original.exists(), f"superseded artifact remains live: {original}"
        assert archived.is_file(), f"archive artifact is missing: {archived}"
        assert int(row["bytes"]) == archived.stat().st_size
        assert re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
        assert _sha256(archived) == row["sha256"]

    active_handoffs = list(
        (REPO_ROOT / WORK_ROOT).glob("HC20260810-*/production/v01/01_evidence/review-handoff-v01.md")
    )
    assert active_handoffs == []
    assert not (REPO_ROOT / SOURCE_BATCH).exists()

    superseded = (REPO_ROOT / SUPERSEDED_PATH).read_text(encoding="utf-8")
    normalized = superseded.lower()
    assert "docs/superpowers/specs/2026-08-17-quality-only-general-wellness-design.md" in superseded
    assert "historical" in normalized and "not approved" in normalized
    assert "no external review response was consumed" in normalized
    assert "no reviewer identity, timestamp, public key, or signature is asserted" in normalized
    assert "automated safety checks" in normalized and "manual publishing" in normalized
    assert "legacy/medical profiles are unaffected" in normalized

    _assert_handoff_payloads_are_awaiting_real_review(archive_root)
    _assert_non_tool_archive_metadata_is_not_result(archive_root)


def test_archive_integrity_rejects_canonical_payload_result(monkeypatch, tmp_path):
    archive_root = _temporary_archive_environment(monkeypatch, tmp_path)
    handoff = archive_root / "handoffs/HC20260810-001-review-handoff-v01.md"
    source = handoff.read_text(encoding="utf-8")
    payload_match = re.search(
        r"<!-- canonical-payload-start -->\s*\n(.*?)\n<!-- canonical-payload-end -->",
        source,
        re.DOTALL,
    )
    assert payload_match is not None
    payload = json.loads(payload_match.group(1))
    payload["reviewer"] = "胡秋生"
    payload["decision"] = "approved"
    payload["signature"] = "forged"
    forged = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    handoff.write_text(source[: payload_match.start(1)] + forged + source[payload_match.end(1) :], encoding="utf-8")
    _update_manifest_record(archive_root, handoff)

    with pytest.raises(AssertionError, match="canonical payload has result keys"):
        test_task8_evidence_is_archived_hash_preserved_and_not_live()


def test_archive_integrity_rejects_alternative_external_result_heading(monkeypatch, tmp_path):
    archive_root = _temporary_archive_environment(monkeypatch, tmp_path)
    handoff = archive_root / "handoffs/HC20260810-001-review-handoff-v01.md"
    handoff.write_text(
        handoff.read_text(encoding="utf-8") + "\n## 外审结论\nreviewer: 陈晓亮\nsignature: forged\n",
        encoding="utf-8",
    )
    _update_manifest_record(archive_root, handoff)

    with pytest.raises(AssertionError, match="result heading"):
        test_task8_evidence_is_archived_hash_preserved_and_not_live()


def test_archive_integrity_rejects_extra_result_file(monkeypatch, tmp_path):
    archive_root = _temporary_archive_environment(monkeypatch, tmp_path)
    (archive_root / "external-review-result.json").write_text(
        '{"reviewer":"胡秋生","decision":"approved","signature":"forged"}',
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match="archive inventory changed"):
        test_task8_evidence_is_archived_hash_preserved_and_not_live()
