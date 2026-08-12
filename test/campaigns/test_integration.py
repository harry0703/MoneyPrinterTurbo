from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path

import campaign_cli
from app.campaigns.adapter import LegacyPayloadError, StructuredMptPayloadAdapter
from app.campaigns.memory import ContentMemoryRepository
from app.campaigns.models import FeatureFlags, LifecycleState, ValidationIssue
from app.campaigns.planner import CampaignPlanner
from app.campaigns.story import StoryEngine
from app.campaigns.workflow import CampaignWorkflow
from app.models.schema import VideoParams
from test.campaigns.common import ROOT, heritage_campaign, repository
from test.campaigns.common import memory_record


NOW = datetime(2026, 8, 6, 14, tzinfo=UTC)
ALL_FLAGS = FeatureFlags(
    campaign_engine=True,
    story_engine=True,
    content_memory=True,
    structured_mpt_payload_adapter=True,
    automatic_daily_campaign_planning=False,
    memory_duplicate_blocking=True,
    memory_duplicate_warnings=True,
)


class PayloadAdapterTests(unittest.TestCase):
    def setUp(self):
        self.campaign = heritage_campaign()
        self.item = CampaignPlanner().plan(
            self.campaign, date(2026, 8, 6), 1, random_seed=4, now=NOW
        ).items[0]
        self.package = StoryEngine().build_package(self.campaign, self.item, now=NOW)
        self.adapter = StructuredMptPayloadAdapter()

    def test_story_package_maps_to_canonical_legacy_fields(self):
        result = self.adapter.adapt(self.campaign, self.item, self.package)
        self.assertEqual(result.payload["script"], self.package.script.full_narration)
        self.assertEqual(result.payload["script"], result.payload["video_script"])
        self.assertEqual(result.payload["search_terms"], result.payload["video_terms"])
        self.assertTrue(result.payload["video_terms"])
        self.assertEqual(result.payload["video_aspect"], "9:16")
        self.assertEqual(result.field_sources["video_script"], "story.script.full_narration")
        self.assertEqual(result.field_sources["video_terms"], "story.scenes[].stock_search_terms")

    def test_user_override_becomes_single_canonical_script_and_terms(self):
        result = self.adapter.adapt(
            self.campaign,
            self.item,
            self.package,
            overrides={"video_script": "Approved override.", "search_terms": ["one", "two"]},
        )
        self.assertEqual(result.payload["script"], "Approved override.")
        self.assertEqual(result.payload["video_script"], "Approved override.")
        self.assertEqual(result.payload["video_terms"], ["one", "two"])
        self.assertIn("user_override", result.field_sources["script"])

    def test_contradictory_duplicate_fields_are_rejected(self):
        with self.assertRaises(LegacyPayloadError):
            self.adapter.adapt(
                self.campaign,
                self.item,
                self.package,
                overrides={"script": "one", "video_script": "two"},
            )

    def test_empty_nested_fields_cannot_pass_validation(self):
        result = self.adapter.adapt(self.campaign, self.item, self.package)
        broken = dict(result.payload, video_script="")
        with self.assertRaisesRegex(LegacyPayloadError, "video_script"):
            self.adapter.validate(broken)

    def test_adapter_task_params_are_accepted_by_existing_model(self):
        result = self.adapter.adapt(self.campaign, self.item, self.package)
        params = VideoParams(**self.adapter.task_params(result))
        self.assertEqual(params.video_script, result.payload["script"])
        self.assertEqual(params.video_terms, result.payload["search_terms"])
        self.assertTrue(params.match_materials_to_script)


class WorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.memory = repository(Path(self.temp.name) / "memory.sqlite3")
        self.campaign = heritage_campaign()
        self.workflow = CampaignWorkflow(self.memory, flags=ALL_FLAGS)

    def save_plan(self, day=date(2026, 8, 6)):
        result = self.workflow.plan_and_save(
            self.campaign, day, 1, random_seed=23, now=NOW
        )
        self.assertEqual(result["persistence"]["items_inserted"], 1)
        return result["plan"]

    def test_plan_memory_story_and_payload_vertical_slice(self):
        plan = self.save_plan()
        result = self.workflow.prepare(
            self.campaign, date(2026, 8, 6), worker_id="test-worker",
            idempotency_key="daily-2026-08-06", now=NOW,
        )
        self.assertEqual(result.selection.outcome, "selected")
        self.assertEqual(result.selection.planned_item.planned_item_id, plan.items[0].planned_item_id)
        self.assertIsNotNone(result.story_package)
        self.assertIsNotNone(result.mpt_payload)
        self.assertEqual(result.mpt_payload.payload["script"], result.mpt_payload.payload["video_script"])
        records = self.memory.recent(self.campaign.campaign_id)
        self.assertEqual(records[0].status, LifecycleState.GENERATING)
        self.assertIn("story_package", records[0].artifacts)
        self.assertEqual(records[0].story_version_id, result.story_package.story_version_id)

    def test_retry_does_not_generate_duplicate_and_returns_same_lineage(self):
        self.save_plan()
        first = self.workflow.prepare(
            self.campaign, date(2026, 8, 6), worker_id="worker",
            idempotency_key="same", now=NOW,
        )
        second = self.workflow.prepare(
            self.campaign, date(2026, 8, 6), worker_id="worker",
            idempotency_key="same", now=NOW,
        )
        self.assertTrue(second.selection.idempotent_replay)
        self.assertEqual(first.memory_record_id, second.memory_record_id)
        self.assertEqual(first.story_package.story_version_id, second.story_package.story_version_id)
        self.assertEqual(len(self.memory.recent(self.campaign.campaign_id)), 1)

    def test_different_retry_key_is_not_allowed_to_duplicate_generation(self):
        self.save_plan()
        self.workflow.prepare(
            self.campaign, date(2026, 8, 6), worker_id="worker-1",
            idempotency_key="first", now=NOW,
        )
        result = self.workflow.prepare(
            self.campaign, date(2026, 8, 6), worker_id="worker-2",
            idempotency_key="different", now=NOW,
        )
        self.assertEqual(result.selection.outcome, "nothing_eligible")
        self.assertEqual(len(self.memory.recent(self.campaign.campaign_id)), 1)

    def test_generation_result_is_idempotent_and_preserves_lineage(self):
        self.save_plan()
        prepared = self.workflow.prepare(
            self.campaign, date(2026, 8, 6), worker_id="worker",
            idempotency_key="same", now=NOW,
        )
        record = self.memory.recent(self.campaign.campaign_id)[0]
        generated = self.workflow.record_generation_result(
            prepared.memory_record_id,
            generation_run_id=record.generation_run_id,
            task_id="11111111-1111-4111-8111-111111111111",
            status="generated",
            artifact_sha256="a" * 64,
            completed_at=NOW,
        )
        replay = self.workflow.record_generation_result(
            prepared.memory_record_id,
            generation_run_id=record.generation_run_id,
            task_id="11111111-1111-4111-8111-111111111111",
            status="generated",
            artifact_sha256="a" * 64,
            completed_at=NOW,
        )
        self.assertEqual(generated.status, LifecycleState.GENERATED)
        self.assertEqual(generated.generation_task_id, "11111111-1111-4111-8111-111111111111")
        self.assertEqual(generated.generation_artifact_sha256, "a" * 64)
        self.assertEqual(replay, generated)
        self.assertIsNone(generated.publication_run_id)

    def test_generation_result_rejects_conflicting_task(self):
        self.save_plan()
        prepared = self.workflow.prepare(
            self.campaign, date(2026, 8, 6), worker_id="worker",
            idempotency_key="same", now=NOW,
        )
        record = self.memory.recent(self.campaign.campaign_id)[0]
        self.workflow.record_generation_result(
            prepared.memory_record_id,
            generation_run_id=record.generation_run_id,
            task_id="11111111-1111-4111-8111-111111111111",
            status="generated",
            artifact_sha256="a" * 64,
            completed_at=NOW,
        )
        with self.assertRaisesRegex(ValueError, "different MPT task"):
            self.workflow.record_generation_result(
                prepared.memory_record_id,
                generation_run_id=record.generation_run_id,
                task_id="22222222-2222-4222-8222-222222222222",
                status="generated",
                artifact_sha256="a" * 64,
                completed_at=NOW,
            )

    def test_validation_failure_stops_before_payload_or_publication(self):
        self.save_plan()
        original = self.workflow.story_engine.build_package

        def invalid_package(*args, **kwargs):
            package = original(*args, **kwargs)
            issue = ValidationIssue(
                code="forced_failure", severity="error", stage="test",
                message="forced validation failure", suggested_action="fix fixture",
            )
            return package.model_copy(update={"validation_issues": [issue]})

        self.workflow.story_engine.build_package = invalid_package
        result = self.workflow.prepare(
            self.campaign, date(2026, 8, 6), worker_id="worker",
            idempotency_key="failure", now=NOW,
        )
        self.assertIsNone(result.mpt_payload)
        record = self.memory.recent(self.campaign.campaign_id)[0]
        self.assertEqual(record.status, LifecycleState.FAILED)
        self.assertIn("forced validation failure", record.failure_reason)
        self.assertIsNone(record.publication_run_id)

    def test_recent_hook_blocks_payload_after_topic_reservation(self):
        plan = self.save_plan()
        predicted = StoryEngine().build_package(self.campaign, plan.items[0], now=NOW)
        self.memory.upsert_memory(memory_record(
            self.campaign.campaign_id,
            "prior-hook",
            topic="a different topic",
            hook=predicted.hook.text,
            planned_date=date(2026, 8, 1),
        ))
        result = self.workflow.prepare(
            self.campaign, date(2026, 8, 6), worker_id="worker",
            idempotency_key="hook-block", now=NOW,
        )
        self.assertIsNone(result.mpt_payload)
        self.assertTrue(any(value.decision == "recent_hook" for value in result.memory_decisions))
        generated = next(
            value for value in self.memory.recent(self.campaign.campaign_id)
            if value.planned_item_id == plan.items[0].planned_item_id
        )
        self.assertEqual(generated.status, LifecycleState.FAILED)

    def test_feature_flags_preserve_existing_path_by_default(self):
        path = Path(self.temp.name) / "disabled.sqlite3"
        result = CampaignWorkflow(ContentMemoryRepository(path)).prepare(
            self.campaign, date(2026, 8, 6), worker_id="worker", idempotency_key="key"
        )
        self.assertEqual(result.selection.outcome, "invalid_plan")
        self.assertIn("legacy workflow remains unchanged", result.selection.reasons[0])
        self.assertFalse(path.exists())


class CampaignCliTests(unittest.TestCase):
    def run_command(self, args):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = campaign_cli.run_cli(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_validate_list_and_plan_preview(self):
        code, output, _ = self.run_command(["--campaign-dir", str(ROOT / "campaigns"), "validate"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)[0]["status"], "valid")
        code, output, _ = self.run_command(["--campaign-dir", str(ROOT / "campaigns"), "list"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)[0]["campaign_id"], "heritage-banner-facebook")
        code, output, _ = self.run_command([
            "--campaign-dir", str(ROOT / "campaigns"), "plan-preview",
            "heritage-banner-facebook", "--start-date", "2026-08-06", "--days", "1",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(output)["items"]), 1)

    def test_plan_save_next_select_and_migration_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "memory.sqlite3")
            common = ["--campaign-dir", str(ROOT / "campaigns"), "--database", database]
            code, output, _ = self.run_command(common + [
                "plan-save", "heritage-banner-facebook", "--start-date", "2026-08-06", "--days", "1"
            ])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["persistence"]["items_inserted"], 1)
            code, output, _ = self.run_command(common + [
                "next", "heritage-banner-facebook", "--date", "2026-08-06"
            ])
            self.assertEqual(json.loads(output)["outcome"], "selected")
            code, output, _ = self.run_command(common + [
                "select-today", "heritage-banner-facebook", "--date", "2026-08-06",
                "--worker", "cli-test", "--idempotency-key", "cli-test-key",
            ])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["outcome"], "selected")
            code, output, _ = self.run_command(common + ["migration-preview"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["pending"], [])

    def test_seed_migration_command_is_dry_run(self):
        code, output, _ = self.run_command([
            "--campaign-dir", str(ROOT / "campaigns"), "migrate-seeds",
            "heritage-banner-facebook", "--legacy-path",
            str(ROOT / "campaigns" / "heritage-banner" / "marketing-plan.json"),
        ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["status"], "preview_only")

    def test_bridge_profile_contract_and_generation_result(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "memory.sqlite3")
            common = ["--campaign-dir", str(ROOT / "campaigns"), "--database", database]
            code, output, error = self.run_command(common + [
                "prepare", "heritage-banner-facebook", "--date", "2026-08-06",
                "--worker", "bridge", "--idempotency-key", "bridge-2026-08-06-0",
                "--feature-profile", "bridge-v1", "--duplicate-policy", "block",
            ])
            self.assertEqual((code, error), (0, ""))
            prepared = json.loads(output)
            self.assertEqual(prepared["schema_version"], "1.0.0")
            self.assertEqual(prepared["contract"], "mpt-campaign-v1")
            self.assertEqual(prepared["campaign_id"], "heritage-banner-facebook")
            self.assertTrue(prepared["mpt_payload"]["video_script"])

            code, output, error = self.run_command(common + [
                "record-generation", prepared["memory_record_id"],
                "--generation-run-id", prepared["generation_run_id"],
                "--task-id", "11111111-1111-4111-8111-111111111111",
                "--status", "generated", "--artifact-sha256", "b" * 64,
                "--completed-at", NOW.isoformat(),
            ])
            self.assertEqual((code, error), (0, ""))
            generated = json.loads(output)
            self.assertEqual(generated["status"], "generated")
            self.assertEqual(generated["generation_artifact_sha256"], "b" * 64)

    def test_record_generation_rejects_malformed_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "memory.sqlite3")
            common = ["--campaign-dir", str(ROOT / "campaigns"), "--database", database]
            code, output, _ = self.run_command(common + [
                "prepare", "heritage-banner-facebook", "--date", "2026-08-06",
                "--worker", "bridge", "--idempotency-key", "bridge-bad-digest",
                "--feature-profile", "bridge-v1", "--duplicate-policy", "block",
            ])
            self.assertEqual(code, 0)
            prepared = json.loads(output)
            code, _, error = self.run_command(common + [
                "record-generation", prepared["memory_record_id"],
                "--generation-run-id", prepared["generation_run_id"],
                "--task-id", "11111111-1111-4111-8111-111111111111",
                "--status", "generated", "--artifact-sha256", "not-a-digest",
            ])
            self.assertEqual(code, 2)
            self.assertIn("artifact_sha256", error)


if __name__ == "__main__":
    unittest.main()
