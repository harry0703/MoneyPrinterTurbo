from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.campaigns.memory import (
    ApproximateSimilarity,
    ContentMemoryRepository,
    TokenJaccardSimilarity,
    fingerprint,
    normalize_text,
)
from app.campaigns.models import LifecycleState, SeriesMetadata
from test.campaigns.common import heritage_campaign, memory_record, repository


class NormalizationAndFingerprintTests(unittest.TestCase):
    def test_case_whitespace_punctuation_and_unicode_normalize_stably(self):
        left = normalize_text("  Café—STORY!!!  ")
        right = normalize_text("cafe\u0301 story")
        self.assertEqual(left, right)
        self.assertEqual(fingerprint("topic", left), fingerprint("topic", right))

    def test_repeated_punctuation_and_formatting_do_not_change_fingerprint(self):
        self.assertEqual(
            fingerprint("hook", "What... is this?!"),
            fingerprint("hook", "what is this"),
        )

    def test_caption_hashtag_order_is_normalized(self):
        self.assertEqual(
            fingerprint("caption", "Remember this. #Family #History"),
            fingerprint("caption", "remember this #history #family"),
        )

    def test_campaign_stop_phrase_can_remove_boilerplate_cta(self):
        phrases = ["Share a memory if this brings one to mind."]
        self.assertEqual(
            fingerprint("script", "A story. Share a memory if this brings one to mind.", stop_phrases=phrases),
            fingerprint("script", "A story", stop_phrases=phrases),
        )

    def test_artifact_types_have_distinct_fingerprint_namespaces(self):
        self.assertNotEqual(fingerprint("hook", "same"), fingerprint("script", "same"))

    def test_token_jaccard_is_lightweight_and_stable(self):
        similarity = TokenJaccardSimilarity()
        self.assertEqual(similarity.method, "token_jaccard_v1")
        self.assertAlmostEqual(similarity.compare("one two", "two three"), 1 / 3)
        self.assertIsInstance(similarity, ApproximateSimilarity)


class ContentMemoryDecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = repository(Path(self.temp.name) / "memory.sqlite3")
        self.campaign = heritage_campaign()

    def add(self, **kwargs):
        record = memory_record(self.campaign.campaign_id, kwargs.pop("record_id", "record-1"), **kwargs)
        self.repo.upsert_memory(record)
        return record

    def test_no_history_is_insufficient_but_allowed(self):
        decision = self.repo.check(self.campaign, "topic", "new topic", date(2026, 8, 1))
        self.assertEqual(decision.decision, "insufficient_history")
        self.assertFalse(decision.blocking)

    def test_exact_and_normalized_topic_duplicate_obeys_cooldown(self):
        self.add(topic="A Familiar Place!", planned_date=date(2026, 7, 20))
        decision = self.repo.check(self.campaign, "topic", "a familiar place", date(2026, 8, 1))
        self.assertEqual(decision.decision, "recent_topic")
        self.assertEqual(decision.days_since_previous_use, 12)
        self.assertTrue(decision.blocking)
        self.assertEqual(decision.similarity.method, "sha256_normalized_v1")

    def test_topic_outside_cooldown_is_warning_not_block(self):
        self.add(topic="A Familiar Place", planned_date=date(2026, 1, 1))
        decision = self.repo.check(self.campaign, "topic", "a familiar place", date(2026, 8, 1))
        self.assertEqual(decision.decision, "allowed_with_warning")
        self.assertFalse(decision.blocking)

    def test_hook_script_and_caption_have_independent_cooldowns(self):
        self.add(planned_date=date(2026, 7, 30))
        self.assertEqual(
            self.repo.check(self.campaign, "hook", "what does this place remember", date(2026, 8, 1)).decision,
            "recent_hook",
        )
        self.assertEqual(
            self.repo.check(self.campaign, "script", "a familiar place can hold a shared memory", date(2026, 8, 1)).decision,
            "recent_script",
        )
        self.assertEqual(
            self.repo.check(self.campaign, "caption", "share a memory #history #community", date(2026, 8, 1)).decision,
            "exact_duplicate",
        )

    def test_media_hash_duplicate_is_blocked(self):
        record = self.add(planned_date=date(2026, 7, 1))
        self.repo.upsert_memory(record.model_copy(update={"media_hashes": ["ABC123"]}))
        decision = self.repo.check(self.campaign, "media", "abc123", date(2026, 8, 1))
        self.assertEqual(decision.decision, "recent_media")
        self.assertTrue(decision.blocking)

    def test_cta_overlap_is_explicitly_allowed(self):
        self.add()
        decision = self.repo.check(self.campaign, "cta", "Share a memory", date(2026, 8, 1))
        self.assertEqual(decision.decision, "allowed")
        self.assertIn("only the CTA", decision.reason)

    def test_intentional_series_overlap_is_allowed(self):
        series = SeriesMetadata(
            series_id="series-1", series_title="One Place", episode_number=1,
            recurring_format_allowance=True, permitted_overlap=["topic"],
        )
        self.add(topic="the old depot", series=series, planned_date=date(2026, 7, 31))
        next_episode = series.model_copy(update={"episode_number": 2, "previous_episode": "episode-1"})
        decision = self.repo.check(
            self.campaign, "topic", "the old depot", date(2026, 8, 1), series=next_episode
        )
        self.assertEqual(decision.decision, "intentional_series_match")
        self.assertFalse(decision.blocking)

    def test_approximate_similarity_returns_structured_warning(self):
        self.add(topic="record an old family recipe with its context")
        decision = self.repo.check(
            self.campaign,
            "topic",
            "record an old family recipe with context",
            date(2026, 8, 1),
        )
        self.assertEqual(decision.decision, "allowed_with_warning")
        self.assertEqual(decision.similarity.method, "token_jaccard_v1")

    def test_comparison_error_is_structured(self):
        decision = self.repo.check(self.campaign, "unknown", "value", date(2026, 8, 1))
        self.assertEqual(decision.decision, "comparison_error")
        self.assertTrue(decision.blocking)

    def test_policy_audit_records_explanation(self):
        self.add()
        self.repo.check(self.campaign, "topic", "new", date(2026, 8, 1), audit=True)
        audit = self.repo.audit_log(self.campaign.campaign_id)
        self.assertEqual(len(audit), 1)
        self.assertIn("decision", audit[0])


class ReservationAndHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "memory.sqlite3"
        self.repo = ContentMemoryRepository(self.path)
        self.campaign = heritage_campaign()

    def test_migration_preview_does_not_create_database(self):
        result = self.repo.migration_preview()
        self.assertFalse(result["database_exists"])
        self.assertEqual(result["pending"], [1])
        self.assertFalse(self.path.exists())

    def test_stale_reservation_recovery(self):
        self.repo.initialize()
        from app.campaigns.planner import CampaignPlanner

        now = datetime(2026, 8, 1, 12, tzinfo=UTC)
        plan = CampaignPlanner().plan(self.campaign, date(2026, 8, 1), 1, now=now)
        self.repo.save_plan(plan)
        first = self.repo.select_and_reserve(
            self.campaign, date(2026, 8, 1), worker_id="old", idempotency_key="old",
            reservation_ttl=timedelta(minutes=5), now=now,
        )
        released = self.repo.release_stale_reservations(now + timedelta(minutes=6))
        second = self.repo.select_and_reserve(
            self.campaign, date(2026, 8, 1), worker_id="new", idempotency_key="new",
            now=now + timedelta(minutes=6),
        )
        self.assertEqual(released, [first.planned_item.planned_item_id])
        self.assertEqual(second.outcome, "selected")
        self.assertNotEqual(first.reservation_id, second.reservation_id)

    def test_active_reservation_requires_force_to_release(self):
        self.repo.initialize()
        from app.campaigns.planner import CampaignPlanner

        plan = CampaignPlanner().plan(self.campaign, date.today(), 1)
        self.repo.save_plan(plan)
        result = self.repo.select_and_reserve(
            self.campaign, date.today(), worker_id="w", idempotency_key="k"
        )
        self.assertFalse(self.repo.release_reservation(result.planned_item.planned_item_id))
        self.assertTrue(self.repo.release_reservation(result.planned_item.planned_item_id, force=True))

    def test_rejected_failed_published_and_lineage_records_are_preserved(self):
        self.repo.initialize()
        statuses = [LifecycleState.REJECTED, LifecycleState.FAILED, LifecycleState.PUBLISHED]
        parent = None
        for index, status in enumerate(statuses):
            record = memory_record(
                self.campaign.campaign_id, f"record-{index}", status=status,
                parent=parent, planned_date=date(2026, 7, index + 1),
            )
            if status == LifecycleState.REJECTED:
                record = record.model_copy(update={"rejection_reason": "not on brand"})
            if status == LifecycleState.FAILED:
                record = record.model_copy(update={"failure_reason": "validation failed"})
            self.repo.upsert_memory(record)
            parent = record.story_version_id
        values = self.repo.recent(self.campaign.campaign_id)
        self.assertEqual(len(values), 3)
        self.assertTrue(any(value.rejection_reason for value in values))
        self.assertTrue(any(value.failure_reason for value in values))
        self.assertTrue(any(value.parent_version_id for value in values))

    def test_rebuild_and_json_csv_export(self):
        self.repo.initialize()
        self.repo.upsert_memory(memory_record(self.campaign.campaign_id, "record"))
        self.assertEqual(self.repo.rebuild_fingerprints(self.campaign), 1)
        exported_json = json.loads(self.repo.export(self.campaign.campaign_id, "json"))
        exported_csv = self.repo.export(self.campaign.campaign_id, "csv")
        self.assertEqual(exported_json[0]["memory_record_id"], "record")
        self.assertIn("memory_record_id", exported_csv.splitlines()[0])
        self.assertNotIn("api_key", exported_csv.casefold())

    def test_activity_summary_distinguishes_plan_and_memory_states(self):
        self.repo.initialize()
        from app.campaigns.planner import CampaignPlanner

        plan = CampaignPlanner().plan(self.campaign, date(2026, 8, 1), 1)
        self.repo.save_plan(plan)
        failed = memory_record(
            self.campaign.campaign_id, "failed", status=LifecycleState.FAILED,
            planned_date=date(2026, 8, 1),
        ).model_copy(update={"failure_reason": "abandoned after validation"})
        self.repo.upsert_memory(failed)
        report = self.repo.activity_summary(self.campaign.campaign_id)
        self.assertEqual(report["planned_item_status_counts"]["planned"], 1)
        self.assertEqual(report["memory_status_counts"]["failed"], 1)
        self.assertEqual(report["failed_or_abandoned"][0]["failure_reason"], "abandoned after validation")


if __name__ == "__main__":
    unittest.main()
