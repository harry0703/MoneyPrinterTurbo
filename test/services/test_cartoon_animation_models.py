# -*- coding: utf-8 -*-
import unittest

from app.services.cartoon_animation import (
    Animation,
    AnimationError,
    CHANNELS,
    Character,
    Keyframe,
    Part,
    Pose,
    RenderSettings,
    Shape,
    tiko,
)


class TestPose(unittest.TestCase):
    def test_clamps_channels_to_joint_limits(self):
        pose = Pose({"head_rotation": 90, "left_arm_rotation": -400, "mouth_open": 4})
        self.assertEqual(pose.value("head_rotation"), 30)
        self.assertEqual(pose.value("left_arm_rotation"), -170)
        self.assertEqual(pose.value("mouth_open"), 1)

    def test_missing_channels_fall_back_to_neutral(self):
        pose = Pose()
        self.assertEqual(pose.value("scale"), 1.0)
        self.assertEqual(pose.value("eye_open"), 1.0)
        self.assertEqual(pose.value("mouth_open"), 0.0)

    def test_rejects_unknown_and_non_finite_channels(self):
        with self.assertRaisesRegex(AnimationError, "unknown animation channel"):
            Pose({"tail_wag": 1})
        with self.assertRaisesRegex(AnimationError, "finite"):
            Pose({"head_rotation": float("nan")})
        with self.assertRaisesRegex(AnimationError, "must be a number"):
            Pose({"head_rotation": True})

    def test_adjust_and_merge_do_not_mutate_the_original(self):
        original = Pose({"head_rotation": 4})
        adjusted = original.adjusted({"head_rotation": 3}, weight=0.5)
        merged = original.merged({"eye_open": 0})
        self.assertEqual(original.value("head_rotation"), 4)
        self.assertAlmostEqual(adjusted.value("head_rotation"), 5.5)
        self.assertEqual(merged.value("eye_open"), 0)


class TestCharacterModel(unittest.TestCase):
    def test_tiko_is_a_complete_component_tree(self):
        character = tiko()
        names = {part.name for part in character.parts}
        self.assertIn("head", names)
        self.assertIn("left_arm", names)
        self.assertIn("right_leg", names)
        self.assertEqual(character.part("left_pupil").parent, "left_eye")
        self.assertEqual(character.part("antenna_ball").parent, "antenna")

    def test_layers_are_sorted_and_stable(self):
        character = tiko()
        layers = [part.layer for part in character.layered()]
        self.assertEqual(layers, sorted(layers))
        self.assertLess(character.part("body").layer, character.part("head").layer)
        self.assertLess(character.part("left_eye").layer, character.part("left_pupil").layer)

    def test_rejects_unknown_parent_cycle_and_missing_palette_key(self):
        shape = Shape("ellipse", 10, 10, "ink")
        with self.assertRaisesRegex(AnimationError, "unknown parent"):
            Character(
                id="x",
                name="X",
                palette={"ink": "#000000"},
                parts=(Part("head", shape, parent="body"),),
            )
        with self.assertRaisesRegex(AnimationError, "cycle"):
            Character(
                id="x",
                name="X",
                palette={"ink": "#000000"},
                parts=(
                    Part("head", shape, parent="body"),
                    Part("body", shape, parent="head"),
                ),
            )
        with self.assertRaisesRegex(AnimationError, "missing palette key"):
            Character(id="x", name="X", palette={}, parts=(Part("head", shape),))

    def test_duplicate_part_and_bad_shape_are_rejected(self):
        shape = Shape("ellipse", 10, 10, "ink")
        with self.assertRaisesRegex(AnimationError, "repeats part"):
            Character(
                id="x",
                name="X",
                palette={"ink": "#000"},
                parts=(Part("a", shape), Part("a", shape)),
            )
        with self.assertRaisesRegex(AnimationError, "positive"):
            Shape("ellipse", 0, 10, "ink")
        with self.assertRaisesRegex(AnimationError, "at least three points"):
            Shape("polygon", 10, 10, "ink")


class TestAnimationModel(unittest.TestCase):
    def test_rejects_unsorted_or_too_long_tracks(self):
        with self.assertRaisesRegex(AnimationError, "not sorted"):
            Animation("x", 1.0, {"head_rotation": (Keyframe(0.5, 0), Keyframe(0.2, 1))})
        with self.assertRaisesRegex(AnimationError, "exceeds its duration"):
            Animation("x", 1.0, {"head_rotation": (Keyframe(2.0, 0),)})

    def test_rejects_unknown_channel_and_easing(self):
        with self.assertRaisesRegex(AnimationError, "unknown channel"):
            Animation("x", 1.0, {"wings": (Keyframe(0, 0),)})
        with self.assertRaisesRegex(AnimationError, "easing"):
            Keyframe(0, 1, "bounce")

    def test_channel_defaults_match_the_documented_limits(self):
        self.assertEqual(CHANNELS["head_rotation"][2], 0.0)
        self.assertEqual(CHANNELS["eye_open"], (0.0, 1.0, 1.0))


class TestRenderSettings(unittest.TestCase):
    def test_defaults_and_validation(self):
        settings = RenderSettings()
        self.assertEqual((settings.width, settings.height), (720, 1280))
        self.assertEqual((settings.output_width, settings.output_height), (1080, 1920))
        with self.assertRaisesRegex(AnimationError, "fps"):
            RenderSettings(fps=0)
        with self.assertRaisesRegex(AnimationError, "crf"):
            RenderSettings(crf=52)


if __name__ == "__main__":
    unittest.main()
