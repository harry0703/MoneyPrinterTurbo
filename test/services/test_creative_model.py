import unittest

from pydantic import ValidationError

from app.models.creative import (
    SHOT_SOURCE_TYPES,
    CreativeBrief,
    ShotPlan,
    ShotPlanItem,
    StyleProfile,
    validate_shot_plan,
)
from app.models.schema import VideoParams


def make_shot(index, source_type="stock", **overrides):
    data = {
        "index": index,
        "script_segment": f"segment {index}",
        "duration": 4.0,
        "source_type": source_type,
    }
    if source_type in ("stock", "local"):
        data["query"] = "city aerial"
    else:
        data["prompt"] = "A cat in a garden, soft light"
    data.update(overrides)
    return ShotPlanItem(**data)


class TestCreativeBrief(unittest.TestCase):
    def test_minimal_brief(self):
        brief = CreativeBrief(topic="a day in shanghai")
        self.assertEqual(brief.topic, "a day in shanghai")
        self.assertIsNone(brief.audience)
        self.assertEqual(brief.references, [])
        self.assertEqual(brief.forbidden_elements, [])

    def test_topic_is_required(self):
        with self.assertRaises(ValidationError):
            CreativeBrief()

    def test_full_brief(self):
        brief = CreativeBrief(
            topic="t",
            audience="tourists",
            tone="calm",
            references=["ref1"],
            forbidden_elements=["no text overlays"],
        )
        self.assertEqual(brief.audience, "tourists")
        self.assertEqual(brief.forbidden_elements, ["no text overlays"])


class TestStyleProfile(unittest.TestCase):
    def test_minimal_profile(self):
        profile = StyleProfile(name="wonderland")
        self.assertEqual(profile.palette, [])
        self.assertEqual(profile.negative_rules, [])

    def test_name_is_required(self):
        with self.assertRaises(ValidationError):
            StyleProfile()


class TestShotPlanItem(unittest.TestCase):
    def test_defaults(self):
        shot = make_shot(1)
        self.assertEqual(shot.status, "planned")
        self.assertIsNone(shot.asset_path)

    def test_all_source_types_accepted(self):
        for source_type in SHOT_SOURCE_TYPES:
            self.assertEqual(
                make_shot(1, source_type).source_type, source_type
            )

    def test_source_type_is_normalized(self):
        self.assertEqual(make_shot(1, "STOCK").source_type, "stock")

    def test_unknown_source_type_rejected(self):
        with self.assertRaises(ValidationError):
            ShotPlanItem(index=1, source_type="drone")

    def test_duration_must_be_positive(self):
        with self.assertRaises(ValidationError):
            make_shot(1, duration=0)
        with self.assertRaises(ValidationError):
            make_shot(1, duration=-2.5)

    def test_invalid_status_rejected(self):
        with self.assertRaises(ValidationError):
            make_shot(1, status="done")


class TestShotPlan(unittest.TestCase):
    def test_sequential_indices_accepted(self):
        plan = ShotPlan(task_id="task-1", shots=[make_shot(1), make_shot(2)])
        self.assertEqual([shot.index for shot in plan.shots], [1, 2])

    def test_non_sequential_indices_rejected(self):
        with self.assertRaises(ValidationError):
            ShotPlan(task_id="task-1", shots=[make_shot(1), make_shot(3)])

    def test_indices_must_start_at_one(self):
        with self.assertRaises(ValidationError):
            ShotPlan(task_id="task-1", shots=[make_shot(2)])

    def test_empty_shots_allowed_at_model_level(self):
        plan = ShotPlan(task_id="task-1")
        self.assertEqual(plan.shots, [])
        self.assertEqual(plan.version, 1)


class TestValidateShotPlan(unittest.TestCase):
    def test_valid_plan_has_no_issues(self):
        plan = ShotPlan(
            task_id="task-1",
            shots=[
                make_shot(1, "stock"),
                make_shot(2, "generated_image"),
                make_shot(3, "graphic", duration=None),
            ],
        )
        self.assertEqual(validate_shot_plan(plan), [])

    def test_empty_plan_is_invalid(self):
        issues = validate_shot_plan(ShotPlan(task_id="task-1"))
        self.assertEqual(issues, ["shot plan contains no shots"])

    def test_stock_shot_requires_query(self):
        plan = ShotPlan(
            task_id="task-1",
            shots=[make_shot(1, "stock", query="   ")],
        )
        issues = validate_shot_plan(plan)
        self.assertTrue(any("search query" in issue for issue in issues))

    def test_generated_shot_requires_prompt(self):
        plan = ShotPlan(
            task_id="task-1",
            shots=[make_shot(1, "generated_image", prompt=None)],
        )
        issues = validate_shot_plan(plan)
        self.assertTrue(any("generation prompt" in issue for issue in issues))


class TestVideoParamsCreativeFields(unittest.TestCase):
    def test_defaults_keep_vanilla_flow(self):
        params = VideoParams(video_subject="test subject")
        self.assertFalse(params.creative_mode)
        self.assertIsNone(params.creative_brief)
        self.assertIsNone(params.style_profile)

    def test_legacy_payload_still_validates(self):
        params = VideoParams(
            video_subject="test subject",
            video_script="a short script",
            video_terms=["city", "night"],
            video_aspect="16:9",
        )
        self.assertFalse(params.creative_mode)

    def test_creative_fields_are_accepted(self):
        params = VideoParams(
            video_subject="a day in shanghai",
            creative_mode=True,
            creative_brief={"topic": "a day in shanghai", "tone": "calm"},
            style_profile={"name": "wonderland", "palette": ["#fff"]},
        )
        self.assertTrue(params.creative_mode)
        self.assertEqual(params.creative_brief.tone, "calm")
        self.assertEqual(params.style_profile.palette, ["#fff"])
