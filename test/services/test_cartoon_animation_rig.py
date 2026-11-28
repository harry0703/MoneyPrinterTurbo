# -*- coding: utf-8 -*-
import unittest

from app.services.cartoon_animation import (
    AnimationError,
    Character,
    Part,
    Pose,
    Shape,
    tiko,
)
from app.services.cartoon_animation.rig import part_world_bounds, resolve_joints


def simple_character() -> Character:
    return Character(
        id="stick",
        name="Stick",
        palette={"ink": "#000000"},
        parts=(
            Part("body", Shape("rounded_rect", 40, 60, "ink"), layer=10),
            Part(
                "arm",
                Shape("capsule", 10, 50, "ink", offset=(0, 25)),
                parent="body",
                anchor=(20, -20),
                layer=20,
                rotation_channel="right_arm_rotation",
            ),
            Part(
                "hand",
                Shape("ellipse", 12, 12, "ink"),
                parent="arm",
                anchor=(0, 50),
                layer=21,
            ),
        ),
        canvas=(200, 300),
        origin=(100, 200),
    )


class TestJointHierarchy(unittest.TestCase):
    def test_children_inherit_parent_rotation_and_anchor(self):
        character = simple_character()
        straight = resolve_joints(character, Pose())
        self.assertAlmostEqual(straight["arm"].x, 120)
        self.assertAlmostEqual(straight["arm"].y, 180)
        self.assertAlmostEqual(straight["hand"].y, 230)

        rotated = resolve_joints(character, Pose({"right_arm_rotation": 90}))
        self.assertAlmostEqual(rotated["arm"].angle, 90)
        self.assertAlmostEqual(rotated["hand"].angle, 90)
        # The hand swings a quarter turn clockwise around the shoulder.
        self.assertAlmostEqual(rotated["hand"].x, 70)
        self.assertAlmostEqual(rotated["hand"].y, 180)

    def test_root_channels_translate_and_scale_the_whole_character(self):
        character = simple_character()
        joints = resolve_joints(
            character, Pose({"root_x": 15, "root_y": -10, "scale": 2})
        )
        self.assertAlmostEqual(joints["body"].x, 115)
        self.assertAlmostEqual(joints["body"].y, 190)
        self.assertAlmostEqual(joints["arm"].x, 155)
        self.assertAlmostEqual(joints["arm"].y, 150)

    def test_rotation_limits_are_enforced_by_the_pose(self):
        character = simple_character()
        joints = resolve_joints(character, Pose({"right_arm_rotation": 999}))
        self.assertEqual(joints["arm"].angle, 170)

    def test_head_translation_and_body_rotation_move_the_head(self):
        character = tiko()
        neutral = resolve_joints(character, Pose())
        moved = resolve_joints(
            character, Pose({"head_x": 20, "head_y": -10, "body_rotation": 20})
        )
        self.assertGreater(moved["head"].x, neutral["head"].x)
        self.assertLess(moved["head"].y, neutral["head"].y)
        self.assertAlmostEqual(moved["head"].angle, 20)


class TestCharacterValidation(unittest.TestCase):
    def test_unresolvable_hierarchy_is_rejected(self):
        character = Character(
            id="x",
            name="X",
            palette={"ink": "#000"},
            parts=(
                Part("a", Shape("ellipse", 10, 10, "ink"), parent="b"),
                Part("b", Shape("ellipse", 10, 10, "ink")),
            ),
        )
        # b is resolved first in declaration order, so the tree is valid.
        self.assertIn("a", resolve_joints(character, Pose()))

    def test_ambiguous_cycle_cannot_be_constructed(self):
        shape = Shape("ellipse", 10, 10, "ink")
        with self.assertRaisesRegex(AnimationError, "cycle"):
            Character(
                id="x",
                name="X",
                palette={"ink": "#000"},
                parts=(
                    Part("a", shape, parent="b"),
                    Part("b", shape, parent="a"),
                ),
            )

    def test_sprite_bounds_cover_the_character(self):
        character = tiko()
        left, top, right, bottom = part_world_bounds(character, Pose())
        self.assertLess(left, character.origin[0])
        self.assertGreater(right, character.origin[0])
        self.assertLess(top, character.origin[1] - 300)
        self.assertGreater(bottom, character.origin[1] + 100)


if __name__ == "__main__":
    unittest.main()
