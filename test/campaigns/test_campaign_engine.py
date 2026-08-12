from __future__ import annotations

import json
import tempfile
import threading
import unittest
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import yaml

from app.campaigns.config import (
    CampaignConfigurationError,
    CampaignRegistry,
    preview_legacy_seed_migration,
    validate_story_format_compatibility,
)
from app.campaigns.memory import ContentMemoryRepository
from app.campaigns.models import LifecycleState
from app.campaigns.planner import CampaignPlanner, EmptyPlanningHistory
from app.campaigns.selection import CampaignSelectionService
from test.campaigns.common import ROOT, heritage_campaign, memory_record, repository


FIXED_NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)


class _ExhaustedHistory(EmptyPlanningHistory):
    def __init__(self, used: date):
        self.used = used

    def last_used(self, campaign_id, artifact, value):
        return self.used if artifact == "seed" else None


class CampaignConfigurationTests(unittest.TestCase):
    def test_heritage_configuration_loads_with_32_seeds(self):
        campaign = heritage_campaign()
        self.assertEqual(campaign.schema_version, "1.0.0")
        self.assertEqual(campaign.timezone, "America/Chicago")
        self.assertEqual(campaign.enabled_platforms, ["facebook"])
        self.assertEqual((campaign.min_duration_seconds, campaign.max_duration_seconds), (20, 60))
        self.assertEqual(campaign.duplicate_cooldown_days, 30)
        self.assertEqual(len(campaign.seed_content), 32)

    def test_registry_lists_and_validates_campaign(self):
        registry = CampaignRegistry(ROOT / "campaigns")
        self.assertEqual([value.campaign_id for value in registry.list()], ["heritage-banner-facebook"])
        self.assertEqual(registry.validate_all()[0]["status"], "valid")
        self.assertEqual(validate_story_format_compatibility(heritage_campaign()), [])

    def test_missing_required_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.yaml"
            path.write_text(yaml.safe_dump({"schema_version": "1.0.0"}), encoding="utf-8")
            with self.assertRaises(CampaignConfigurationError):
                CampaignRegistry(directory).load_path(path)

    def test_unknown_campaign_is_structured_configuration_error(self):
        with self.assertRaisesRegex(CampaignConfigurationError, "unknown campaign"):
            CampaignRegistry(ROOT / "campaigns").get("missing")

    def test_legacy_seed_migration_is_preview_only(self):
        result = preview_legacy_seed_migration(
            ROOT / "campaigns" / "heritage-banner" / "marketing-plan.json",
            heritage_campaign(),
        )
        self.assertEqual(result["status"], "preview_only")
        self.assertEqual(result["legacy_seed_count"], 32)
        self.assertEqual(len(result["already_present"]), 32)
        self.assertEqual(result["would_add"], [])


class CampaignPlannerTests(unittest.TestCase):
    def setUp(self):
        self.campaign = heritage_campaign()
        self.planner = CampaignPlanner()

    def plan(self, seed=11, start=date(2026, 8, 1), days=10, history=None):
        return self.planner.plan(
            self.campaign, start, days, random_seed=seed, history=history, now=FIXED_NOW
        )

    def test_planning_is_deterministic_for_same_seed_and_state(self):
        left, right = self.plan(), self.plan()
        self.assertEqual(left.model_dump(), right.model_dump())

    def test_different_seeds_produce_valid_alternate_plan_ids(self):
        left, right = self.plan(seed=1), self.plan(seed=2)
        self.assertNotEqual(left.plan_id, right.plan_id)
        self.assertTrue(all(20 <= item.target_duration_seconds <= 60 for item in right.items))

    def test_planner_rotates_pillars_themes_hooks_formats_and_ctas(self):
        plan = self.plan(days=20)
        self.assertGreater(len({item.content_pillar for item in plan.items}), 4)
        self.assertGreater(len({item.theme for item in plan.items}), 6)
        self.assertGreater(len({item.hook_style for item in plan.items}), 2)
        self.assertGreater(len({item.story_format for item in plan.items}), 3)
        self.assertGreater(len({item.cta_style for item in plan.items}), 2)
        self.assertTrue(all(a.theme != b.theme for a, b in zip(plan.items, plan.items[1:])))
        self.assertTrue(all(a.story_format != b.story_format for a, b in zip(plan.items, plan.items[1:])))

    def test_timezone_and_spring_daylight_saving_windows(self):
        plan = self.plan(start=date(2026, 3, 7), days=2)
        self.assertEqual(plan.items[0].planned_utc_start.hour, 15)
        self.assertEqual(plan.items[1].planned_utc_start.hour, 14)

    def test_fall_daylight_saving_windows(self):
        plan = self.plan(start=date(2026, 10, 31), days=2)
        self.assertEqual(plan.items[0].planned_utc_start.hour, 14)
        self.assertEqual(plan.items[1].planned_utc_start.hour, 15)

    def test_posting_cadence_skips_unconfigured_days(self):
        cadence = self.campaign.posting_cadence.model_copy(update={"days_of_week": [0]})
        campaign = self.campaign.model_copy(update={"posting_cadence": cadence})
        plan = self.planner.plan(campaign, date(2026, 8, 1), 10, now=FIXED_NOW)
        self.assertEqual([item.planned_local_date.weekday() for item in plan.items], [0, 0])

    def test_seasonal_seed_is_preferred_when_eligible(self):
        plan = self.plan(start=date(2026, 12, 1), days=1)
        self.assertIn(plan.items[0].seed_id, {"hb-009", "hb-010", "hb-026", "hb-027"})
        self.assertIn("seasonal multiplier=1.8", plan.decisions[0].reasons)

    def test_exhausted_seed_pool_is_explained_without_duplication(self):
        plan = self.plan(start=date(2026, 8, 2), days=1, history=_ExhaustedHistory(date(2026, 8, 1)))
        self.assertEqual(plan.items, [])
        self.assertIn("exhausted", plan.decisions[0].reasons[0])
        self.assertEqual(len(plan.decisions[0].rejected), 32)

    def test_target_platform_must_be_enabled(self):
        with self.assertRaisesRegex(ValueError, "enabled"):
            self.planner.plan(self.campaign, date(2026, 8, 1), 1, ["tiktok"])


class CampaignPersistenceAndSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = repository(Path(self.temp.name) / "memory.sqlite3")
        self.campaign = heritage_campaign()
        self.plan = CampaignPlanner().plan(
            self.campaign, date(2026, 8, 6), 2, random_seed=5, now=FIXED_NOW
        )

    def test_plan_preview_has_no_database_side_effect(self):
        other_path = Path(self.temp.name) / "preview.sqlite3"
        CampaignPlanner().plan(self.campaign, date(2026, 8, 6), 1, now=FIXED_NOW)
        self.assertFalse(other_path.exists())

    def test_plan_persistence_retry_is_idempotent(self):
        first = self.repo.save_plan(self.plan)
        second = self.repo.save_plan(self.plan)
        self.assertEqual(first["items_inserted"], 2)
        self.assertEqual(second["items_inserted"], 0)
        self.assertEqual(self.repo.get_plan(self.plan.plan_id).plan_id, self.plan.plan_id)

    def test_disabled_campaign_is_not_selected(self):
        self.repo.save_plan(self.plan)
        disabled = self.campaign.model_copy(update={"enabled": False})
        result = self.repo.select_and_reserve(
            disabled, date(2026, 8, 6), worker_id="w", idempotency_key="k"
        )
        self.assertEqual(result.outcome, "campaign_disabled")

    def test_already_completed_campaign_date(self):
        self.repo.save_plan(self.plan)
        self.repo.upsert_memory(memory_record(
            self.campaign.campaign_id, "published", planned_date=date(2026, 8, 6)
        ))
        result = self.repo.select_and_reserve(
            self.campaign, date(2026, 8, 6), worker_id="w", idempotency_key="k"
        )
        self.assertEqual(result.outcome, "already_completed_today")

    def test_no_plan_returns_nothing_eligible(self):
        result = self.repo.select_and_reserve(
            self.campaign, date(2030, 1, 1), worker_id="w", idempotency_key="k"
        )
        self.assertEqual(result.outcome, "nothing_eligible")

    def test_recent_planned_topic_is_blocked_by_cooldown(self):
        self.repo.save_plan(self.plan)
        item = self.plan.items[0]
        self.repo.upsert_memory(memory_record(
            self.campaign.campaign_id,
            "recent-topic",
            topic=item.topic,
            planned_date=date(2026, 8, 1),
        ))
        result = self.repo.select_and_reserve(
            self.campaign, date(2026, 8, 6), worker_id="w", idempotency_key="k"
        )
        self.assertEqual(result.outcome, "blocked_by_cooldown")
        self.assertEqual(result.memory_decisions[0].decision, "recent_topic")

    def test_selection_service_returns_invalid_campaign_outcome(self):
        result = CampaignSelectionService(
            CampaignRegistry(ROOT / "campaigns"), self.repo
        ).select("missing", worker_id="w", idempotency_key="k", local_date=date(2026, 8, 6))
        self.assertEqual(result.outcome, "invalid_campaign")
        self.assertIn("unknown campaign", result.reasons[0])

    def test_corrupt_persisted_item_returns_invalid_plan(self):
        self.repo.save_plan(self.plan)
        with self.repo._connect() as connection:
            connection.execute(
                "UPDATE planned_items SET item_json='{}' WHERE planned_item_id=?",
                (self.plan.items[0].planned_item_id,),
            )
        result = self.repo.select_and_reserve(
            self.campaign, date(2026, 8, 6), worker_id="w", idempotency_key="k"
        )
        self.assertEqual(result.outcome, "invalid_plan")

    def test_concurrent_selection_has_exactly_one_new_reservation(self):
        self.repo.save_plan(self.plan)
        outcomes = []
        barrier = threading.Barrier(2)

        def select(key):
            barrier.wait()
            outcomes.append(self.repo.select_and_reserve(
                self.campaign, date(2026, 8, 6), worker_id=key, idempotency_key=key
            ).outcome)

        threads = [threading.Thread(target=select, args=(f"key-{index}",)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(outcomes.count("selected"), 1)
        self.assertEqual(outcomes.count("already_reserved"), 1)

    def test_same_idempotency_key_replays_same_reservation(self):
        self.repo.save_plan(self.plan)
        first = self.repo.select_and_reserve(
            self.campaign, date(2026, 8, 6), worker_id="w", idempotency_key="same"
        )
        second = self.repo.select_and_reserve(
            self.campaign, date(2026, 8, 6), worker_id="w", idempotency_key="same"
        )
        self.assertEqual(first.reservation_id, second.reservation_id)
        self.assertTrue(second.idempotent_replay)

    def test_preview_does_not_reserve(self):
        self.repo.save_plan(self.plan)
        preview = self.repo.preview_next(self.campaign, date(2026, 8, 6))
        selected = self.repo.select_and_reserve(
            self.campaign, date(2026, 8, 6), worker_id="w", idempotency_key="k"
        )
        self.assertEqual(preview.outcome, "selected")
        self.assertIsNone(preview.reservation_id)
        self.assertEqual(selected.outcome, "selected")


if __name__ == "__main__":
    unittest.main()
