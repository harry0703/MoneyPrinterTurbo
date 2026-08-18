from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from health_trend_intelligence.batch import (
    BatchInputError,
    SourceSpec,
    build_retention_report,
    register_batch,
    verify_raw_batch,
)
from health_trend_intelligence.canonical import canonical_json_bytes
from health_trend_intelligence.cli import app
from health_trend_intelligence.models import QuerySpec
from health_trend_intelligence.storage import DataLayout

SNAPSHOT = datetime(2026, 8, 18, 15, 30, tzinfo=timezone(timedelta(hours=8)))


def query(query_id: str = "q-1") -> QuerySpec:
    return QuerySpec(
        query_id=query_id,
        platform="dy",
        keyword="sleep",
        window_start=SNAPSHOT - timedelta(days=1),
        window_end=SNAPSHOT,
    )


def source_file(tmp_path: Path, name: str = "dy-posts.jsonl", payload: bytes | None = None) -> Path:
    path = tmp_path / "sources" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload if payload is not None else b'{"post_id":"p-1","likes":3}\n')
    return path


def source_spec(path: Path, *, platform: str = "dy", record_kind: str = "posts") -> SourceSpec:
    return SourceSpec(path=path, platform=platform, record_kind=record_kind)  # type: ignore[arg-type]


def initialized_layout(tmp_path: Path) -> DataLayout:
    layout = DataLayout.from_root(tmp_path / "data")
    layout.initialize()
    return layout


def register_fixture_batch(
    tmp_path: Path,
    *,
    batch_id: str = "HTI-20260818-01",
    snapshot_at: datetime = SNAPSHOT,
    source: Path | None = None,
) -> tuple[DataLayout, Any]:
    layout = initialized_layout(tmp_path)
    manifest = register_batch(
        layout,
        batch_id,
        (query(),),
        (source_spec(source or source_file(tmp_path)),),
        snapshot_at,
    )
    return layout, manifest


def test_register_is_no_overwrite_and_binds_exact_source_bytes(tmp_path: Path) -> None:
    layout, manifest = register_fixture_batch(tmp_path)

    assert manifest.state == "raw_registered"
    for binding in manifest.sources:
        registered = layout.raw / manifest.batch_id / binding.relative_path
        payload = registered.read_bytes()
        assert binding.sha256 == hashlib.sha256(payload).hexdigest()
        assert binding.bytes == len(payload)
        assert binding.records == 1

    with pytest.raises(FileExistsError):
        register_batch(
            layout,
            manifest.batch_id,
            (query(),),
            (source_spec(source_file(tmp_path)),),
            SNAPSHOT,
        )


@pytest.mark.parametrize(
    "name",
    ["clip-video.jsonl", "cookies.jsonl", "profile.jsonl", "voice-audio.jsonl"],
)
def test_registration_rejects_media_and_credential_file_names(
    tmp_path: Path, name: str
) -> None:
    layout = initialized_layout(tmp_path)

    with pytest.raises(BatchInputError):
        register_batch(
            layout,
            "HTI-20260818-01",
            (query(),),
            (source_spec(source_file(tmp_path, name)),),
            SNAPSHOT,
        )

    assert not (layout.raw / "HTI-20260818-01").exists()


def test_registration_rejects_source_symlink_before_destination_creation(tmp_path: Path) -> None:
    layout = initialized_layout(tmp_path)
    actual = source_file(tmp_path)
    linked = actual.with_name("linked.jsonl")
    try:
        os.symlink(actual, linked)
    except OSError as error:
        pytest.skip(f"current account cannot create file symlinks: {error.winerror}")

    with pytest.raises(BatchInputError):
        register_batch(
            layout,
            "HTI-20260818-01",
            (query(),),
            (source_spec(linked),),
            SNAPSHOT,
        )

    assert not (layout.raw / "HTI-20260818-01").exists()


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff\n",
        b'{"post_id":"p-1"}\n\n',
        b"[]\n",
        b'{"post_id":"p-1","post_id":"p-2"}\n',
        '{"é":1,"é":2}\n'.encode(),
        b'{"nested":{"phone_number":"123"}}\n',
        b'{"nested":[{"access_token":"value"}]}\n',
    ],
)
def test_registration_rejects_invalid_or_sensitive_jsonl(
    tmp_path: Path, payload: bytes
) -> None:
    layout = initialized_layout(tmp_path)

    with pytest.raises(BatchInputError):
        register_batch(
            layout,
            "HTI-20260818-01",
            (query(),),
            (source_spec(source_file(tmp_path, payload=payload)),),
            SNAPSHOT,
        )

    assert not (layout.raw / "HTI-20260818-01").exists()


@pytest.mark.parametrize("count", [0, 51])
def test_registration_rejects_query_count_outside_one_to_fifty(
    tmp_path: Path, count: int
) -> None:
    layout = initialized_layout(tmp_path)
    queries = tuple(query(f"q-{index}") for index in range(count))

    with pytest.raises(BatchInputError):
        register_batch(
            layout,
            "HTI-20260818-01",
            queries,
            (source_spec(source_file(tmp_path)),),
            SNAPSHOT,
        )

    assert not (layout.raw / "HTI-20260818-01").exists()


def test_registration_rejects_same_destination_name_before_writing(tmp_path: Path) -> None:
    layout = initialized_layout(tmp_path)
    first = source_file(tmp_path / "first", "posts.jsonl")
    second = source_file(tmp_path / "second", "posts.jsonl")

    with pytest.raises(BatchInputError):
        register_batch(
            layout,
            "HTI-20260818-01",
            (query(),),
            (source_spec(first), source_spec(second, platform="xhs")),
            SNAPSHOT,
        )

    assert not (layout.raw / "HTI-20260818-01").exists()


def test_registration_rejects_relative_source_path(tmp_path: Path) -> None:
    layout = initialized_layout(tmp_path)

    with pytest.raises(BatchInputError):
        register_batch(
            layout,
            "HTI-20260818-01",
            (query(),),
            (source_spec(Path("relative.jsonl")),),
            SNAPSHOT,
        )

    assert not (layout.raw / "HTI-20260818-01").exists()


def test_source_change_between_validation_and_copy_fails_without_manifest(tmp_path: Path) -> None:
    layout = initialized_layout(tmp_path)
    first = source_file(tmp_path / "first", "first.jsonl", b'{"padding":"' + b"x" * 8_000_000 + b'"}\n')
    second = source_file(tmp_path / "second", "second.jsonl")
    batch_dir = layout.raw / "HTI-20260818-01"
    changed = threading.Event()

    def change_second_after_validation() -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if batch_dir.exists():
                second.write_bytes(b'{"post_id":"changed"}\n')
                changed.set()
                return
            time.sleep(0.001)

    worker = threading.Thread(target=change_second_after_validation)
    worker.start()
    try:
        with pytest.raises(BatchInputError):
            register_batch(
                layout,
                "HTI-20260818-01",
                (query(),),
                (source_spec(first), source_spec(second)),
                SNAPSHOT,
            )
    finally:
        worker.join(timeout=10)

    assert changed.is_set()
    assert not (batch_dir / "batch-manifest.json").exists()


def test_verify_detects_registered_file_and_manifest_tampering(tmp_path: Path) -> None:
    layout, manifest = register_fixture_batch(tmp_path)
    binding = manifest.sources[0]
    registered = layout.raw / manifest.batch_id / binding.relative_path
    registered.write_bytes(b'{"post_id":"tampered"}\n')

    with pytest.raises(BatchInputError):
        verify_raw_batch(layout, manifest.batch_id)

    registered.write_bytes(b'{"post_id":"p-1","likes":3}\n')
    manifest_path = layout.raw / manifest.batch_id / "batch-manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["query_manifest_sha256"] = "0" * 64
    manifest_path.write_bytes(canonical_json_bytes(data))

    with pytest.raises(BatchInputError):
        verify_raw_batch(layout, manifest.batch_id)


def test_query_manifest_hash_is_bound_to_canonical_bytes(tmp_path: Path) -> None:
    layout, manifest = register_fixture_batch(tmp_path)
    query_path = layout.raw / manifest.batch_id / "query-manifest.json"
    assert manifest.query_manifest_sha256 == hashlib.sha256(query_path.read_bytes()).hexdigest()

    query_path.write_bytes(query_path.read_bytes().replace(b"\n", b" \n"))
    with pytest.raises(BatchInputError):
        verify_raw_batch(layout, manifest.batch_id)


def test_verify_reapplies_forbidden_filename_policy_to_tampered_manifest(
    tmp_path: Path,
) -> None:
    layout, manifest = register_fixture_batch(tmp_path)
    batch_dir = layout.raw / manifest.batch_id
    original = batch_dir / manifest.sources[0].relative_path
    forbidden = original.with_name("access-token.jsonl")
    original.rename(forbidden)
    manifest_path = batch_dir / "batch-manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["sources"][0]["relative_path"] = "inputs/access-token.jsonl"
    manifest_path.write_bytes(canonical_json_bytes(data))

    with pytest.raises(BatchInputError):
        verify_raw_batch(layout, manifest.batch_id)


def test_retention_report_uses_exact_thirty_day_instant_across_timezones(
    tmp_path: Path,
) -> None:
    layout, _ = register_fixture_batch(tmp_path, batch_id="HTI-20260818-01")
    second_source = source_file(tmp_path / "later")
    register_batch(
        layout,
        "HTI-20260818-02",
        (query(),),
        (source_spec(second_source),),
        SNAPSHOT + timedelta(seconds=1),
    )
    as_of = (SNAPSHOT + timedelta(days=30, microseconds=1)).astimezone(timezone.utc)

    report = build_retention_report(layout, as_of)

    assert [(entry.batch_id, entry.age_days, entry.eligible_for_manual_deletion) for entry in report] == [
        ("HTI-20260818-01", 30, True)
    ]
    assert (layout.raw / "HTI-20260818-01" / "batch-manifest.json").is_file()


def test_cli_returns_three_without_echoing_secret_or_source_path(tmp_path: Path) -> None:
    root = tmp_path / "data"
    source = source_file(tmp_path, "access-token.jsonl")
    queries_path = tmp_path / "queries.json"
    queries_path.write_bytes(canonical_json_bytes([query().model_dump(mode="json")]))
    source_spec_path = tmp_path / "sources.json"
    source_spec_path.write_bytes(
        canonical_json_bytes(
            [{"path": str(source), "platform": "dy", "record_kind": "posts"}]
        )
    )
    runner = CliRunner()
    assert runner.invoke(app, ["init", "--root", str(root)]).exit_code == 0

    result = runner.invoke(
        app,
        [
            "register",
            "--root",
            str(root),
            "--batch-id",
            "HTI-20260818-01",
            "--queries",
            str(queries_path),
            "--source",
            str(source_spec_path),
            "--snapshot-at",
            SNAPSHOT.isoformat(),
        ],
    )

    assert result.exit_code == 3
    assert "token" not in result.output.casefold()
    assert str(source) not in result.output
    assert "post_id" not in result.output


def test_cli_usage_errors_also_return_three() -> None:
    result = CliRunner().invoke(app, ["verify-raw"])

    assert result.exit_code == 3


def test_cli_success_smoke_uses_only_batch_metadata(tmp_path: Path) -> None:
    root = tmp_path / "data"
    source = source_file(tmp_path)
    queries_path = tmp_path / "queries.json"
    queries_path.write_bytes(canonical_json_bytes([query().model_dump(mode="json")]))
    source_spec_path = tmp_path / "sources.json"
    source_spec_path.write_bytes(
        canonical_json_bytes(
            [{"path": str(source), "platform": "dy", "record_kind": "posts"}]
        )
    )
    runner = CliRunner()

    results = [
        runner.invoke(app, ["init", "--root", str(root)]),
        runner.invoke(
            app,
            [
                "register",
                "--root",
                str(root),
                "--batch-id",
                "HTI-20260818-01",
                "--queries",
                str(queries_path),
                "--source",
                str(source_spec_path),
                "--snapshot-at",
                SNAPSHOT.isoformat(),
            ],
        ),
        runner.invoke(
            app,
            ["verify-raw", "--root", str(root), "--batch-id", "HTI-20260818-01"],
        ),
        runner.invoke(
            app,
            [
                "retention-report",
                "--root",
                str(root),
                "--as-of",
                (SNAPSHOT + timedelta(days=31)).isoformat(),
            ],
        ),
    ]

    assert [result.exit_code for result in results] == [0, 0, 0, 0]
    output = "".join(result.output for result in results)
    assert str(source) not in output
    assert "post_id" not in output
