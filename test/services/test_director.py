import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models.creative import CreativeBrief, ShotPlan, StyleProfile
from app.models.schema import VideoParams
from app.services import director


VALID_PLAN = {
    "shots": [
        {
            "index": 1,
            "script_segment": "Intro",
            "duration": 4.0,
            "source_type": "stock",
            "query": "city aerial",
            "camera": "drone",
        },
        {
            "index": 2,
            "script_segment": "Scene",
            "duration": 5.0,
            "source_type": "generated_image",
            "prompt": "A cat in a garden, soft light",
        },
    ]
}


def make_params(**overrides):
    data = {
        "video_subject": "a day in shanghai",
        "creative_mode": True,
        "creative_brief": {
            "topic": "a day in shanghai",
            "audience": "tourists",
            "forbidden_elements": ["no text overlays"],
        },
        "style_profile": {"name": "wonderland", "visual_style": "watercolor"},
    }
    data.update(overrides)
    return VideoParams(**data)


class TestBuildShotPlanPrompt(unittest.TestCase):
    def test_prompt_contains_script_and_context(self):
        prompt = director.build_shot_plan_prompt(
            video_script="Line one. Line two.",
            brief=CreativeBrief(
                topic="t",
                audience="tourists",
                forbidden_elements=["no text overlays"],
            ),
            style_profile=StyleProfile(name="wonderland", palette=["#fff"]),
            aspect_ratio="9:16",
            clip_duration=5,
        )
        self.assertIn("Line one. Line two.", prompt)
        self.assertIn("tourists", prompt)
        self.assertIn("no text overlays", prompt)
        self.assertIn("wonderland", prompt)
        self.assertIn("#fff", prompt)
        self.assertIn("9:16", prompt)

    def test_prompt_without_brief_and_style(self):
        prompt = director.build_shot_plan_prompt(video_script="Only script.")
        self.assertIn("Only script.", prompt)
        self.assertNotIn("Creative Brief", prompt)
        self.assertNotIn("Style Profile", prompt)


class TestParseShotPlanResponse(unittest.TestCase):
    def test_parses_object_response(self):
        plan = director.parse_shot_plan_response(
            json.dumps(VALID_PLAN), "task-1"
        )
        self.assertEqual(plan.task_id, "task-1")
        self.assertEqual(len(plan.shots), 2)

    def test_parses_bare_list_response(self):
        plan = director.parse_shot_plan_response(
            json.dumps(VALID_PLAN["shots"]), "task-1"
        )
        self.assertEqual(len(plan.shots), 2)

    def test_strips_code_fence(self):
        fenced = "```json\n" + json.dumps(VALID_PLAN) + "\n```"
        plan = director.parse_shot_plan_response(fenced, "task-1")
        self.assertEqual(len(plan.shots), 2)

    def test_rejects_invalid_json(self):
        with self.assertRaises(Exception):
            director.parse_shot_plan_response("not json", "task-1")

    def test_rejects_unknown_source_type(self):
        bad = {"shots": [{"index": 1, "source_type": "drone"}]}
        with self.assertRaises(Exception):
            director.parse_shot_plan_response(json.dumps(bad), "task-1")

    def test_promotes_query_to_prompt_for_generated_shot(self):
        plan_dict = {
            "shots": [
                {
                    "index": 1,
                    "source_type": "generated_image",
                    "query": "A cat in a garden, soft light",
                }
            ]
        }
        plan = director.parse_shot_plan_response(
            json.dumps(plan_dict), "task-1"
        )
        self.assertEqual(plan.shots[0].prompt, "A cat in a garden, soft light")
        self.assertIsNone(plan.shots[0].query)
        self.assertEqual(director.validate_shot_plan(plan), [])

    def test_keeps_explicit_prompt_over_query(self):
        plan_dict = {
            "shots": [
                {
                    "index": 1,
                    "source_type": "generated_video",
                    "prompt": "steam rising from a pot",
                    "query": "steam broll",
                }
            ]
        }
        plan = director.parse_shot_plan_response(
            json.dumps(plan_dict), "task-1"
        )
        self.assertEqual(plan.shots[0].prompt, "steam rising from a pot")
        self.assertEqual(plan.shots[0].query, "steam broll")

    def test_stock_shot_query_untouched(self):
        plan = director.parse_shot_plan_response(
            json.dumps(VALID_PLAN), "task-1"
        )
        self.assertEqual(plan.shots[0].query, "city aerial")
        self.assertIsNone(plan.shots[0].prompt)


class TestGenerateShotPlan(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.task_dir = Path(self.temp_dir.name)
        self.task_dir_patch = patch(
            "app.services.task_artifacts.utils.task_dir",
            return_value=str(self.task_dir),
        )
        self.task_dir_patch.start()

    def tearDown(self):
        self.task_dir_patch.stop()
        self.temp_dir.cleanup()

    def test_success_persists_shot_plan(self):
        params = make_params()
        with patch(
            "app.services.llm._generate_response",
            return_value=json.dumps(VALID_PLAN),
        ) as mock_llm:
            plan = director.generate_shot_plan("task-1", params, "Intro. Scene.")

        self.assertIsInstance(plan, ShotPlan)
        self.assertEqual(len(plan.shots), 2)
        payload = json.loads((self.task_dir / "shot_plan.json").read_text())
        self.assertEqual(payload["task_id"], "task-1")
        self.assertEqual(payload["shots"][1]["source_type"], "generated_image")
        prompt = mock_llm.call_args[0][0]
        self.assertIn("tourists", prompt)

    def test_retry_then_success(self):
        invalid = {"shots": [{"index": 1, "source_type": "stock"}]}
        responses = [json.dumps(invalid), json.dumps(VALID_PLAN)]
        params = make_params()
        with patch(
            "app.services.llm._generate_response", side_effect=responses
        ) as mock_llm:
            plan = director.generate_shot_plan("task-1", params, "Intro.")
        self.assertIsInstance(plan, ShotPlan)
        self.assertEqual(mock_llm.call_count, 2)

    def test_error_response_returns_none(self):
        params = make_params()
        with patch(
            "app.services.llm._generate_response",
            return_value="Error: boom",
        ) as mock_llm:
            plan = director.generate_shot_plan("task-1", params, "Intro.")
        self.assertIsNone(plan)
        self.assertEqual(mock_llm.call_count, 1)
        self.assertFalse((self.task_dir / "shot_plan.json").exists())

    def test_persistent_semantic_failure_returns_none(self):
        invalid = {
            "shots": [
                {"index": 1, "source_type": "stock"},
                {"index": 2, "source_type": "generated_image"},
            ]
        }
        params = make_params()
        with patch(
            "app.services.llm._generate_response",
            return_value=json.dumps(invalid),
        ) as mock_llm:
            plan = director.generate_shot_plan("task-1", params, "Intro.")
        self.assertIsNone(plan)
        self.assertEqual(mock_llm.call_count, 5)
        self.assertFalse((self.task_dir / "shot_plan.json").exists())
