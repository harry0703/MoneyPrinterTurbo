from __future__ import annotations

import unittest
from datetime import UTC, date, datetime

from app.campaigns.models import SourceStatus
from app.campaigns.planner import CampaignPlanner
from app.campaigns.story import LegacyLlmConceptAdapter, RuleBasedConceptGenerator, StoryEngine
from test.campaigns.common import heritage_campaign


NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)


class StoryEngineTests(unittest.TestCase):
    def setUp(self):
        self.campaign = heritage_campaign()
        self.item = CampaignPlanner().plan(
            self.campaign, date(2026, 8, 1), 1, random_seed=9, now=NOW
        ).items[0]
        self.engine = StoryEngine()
        self.package = self.engine.build_package(self.campaign, self.item, now=NOW)

    def test_story_brief_is_campaign_and_item_derived(self):
        brief = self.package.brief
        self.assertEqual(brief.planned_item_id, self.item.planned_item_id)
        self.assertEqual(brief.campaign_id, self.campaign.campaign_id)
        self.assertEqual(brief.story_format, self.item.story_format)
        self.assertEqual(brief.target_word_count, round(self.item.target_duration_seconds * 150 / 60))
        self.assertEqual(brief.source_status, SourceStatus.SOURCE_NOT_REQUIRED)

    def test_rule_based_concepts_are_deterministic_and_multiple(self):
        provider = RuleBasedConceptGenerator()
        left = provider.generate(self.package.brief, 4)
        right = provider.generate(self.package.brief, 4)
        self.assertEqual(left, right)
        self.assertEqual(len(left), 4)
        self.assertEqual(len({value.concept_id for value in left}), 4)

    def test_concept_selection_is_scored_and_explainable(self):
        selected = next(
            value for value in self.package.concept_candidates
            if value.concept_id == self.package.selected_concept_id
        )
        self.assertGreater(selected.selection_score, 0)
        self.assertIn("campaign_fit", selected.score_breakdown)
        self.assertGreaterEqual(len(selected.selection_reasoning), 3)

    def test_memory_similarity_reduces_concept_novelty_score(self):
        brief = self.package.brief
        candidates = RuleBasedConceptGenerator().generate(brief, 2)
        selected = self.engine.select_concept(
            brief, candidates, {candidates[0].concept_id: 1.0, candidates[1].concept_id: 0.0}
        )
        self.assertEqual(selected.concept_id, candidates[1].concept_id)

    def test_hook_is_separate_with_alternatives_and_fingerprint(self):
        hook = self.package.hook
        self.assertTrue(hook.text)
        self.assertTrue(hook.hook_type)
        self.assertEqual(len(hook.novelty_fingerprint), 64)
        self.assertTrue(hook.alternatives)
        self.assertTrue(hook.selection_reasoning)

    def test_story_format_template_controls_beat_structure(self):
        template = next(
            value for value in self.campaign.story_formats
            if value.id == self.package.brief.story_format
        )
        self.assertEqual([beat.beat_type for beat in self.package.beats], template.beat_structure)
        self.assertEqual([beat.beat_number for beat in self.package.beats], list(range(1, len(self.package.beats) + 1)))

    def test_script_has_segments_and_configurable_duration_estimate(self):
        script = self.package.script
        self.assertEqual(script.full_narration, " ".join(value.text for value in script.narration_segments))
        self.assertEqual(script.word_count, len(script.full_narration.split()))
        self.assertAlmostEqual(script.estimated_spoken_duration_seconds, script.word_count / 2.5, places=1)
        self.assertIn("150", script.estimate_method)

    def test_scene_plan_is_aligned_and_visually_varied(self):
        self.assertEqual(len(self.package.scenes), len(self.package.script.narration_segments))
        self.assertEqual(self.package.scenes[0].start_time_seconds, 0)
        self.assertTrue(all(scene.stock_search_terms for scene in self.package.scenes))
        self.assertGreaterEqual(len({scene.shot_type for scene in self.package.scenes}), 3)
        self.assertEqual(
            [scene.narration_segment for scene in self.package.scenes],
            [segment.text for segment in self.package.script.narration_segments],
        )

    def test_caption_package_has_distribution_and_accessibility_fields(self):
        caption = self.package.caption
        self.assertTrue(caption.primary_caption)
        self.assertIn("facebook", caption.platform_variants)
        self.assertTrue(caption.community_question.endswith("?"))
        self.assertTrue(caption.accessibility_description)
        self.assertEqual(len(caption.caption_fingerprint), 64)

    def test_offline_package_has_no_validation_errors(self):
        errors = [value for value in self.package.validation_issues if value.severity == "error"]
        self.assertEqual(errors, [])
        self.assertTrue(20 <= self.package.script.estimated_spoken_duration_seconds <= 60)

    def test_stage_regeneration_preserves_lineage(self):
        for stage in ("hook", "script", "scene_plan", "caption", "validation"):
            regenerated = self.engine.regenerate(self.package, self.campaign, stage)
            self.assertEqual(regenerated.parent_story_version_id, self.package.story_version_id)
            self.assertNotEqual(regenerated.story_version_id, self.package.story_version_id)
        hook = self.engine.regenerate(self.package, self.campaign, "hook")
        self.assertEqual(hook.hook.metadata.parent_stage_id, self.package.hook.metadata.stage_id)

    def test_single_beat_regeneration_preserves_other_beats(self):
        regenerated = self.engine.regenerate(self.package, self.campaign, "beat", beat_number=2)
        self.assertEqual(regenerated.beats[0], self.package.beats[0])
        self.assertEqual(
            regenerated.beats[1].metadata.parent_stage_id,
            self.package.beats[1].metadata.stage_id,
        )

    def test_alternate_concept_generation_adds_candidate_and_rebuilds_dependents(self):
        regenerated = self.engine.regenerate(
            self.package, self.campaign, "alternate_concept"
        )
        self.assertEqual(
            len(regenerated.concept_candidates),
            len(self.package.concept_candidates) + 1,
        )
        self.assertNotEqual(regenerated.selected_concept_id, self.package.selected_concept_id)
        self.assertEqual(regenerated.parent_story_version_id, self.package.story_version_id)
        self.assertEqual(
            regenerated.script.generation_metadata.parent_stage_id,
            self.package.script.generation_metadata.stage_id,
        )

    def test_missing_hook_and_scene_misalignment_are_errors(self):
        bad_hook = self.package.hook.model_copy(update={"text": ""})
        bad = self.package.model_copy(update={"hook": bad_hook, "scenes": self.package.scenes[:-1]})
        codes = {value.code for value in self.engine.validate(bad, self.campaign)}
        self.assertIn("missing_hook", codes)
        self.assertIn("scene_narration_misalignment", codes)

    def test_duration_and_word_count_validation(self):
        script = self.package.script.model_copy(
            update={"estimated_spoken_duration_seconds": 10, "word_count": 5}
        )
        bad = self.package.model_copy(update={"script": script})
        codes = {value.code for value in self.engine.validate(bad, self.campaign)}
        self.assertIn("duration_out_of_range", codes)
        self.assertIn("word_count_out_of_range", codes)

    def test_repeated_phrase_and_unresolved_placeholder_validation(self):
        narration = "A repeated phrase. A repeated phrase. {{missing_value}}"
        script = self.package.script.model_copy(update={"full_narration": narration})
        bad = self.package.model_copy(update={"script": script})
        codes = {value.code for value in self.engine.validate(bad, self.campaign)}
        self.assertIn("repeated_phrase", codes)
        self.assertIn("unresolved_placeholder", codes)

    def test_generic_opening_and_excessive_questions_are_warnings(self):
        narration = "In today's video? One? Two? Three? Four?"
        script = self.package.script.model_copy(update={"full_narration": narration})
        bad = self.package.model_copy(update={"script": script})
        codes = {value.code for value in self.engine.validate(bad, self.campaign)}
        self.assertIn("generic_opening", codes)
        self.assertIn("excessive_rhetorical_questions", codes)

    def test_unsupported_factual_status_blocks_validation(self):
        brief = self.package.brief.model_copy(update={"source_status": SourceStatus.SOURCE_REQUIRED})
        bad = self.package.model_copy(update={"brief": brief})
        issues = self.engine.validate(bad, self.campaign)
        self.assertTrue(any(value.code == "unsupported_factual_claim" and value.severity == "error" for value in issues))

    def test_duplicate_hook_missing_cta_and_unsupported_format(self):
        brief = self.package.brief.model_copy(update={"story_format": "not-allowed"})
        script = self.package.script.model_copy(update={"cta": ""})
        bad = self.package.model_copy(update={"brief": brief, "script": script})
        issues = self.engine.validate(
            bad,
            self.campaign,
            recent_hook_fingerprints={self.package.hook.novelty_fingerprint},
        )
        codes = {value.code for value in issues}
        self.assertIn("duplicate_hook", codes)
        self.assertIn("missing_cta", codes)
        self.assertIn("unsupported_story_format", codes)

    def test_contradictory_absolutes_and_excessive_disclaimers_warn(self):
        narration = "This always happens. This never happens. Disclaimer one. Disclaimer two."
        script = self.package.script.model_copy(update={"full_narration": narration})
        bad = self.package.model_copy(update={"script": script})
        codes = {value.code for value in self.engine.validate(bad, self.campaign)}
        self.assertIn("contradictory_details", codes)
        self.assertIn("excessive_disclaimers", codes)

    def test_content_exclusion_and_tone_violation_are_errors(self):
        narration = "This includes invented genealogy and sensationalism."
        script = self.package.script.model_copy(update={"full_narration": narration})
        bad = self.package.model_copy(update={"script": script})
        codes = {value.code for value in self.engine.validate(bad, self.campaign)}
        self.assertIn("content_exclusion", codes)
        self.assertIn("campaign_tone_violation", codes)

    def test_private_unsafe_and_artist_imitation_language_is_flagged(self):
        narration = "Reveal a home address, build a weapon, and imitate Taylor Swift."
        script = self.package.script.model_copy(update={"full_narration": narration})
        bad = self.package.model_copy(update={"script": script})
        codes = {value.code for value in self.engine.validate(bad, self.campaign)}
        self.assertIn("private_person_claim", codes)
        self.assertIn("unsafe_instruction", codes)
        self.assertIn("living_artist_imitation", codes)

    def test_existing_llm_adapter_contract_uses_injected_function(self):
        calls = []

        def generate_script(**kwargs):
            calls.append(kwargs)
            return "A provider draft that remains subject to structured validation."

        concepts = LegacyLlmConceptAdapter(generate_script).generate(self.package.brief)
        self.assertEqual(len(concepts), 1)
        self.assertEqual(calls[0]["video_subject"], self.package.brief.topic)
        self.assertEqual(concepts[0].metadata.provider, "legacy_llm_adapter")


if __name__ == "__main__":
    unittest.main()
