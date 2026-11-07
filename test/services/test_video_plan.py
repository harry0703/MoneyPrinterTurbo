import unittest

from pydantic import ValidationError

from app.models.schema import TaskVideoRequest, VideoParams
from app.models.video_plan import (
    Scene,
    SceneTiming,
    Shot,
    VideoPlan,
    VisualBrief,
    validate_plan_script_coverage,
)


def make_scene(text="The Sun rises above the horizon.", order=0):
    return Scene(
        scene_id=f"scene-{order + 1:03d}",
        order=order,
        narration_text=text,
        timing=SceneTiming(estimated_duration_ms=3500, confidence=0.6),
        visual=VisualBrief(
            subject=["Sun"],
            action="rises above the horizon",
            description="The Sun appearing above a flat ocean horizon at dawn.",
            visual_prompt="Documentary shot of sunrise over the ocean",
            search_queries=["sunrise ocean horizon"],
            recommended_material_type=["stock_video"],
        ),
        shots=[Shot(shot_id=f"scene-{order + 1:03d}-shot-001")],
    )


class TestVideoPlan(unittest.TestCase):
    def test_legacy_video_params_default_to_legacy_pipeline(self):
        params = VideoParams(video_subject="test")
        self.assertEqual(params.video_pipeline, "legacy")
        self.assertEqual(params.scene_plan_fallback, "legacy")
        self.assertEqual(params.model_dump(mode="json")["video_pipeline"], "legacy")

    def test_api_request_can_opt_in_without_changing_legacy_default(self):
        request = TaskVideoRequest(
            video_subject="test",
            video_pipeline="scene",
            scene_plan_fallback="fail",
        )
        self.assertEqual(request.video_pipeline, "scene")
        self.assertEqual(request.scene_plan_fallback, "fail")
        legacy_request = TaskVideoRequest(video_subject="test")
        self.assertEqual(legacy_request.video_pipeline, "legacy")

    def test_scene_plan_round_trips_as_json(self):
        script = "The Sun rises above the horizon."
        plan = VideoPlan(
            script_sha256="a" * 64,
            subject="Sunrise",
            scenes=[make_scene(script)],
        )
        validate_plan_script_coverage(script, plan)
        restored = VideoPlan.model_validate_json(plan.model_dump_json())
        self.assertEqual(restored.scenes[0].narration_text, script)
        self.assertEqual(restored.schema_version, "1.0")

    def test_coverage_allows_whitespace_normalization_only(self):
        script = "The Sun rises\nabove the horizon."
        plan = VideoPlan(
            script_sha256="a" * 64,
            subject="Sunrise",
            scenes=[make_scene("The Sun rises above the horizon.")],
        )
        validate_plan_script_coverage(script, plan)

    def test_coverage_rejects_omission_reordering_and_punctuation_changes(self):
        for script, excerpts in (
            ("The Sun rises. The sky brightens.", ["The Sun rises."]),
            ("First. Second.", ["Second.", "First."]),
            ("Wait!", ["Wait."]),
        ):
            with self.subTest(script=script), self.assertRaises(ValueError):
                plan = VideoPlan(
                    script_sha256="a" * 64,
                    subject="test",
                    scenes=[make_scene(text, index) for index, text in enumerate(excerpts)],
                )
                validate_plan_script_coverage(script, plan)

    def test_scene_order_and_timing_are_validated(self):
        with self.assertRaises(ValidationError):
            VideoPlan(
                script_sha256="a" * 64,
                subject="test",
                scenes=[make_scene(order=1)],
            )
        with self.assertRaises(ValidationError):
            SceneTiming(
                estimated_duration_ms=1000,
                actual_start_ms=0,
                actual_end_ms=500,
                confidence=0.5,
            )


if __name__ == "__main__":
    unittest.main()
