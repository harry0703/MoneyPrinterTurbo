"""Developer CLI for campaign planning, story preparation, and content memory."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from app.campaigns.config import (
    CampaignConfigurationError,
    CampaignRegistry,
    preview_legacy_seed_migration,
    validate_story_format_compatibility,
)
from app.campaigns.memory import ContentMemoryRepository, DEFAULT_MEMORY_PATH
from app.campaigns.models import BridgeCampaignPreparation, FeatureFlags
from app.campaigns.planner import CampaignPlanner, stable_id
from app.campaigns.selection import CampaignSelectionService
from app.campaigns.workflow import CampaignWorkflow
from app.config import config


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def _json(value: Any) -> str:
    def serializable(item: Any) -> Any:
        if hasattr(item, "model_dump"):
            return item.model_dump(mode="json")
        if isinstance(item, dict):
            return {key: serializable(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [serializable(child) for child in item]
        return item

    return json.dumps(serializable(value), ensure_ascii=False, indent=2, default=str)


def _flags(
    feature_profile: str = "configured",
    duplicate_policy: str = "configured",
) -> FeatureFlags:
    if feature_profile == "bridge-v1":
        values = FeatureFlags(
            campaign_engine=True,
            story_engine=True,
            content_memory=True,
            structured_mpt_payload_adapter=True,
            automatic_daily_campaign_planning=False,
        ).model_dump()
    else:
        values = FeatureFlags.model_validate(config.campaign_features).model_dump()
    if duplicate_policy != "configured":
        values["memory_duplicate_warnings"] = duplicate_policy in {"warn", "block"}
        values["memory_duplicate_blocking"] = duplicate_policy == "block"
    return FeatureFlags.model_validate(values)


def _bridge_contract(result, idempotency_key: str) -> BridgeCampaignPreparation:
    item = result.selection.planned_item
    package = result.story_package
    payload = result.mpt_payload
    if not item or not package or not payload or not result.memory_record_id:
        raise RuntimeError("bridge-v1 preparation did not produce generation-ready content")
    record_id = result.memory_record_id
    generation_run_id = stable_id(
        "generation", item.planned_item_id, package.story_version_id
    )
    return BridgeCampaignPreparation(
        selection_outcome=result.selection.outcome,
        idempotent_replay=result.selection.idempotent_replay,
        idempotency_key=idempotency_key,
        campaign_id=item.campaign_id,
        planned_item_id=item.planned_item_id,
        story_id=package.brief.story_id,
        story_version_id=package.story_version_id,
        memory_record_id=record_id,
        generation_run_id=generation_run_id,
        mpt_payload=payload.payload,
        caption=package.caption,
    )


def _today(campaign) -> date:
    return datetime.now(ZoneInfo(campaign.timezone)).date()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local campaign/story/memory developer tools")
    parser.add_argument("--campaign-dir", default="campaigns")
    parser.add_argument("--database", default=str(DEFAULT_MEMORY_PATH))
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("validate", help="validate every campaign configuration")
    commands.add_parser("list", help="list campaigns")
    show = commands.add_parser("show", help="show one campaign")
    show.add_argument("campaign_id")
    compatibility = commands.add_parser("validate-compatibility")
    compatibility.add_argument("campaign_id")

    for name in ("plan-preview", "plan-save", "why-selected", "why-skipped"):
        command = commands.add_parser(name)
        command.add_argument("campaign_id")
        command.add_argument("--start-date", type=_date, required=True)
        command.add_argument("--days", type=int, default=7)
        command.add_argument("--platform", action="append")
        command.add_argument("--seed", type=int, default=0)

    next_item = commands.add_parser("next", help="preview the next eligible item without reservation")
    next_item.add_argument("campaign_id")
    next_item.add_argument("--date", type=_date)
    select = commands.add_parser("select-today", help="atomically reserve today's item")
    select.add_argument("campaign_id")
    select.add_argument("--worker", required=True)
    select.add_argument("--idempotency-key", required=True)
    select.add_argument("--date", type=_date)

    recent = commands.add_parser("recent", help="show recent campaign memory")
    recent.add_argument("campaign_id")
    recent.add_argument("--limit", type=int, default=20)
    for name in ("find-topic", "find-hook", "find-script"):
        command = commands.add_parser(name)
        command.add_argument("campaign_id")
        command.add_argument("value")
        command.add_argument("--date", type=_date)
    usage = commands.add_parser("usage", help="show pillar, theme, hook, CTA, seed, and format usage")
    usage.add_argument("campaign_id")
    activity = commands.add_parser("activity", help="show planned versus published and failed content")
    activity.add_argument("campaign_id")
    lineage = commands.add_parser("lineage", help="show regeneration lineage")
    lineage.add_argument("campaign_id")
    release = commands.add_parser("release-stale")
    release.add_argument("--date-time", help="UTC ISO timestamp; default is now")
    rebuild = commands.add_parser("rebuild-fingerprints")
    rebuild.add_argument("campaign_id")
    audit = commands.add_parser("audit")
    audit.add_argument("campaign_id")
    audit.add_argument("--limit", type=int, default=100)
    export = commands.add_parser("export")
    export.add_argument("campaign_id")
    export.add_argument("--format", choices=["json", "csv"], default="json")
    export.add_argument("--output")
    migrate = commands.add_parser("migrate-seeds", help="preview legacy Heritage seed migration")
    migrate.add_argument("campaign_id")
    migrate.add_argument("--legacy-path", default="campaigns/heritage-banner/marketing-plan.json")
    commands.add_parser("migration-preview", help="show pending SQLite migrations without applying them")

    prepare = commands.add_parser("prepare", help="prepare structured content; never generate media or publish")
    prepare.add_argument("campaign_id")
    prepare.add_argument("--date", type=_date)
    prepare.add_argument("--worker", required=True)
    prepare.add_argument("--idempotency-key", required=True)
    prepare.add_argument(
        "--feature-profile", choices=["configured", "bridge-v1"], default="configured"
    )
    prepare.add_argument(
        "--duplicate-policy", choices=["configured", "off", "warn", "block"],
        default="configured",
    )
    generation = commands.add_parser(
        "record-generation", help="record a bridge-observed MPT generation result"
    )
    generation.add_argument("memory_record_id")
    generation.add_argument("--generation-run-id", required=True)
    generation.add_argument("--task-id", required=True)
    generation.add_argument("--status", choices=["generated", "failed"], required=True)
    generation.add_argument("--artifact-sha256")
    generation.add_argument("--completed-at")
    generation.add_argument("--failure-reason")
    return parser


def run_cli(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry = CampaignRegistry(args.campaign_dir)
    memory = ContentMemoryRepository(args.database)
    try:
        if args.command == "validate":
            results = registry.validate_all()
            print(_json(results))
            return 0 if results and all(value["status"] == "valid" for value in results) else 1
        if args.command == "list":
            print(_json([
                {"campaign_id": campaign.campaign_id, "display_name": campaign.display_name,
                 "enabled": campaign.enabled, "schema_version": campaign.schema_version}
                for campaign in registry.list()
            ]))
            return 0
        if args.command == "migration-preview":
            print(_json(memory.migration_preview()))
            return 0
        if args.command in {"next", "select-today"}:
            selector = CampaignSelectionService(registry, memory)
            if args.command == "next":
                outcome = selector.preview(args.campaign_id, args.date)
            else:
                outcome = selector.select(
                    args.campaign_id,
                    worker_id=args.worker,
                    idempotency_key=args.idempotency_key,
                    local_date=args.date,
                    duplicate_blocking=_flags().memory_duplicate_blocking,
                )
            print(_json(outcome))
            return 0 if outcome.outcome in {"selected", "already_completed_today", "already_reserved"} else 2

        campaign = registry.get(args.campaign_id) if hasattr(args, "campaign_id") else None
        if args.command == "show":
            print(_json(campaign))
        elif args.command == "validate-compatibility":
            errors = validate_story_format_compatibility(campaign)
            print(_json({"campaign_id": campaign.campaign_id, "valid": not errors, "errors": errors}))
            return 1 if errors else 0
        elif args.command in {"plan-preview", "plan-save", "why-selected", "why-skipped"}:
            plan = CampaignPlanner().plan(
                campaign,
                args.start_date,
                args.days,
                target_platforms=args.platform,
                random_seed=args.seed,
                history=memory if Path(args.database).exists() else None,
            )
            if args.command == "plan-save":
                print(_json({"plan": plan, "persistence": memory.save_plan(plan)}))
            elif args.command == "why-selected":
                print(_json([decision for decision in plan.decisions if decision.selected_seed_id]))
            elif args.command == "why-skipped":
                print(_json([decision for decision in plan.decisions if decision.rejected or not decision.selected_seed_id]))
            else:
                print(_json(plan))
        elif args.command == "recent":
            print(_json(memory.recent(campaign.campaign_id, args.limit)))
        elif args.command in {"find-topic", "find-hook", "find-script"}:
            artifact = args.command.removeprefix("find-")
            print(_json(memory.check(
                campaign, artifact, args.value, args.date or _today(campaign), audit=True
            )))
        elif args.command == "usage":
            counts = memory.usage_counts(campaign.campaign_id)
            print(_json({key: dict(value) for key, value in counts.items()}))
        elif args.command == "activity":
            print(_json(memory.activity_summary(campaign.campaign_id)))
        elif args.command == "lineage":
            records = memory.recent(campaign.campaign_id, 10000)
            print(_json([
                {"story_version_id": value.story_version_id, "parent_version_id": value.parent_version_id,
                 "status": value.status.value, "superseded": value.superseded}
                for value in records if value.story_version_id
            ]))
        elif args.command == "release-stale":
            timestamp = datetime.fromisoformat(args.date_time) if args.date_time else None
            print(_json({"released": memory.release_stale_reservations(timestamp)}))
        elif args.command == "rebuild-fingerprints":
            print(_json({"rebuilt": memory.rebuild_fingerprints(campaign)}))
        elif args.command == "audit":
            print(_json(memory.audit_log(campaign.campaign_id, args.limit)))
        elif args.command == "export":
            rendered = memory.export(campaign.campaign_id, args.format)
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
                print(_json({"output": args.output, "format": args.format}))
            else:
                print(rendered)
        elif args.command == "migrate-seeds":
            print(_json(preview_legacy_seed_migration(args.legacy_path, campaign)))
        elif args.command == "prepare":
            flags = _flags(args.feature_profile, args.duplicate_policy)
            workflow = CampaignWorkflow(memory, flags=flags)
            target_date = args.date or _today(campaign)
            if args.feature_profile == "bridge-v1":
                workflow.plan_and_save(campaign, target_date, 1)
            result = workflow.prepare(
                campaign, target_date, worker_id=args.worker,
                idempotency_key=args.idempotency_key,
            )
            rendered = (
                _bridge_contract(result, args.idempotency_key)
                if args.feature_profile == "bridge-v1"
                else result
            )
            print(_json(rendered))
            return 0 if result.selection.outcome == "selected" and result.mpt_payload else 2
        elif args.command == "record-generation":
            workflow = CampaignWorkflow(memory)
            completed_at = (
                datetime.fromisoformat(args.completed_at)
                if args.completed_at else None
            )
            result = workflow.record_generation_result(
                args.memory_record_id,
                generation_run_id=args.generation_run_id,
                task_id=args.task_id,
                status=args.status,
                artifact_sha256=args.artifact_sha256,
                completed_at=completed_at,
                failure_reason=args.failure_reason,
            )
            print(_json(result))
        return 0
    except (CampaignConfigurationError, ValueError, RuntimeError) as exc:
        print(_json({"error": str(exc), "command": args.command}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run_cli())
