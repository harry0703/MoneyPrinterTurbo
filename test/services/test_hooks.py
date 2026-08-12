import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.services import hooks, llm


class TestHookRejection(unittest.TestCase):
    def test_greetings_and_topic_announcements_are_rejected(self):
        """The one rule docs/playbook/hooks.md states outright: no warm-up openings."""
        for opening in [
            "Hi everyone, today we're going to talk about Messi.",
            "Hello guys, welcome back to the channel.",
            "In this video I will explain the offside rule.",
            "Today we look at the strangest goal ever scored.",
            "Привет! Сегодня мы разберём самый странный гол.",
            "В этом видео расскажу про офсайд.",
        ]:
            with self.subTest(opening=opening):
                self.assertTrue(hooks.rejection_reason(opening))

    def test_concrete_openings_pass(self):
        for opening in [
            "This goal should never have counted.",
            "Look at the player on the left one second before the shot.",
            "Messi scored 91 goals in 2012 and nobody has come close since.",
        ]:
            with self.subTest(opening=opening):
                self.assertEqual(hooks.rejection_reason(opening), "")

    def test_length_bounds(self):
        self.assertTrue(hooks.rejection_reason("Wow."))
        self.assertTrue(hooks.rejection_reason(" ".join(["word"] * 40)))

    def test_banned_words_are_only_rejected_at_the_start(self):
        """"Today" mid-sentence is a fact, not a warm-up."""
        self.assertEqual(
            hooks.rejection_reason("Nobody today can explain what happened next."),
            "",
        )


class TestCandidateParsing(unittest.TestCase):
    def test_rejected_and_duplicate_candidates_are_dropped(self):
        parsed = [
            {"hook": "Hi everyone, today we talk about coffee.", "hook_type": "myth"},
            {"hook": "This cup cost 400 dollars.", "hook_type": "unexpected_number"},
            {"hook": "this cup cost 400 dollars.", "hook_type": "stakes"},
            {"hook": "Look at the label on the left.", "hook_type": "visual_instruction"},
        ]

        candidates = hooks.parse_candidates(parsed, count=5)

        self.assertEqual(
            [item["hook"] for item in candidates],
            ["This cup cost 400 dollars.", "Look at the label on the left."],
        )

    def test_unknown_hook_type_keeps_the_hook(self):
        """An unusable label costs the analytics dimension, not a usable hook."""
        candidates = hooks.parse_candidates(
            [{"hook": "This cup cost 400 dollars.", "hook_type": "clickbait"}], count=5
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["hook_type"], "unknown")

    def test_count_is_respected(self):
        parsed = [{"hook": f"Fact number {i} nobody checked.", "hook_type": "myth"} for i in range(9)]

        self.assertEqual(len(hooks.parse_candidates(parsed, count=3)), 3)

    def test_non_list_payload_yields_nothing(self):
        self.assertEqual(hooks.parse_candidates({"hook": "x"}, count=3), [])


class TestScorerParsing(unittest.TestCase):
    def setUp(self):
        self.candidates = [
            {"hook": "First candidate line here.", "hook_type": "myth"},
            {"hook": "Second candidate line here.", "hook_type": "stakes"},
        ]

    def test_choice_is_resolved_with_its_reason(self):
        chosen = hooks.parse_choice({"best": 1, "reason": "opens a loop"}, self.candidates)

        self.assertEqual(chosen["hook"], "Second candidate line here.")
        self.assertEqual(chosen["hook_type"], "stakes")
        self.assertEqual(chosen["reason"], "opens a loop")

    def test_out_of_range_and_garbage_fall_back_to_the_first_candidate(self):
        for payload in [{"best": 7}, {"best": -1}, {"best": "best one"}, ["nope"]]:
            with self.subTest(payload=payload):
                chosen = hooks.parse_choice(payload, self.candidates)
                self.assertEqual(chosen["hook"], "First candidate line here.")

    def test_no_candidates_gives_nothing(self):
        self.assertEqual(hooks.parse_choice({"best": 0}, []), {})


class TestCandidatesPrompt(unittest.TestCase):
    def test_prompt_carries_the_classes_and_constraints(self):
        prompt = hooks.build_candidates_prompt("Messi in 2012", count=4)

        self.assertIn("visual_instruction", prompt)
        self.assertIn("Messi in 2012", prompt)
        self.assertIn("4 competing opening lines", prompt)
        self.assertIn("never open with a greeting", prompt)

    def test_format_and_platform_are_injected_when_known(self):
        prompt = hooks.build_candidates_prompt(
            "Messi in 2012", platform="reels", video_format="mystery_reveal"
        )

        self.assertIn("mystery reveal", prompt)
        self.assertIn("open loop", prompt)
        self.assertIn("Instagram Reels", prompt)

    def test_unknown_format_is_ignored(self):
        prompt = hooks.build_candidates_prompt("Messi", video_format="tiktok_dance")

        self.assertNotIn("## Format:", prompt)


class TestExtractJson(unittest.TestCase):
    def test_code_fenced_and_chatty_payloads_are_recovered(self):
        self.assertEqual(hooks.extract_json('```json\n[{"a": 1}]\n```'), [{"a": 1}])
        self.assertEqual(
            hooks.extract_json('Sure! Here you go: {"best": 2} hope this helps'),
            {"best": 2},
        )


class TestGenerateHook(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        config.app.update(
            {"script_prompt_preset": "playbook", "hook_candidates": 3}
        )

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def _responses(self, *payloads):
        return [json.dumps(payload) for payload in payloads]

    def test_candidates_then_scorer(self):
        responses = self._responses(
            [
                {"hook": "First candidate line here.", "hook_type": "myth"},
                {"hook": "Second candidate line here.", "hook_type": "stakes"},
            ],
            {"best": 1, "reason": "higher stakes"},
        )

        with patch.object(llm, "_generate_response", side_effect=responses) as call:
            chosen = llm.generate_hook("Messi in 2012")

        self.assertEqual(chosen["hook"], "Second candidate line here.")
        self.assertEqual(chosen["hook_type"], "stakes")
        self.assertEqual(chosen["candidates"], 2)
        self.assertEqual(call.call_count, 2)

    def test_single_candidate_skips_the_scorer(self):
        """One survivor has nothing to be scored against; do not pay for the call."""
        responses = self._responses(
            [{"hook": "Only candidate line here.", "hook_type": "myth"}]
        )

        with patch.object(llm, "_generate_response", side_effect=responses) as call:
            chosen = llm.generate_hook("Messi in 2012")

        self.assertEqual(chosen["hook"], "Only candidate line here.")
        self.assertEqual(call.call_count, 1)

    def test_disabled_when_preset_is_off(self):
        config.app["script_prompt_preset"] = ""

        with patch.object(llm, "_generate_response") as call:
            self.assertEqual(llm.generate_hook("Messi"), {})

        call.assert_not_called()

    def test_disabled_when_candidate_count_is_zero(self):
        config.app["hook_candidates"] = 0

        with patch.object(llm, "_generate_response") as call:
            self.assertEqual(llm.generate_hook("Messi"), {})

        call.assert_not_called()

    def test_provider_error_degrades_to_a_plain_script(self):
        """A failed hook step must not fail the video: the script step still runs."""
        with patch.object(llm, "_generate_response", return_value="Error: quota"):
            self.assertEqual(llm.generate_hook("Messi"), {})

    def test_all_candidates_rejected_degrades_to_a_plain_script(self):
        responses = self._responses(
            [{"hook": "Hi everyone, today we talk about Messi.", "hook_type": "myth"}]
        )

        with patch.object(llm, "_generate_response", side_effect=responses * 5):
            self.assertEqual(llm.generate_hook("Messi"), {})


class TestHookReachesTheScriptPrompt(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        config.app["script_prompt_preset"] = "playbook"

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def test_hook_is_pinned_verbatim(self):
        prompt = llm.build_script_prompt(
            video_subject="Messi", hook="This goal should never have counted."
        )

        self.assertIn("verbatim", prompt)
        self.assertIn("This goal should never have counted.", prompt)

    def test_no_hook_leaves_the_prompt_untouched(self):
        prompt = llm.build_script_prompt(video_subject="Messi", hook="   ")

        self.assertNotIn("opening line", prompt)

    def test_hook_survives_a_custom_system_prompt(self):
        """The hook is runtime context, not a rule: overriding the rules keeps it."""
        prompt = llm.build_script_prompt(
            video_subject="Messi",
            custom_system_prompt="# Role: My Own Writer",
            hook="This goal should never have counted.",
        )

        self.assertIn("This goal should never have counted.", prompt)


if __name__ == "__main__":
    unittest.main()
