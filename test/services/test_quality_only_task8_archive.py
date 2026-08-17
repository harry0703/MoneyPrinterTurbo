import csv
import hashlib
import re
from pathlib import Path


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _result_sections(markdown: str) -> str:
    """Return only explicit approval/result sections, not frozen handoff schema text."""
    sections = []
    heading_pattern = re.compile(r"^##+\s+(.+?)\s*$", re.MULTILINE)
    headings = list(heading_pattern.finditer(markdown))
    for index, heading in enumerate(headings):
        title = heading.group(1).lower()
        if not re.search(r"(?:审核结果|审批结果|approval|review result|result)", title):
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
        sections.append(markdown[heading.start() : end])
    return "\n".join(sections)


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

    superseded = SUPERSEDED_PATH.read_text(encoding="utf-8")
    normalized = superseded.lower()
    assert "docs/superpowers/specs/2026-08-17-quality-only-general-wellness-design.md" in superseded
    assert "historical" in normalized and "not approved" in normalized
    assert "no external review response was consumed" in normalized
    assert "no reviewer identity, timestamp, public key, or signature is asserted" in normalized
    assert "automated safety checks" in normalized and "manual publishing" in normalized
    assert "legacy/medical profiles are unaffected" in normalized

    forbidden = ("胡秋生", "陈晓亮", "2026-08-17T15:30:00+08:00", "signature", "private_key")
    approval_result_text = _result_sections(superseded)
    for handoff_id in HANDOFF_IDS:
        handoff = (REPO_ROOT / ARCHIVE_ROOT / "handoffs" / f"{handoff_id}-review-handoff-v01.md").read_text(
            encoding="utf-8"
        )
        approval_result_text += "\n" + _result_sections(handoff)
    for forbidden_value in forbidden:
        assert forbidden_value not in approval_result_text
