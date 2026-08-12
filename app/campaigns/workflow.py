"""Feature-gated orchestration through generation-ready MPT input (never publishing)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from app.campaigns.adapter import StructuredMptPayloadAdapter
from app.campaigns.memory import ContentMemoryRepository, fingerprint
from app.campaigns.models import (
    CampaignConfig,
    FeatureFlags,
    LifecycleState,
    MemoryDecision,
    MemoryRecord,
    PreparedCampaignContent,
    SelectionOutcome,
    StoryPackage,
)
from app.campaigns.planner import CampaignPlanner, stable_id
from app.campaigns.story import StoryEngine


class CampaignWorkflow:
    def __init__(
        self,
        memory: ContentMemoryRepository,
        *,
        flags: FeatureFlags | None = None,
        planner: CampaignPlanner | None = None,
        story_engine: StoryEngine | None = None,
        adapter: StructuredMptPayloadAdapter | None = None,
    ):
        self.memory = memory
        self.flags = flags or FeatureFlags()
        self.planner = planner or CampaignPlanner()
        self.story_engine = story_engine or StoryEngine()
        self.adapter = adapter or StructuredMptPayloadAdapter()

    @staticmethod
    def _inactive(campaign_id: str, local_date: date, reason: str) -> PreparedCampaignContent:
        selection = SelectionOutcome(
            outcome="invalid_plan",
            campaign_id=campaign_id,
            local_date=local_date,
            reasons=[reason],
        )
        return PreparedCampaignContent(
            selection=selection,
            memory_decision=MemoryDecision(
                decision="comparison_error",
                reason=reason,
                recommended_next_action="enable the required feature flags explicitly",
                blocking=True,
            ),
        )

    def plan_and_save(
        self,
        campaign: CampaignConfig,
        start_date: date,
        number_of_days: int,
        *,
        target_platforms: list[str] | None = None,
        random_seed: int = 0,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not self.flags.campaign_engine:
            raise RuntimeError("campaign_engine feature flag is disabled")
        plan = self.planner.plan(
            campaign,
            start_date,
            number_of_days,
            target_platforms=target_platforms,
            random_seed=random_seed,
            history=self.memory if self.flags.content_memory else None,
            now=now,
        )
        persisted = self.memory.save_plan(plan)
        return {"plan": plan, "persistence": persisted}

    def prepare(
        self,
        campaign: CampaignConfig,
        local_date: date,
        *,
        worker_id: str,
        idempotency_key: str,
        overrides: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> PreparedCampaignContent:
        required = {
            "campaign_engine": self.flags.campaign_engine,
            "story_engine": self.flags.story_engine,
            "content_memory": self.flags.content_memory,
        }
        disabled = [name for name, enabled in required.items() if not enabled]
        if disabled:
            return self._inactive(
                campaign.campaign_id,
                local_date,
                f"feature flags disabled: {', '.join(disabled)}; legacy workflow remains unchanged",
            )
        selection = self.memory.select_and_reserve(
            campaign,
            local_date,
            worker_id=worker_id,
            idempotency_key=idempotency_key,
            now=now,
            duplicate_blocking=self.flags.memory_duplicate_blocking,
        )
        memory_decision = (
            selection.memory_decisions[0]
            if selection.memory_decisions
            else MemoryDecision(
                decision="allowed" if selection.outcome == "selected" else "comparison_error",
                reason="reservation is eligible" if selection.outcome == "selected" else "no new reservation",
                recommended_next_action="continue" if selection.outcome == "selected" else "inspect selection outcome",
                blocking=selection.outcome != "selected",
            )
        )
        if selection.outcome != "selected" or selection.idempotent_replay or not selection.planned_item:
            existing = self._memory_for_item(selection.planned_item.planned_item_id) if selection.planned_item else None
            if selection.idempotent_replay and existing:
                package_data = existing.artifacts.get("story_package")
                payload_data = existing.artifacts.get("mpt_payload")
                return PreparedCampaignContent(
                    selection=selection,
                    memory_decision=memory_decision,
                    memory_decisions=[memory_decision],
                    story_package=StoryPackage.model_validate(package_data) if package_data else None,
                    mpt_payload=(
                        self.adapter.adapt(
                            campaign,
                            selection.planned_item,
                            StoryPackage.model_validate(package_data),
                            overrides=overrides,
                        ) if package_data and self.flags.structured_mpt_payload_adapter else None
                    ),
                    memory_record_id=existing.memory_record_id,
                )
            return PreparedCampaignContent(selection=selection, memory_decision=memory_decision)

        item = selection.planned_item
        self.memory.update_item_status(item.planned_item_id, LifecycleState.GENERATING)
        package = self.story_engine.build_package(campaign, item, now=now)
        errors = [issue for issue in package.validation_issues if issue.severity == "error"]
        artifact_decisions = (
            [
                self.memory.check(
                    campaign,
                    artifact_type,
                    value,
                    local_date,
                    series=item.series,
                    audit=True,
                )
                for artifact_type, value in (
                    ("hook", package.hook.text),
                    ("script", package.script.full_narration),
                    ("caption", package.caption.primary_caption),
                    (
                        "visual_concept",
                        " | ".join(scene.visual_objective for scene in package.scenes),
                    ),
                )
            ]
            if self.flags.memory_duplicate_blocking or self.flags.memory_duplicate_warnings
            else []
        )
        blocking_artifacts = [
            decision for decision in artifact_decisions
            if decision.blocking and self.flags.memory_duplicate_blocking
        ]
        # A prepared story/payload is generation-ready, not a completed media
        # artifact. The bridge records the terminal generation result later.
        status = LifecycleState.FAILED if errors else LifecycleState.GENERATING
        if blocking_artifacts:
            status = LifecycleState.FAILED
        adapted = (
            self.adapter.adapt(campaign, item, package, overrides=overrides)
            if self.flags.structured_mpt_payload_adapter and not errors and not blocking_artifacts
            else None
        )
        record = self._record_from_package(
            campaign, item, package, status,
            failure_reason=(
                "; ".join(
                    [issue.message for issue in errors]
                    + [decision.reason for decision in blocking_artifacts]
                )
                or None
            ),
            mpt_payload=adapted.model_dump(mode="json") if adapted else None,
            memory_decisions=[memory_decision, *artifact_decisions],
            now=now,
        )
        self.memory.upsert_memory(record)
        self.memory.update_item_status(item.planned_item_id, status)
        return PreparedCampaignContent(
            selection=selection,
            memory_decision=memory_decision,
            memory_decisions=[memory_decision, *artifact_decisions],
            story_package=package,
            mpt_payload=adapted,
            memory_record_id=record.memory_record_id,
        )

    def _memory_for_item(self, planned_item_id: str) -> MemoryRecord | None:
        for campaign_id in self._campaign_ids_for_item(planned_item_id):
            for record in self.memory.recent(campaign_id, limit=10000):
                if record.planned_item_id == planned_item_id:
                    return record
        return None

    def _campaign_ids_for_item(self, planned_item_id: str) -> list[str]:
        self.memory._ready()
        with self.memory._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT campaign_id FROM planned_items WHERE planned_item_id=?",
                (planned_item_id,),
            ).fetchall()
        return [row[0] for row in rows]

    @staticmethod
    def _record_from_package(
        campaign: CampaignConfig,
        item,
        package: StoryPackage,
        status: LifecycleState,
        *,
        failure_reason: str | None,
        mpt_payload: dict[str, Any] | None,
        memory_decisions: list[MemoryDecision],
        now: datetime | None,
    ) -> MemoryRecord:
        created = now or datetime.now(UTC)
        selected = next(
            concept for concept in package.concept_candidates
            if concept.concept_id == package.selected_concept_id
        )
        beats_data = [beat.model_dump(mode="json") for beat in package.beats]
        scenes_data = [scene.model_dump(mode="json") for scene in package.scenes]
        return MemoryRecord(
            memory_record_id=stable_id("memory", item.planned_item_id, package.story_version_id),
            campaign_id=campaign.campaign_id,
            planned_item_id=item.planned_item_id,
            story_id=package.brief.story_id,
            story_version_id=package.story_version_id,
            generation_run_id=stable_id("generation", item.planned_item_id, package.story_version_id),
            content_pillar=item.content_pillar,
            theme=item.theme,
            original_seed=item.topic,
            normalized_topic=item.topic.casefold(),
            fingerprints={
                "topic": fingerprint("topic", item.topic, stop_phrases=campaign.stop_phrases),
                "concept": fingerprint("concept", selected.premise, stop_phrases=campaign.stop_phrases),
                "hook": package.hook.novelty_fingerprint,
                "story_beat": fingerprint("story_beat", beats_data),
                "script": package.script.script_fingerprint,
                "caption": package.caption.caption_fingerprint,
                "scene_plan": fingerprint("scene_plan", scenes_data),
            },
            hook_text=package.hook.text,
            visual_prompt_fingerprints=[
                fingerprint("visual_prompt", scene.visual_prompt or {}) for scene in package.scenes
            ],
            stock_search_term_fingerprints=[
                fingerprint("visual_prompt", term)
                for scene in package.scenes for term in scene.stock_search_terms
            ],
            platform=item.platform,
            planned_date=item.planned_local_date,
            generated_at=created if status == LifecycleState.GENERATED else None,
            status=status,
            failure_reason=failure_reason,
            series=item.series,
            artifacts={
                "topic": item.topic,
                "concept": selected.premise,
                "hook": item.hook_style,
                "script": package.script.full_narration,
                "caption": package.caption.primary_caption,
                "story_beat": beats_data,
                "scene_plan": scenes_data,
                "format": item.story_format,
                "cta": item.cta_style,
                "seed": item.seed_id,
                "story_package": package.model_dump(mode="json"),
                "mpt_payload": mpt_payload,
                "memory_decisions": [
                    decision.model_dump(mode="json") for decision in memory_decisions
                ],
            },
        )

    def record_generation_result(
        self,
        memory_record_id: str,
        *,
        generation_run_id: str,
        task_id: str,
        status: str,
        artifact_sha256: str | None = None,
        completed_at: datetime | None = None,
        failure_reason: str | None = None,
    ) -> MemoryRecord:
        """Idempotently reconcile a bridge-observed MPT generation result."""
        if status not in {"generated", "failed"}:
            raise ValueError("generation status must be generated or failed")
        if status == "generated" and not artifact_sha256:
            raise ValueError("generated status requires artifact_sha256")
        if artifact_sha256 and (
            len(artifact_sha256) != 64
            or any(value not in "0123456789abcdef" for value in artifact_sha256.casefold())
        ):
            raise ValueError("artifact_sha256 must be a 64-character hexadecimal digest")
        observed_at = (completed_at or datetime.now(UTC)).astimezone(UTC)
        for campaign_id in self._all_campaign_ids():
            record = next(
                (value for value in self.memory.recent(campaign_id, limit=10000)
                 if value.memory_record_id == memory_record_id),
                None,
            )
            if not record:
                continue
            if record.generation_run_id != generation_run_id:
                raise ValueError("generation_run_id does not match the prepared memory record")
            if record.generation_task_id and record.generation_task_id != task_id:
                raise ValueError("memory record is already associated with a different MPT task")
            terminal_state = (
                record.status == LifecycleState.GENERATED
                and status == "generated"
                and record.generation_artifact_sha256 == artifact_sha256
            ) or (
                record.status == LifecycleState.FAILED
                and status == "failed"
                and record.failure_reason == failure_reason
            )
            if terminal_state:
                return record
            result_artifact = {
                "generation_run_id": generation_run_id,
                "task_id": task_id,
                "status": status,
                "artifact_sha256": artifact_sha256,
                "observed_at": observed_at.isoformat(),
            }
            updated = record.model_copy(
                update={
                    "generation_task_id": task_id,
                    "generation_artifact_sha256": artifact_sha256,
                    "generation_completed_at": observed_at if status == "generated" else None,
                    "generation_failed_at": observed_at if status == "failed" else None,
                    "generated_at": observed_at if status == "generated" else record.generated_at,
                    "status": LifecycleState.GENERATED if status == "generated" else LifecycleState.FAILED,
                    "failure_reason": failure_reason if status == "failed" else None,
                    "media_hashes": list(dict.fromkeys([
                        *record.media_hashes,
                        *([artifact_sha256] if artifact_sha256 else []),
                    ])),
                    "artifacts": {**record.artifacts, "generation_result": result_artifact},
                }
            )
            self.memory.upsert_memory(updated)
            if updated.planned_item_id:
                self.memory.update_item_status(updated.planned_item_id, updated.status)
            return updated
        raise ValueError(f"unknown memory record: {memory_record_id}")

    def _all_campaign_ids(self) -> list[str]:
        self.memory._ready()
        with self.memory._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT campaign_id FROM content_memory_records"
            ).fetchall()
        return [row[0] for row in rows]
