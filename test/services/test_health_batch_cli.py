from __future__ import annotations

import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLI = PROJECT_ROOT / "09_泛健康日更" / "scripts" / "health_batch.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def _topics_payload() -> dict:
    return {
        "schema": "health-topic-input-v1",
        "content_profile": "general_wellness_uncredentialed",
        "topics": [
            {
                "slot": slot,
                "category": f"lifestyle_{slot}",
                "topic": f"第{slot}个日常习惯观察",
                "audience": "35-60岁关注日常生活习惯的人群",
            }
            for slot in range(1, 11)
        ],
    }


def test_start_batch_creates_versioned_inventory_and_status_is_read_only(tmp_path):
    output = tmp_path / "inventory"

    started = _run("start-batch", "--date", "20260809", "--output", str(output))

    assert started.returncode == 0, started.stderr
    payload = json.loads(started.stdout)
    assert payload["status"] == "research_pending"
    assert payload["topic_count"] == 10
    active = output / "active-batch.json"
    versioned = output / "batches" / "20260809" / "active-batch.json"
    first_wave = output / "batches" / "20260809" / "first-wave-inputs.json"
    report = output / "batches" / "20260809" / "dry-run-report.json"
    assert active.exists()
    assert versioned.exists()
    assert first_wave.exists()
    assert report.exists()

    before = active.read_bytes()
    status = _run("status", "--batch", str(active))
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["topic_count"] == 10
    assert active.read_bytes() == before


def test_start_batch_refuses_to_overwrite_existing_inventory(tmp_path):
    output = tmp_path / "inventory"
    first = _run("start-batch", "--date", "20260809", "--output", str(output))
    assert first.returncode == 0, first.stderr

    repeated = _run("start-batch", "--date", "20260809", "--output", str(output))

    assert repeated.returncode == 3
    assert "已存在" in json.loads(repeated.stdout)["error"]


def test_start_batch_accepts_validated_general_wellness_topics_file(tmp_path):
    output = tmp_path / "inventory"
    topics_file = tmp_path / "topics.json"
    topics_file.write_text(
        json.dumps(_topics_payload(), ensure_ascii=False), encoding="utf-8"
    )

    started = _run(
        "start-batch",
        "--date",
        "20260810",
        "--output",
        str(output),
        "--topics-file",
        str(topics_file),
    )

    assert started.returncode == 0, started.stdout
    active = json.loads((output / "active-batch.json").read_text("utf-8"))
    version_root = output / "batches" / "20260810"
    first_wave = json.loads(
        (version_root / "first-wave-inputs.json").read_text("utf-8")
    )
    report = json.loads((version_root / "dry-run-report.json").read_text("utf-8"))
    assert active["content_profile"] == "general_wellness_uncredentialed"
    assert first_wave["content_profile"] == "general_wellness_uncredentialed"
    assert report["content_profile"] == "general_wellness_uncredentialed"
    assert first_wave["audience"] == active["topics"][0]["audience"]
    assert {topic["audience"] for topic in active["topics"]} == {
        first_wave["audience"]
    }
    assert [topic["content_id"] for topic in active["topics"]] == [
        f"HC20260810-{slot:03d}" for slot in range(1, 11)
    ]


def test_start_batch_rejects_mixed_topic_audiences_before_creating_output(tmp_path):
    payload = _topics_payload()
    payload["topics"][-1]["audience"] = "35-60岁关注午后节奏的人群"
    topics_file = tmp_path / "mixed-audiences.json"
    topics_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "inventory"

    started = _run(
        "start-batch",
        "--date",
        "20260810",
        "--output",
        str(output),
        "--topics-file",
        str(topics_file),
    )

    assert started.returncode == 3, started.stdout
    assert not output.exists()


def test_start_batch_rejects_invalid_topics_file_before_creating_output(tmp_path):
    invalid_payloads = []

    nine_topics = _topics_payload()
    nine_topics["topics"] = nine_topics["topics"][:9]
    invalid_payloads.append(nine_topics)

    duplicate_slots = _topics_payload()
    duplicate_slots["topics"][1]["slot"] = 1
    invalid_payloads.append(duplicate_slots)

    forbidden_copy = _topics_payload()
    forbidden_copy["topics"][0]["topic"] = "需要去医院检查的日常状态"
    invalid_payloads.append(forbidden_copy)

    unknown_profile = _topics_payload()
    unknown_profile["content_profile"] = "unknown_profile"
    invalid_payloads.append(unknown_profile)

    for index, payload in enumerate(invalid_payloads):
        topics_file = tmp_path / f"invalid-{index}.json"
        topics_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        output = tmp_path / f"inventory-{index}"

        started = _run(
            "start-batch",
            "--date",
            "20260810",
            "--output",
            str(output),
            "--topics-file",
            str(topics_file),
        )

        assert started.returncode == 3, started.stdout
        assert not output.exists()


@pytest.mark.parametrize("field", ("category", "topic", "audience"))
@pytest.mark.parametrize("invalid_value", (None, 42, True, [], {}))
def test_start_batch_rejects_non_string_topic_text_without_creating_output(
    tmp_path, field, invalid_value
):
    payload = _topics_payload()
    payload["topics"][0][field] = invalid_value
    topics_file = tmp_path / f"invalid-{field}.json"
    topics_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "inventory"

    started = _run(
        "start-batch",
        "--date",
        "20260810",
        "--output",
        str(output),
        "--topics-file",
        str(topics_file),
    )

    assert started.returncode == 3, started.stdout
    assert not output.exists()


def test_next_daily_returns_earliest_unfinished_topic_without_mutating_batch(tmp_path):
    output = tmp_path / "inventory"
    started = _run("start-batch", "--date", "20260809", "--output", str(output))
    assert started.returncode == 0, started.stderr
    batch_path = output / "active-batch.json"
    before = batch_path.read_bytes()

    selected = _run("next-daily", "--batch", str(batch_path))

    assert selected.returncode == 0, selected.stderr
    payload = json.loads(selected.stdout)
    assert payload["content_id"] == "HC20260809-001"
    assert payload["state"] == "research_pending"
    assert batch_path.read_bytes() == before


def test_advance_updates_active_batch_atomically_without_skipping_states(tmp_path):
    from test.services.test_health_content import _approved_manifest

    output = tmp_path / "inventory"
    started = _run("start-batch", "--date", "20260809", "--output", str(output))
    assert started.returncode == 0, started.stderr
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(_approved_manifest(), ensure_ascii=False), encoding="utf-8"
    )
    batch_path = output / "active-batch.json"

    advanced = _run(
        "advance",
        "--batch",
        str(batch_path),
        "--content-id",
        "HC20260809-001",
        "--to",
        "medical_review_pending",
        "--manifest",
        str(manifest_path),
    )

    assert advanced.returncode == 0, advanced.stderr
    stored = json.loads(batch_path.read_text(encoding="utf-8"))
    assert stored["topics"][0]["state"] == "medical_review_pending"
    assert not (output / ".batch-mutation.lock").exists()
    assert not list(output.glob(".batch-mutation-*.journal.json"))

    skipped = _run(
        "advance",
        "--batch",
        str(batch_path),
        "--content-id",
        "HC20260809-001",
        "--to",
        "production",
        "--manifest",
        str(manifest_path),
    )
    assert skipped.returncode == 3
    assert "非法状态跃迁" in json.loads(skipped.stdout)["error"]


def test_prepare_quality_only_updates_only_review_policy_atomically(tmp_path):
    from test.services.test_health_content import _general_wellness_manifest

    manifest = _general_wellness_manifest()
    manifest["medical_review"]["status"] = "pending"
    manifest["final_qa"]["status"] = "pending"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    result = _run("prepare-quality-only", "--manifest", str(manifest_path))

    assert result.returncode == 0, result.stdout
    stored = json.loads(manifest_path.read_text("utf-8"))
    assert stored["medical_review"] == {
        "status": "not_required",
        "reviewer": "",
        "reviewed_at": "",
        "notes": "一般生活方式内容不要求外部医学审核。",
    }
    assert stored["final_qa"] == {
        "status": "not_required",
        "reviewer": "",
        "reviewed_at": "",
    }
    assert stored["automated_qa"] == {"status": "pending", "checked_at": ""}
    assert not list(tmp_path.glob(".*.tmp"))


def test_prepare_quality_only_rejects_legacy_without_rewriting(tmp_path):
    from test.services.test_health_content import _approved_manifest

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(_approved_manifest(), ensure_ascii=False), encoding="utf-8"
    )
    before = manifest_path.read_bytes()

    result = _run("prepare-quality-only", "--manifest", str(manifest_path))

    assert result.returncode == 3, result.stdout
    assert manifest_path.read_bytes() == before
    assert not list(tmp_path.glob(".*.tmp"))


def test_general_direct_production_updates_active_reference_and_rejects_skips(tmp_path):
    from test.services.test_health_content import _general_wellness_manifest

    output = tmp_path / "inventory"
    topics_file = tmp_path / "topics.json"
    topics_file.write_text(
        json.dumps(_topics_payload(), ensure_ascii=False), encoding="utf-8"
    )
    started = _run(
        "start-batch",
        "--date",
        "20260810",
        "--output",
        str(output),
        "--topics-file",
        str(topics_file),
    )
    assert started.returncode == 0, started.stdout
    batch_path = output / "active-batch.json"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(_general_wellness_manifest(), ensure_ascii=False), encoding="utf-8"
    )

    skipped = _run(
        "advance",
        "--batch",
        str(batch_path),
        "--content-id",
        "HC20260810-001",
        "--to",
        "automated_qa_passed",
        "--manifest",
        str(manifest_path),
    )
    assert skipped.returncode == 3, skipped.stdout
    assert "非法状态跃迁" in json.loads(skipped.stdout)["error"]

    result = _run(
        "advance",
        "--batch",
        str(batch_path),
        "--content-id",
        "HC20260810-001",
        "--to",
        "production",
        "--manifest",
        str(manifest_path),
    )

    assert result.returncode == 0, result.stdout
    active_bytes = batch_path.read_bytes()
    active = json.loads(active_bytes)
    current_ref = json.loads((output / "current-batch-ref.json").read_text("utf-8"))
    assert active["topics"][0]["state"] == "production"
    assert current_ref["active_sha256"] == sha256(active_bytes).hexdigest()


def test_general_cli_self_reported_qa_cannot_write_state_or_publish_pack(tmp_path):
    from test.services.test_health_content import _general_wellness_manifest

    output = tmp_path / "inventory"
    topics_file = tmp_path / "topics.json"
    topics_file.write_text(
        json.dumps(_topics_payload(), ensure_ascii=False), encoding="utf-8"
    )
    assert _run(
        "start-batch",
        "--date",
        "20260810",
        "--output",
        str(output),
        "--topics-file",
        str(topics_file),
    ).returncode == 0
    batch_path = output / "active-batch.json"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(_general_wellness_manifest(), ensure_ascii=False), encoding="utf-8"
    )
    assert _run(
        "advance",
        "--batch",
        str(batch_path),
        "--content-id",
        "HC20260810-001",
        "--to",
        "production",
        "--manifest",
        str(manifest_path),
    ).returncode == 0
    before = batch_path.read_bytes()
    reference_path = output / "current-batch-ref.json"
    reference_before = reference_path.read_bytes()

    advanced = _run(
        "advance",
        "--batch",
        str(batch_path),
        "--content-id",
        "HC20260810-001",
        "--to",
        "automated_qa_passed",
        "--manifest",
        str(manifest_path),
    )
    pack_path = tmp_path / "publish-pack.json"
    packed = _run(
        "build-publish-pack",
        "--manifest",
        str(manifest_path),
        "--output",
        str(pack_path),
    )

    assert advanced.returncode == 2, advanced.stdout
    assert packed.returncode == 2, packed.stdout
    assert batch_path.read_bytes() == before
    assert reference_path.read_bytes() == reference_before
    assert not pack_path.exists()
    assert not (output / ".batch-mutation.lock").exists()
    assert not list(output.glob(".batch-mutation-*.journal.json"))


def test_general_cli_recomputes_manifest_bound_artifact_evidence(tmp_path):
    from test.services.test_health_content import (
        _general_wellness_manifest,
        _write_quality_only_artifact_evidence,
    )

    output = tmp_path / "inventory"
    topics_file = tmp_path / "topics.json"
    topics_file.write_text(
        json.dumps(_topics_payload(), ensure_ascii=False), encoding="utf-8"
    )
    assert _run(
        "start-batch",
        "--date",
        "20260810",
        "--output",
        str(output),
        "--topics-file",
        str(topics_file),
    ).returncode == 0
    episode_root = tmp_path / "episode"
    manifest = _general_wellness_manifest()
    _write_quality_only_artifact_evidence(episode_root, manifest)
    manifest_path = episode_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    batch_path = output / "active-batch.json"

    assert _run(
        "advance",
        "--batch",
        str(batch_path),
        "--content-id",
        manifest["content_id"],
        "--to",
        "production",
        "--manifest",
        str(manifest_path),
    ).returncode == 0
    assert _run(
        "advance",
        "--batch",
        str(batch_path),
        "--content-id",
        manifest["content_id"],
        "--to",
        "automated_qa_passed",
        "--manifest",
        str(manifest_path),
    ).returncode == 0
    pack_path = tmp_path / "publish-pack.json"
    packed = _run(
        "build-publish-pack",
        "--manifest",
        str(manifest_path),
        "--output",
        str(pack_path),
    )
    advanced = _run(
        "advance",
        "--batch",
        str(batch_path),
        "--content-id",
        manifest["content_id"],
        "--to",
        "ready_to_publish",
        "--manifest",
        str(manifest_path),
    )

    assert packed.returncode == 0, packed.stdout
    assert json.loads(pack_path.read_text(encoding="utf-8"))["status"] == "human_pending"
    assert advanced.returncode == 0, advanced.stdout
    assert json.loads(batch_path.read_text(encoding="utf-8"))["topics"][0]["state"] == "ready_to_publish"


def test_general_cli_ready_to_publish_rechecks_artifact_evidence(tmp_path):
    from test.services.test_health_content import (
        _general_wellness_manifest,
        _write_quality_only_artifact_evidence,
    )

    output = tmp_path / "inventory"
    topics_file = tmp_path / "topics.json"
    topics_file.write_text(
        json.dumps(_topics_payload(), ensure_ascii=False), encoding="utf-8"
    )
    assert _run(
        "start-batch",
        "--date",
        "20260810",
        "--output",
        str(output),
        "--topics-file",
        str(topics_file),
    ).returncode == 0
    episode_root = tmp_path / "episode"
    manifest = _general_wellness_manifest()
    _write_quality_only_artifact_evidence(episode_root, manifest)
    manifest_path = episode_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    batch_path = output / "active-batch.json"
    for target in ("production", "automated_qa_passed"):
        assert _run(
            "advance",
            "--batch",
            str(batch_path),
            "--content-id",
            manifest["content_id"],
            "--to",
            target,
            "--manifest",
            str(manifest_path),
        ).returncode == 0
    (episode_root / "production/v01/05_qa/automated-qa-evidence-v01.json").unlink()
    before = batch_path.read_bytes()
    reference_path = output / "current-batch-ref.json"
    reference_before = reference_path.read_bytes()

    ready = _run(
        "advance",
        "--batch",
        str(batch_path),
        "--content-id",
        manifest["content_id"],
        "--to",
        "ready_to_publish",
        "--manifest",
        str(manifest_path),
    )

    assert ready.returncode == 2, ready.stdout
    assert batch_path.read_bytes() == before
    assert reference_path.read_bytes() == reference_before
    assert not (output / ".batch-mutation.lock").exists()
    assert not list(output.glob(".batch-mutation-*.journal.json"))


def test_metrics_csv_round_trip_preserves_missing_values_and_blocks_duplicates(
    tmp_path,
):
    from app.services import health_content

    path = tmp_path / "metrics.csv"
    rows = [
        {
            "content_id": "HC20260809-001",
            "category": "metabolism",
            "platform": "douyin",
            "format": "video",
            "window_hours": 24,
            "views": 1000,
            "completion_rate": 0.7,
            "save_rate": None,
            "share_rate": 0.01,
            "follow_rate": 0.008,
        }
    ]

    health_content.write_metric_csv(path, rows)
    restored = health_content.parse_metric_csv(path)

    assert restored == rows
    duplicate_path = tmp_path / "duplicates.csv"
    duplicate_path.write_text(path.read_text(encoding="utf-8") * 2, encoding="utf-8")
    try:
        health_content.parse_metric_csv(duplicate_path)
    except health_content.HealthContentError as exc:
        assert "指标" in str(exc)
    else:
        raise AssertionError("重复指标必须被拒绝")
