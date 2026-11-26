# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from PIL import ImageChops

from app.services.cartoon_animation import (
    AnimationError,
    Pose,
    RenderSettings,
    ScenePlan,
    render_character,
    render_frame,
    render_scene_video,
    tiko,
)
from app.services.cartoon_animation.compositor import Actor, Prop
from app.services.cartoon_animation.renderer import encode_frames


class TestCharacterRenderer(unittest.TestCase):
    def test_renders_a_transparent_sprite_and_is_deterministic(self):
        character = tiko()
        first = render_character(character, Pose())
        second = render_character(character, Pose())
        self.assertEqual(first.size, (480, 660))
        self.assertEqual(first.mode, "RGBA")
        self.assertEqual(first.tobytes(), second.tobytes())
        self.assertIsNotNone(first.getbbox())
        self.assertGreater(first.getchannel("A").getextrema()[1], 0)

    def test_blink_and_mouth_open_change_pixels(self):
        character = tiko()
        neutral = render_character(character, Pose())
        blinked = render_character(character, Pose({"eye_open": 0}))
        talking = render_character(character, Pose({"mouth_open": 1, "mouth_width": 0.8}))
        self.assertIsNotNone(
            ImageChops.difference(neutral.convert("RGB"), blinked.convert("RGB")).getbbox()
        )
        self.assertIsNotNone(
            ImageChops.difference(neutral.convert("RGB"), talking.convert("RGB")).getbbox()
        )

    def test_pose_scale_and_rotation_change_the_sprite(self):
        character = tiko()
        neutral = render_character(character, Pose())
        tilted = render_character(character, Pose({"head_rotation": 20}))
        scaled = render_character(character, Pose({"scale": 0.5}))
        self.assertIsNotNone(
            ImageChops.difference(neutral.convert("RGB"), tilted.convert("RGB")).getbbox()
        )
        neutral_box = neutral.getbbox()
        scaled_box = scaled.getbbox()
        self.assertLess(scaled_box[2] - scaled_box[0], neutral_box[2] - neutral_box[0])


class TestSceneComposition(unittest.TestCase):
    def _plan(self, *, props=(), actors=(), duration=2.0):
        return ScenePlan(
            background="garden",
            duration=duration,
            settings=RenderSettings(width=240, height=426, fps=8, output_width=240, output_height=426),
            actors=actors,
            props=props,
        )

    def test_frame_size_and_determinism(self):
        plan = self._plan(actors=(Actor(tiko(), x=120, y=300, scale=0.6),))
        first = render_frame(plan, 0.5)
        second = render_frame(plan, 0.5)
        self.assertEqual(first.size, (240, 426))
        self.assertEqual(first.mode, "RGB")
        self.assertEqual(first.tobytes(), second.tobytes())

    def test_prop_appears_and_grows_over_time(self):
        empty = render_frame(self._plan(), 0.0)
        growing = self._plan(
            props=(
                Prop(
                    "flower",
                    x=160,
                    y=200,
                    scale=0.6,
                    appear=0.2,
                    growth_from=0,
                    growth_to=1,
                    grow_duration=1.0,
                    base_y=330,
                ),
            )
        )
        early = render_frame(growing, 0.1)
        middle = render_frame(growing, 0.7)
        late = render_frame(growing, 1.5)
        self.assertEqual(early.tobytes(), empty.tobytes())
        self.assertIsNotNone(ImageChops.difference(middle, early).getbbox())
        self.assertIsNotNone(ImageChops.difference(late, middle).getbbox())

    def test_actor_fades_in_and_disappears_before_appearing(self):
        plan = self._plan(actors=(Actor(tiko(), x=120, y=300, scale=0.6, appear=0.5),))
        before = render_frame(plan, 0.2)
        during = render_frame(plan, 0.6)
        after = render_frame(plan, 1.2)
        self.assertEqual(before.tobytes(), render_frame(self._plan(), 0.2).tobytes())
        self.assertIsNotNone(ImageChops.difference(during, before).getbbox())
        self.assertIsNotNone(ImageChops.difference(after, during).getbbox())

    def test_actor_travel_moves_smoothly_and_stays_put(self):
        actor = Actor(
            tiko(), x=100, y=300, scale=0.5, travel_to_x=200, travel_start=0.5, travel_duration=1.0
        )
        self.assertEqual(actor.x_at(0.2), 100)
        self.assertEqual(actor.x_at(0.5), 100)
        self.assertAlmostEqual(actor.x_at(1.0), 150)
        self.assertEqual(actor.x_at(2.0), 200)
        self.assertEqual(actor.x_at(5.0), 200)

    def test_invalid_background_is_rejected(self):
        with self.assertRaisesRegex(AnimationError, "background"):
            ScenePlan(background="space", duration=1.0)


class TestEncoding(unittest.TestCase):
    def test_streams_frames_to_h264(self):
        plan = ScenePlan(
            background="studio",
            duration=0.6,
            settings=RenderSettings(
                width=160,
                height=284,
                fps=8,
                output_width=160,
                output_height=284,
                preset="ultrafast",
            ),
            actors=(Actor(tiko(), x=80, y=210, scale=0.4),),
        )
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary, "scene.mp4")
            result = render_scene_video(plan, str(target))
            self.assertEqual(Path(result), target)
            self.assertTrue(target.is_file())
            payload = target.read_bytes()
            self.assertGreater(len(payload), 512)
            self.assertIn(b"ftyp", payload[:64])

    def test_empty_frame_sequence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(AnimationError, "no frames"):
                encode_frames(
                    iter(()),
                    str(Path(temporary, "empty.mp4")),
                    RenderSettings(
                        width=64,
                        height=64,
                        fps=4,
                        output_width=64,
                        output_height=64,
                        preset="ultrafast",
                    ),
                )


if __name__ == "__main__":
    unittest.main()
