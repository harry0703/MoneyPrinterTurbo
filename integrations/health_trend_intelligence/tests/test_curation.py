from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from health_trend_intelligence.batch import SourceSpec, register_batch
from health_trend_intelligence.canonical import canonical_json_bytes, load_unique_json
from health_trend_intelligence.cli import app
from health_trend_intelligence.curation import CurationError, curate_batch, verify_curated_batch
from health_trend_intelligence.privacy import PrivacyHasher
from health_trend_intelligence.storage import DataLayout

CHINA_TZ = timezone(timedelta(hours=8))
BATCH_ID = "HTI-20260818-01"


class InjectedInterruption(RuntimeError):
    pass


def _post(post_id: str, *, likes: int = 12, title: str = "合成睡眠建议") -> dict[str, object]:
    return {
        "aweme_id": post_id,
        "title": title,
        "desc": "",
        "create_time": 1_776_398_400,
        "user_id": f"user-{post_id}",
        "source_keyword": "睡眠",
        "liked_count": likes,
        "comment_count": 3,
        "collected_count": 2,
        "share_count": 1,
        "hashtags": ["睡眠"],
    }


def _comment(comment_id: str, post_id: str, *, text: str = "这是合成评论") -> dict[str, object]:
    return {
        "comment_id": comment_id,
        "aweme_id": post_id,
        "create_time": 1_776_402_000,
        "content": text,
        "like_count": 2,
    }


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_bytes(b"".join(canonical_json_bytes(record) for record in records))


def _registered_layout(root: Path) -> DataLayout:
    layout = DataLayout.from_root(root)
    layout.initialize()
    staging = root / "synthetic"
    staging.mkdir()
    posts = staging / "dy_posts.jsonl"
    comments = staging / "dy_comments.jsonl"
    _write_jsonl(posts, [_post("post-a"), _post("post-a", likes=19)])
    _write_jsonl(comments, [_comment("comment-a", "post-a")])
    query = {
        "query_id": "dy-sleep-v1",
        "platform": "dy",
        "keyword": "睡眠",
        "window_start": "2026-04-01T00:00:00+08:00",
        "window_end": "2026-04-30T23:59:59+08:00",
    }
    register_batch(
        layout,
        BATCH_ID,
        [query],
        [
            SourceSpec(posts, "dy", "posts"),
            SourceSpec(comments, "dy", "comments"),
        ],
        datetime(2026, 4, 20, 12, tzinfo=CHINA_TZ),
    )
    return layout


def _tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(child.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(child.read_bytes())
    return digest.hexdigest()


def _curate_fixture(root: Path, event_hook: Callable[[str], None] | None = None):
    layout = _registered_layout(root)
    return curate_batch(layout, BATCH_ID, PrivacyHasher(b"synthetic-test-key"), event_hook)


def test_resume_after_chunk_interrupt_is_byte_identical(tmp_path: Path) -> None:
    interrupted_root = tmp_path / "interrupted"
    layout = _registered_layout(interrupted_root)
    seen = 0

    def raise_after_first_chunk(event: str) -> None:
        nonlocal seen
        if event == "chunk_committed":
            seen += 1
            if seen == 1:
                raise InjectedInterruption

    with pytest.raises(InjectedInterruption):
        curate_batch(
            layout,
            BATCH_ID,
            PrivacyHasher(b"synthetic-test-key"),
            raise_after_first_chunk,
        )

    resumed = curate_batch(layout, BATCH_ID, PrivacyHasher(b"synthetic-test-key"))
    clean = _curate_fixture(tmp_path / "clean")

    assert _tree_sha256(resumed.path) == _tree_sha256(clean.path)


def test_finalize_has_deterministic_counts_and_manifest_bindings(tmp_path: Path) -> None:
    result = _curate_fixture(tmp_path / "root")

    assert result.raw_records == 3
    assert result.curated_posts == 1
    assert result.curated_comments == 1
    assert result.duplicate_records == 1
    assert result.quarantined_records == 0
    assert result.pii_redacted_records == 0
    assert (
        result.manifest_sha256
        == hashlib.sha256((result.path / "curated-manifest.json").read_bytes()).hexdigest()
    )
    assert (result.path / "READY.json").is_file()
    assert verify_curated_batch(DataLayout.from_root(tmp_path / "root"), BATCH_ID) == result


def test_two_clean_roots_are_byte_identical(tmp_path: Path) -> None:
    first = _curate_fixture(tmp_path / "clean-a")
    second = _curate_fixture(tmp_path / "clean-b")

    assert _tree_sha256(first.path) == _tree_sha256(second.path)


def test_final_manifest_and_ready_do_not_capture_machine_specific_values(tmp_path: Path) -> None:
    result = _curate_fixture(tmp_path / "machine-a")

    manifest = (result.path / "curated-manifest.json").read_text(encoding="utf-8")
    ready = (result.path / "READY.json").read_text(encoding="utf-8")

    assert str(tmp_path) not in manifest
    assert str(tmp_path) not in ready
    assert "created_at" not in manifest
    assert "created_at" not in ready


def test_adapter_error_creates_safe_quarantine_without_original_text(tmp_path: Path) -> None:
    root = tmp_path / "root"
    layout = DataLayout.from_root(root)
    layout.initialize()
    source = root / "synthetic-invalid.jsonl"
    secret = "SENSITIVE_SYNTHETIC_ORIGINAL"
    _write_jsonl(source, [{"title": secret}])
    register_batch(
        layout,
        BATCH_ID,
        [
            {
                "query_id": "dy-sleep-v1",
                "platform": "dy",
                "keyword": "睡眠",
                "window_start": "2026-04-01T00:00:00+08:00",
                "window_end": "2026-04-30T23:59:59+08:00",
            }
        ],
        [SourceSpec(source, "dy", "posts")],
        datetime(2026, 4, 20, 12, tzinfo=CHINA_TZ),
    )

    result = curate_batch(layout, BATCH_ID, PrivacyHasher(b"synthetic-test-key"))
    quarantine = (result.path / "quarantine.jsonl").read_bytes()

    assert result.quarantined_records == 1
    assert secret.encode() not in quarantine
    assert set(load_unique_json(quarantine)) == {
        "line_number",
        "platform",
        "reason_code",
        "schema",
        "source_sha256",
    }


def test_verify_rejects_changed_output_and_extra_file(tmp_path: Path) -> None:
    root = tmp_path / "root"
    result = _curate_fixture(root)
    layout = DataLayout.from_root(root)
    posts = result.path / "posts.jsonl"
    original = posts.read_bytes()
    posts.write_bytes(original + b"{}\n")
    with pytest.raises(ValueError):
        verify_curated_batch(layout, BATCH_ID)
    posts.write_bytes(original)
    (result.path / "extra.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError):
        verify_curated_batch(layout, BATCH_ID)


def test_event_hook_exposes_only_stable_stage_names(tmp_path: Path) -> None:
    events: list[str] = []

    _curate_fixture(tmp_path / "root", events.append)

    assert events == [
        "curation_started",
        "chunk_payload_staged",
        "chunk_manifest_staged",
        "chunk_published",
        "checkpoint_temp_written",
        "checkpoint_committed",
        "chunk_committed",
        "chunk_payload_staged",
        "chunk_manifest_staged",
        "chunk_published",
        "checkpoint_temp_written",
        "checkpoint_committed",
        "chunk_committed",
        "finalization_started",
        "final_posts_staged",
        "curated_manifest_staged",
        "ready_temp_written",
        "ready_committed",
        "publication_started",
        "curation_completed",
    ]
    assert all("post-a" not in event and "comment-a" not in event for event in events)


def test_interruption_after_ready_does_not_publish_and_can_resume(tmp_path: Path) -> None:
    root = tmp_path / "root"
    layout = _registered_layout(root)

    def interrupt(event: str) -> None:
        if event == "ready_committed":
            raise InjectedInterruption

    with pytest.raises(InjectedInterruption):
        curate_batch(layout, BATCH_ID, PrivacyHasher(b"synthetic-test-key"), interrupt)

    assert not (layout.curated / BATCH_ID).exists()
    assert (layout.curated / f"{BATCH_ID}.work" / "READY.json").is_file()
    resumed = curate_batch(layout, BATCH_ID, PrivacyHasher(b"synthetic-test-key"))
    clean = _curate_fixture(tmp_path / "clean")
    assert _tree_sha256(resumed.path) == _tree_sha256(clean.path)


def test_changed_completed_chunk_fails_closed_on_resume(tmp_path: Path) -> None:
    root = tmp_path / "root"
    layout = _registered_layout(root)

    def interrupt(event: str) -> None:
        if event == "chunk_committed":
            raise InjectedInterruption

    with pytest.raises(InjectedInterruption):
        curate_batch(layout, BATCH_ID, PrivacyHasher(b"synthetic-test-key"), interrupt)
    chunk = next((layout.curated / f"{BATCH_ID}.work" / "chunks").iterdir())
    target = chunk / "quarantine.jsonl"
    target.write_bytes(target.read_bytes() + b"{}\n")

    with pytest.raises(CurationError):
        curate_batch(layout, BATCH_ID, PrivacyHasher(b"synthetic-test-key"))


def test_comment_hash_with_conflicting_text_fails_entire_batch(tmp_path: Path) -> None:
    root = tmp_path / "root"
    layout = DataLayout.from_root(root)
    layout.initialize()
    staging = root / "synthetic"
    staging.mkdir()
    first = staging / "comments_a.jsonl"
    second = staging / "comments_b.jsonl"
    _write_jsonl(first, [_comment("same-comment", "post-a", text="文本一")])
    _write_jsonl(second, [_comment("same-comment", "post-a", text="文本二")])
    register_batch(
        layout,
        BATCH_ID,
        [
            {
                "query_id": "dy-sleep-v1",
                "platform": "dy",
                "keyword": "睡眠",
                "window_start": "2026-04-01T00:00:00+08:00",
                "window_end": "2026-04-30T23:59:59+08:00",
            }
        ],
        [SourceSpec(first, "dy", "comments"), SourceSpec(second, "dy", "comments")],
        datetime(2026, 4, 20, 12, tzinfo=CHINA_TZ),
    )

    with pytest.raises(CurationError, match="comment_text_conflict"):
        curate_batch(layout, BATCH_ID, PrivacyHasher(b"synthetic-test-key"))
    assert not (layout.curated / BATCH_ID).exists()
    assert not (layout.curated / f"{BATCH_ID}.work" / "READY.json").exists()


def test_identical_comments_deduplicate_and_count_once(tmp_path: Path) -> None:
    root = tmp_path / "root"
    layout = DataLayout.from_root(root)
    layout.initialize()
    first = root / "comments_a.jsonl"
    second = root / "comments_b.jsonl"
    _write_jsonl(first, [_comment("same-comment", "post-a")])
    _write_jsonl(second, [_comment("same-comment", "post-a"), _comment("other", "post-a")])
    register_batch(
        layout,
        BATCH_ID,
        [
            {
                "query_id": "dy-sleep-v1",
                "platform": "dy",
                "keyword": "睡眠",
                "window_start": "2026-04-01T00:00:00+08:00",
                "window_end": "2026-04-30T23:59:59+08:00",
            }
        ],
        [SourceSpec(first, "dy", "comments"), SourceSpec(second, "dy", "comments")],
        datetime(2026, 4, 20, 12, tzinfo=CHINA_TZ),
    )

    result = curate_batch(layout, BATCH_ID, PrivacyHasher(b"synthetic-test-key"))

    assert result.raw_records == 3
    assert result.curated_comments == 2
    assert result.duplicate_records == 1


def test_pii_redaction_count_is_record_based_after_resume(tmp_path: Path) -> None:
    root = tmp_path / "root"
    layout = DataLayout.from_root(root)
    layout.initialize()
    posts = root / "dy_posts.jsonl"
    comments = root / "dy_comments.jsonl"
    _write_jsonl(posts, [_post("post-a", title="合成联系 13800138000")])
    _write_jsonl(comments, [_comment("comment-a", "post-a", text="user@example.com")])
    register_batch(
        layout,
        BATCH_ID,
        [
            {
                "query_id": "dy-sleep-v1",
                "platform": "dy",
                "keyword": "睡眠",
                "window_start": "2026-04-01T00:00:00+08:00",
                "window_end": "2026-04-30T23:59:59+08:00",
            }
        ],
        [SourceSpec(posts, "dy", "posts"), SourceSpec(comments, "dy", "comments")],
        datetime(2026, 4, 20, 12, tzinfo=CHINA_TZ),
    )

    def interrupt(event: str) -> None:
        if event == "chunk_committed":
            raise InjectedInterruption

    with pytest.raises(InjectedInterruption):
        curate_batch(layout, BATCH_ID, PrivacyHasher(b"synthetic-test-key"), interrupt)
    result = curate_batch(layout, BATCH_ID, PrivacyHasher(b"synthetic-test-key"))

    assert result.pii_redacted_records == 2
    assert b"13800138000" not in (result.path / "posts.jsonl").read_bytes()
    assert b"user@example.com" not in (result.path / "comments.jsonl").read_bytes()


def test_checkpoint_is_canonical_sorted_unique_and_raw_bound(tmp_path: Path) -> None:
    result = _curate_fixture(tmp_path / "root")
    checkpoint_payload = (result.path / "checkpoint.json").read_bytes()
    checkpoint = load_unique_json(checkpoint_payload)
    raw_manifest = (tmp_path / "root" / "raw" / BATCH_ID / "batch-manifest.json").read_bytes()

    assert checkpoint_payload == canonical_json_bytes(checkpoint)
    assert checkpoint["completed_source_sha256"] == sorted(
        set(checkpoint["completed_source_sha256"])
    )
    assert checkpoint["raw_manifest_sha256"] == hashlib.sha256(raw_manifest).hexdigest()


def test_suspicious_signal_uses_tested_distribution_boundary(tmp_path: Path) -> None:
    root = tmp_path / "root"
    layout = DataLayout.from_root(root)
    layout.initialize()
    source = root / "synthetic-posts.jsonl"
    records = [_post(f"base-{index}", likes=10) for index in range(4)]
    records.extend([_post("at-boundary", likes=994), _post("below-boundary", likes=993)])
    _write_jsonl(source, records)
    register_batch(
        layout,
        BATCH_ID,
        [
            {
                "query_id": "dy-sleep-v1",
                "platform": "dy",
                "keyword": "睡眠",
                "window_start": "2026-04-01T00:00:00+08:00",
                "window_end": "2026-04-30T23:59:59+08:00",
            }
        ],
        [SourceSpec(source, "dy", "posts")],
        datetime(2026, 4, 20, 12, tzinfo=CHINA_TZ),
    )

    result = curate_batch(layout, BATCH_ID, PrivacyHasher(b"synthetic-test-key"))
    posts = [
        load_unique_json(line) for line in (result.path / "posts.jsonl").read_bytes().splitlines()
    ]
    by_url = {post["source_url_restricted"].rsplit("/", 1)[-1]: post for post in posts}
    manifest = load_unique_json((result.path / "curated-manifest.json").read_bytes())

    assert by_url["at-boundary"]["suspicious_engagement_signal"] is True
    assert by_url["below-boundary"]["suspicious_engagement_signal"] is False
    assert manifest["warnings"] == []


def test_unavailable_suspicious_distribution_is_false_with_warning(tmp_path: Path) -> None:
    result = _curate_fixture(tmp_path / "root")
    post = load_unique_json((result.path / "posts.jsonl").read_bytes())
    manifest = load_unique_json((result.path / "curated-manifest.json").read_bytes())

    assert post["suspicious_engagement_signal"] is False
    assert manifest["warnings"] == ["suspicious_signal_unavailable"]


def test_cli_curate_and_verify_use_metadata_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    _registered_layout(root)
    monkeypatch.setenv("HTI_HASH_KEY", "hex:" + "11" * 32)
    runner = CliRunner()

    curated = runner.invoke(app, ["curate", "--root", str(root), "--batch-id", BATCH_ID])
    verified = runner.invoke(app, ["verify-curated", "--root", str(root), "--batch-id", BATCH_ID])

    assert curated.exit_code == 0
    assert verified.exit_code == 0
    assert curated.output == f"curated {BATCH_ID}\n"
    assert verified.output == f"verified-curated {BATCH_ID}\n"
    assert "post-a" not in curated.output + verified.output


def test_cli_curation_failure_prints_only_identifier_and_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_root = tmp_path / "secret-root-name"
    layout = _registered_layout(secret_root)
    monkeypatch.setenv("HTI_HASH_KEY", "hex:" + "11" * 32)
    result = CliRunner().invoke(
        app, ["verify-curated", "--root", str(secret_root), "--batch-id", BATCH_ID]
    )

    assert result.exit_code == 3
    assert result.output == f"verify-curated {BATCH_ID} directory_unavailable\n"
    assert str(secret_root) not in result.output
    assert not (layout.curated / BATCH_ID).exists()


def test_task3_accepted_noncanonical_raw_curates_successfully(tmp_path: Path) -> None:
    root = tmp_path / "root"
    layout = DataLayout.from_root(root)
    layout.initialize()
    source = root / "dy_posts.jsonl"
    row = _post("post-a")
    reversed_row = dict(reversed(tuple(row.items())))
    source.write_text(json.dumps(reversed_row, ensure_ascii=False, indent=None), encoding="utf-8")
    register_batch(
        layout,
        BATCH_ID,
        [
            {
                "query_id": "dy-sleep-v1",
                "platform": "dy",
                "keyword": "睡眠",
                "window_start": "2026-04-01T00:00:00+08:00",
                "window_end": "2026-04-30T23:59:59+08:00",
            }
        ],
        [SourceSpec(source, "dy", "posts")],
        datetime(2026, 4, 20, 12, tzinfo=CHINA_TZ),
    )

    result = curate_batch(layout, BATCH_ID, PrivacyHasher(b"key-a"))

    assert result.raw_records == 1
    assert result.curated_posts == 1


@pytest.mark.parametrize(
    "event",
    [
        "chunk_payload_staged",
        "chunk_manifest_staged",
        "chunk_published",
        "checkpoint_temp_written",
        "checkpoint_committed",
        "final_posts_staged",
        "curated_manifest_staged",
        "ready_temp_written",
        "ready_committed",
        "publication_started",
        "curation_completed",
    ],
)
def test_every_write_interruption_resumes_to_clean_tree(tmp_path: Path, event: str) -> None:
    root = tmp_path / "interrupted"
    layout = _registered_layout(root)

    def interrupt(observed: str) -> None:
        if observed == event:
            raise InjectedInterruption

    with pytest.raises(InjectedInterruption):
        curate_batch(layout, BATCH_ID, PrivacyHasher(b"key-a"), interrupt)

    resumed = curate_batch(layout, BATCH_ID, PrivacyHasher(b"key-a"))
    clean_layout = _registered_layout(tmp_path / "clean")
    clean = curate_batch(clean_layout, BATCH_ID, PrivacyHasher(b"key-a"))
    assert _tree_sha256(resumed.path) == _tree_sha256(clean.path)


def test_partial_checkpoint_and_ready_temp_are_rebuilt(tmp_path: Path) -> None:
    checkpoint_root = tmp_path / "checkpoint"
    checkpoint_layout = _registered_layout(checkpoint_root)

    def checkpoint_interrupt(event: str) -> None:
        if event == "checkpoint_temp_written":
            raise InjectedInterruption

    with pytest.raises(InjectedInterruption):
        curate_batch(
            checkpoint_layout,
            BATCH_ID,
            PrivacyHasher(b"key-a"),
            checkpoint_interrupt,
        )
    checkpoint_temp = checkpoint_layout.curated / f"{BATCH_ID}.work" / "checkpoint.json.tmp"
    checkpoint_temp.write_bytes(checkpoint_temp.read_bytes()[:17])
    checkpoint_result = curate_batch(checkpoint_layout, BATCH_ID, PrivacyHasher(b"key-a"))

    ready_root = tmp_path / "ready"
    ready_layout = _registered_layout(ready_root)

    def ready_interrupt(event: str) -> None:
        if event == "ready_temp_written":
            raise InjectedInterruption

    with pytest.raises(InjectedInterruption):
        curate_batch(ready_layout, BATCH_ID, PrivacyHasher(b"key-a"), ready_interrupt)
    ready_temp = ready_layout.curated / f"{BATCH_ID}.work" / "READY.json.tmp"
    ready_temp.write_bytes(ready_temp.read_bytes()[:13])
    ready_result = curate_batch(ready_layout, BATCH_ID, PrivacyHasher(b"key-a"))

    clean_layout = _registered_layout(tmp_path / "clean")
    clean = curate_batch(clean_layout, BATCH_ID, PrivacyHasher(b"key-a"))
    assert _tree_sha256(checkpoint_result.path) == _tree_sha256(clean.path)
    assert _tree_sha256(ready_result.path) == _tree_sha256(clean.path)


@pytest.mark.parametrize(
    ("event", "artifact"),
    [
        ("chunk_payload_staged", "post-drafts.jsonl"),
        ("chunk_manifest_staged", "chunk-manifest.json"),
    ],
)
def test_partial_chunk_staging_is_rebuilt(tmp_path: Path, event: str, artifact: str) -> None:
    layout = _registered_layout(tmp_path / "root")

    def interrupt(observed: str) -> None:
        if observed == event:
            raise InjectedInterruption

    with pytest.raises(InjectedInterruption):
        curate_batch(layout, BATCH_ID, PrivacyHasher(b"key-a"), interrupt)
    temporary_chunk = next(
        path
        for path in (layout.curated / f"{BATCH_ID}.work" / "chunks").iterdir()
        if path.name.endswith(".tmp")
    )
    target = temporary_chunk / artifact
    target.write_bytes(target.read_bytes()[:11])

    resumed = curate_batch(layout, BATCH_ID, PrivacyHasher(b"key-a"))
    clean_layout = _registered_layout(tmp_path / "clean")
    clean = curate_batch(clean_layout, BATCH_ID, PrivacyHasher(b"key-a"))
    assert _tree_sha256(resumed.path) == _tree_sha256(clean.path)


def test_partial_published_chunk_fails_closed(tmp_path: Path) -> None:
    layout = _registered_layout(tmp_path / "root")

    def interrupt(observed: str) -> None:
        if observed == "chunk_published":
            raise InjectedInterruption

    with pytest.raises(InjectedInterruption):
        curate_batch(layout, BATCH_ID, PrivacyHasher(b"key-a"), interrupt)
    published_chunk = next(
        path
        for path in (layout.curated / f"{BATCH_ID}.work" / "chunks").iterdir()
        if not path.name.endswith(".tmp")
    )
    (published_chunk / "chunk-manifest.json").unlink()

    with pytest.raises(CurationError, match="unexpected_chunk"):
        curate_batch(layout, BATCH_ID, PrivacyHasher(b"key-a"))


def test_changed_hasher_cannot_resume_completed_chunk(tmp_path: Path) -> None:
    layout = _registered_layout(tmp_path / "root")

    def interrupt(event: str) -> None:
        if event == "chunk_committed":
            raise InjectedInterruption

    with pytest.raises(InjectedInterruption):
        curate_batch(layout, BATCH_ID, PrivacyHasher(b"key-a"), interrupt)

    with pytest.raises(CurationError, match="curation_key_mismatch"):
        curate_batch(layout, BATCH_ID, PrivacyHasher(b"key-b"))


def test_final_comments_reference_a_curated_post(tmp_path: Path) -> None:
    result = _curate_fixture(tmp_path / "root")
    posts = {
        load_unique_json(line)["source_post_key"]
        for line in (result.path / "posts.jsonl").read_bytes().splitlines()
    }
    comments = [
        load_unique_json(line)
        for line in (result.path / "comments.jsonl").read_bytes().splitlines()
    ]

    assert comments
    assert {comment["source_post_key"] for comment in comments} <= posts


@pytest.mark.parametrize("command", ["curate", "verify-curated"])
@pytest.mark.parametrize(
    "untrusted",
    [
        r"C:\synthetic-secret-source\records.jsonl",
        "bad\nrecord-content",
        "post_id=synthetic-secret",
        "hex:" + "ab" * 32,
    ],
)
def test_cli_invalid_batch_id_never_echoes_untrusted_text(
    tmp_path: Path, command: str, untrusted: str
) -> None:
    result = CliRunner().invoke(
        app, [command, "--root", str(tmp_path / "root"), "--batch-id", untrusted]
    )

    assert result.exit_code == 3
    assert untrusted not in result.output
    assert result.output == f"{command} <invalid-batch> invalid_input\n"


def test_curation_completed_observes_published_verified_final(tmp_path: Path) -> None:
    layout = _registered_layout(tmp_path / "root")
    observed: list[str] = []

    def inspect(event: str) -> None:
        if event == "curation_completed":
            final_path = layout.curated / BATCH_ID
            assert final_path.is_dir()
            assert verify_curated_batch(layout, BATCH_ID).path == final_path
            observed.append(event)

    result = curate_batch(layout, BATCH_ID, PrivacyHasher(b"key-a"), inspect)

    assert result.path == layout.curated / BATCH_ID
    assert observed == ["curation_completed"]
