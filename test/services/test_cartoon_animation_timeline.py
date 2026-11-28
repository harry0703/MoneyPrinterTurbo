# -*- coding: utf-8 -*-
import unittest

from app.services.cartoon_animation import (
    Animation,
    AnimationClip,
    AnimationError,
    Keyframe,
    Pose,
    apply_easing,
    apply_expression,
    merged_animation,
    sample_animation,
    sample_clips,
    sample_track,
)
from app.services.cartoon_animation.expressions import expression_names


class TestInterpolation(unittest.TestCase):
    def test_easings_are_deterministic_and_bounded(self):
        for name in ("linear", "ease-in", "ease-out", "ease-in-out", "smoothstep"):
            self.assertAlmostEqual(apply_easing(name, 0), 0)
            self.assertAlmostEqual(apply_easing(name, 1), 1)
            self.assertAlmostEqual(apply_easing(name, 0.5), apply_easing(name, 0.5))
        self.assertAlmostEqual(apply_easing("linear", 0.25), 0.25)
        self.assertLess(apply_easing("ease-in", 0.25), 0.25)
        self.assertGreater(apply_easing("ease-out", 0.25), 0.25)

    def test_rejects_unknown_easing(self):
        with self.assertRaisesRegex(AnimationError, "easing"):
            apply_easing("bounce", 0.5)


class TestKeyframes(unittest.TestCase):
    def test_holds_before_and_after_the_track(self):
        frames = (Keyframe(1.0, 10), Keyframe(2.0, 20))
        self.assertEqual(sample_track(frames, 0.0), 10)
        self.assertEqual(sample_track(frames, 3.0), 20)

    def test_target_keyframe_selects_the_easing(self):
        frames = (Keyframe(0.0, 0), Keyframe(1.0, 100, "linear"))
        self.assertAlmostEqual(sample_track(frames, 0.25), 25)

    def test_step_easing_holds_the_previous_value(self):
        frames = (Keyframe(0.0, 0), Keyframe(1.0, 100, "step"))
        self.assertEqual(sample_track(frames, 0.99), 0)
        self.assertEqual(sample_track(frames, 1.0), 100)

    def test_looping_animation_wraps_time(self):
        animation = Animation(
            "loop", 2.0, {"head_rotation": (Keyframe(0, 0), Keyframe(2, 10))}, loop=True
        )
        self.assertAlmostEqual(sample_animation(animation, 3.0)["head_rotation"], 5)

    def test_one_shot_animation_stops_after_its_duration(self):
        animation = Animation("once", 1.0, {"head_rotation": (Keyframe(0, 0),)})
        self.assertEqual(sample_animation(animation, 1.5), {})


class TestClipMixing(unittest.TestCase):
    def _blink(self):
        return Animation(
            "blink",
            0.2,
            {"eye_open": (Keyframe(0, 1), Keyframe(0.1, 0), Keyframe(0.2, 1))},
            priority=50,
        )

    def _idle(self):
        return Animation(
            "idle", 2.0, {"head_rotation": (Keyframe(0, 0), Keyframe(2, 4))}, loop=True
        )

    def test_higher_priority_wins_on_shared_channels(self):
        pose = sample_clips(
            [AnimationClip(self._idle()), AnimationClip(self._blink(), start=0.0)], 0.1
        )
        self.assertLess(pose.value("eye_open"), 0.1)
        self.assertGreater(pose.value("head_rotation"), 0)

    def test_weight_blends_towards_the_clip_value(self):
        half = sample_clips([AnimationClip(self._blink(), weight=0.5)], 0.1)
        self.assertAlmostEqual(half.value("eye_open"), 0.5)

    def test_additive_animation_offsets_the_base_value(self):
        base = Animation("base", 1.0, {"head_rotation": (Keyframe(0, 10),)})
        offset = Animation(
            "offset", 1.0, {"head_rotation": (Keyframe(0, 5),)}, additive=True
        )
        pose = sample_clips([AnimationClip(base), AnimationClip(offset)], 0.0)
        self.assertAlmostEqual(pose.value("head_rotation"), 15)

    def test_clip_start_and_speed_shift_local_time(self):
        animation = Animation(
            "move", 1.0, {"root_x": (Keyframe(0, 0), Keyframe(1, 100))}
        )
        clip = AnimationClip(animation, start=0.5, speed=2.0)
        pose = sample_clips([clip], 0.75)
        self.assertAlmostEqual(pose.value("root_x"), 50)

    def test_invalid_clip_parameters_are_rejected(self):
        with self.assertRaisesRegex(AnimationError, "weight"):
            AnimationClip(self._blink(), weight=1.5)
        with self.assertRaisesRegex(AnimationError, "speed"):
            AnimationClip(self._blink(), speed=0)


class TestExpressions(unittest.TestCase):
    def test_expression_offsets_are_applied_with_weight(self):
        base = Pose({"mouth_open": 0.1})
        surprised = apply_expression(base, "surprised")
        half = apply_expression(base, "surprised", weight=0.5)
        self.assertGreater(surprised.value("mouth_open"), base.value("mouth_open"))
        self.assertGreater(surprised.value("mouth_open"), half.value("mouth_open"))
        self.assertGreater(surprised.value("brow_raise"), 0)

    def test_unknown_expression_lists_choices(self):
        with self.assertRaisesRegex(AnimationError, "expression must be one of"):
            apply_expression(Pose(), "angry")
        self.assertIn("curious", expression_names())


class TestMergedAnimation(unittest.TestCase):
    def test_union_of_compatible_tracks(self):
        first = Animation("a", 1.0, {"head_rotation": (Keyframe(0, 0),)})
        second = Animation("b", 2.0, {"eye_open": (Keyframe(0, 1),)})
        merged = merged_animation("combined", [first, second])
        self.assertEqual(merged.duration, 2.0)
        self.assertEqual(set(merged.tracks), {"head_rotation", "eye_open"})

    def test_conflicting_channels_are_rejected(self):
        first = Animation("a", 1.0, {"head_rotation": (Keyframe(0, 0),)})
        second = Animation("b", 1.0, {"head_rotation": (Keyframe(0, 1),)})
        with self.assertRaisesRegex(AnimationError, "conflict"):
            merged_animation("combined", [first, second])


if __name__ == "__main__":
    unittest.main()
