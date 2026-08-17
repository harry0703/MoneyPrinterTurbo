from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services import health_content  # noqa: E402


def _dump(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except FileExistsError as exc:
        raise health_content.HealthContentError(f"目标已存在: {path}") from exc


def _read_json(path: str | Path) -> dict:
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise health_content.HealthContentError(f"无法读取JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise health_content.HealthContentError("JSON根对象必须是映射")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def start_batch(args: argparse.Namespace) -> int:
    output = Path(args.output).resolve()
    if output.exists():
        raise health_content.HealthContentError(f"批次输出目录已存在: {output}")
    if args.topics_file is not None:
        topics_payload = _read_json(args.topics_file)
        if topics_payload.get("schema") != "health-topic-input-v1":
            raise health_content.HealthContentError("主题文件 schema 必须为 health-topic-input-v1")
        topics = topics_payload.get("topics")
        if not isinstance(topics, list):
            raise health_content.HealthContentError("主题文件 topics 必须为列表")
        batch = health_content.create_seed_batch(
            args.date,
            topics=topics,
            content_profile=topics_payload.get("content_profile"),
        )
        topic_audiences = {topic["audience"] for topic in batch["topics"]}
        if len(topic_audiences) != 1:
            raise health_content.HealthContentError("主题文件中的 audience 必须完全一致")
        first_wave_audience = topic_audiences.pop()
    else:
        batch = health_content.create_seed_batch(args.date)
        first_wave_audience = "35-60岁关注家庭健康的人群"
    version_root = output / "batches" / args.date
    _write_json(version_root / "active-batch.json", batch)
    _write_json(
        version_root / "first-wave-inputs.json",
        _with_content_profile(
            {
            "schema": "health-first-wave-v1",
            "batch_id": batch["batch_id"],
            "audience": first_wave_audience,
            "content_style": "生活场景动画",
            "article_format": "7页卡片组",
            "platform_strategy": "一母版四包装",
            "topics": batch["topics"],
            },
            batch,
        ),
    )
    _write_json(
        version_root / "dry-run-report.json",
        _with_content_profile(
            {
            "schema": "health-dry-run-v1",
            "batch_id": batch["batch_id"],
            "status": "research_pending",
            "checks": {
                "topic_count": len(batch["topics"]),
                "unique_content_ids": len(
                    {item["content_id"] for item in batch["topics"]}
                ),
                "platforms": list(health_content.PLATFORMS),
                "automatic_publishing": False,
                "medical_review_required": True,
            },
            },
            batch,
        ),
    )
    _write_json(output / "active-batch.json", batch)
    _write_json(
        output / "current-batch-ref.json",
        {
            "schema": "health-batch-ref-v1",
            "batch_id": batch["batch_id"],
            "date": args.date,
            "path": f"batches/{args.date}/active-batch.json",
            "sha256": _sha256(version_root / "active-batch.json"),
            "active_sha256": _sha256(output / "active-batch.json"),
        },
    )
    _dump(
        {
            "status": "research_pending",
            "batch_id": batch["batch_id"],
            "topic_count": len(batch["topics"]),
            "batch": str(output / "active-batch.json"),
            "next_action": "为每个主题补齐权威来源与事实卡，再提交真实医学人工审核",
        }
    )
    return 0


def _with_content_profile(payload: dict, batch: dict) -> dict:
    if "content_profile" in batch:
        payload["content_profile"] = batch["content_profile"]
    return payload


def status(args: argparse.Namespace) -> int:
    batch = _read_json(args.batch)
    states: dict[str, int] = {}
    for topic in batch.get("topics", []):
        state = str(topic.get("state", "unknown"))
        states[state] = states.get(state, 0) + 1
    _dump(
        {
            "batch_id": batch.get("batch_id"),
            "topic_count": len(batch.get("topics", [])),
            "states": states,
            "publication_policy": batch.get("publication_policy"),
        }
    )
    return 0


def next_daily(args: argparse.Namespace) -> int:
    batch = _read_json(args.batch)
    topic = next(
        (
            item
            for item in batch.get("topics", [])
            if item.get("state") not in {"ready_to_publish", "published"}
        ),
        None,
    )
    if topic is None:
        _dump(
            {
                "status": "no_actionable_topic",
                "batch_id": batch.get("batch_id"),
            }
        )
        return 0
    _dump(
        {
            "batch_id": batch.get("batch_id"),
            "content_id": topic.get("content_id"),
            "slot": topic.get("slot"),
            "category": topic.get("category"),
            "topic": topic.get("topic"),
            "state": topic.get("state"),
            "next_action": "补齐权威来源和事实卡"
            if topic.get("state") == "research_pending"
            else "按当前门禁继续处理",
        }
    )
    return 0


def build_publish_pack(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).resolve()
    manifest = _read_json(manifest_path)
    pack = health_content.build_publish_pack(manifest, manifest_path.parent)
    destination = Path(args.output).resolve()
    _write_json(destination, pack)
    _dump(
        {
            "status": pack["status"],
            "content_id": pack["content_id"],
            "output": str(destination),
            "platforms": list(pack["platforms"]),
        }
    )
    return 0


def _atomic_replace_json(path: Path, payload: dict, suffix: str) -> None:
    temporary = path.with_name(f".{path.name}.{suffix}.tmp")
    if temporary.exists():
        raise health_content.HealthContentError(f"检测到遗留临时文件: {temporary}")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def prepare_quality_only(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).resolve()
    manifest = _read_json(manifest_path)
    if manifest.get("content_profile") != health_content.GENERAL_WELLNESS_PROFILE:
        raise health_content.HealthContentError(
            "仅显式 general_wellness_uncredentialed manifest 可切换免外部审核策略"
        )
    manifest["medical_review"] = {
        "status": "not_required",
        "reviewer": "",
        "reviewed_at": "",
        "notes": "一般生活方式内容不要求外部医学审核。",
    }
    manifest["automated_qa"] = {"status": "pending", "checked_at": ""}
    manifest["final_qa"] = {
        "status": "not_required",
        "reviewer": "",
        "reviewed_at": "",
    }
    validated = health_content.validate_manifest(manifest)
    _atomic_replace_json(manifest_path, validated, "quality-only")
    _dump({"status": "quality_only_prepared", "manifest": str(manifest_path)})
    return 0


def advance(args: argparse.Namespace) -> int:
    batch_path = Path(args.batch).resolve()
    batch = _read_json(batch_path)
    manifest_path = Path(args.manifest).resolve()
    manifest = _read_json(manifest_path)
    updated = health_content.advance_topic_state(
        batch, args.content_id, args.to, manifest, manifest_path.parent
    )
    mutation_root = batch_path.parent
    lock_path = mutation_root / ".batch-mutation.lock"
    journals = list(mutation_root.glob(".batch-mutation-*.journal.json"))
    if lock_path.exists() or journals:
        raise health_content.HealthContentError("检测到批次锁或恢复日志，需先人工恢复")
    before_bytes = batch_path.read_bytes()
    before_sha = hashlib.sha256(before_bytes).hexdigest()
    journal_path = mutation_root / f".batch-mutation-{args.content_id}.journal.json"
    try:
        with lock_path.open("x", encoding="utf-8") as lock:
            lock.write(args.content_id)
        _write_json(
            journal_path,
            {
                "status": "recovery_required",
                "batch": str(batch_path),
                "content_id": args.content_id,
                "target_state": args.to,
                "before_sha256": before_sha,
            },
        )
        _atomic_replace_json(batch_path, updated, args.content_id)
        after_sha = _sha256(batch_path)
        ref_path = mutation_root / "current-batch-ref.json"
        if ref_path.exists():
            ref = _read_json(ref_path)
            ref["active_sha256"] = after_sha
            _atomic_replace_json(ref_path, ref, f"{args.content_id}-ref")
    except Exception:
        if batch_path.exists() and _sha256(batch_path) != before_sha:
            rollback_path = batch_path.with_name(f".{batch_path.name}.rollback.tmp")
            rollback_path.write_bytes(before_bytes)
            os.replace(rollback_path, batch_path)
        raise
    else:
        journal_path.unlink()
        lock_path.unlink()
    _dump(
        {
            "status": args.to,
            "batch_id": updated.get("batch_id"),
            "content_id": args.content_id,
            "batch": str(batch_path),
        }
    )
    return 0


def chase(args: argparse.Namespace) -> int:
    rows = health_content.parse_metric_csv(args.metrics)
    proposals = health_content.propose_chase_updates(rows)
    _dump({"status": "human_review", "proposals": proposals})
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="泛健康日更安全批次工具")
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start-batch", help="创建10主题测试批次")
    start.add_argument("--date", required=True)
    start.add_argument("--output", required=True)
    start.add_argument("--topics-file")
    start.set_defaults(handler=start_batch)

    inspect = commands.add_parser("status", help="只读检查批次状态")
    inspect.add_argument("--batch", required=True)
    inspect.set_defaults(handler=status)

    daily = commands.add_parser("next-daily", help="只读选择最早的可处理主题")
    daily.add_argument("--batch", required=True)
    daily.set_defaults(handler=next_daily)

    advance_parser = commands.add_parser("advance", help="按门禁推进单期状态")
    advance_parser.add_argument("--batch", required=True)
    advance_parser.add_argument("--content-id", required=True)
    advance_parser.add_argument("--to", required=True)
    advance_parser.add_argument("--manifest", required=True)
    advance_parser.set_defaults(handler=advance)

    prepare_parser = commands.add_parser(
        "prepare-quality-only", help="将一般生活方式manifest切换为免外部审核策略"
    )
    prepare_parser.add_argument("--manifest", required=True)
    prepare_parser.set_defaults(handler=prepare_quality_only)

    publish = commands.add_parser("build-publish-pack", help="生成四平台人工发布包")
    publish.add_argument("--manifest", required=True)
    publish.add_argument("--output", required=True)
    publish.set_defaults(handler=build_publish_pack)

    chase_parser = commands.add_parser("chase", help="基于72h/7d指标生成人工追击提案")
    chase_parser.add_argument("--metrics", required=True)
    chase_parser.set_defaults(handler=chase)
    return parser


def main() -> int:
    try:
        args = _parser().parse_args()
        return int(args.handler(args))
    except health_content.MedicalReviewRequired as exc:
        _dump({"status": "medical_review_required", "error": str(exc)})
        return 2
    except health_content.QualityGateFailed as exc:
        _dump({"status": "quality_gate_failed", "error": str(exc)})
        return 2
    except health_content.FinalQARequired as exc:
        _dump({"status": "final_qa_required", "error": str(exc)})
        return 2
    except health_content.HealthContentError as exc:
        _dump({"status": "invalid", "error": str(exc)})
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
