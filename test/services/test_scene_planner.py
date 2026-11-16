import json
import unittest
from unittest.mock import patch

from app.services import scene_planner


def response_for(text="The Sun rises above the horizon."):
    return json.dumps(
        {
            "scenes": [
                {
                    "narration_text": text,
                    "estimated_duration_ms": 3500,
                    "timing_confidence": 0.5,
                    "subject": ["Sun"],
                    "action": "rises above the horizon",
                    "context": "ocean at dawn",
                    "description": "The Sun appearing above a flat ocean horizon.",
                    "visual_prompt": "Documentary sunrise over the ocean",
                    "search_queries": ["sunrise ocean horizon"],
                    "recommended_material_type": ["stock_video"],
                }
            ]
        }
    )


class TestScenePlanner(unittest.TestCase):
    def test_plan_script_uses_current_llm_dispatch_and_accepts_fenced_json(self):
        script = "The Sun rises above the horizon."
        with patch.object(
            scene_planner.llm,
            "generate_structured_response",
            return_value=f"```json\n{response_for(script)}\n```",
        ) as generate:
            plan = scene_planner.plan_script(
                script, subject="Sunrise", language="en"
            )

        self.assertEqual(plan.scenes[0].narration_text, script)
        self.assertEqual(plan.scenes[0].visual.subject, ["Sun"])
        self.assertEqual(plan.scenes[0].timing.estimated_duration_ms, 3500)
        self.assertIn("Return one JSON object only", generate.call_args.args[0])

    def test_plan_script_removes_tts_pause_tags_before_planning(self):
        script = "The Sun [pause:1.0] rises."
        with patch.object(
            scene_planner.llm,
            "generate_structured_response",
            return_value=response_for("The Sun rises."),
        ) as generate:
            plan = scene_planner.plan_script(script, subject="Sunrise")

        self.assertEqual(plan.scenes[0].narration_text, "The Sun rises.")
        self.assertIn("The Sun rises.", generate.call_args.args[0])
        self.assertNotIn("[pause", generate.call_args.args[0])

    def test_plan_script_rejects_incomplete_or_invalid_provider_output(self):
        for response in (
            "not json",
            response_for("The Sun rises."),
            "Error: provider unavailable",
        ):
            with self.subTest(response=response), patch.object(
                scene_planner.llm,
                "generate_structured_response",
                return_value=response,
            ), self.assertRaises(scene_planner.ScenePlanError):
                scene_planner.plan_script(
                    "The Sun rises above the horizon.", subject="Sunrise"
                )

    def test_plan_script_rejects_provider_exceptions_with_context(self):
        with patch.object(
            scene_planner.llm,
            "generate_structured_response",
            side_effect=RuntimeError("provider offline"),
        ), self.assertRaisesRegex(scene_planner.ScenePlanError, "provider offline"):
            scene_planner.plan_script("Narration.", subject="test")


if __name__ == "__main__":
    unittest.main()
