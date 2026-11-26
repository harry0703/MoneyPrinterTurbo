# -*- coding: utf-8 -*-
import contextlib
import dataclasses
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models.schema import VideoAspect
from app.services import cartoon_studio


def animated_manifest(**overrides):
    data = {
        "project_id": "tiko-animated",
        "title": "El robot curioso",
        "style": "flat-2d",
        "aspect": "9:16",
        "characters": [
            {"name": "Tiko", "description": "a small blue robot with a yellow antenna"}
        ],
        "animation": {"characters": [{"id": "tiko", "preset": "tiko"}]},
        "scenes": [
            {
                "id": "scene-1",
                "visual": "Tiko finds a seed",
                "narration": "Tiko found a seed.",
                "duration": 4,
                "characters": ["Tiko"],
                "animation": {
                    "background": "garden",
                    "character": "tiko",
                    "expression": "curious",
                    "props": [{"name": "seed", "x": 0.7, "y": 0.8}],
                    "actions": [
                        {"animation": "blink", "at": 0.2},
                        {"animation": "point", "at": 1.2},
                    ],
                },
            },
            {
                "id": "scene-2",
                "visual": "Tiko waters the plant",
                "narration": "He watered it every day.",
                "duration": 4,
                "characters": ["Tiko"],
                "animation": {
                    "background": "garden",
                    "character": "tiko",
                    "props": [{"name": "pot", "x": 0.7, "y": 0.8}],
                    "actions": [{"animation": "water_plant", "at": 0.8}],
                },
            },
            {
                "id": "scene-3",
                "visual": "The flower grows",
                "narration": "Something wonderful needed time.",
                "duration": 4,
                "characters": ["Tiko"],
                "animation": {
                    "background": "garden",
                    "character": "tiko",
                    "expression": "happy",
                    "props": [
                        {"name": "pot", "x": 0.7, "y": 0.8},
                        {
                            "name": "flower",
                            "x": 0.7,
                            "y": 0.5,
                            "base_y": 0.71,
                            "appear": 0.1,
                            "grow_duration": 2,
                        },
                    ],
                    "actions": [{"animation": "celebrate", "at": 1.5}],
                },
            },
        ],
    }
    data.update(overrides)
    return data


class FakeProject:
    def __init__(self, directory):
        self.directory = directory
        FakeProject.created.append(directory)

    created = []

    def create_revision(self, request, *, relative_to):
        self.request = request
        FakeProject.request = request
        return {"revision_id": "revision-1"}

    def render(self, revision, *, retry, stage_timeout):
        FakeProject.render_call = (revision, retry, stage_timeout)
        return {"state": "succeeded", "revision_id": revision}


class TestAnimatedManifest(unittest.TestCase):
    def test_animation_sections_are_parsed_and_preserved(self):
        storyboard = cartoon_studio.parse_storyboard(animated_manifest())
        self.assertIsNotNone(storyboard.animation)
        self.assertEqual(storyboard.scenes[0].animation["background"], "garden")
        document = cartoon_studio.storyboard_document(storyboard)
        self.assertIn("animation", document)
        self.assertEqual(document["scenes"][0]["animation"]["character"], "tiko")

    def test_classic_manifest_document_has_no_animation_key(self):
        data = animated_manifest()
        data.pop("animation")
        for scene in data["scenes"]:
            scene.pop("animation")
        storyboard = cartoon_studio.parse_storyboard(data)
        document = cartoon_studio.storyboard_document(storyboard)
        self.assertNotIn("animation", document)
        self.assertNotIn("animation", document["scenes"][0])
        self.assertFalse(cartoon_studio.animation_requested(storyboard))

    def test_animation_mode_is_detected_or_forced(self):
        storyboard = cartoon_studio.parse_storyboard(animated_manifest())
        self.assertTrue(cartoon_studio.animation_requested(storyboard))
        self.assertFalse(cartoon_studio.animation_requested(storyboard, "classic"))
        self.assertTrue(cartoon_studio.animation_requested(storyboard, "animation"))
        with self.assertRaisesRegex(cartoon_studio.CartoonStudioError, "mode"):
            cartoon_studio.animation_requested(storyboard, "cartoon")

    def test_invalid_animation_sections_are_rejected(self):
        cases = [
            ("unknown action", {"animation": {"characters": [{"id": "tiko"}]}}, lambda d: d["scenes"][0]["animation"]["actions"].append({"animation": "fly"})),
            ("unknown character", {}, lambda d: d["scenes"][0]["animation"].update({"character": "mia"})),
            ("unknown background", {}, lambda d: d["scenes"][0]["animation"].update({"background": "space"})),
            ("unknown field", {}, lambda d: d["scenes"][0]["animation"].update({"camera": "pan"})),
            ("x range", {}, lambda d: d["scenes"][0]["animation"].update({"x": 2})),
            ("bad prop", {}, lambda d: d["scenes"][0]["animation"]["props"].append({"name": "rocket"})),
            ("lip sync", {}, lambda d: d["scenes"][0]["animation"].update({"lip_sync": "yes"})),
            ("palette", {"animation": {"characters": [{"id": "tiko", "palette": {"glow": "#fff"}}]}}, lambda d: None),
            ("duplicate character", {"animation": {"characters": [{"id": "tiko"}, {"id": "tiko"}]}}, lambda d: None),
        ]
        for label, overrides, mutate in cases:
            with self.subTest(label):
                data = animated_manifest(**overrides)
                mutate(data)
                with self.assertRaises(cartoon_studio.CartoonStudioError):
                    cartoon_studio.parse_storyboard(data)


class TestAnimatedBuild(unittest.TestCase):
    def _fake_renderer(self, calls):
        def render(plan, target):
            calls.append((plan, target))
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            Path(target).write_bytes(b"mp4")
            return target

        return render

    def _run_build(self, temporary, *, settings=None, mode="auto", storyboard=None):
        Storyboard = storyboard or cartoon_studio.parse_storyboard(animated_manifest())
        calls = []
        with patch.object(
            cartoon_studio,
            "narrate_scenes",
            return_value={
                "scene-1": (str(Path(temporary, "a1.mp3")), 3.0),
                "scene-2": (str(Path(temporary, "a2.mp3")), 3.5),
                "scene-3": (str(Path(temporary, "a3.mp3")), 4.0),
            },
        ), patch.object(
            cartoon_studio, "generate_scene_images", side_effect=AssertionError("images")
        ), patch.object(
            cartoon_studio.video_project, "VideoProject", FakeProject
        ):
            result = cartoon_studio.build(
                temporary,
                Storyboard,
                animation_settings=settings,
                render_animation_clip=self._fake_renderer(calls),
                mode=mode,
            )
        return result, calls

    def test_build_renders_each_scene_and_assembles_the_episode(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, calls = self._run_build(temporary)
            self.assertEqual(result["mode"], "animation")
            self.assertEqual(len(calls), 3)
            self.assertEqual(result["revision"], "revision-1")
            self.assertEqual([clip["id"] for clip in result["clips"]], ["scene-1", "scene-2", "scene-3"])
            for clip in result["clips"]:
                self.assertTrue(Path(clip["path"]).is_file())
            self.assertFalse(Path(temporary, "images").exists())
            scenes = FakeProject.request["scenes"]
            self.assertEqual(scenes[0]["duration"], 3.0)
            self.assertEqual(scenes[0]["audio"], str(Path(temporary, "a1.mp3")))
            self.assertEqual(scenes[1]["duration"], 3.5)
            self.assertTrue(Path(temporary, "storyboard.json").is_file())

    def test_second_build_reuses_clips_and_settings_change_invalidates_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            first, first_calls = self._run_build(temporary)
            second, second_calls = self._run_build(temporary)
            self.assertEqual(len(first_calls), 3)
            self.assertEqual(len(second_calls), 0)
            self.assertEqual(first["clips"], second["clips"])

            settings = cartoon_studio.animation_render_settings(
                VideoAspect.portrait, fps=12
            )
            _, changed_calls = self._run_build(temporary, settings=settings)
            self.assertEqual(len(changed_calls), 3)

    def test_animation_mode_requires_every_scene_to_be_animated(self):
        storyboard = cartoon_studio.parse_storyboard(animated_manifest())
        scenes = list(storyboard.scenes)
        scenes[1] = dataclasses.replace(scenes[1], animation=None)
        incomplete = dataclasses.replace(storyboard, scenes=tuple(scenes))
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                cartoon_studio.CartoonStudioError, "every scene"
            ):
                self._run_build(temporary, storyboard=incomplete)

    def test_classic_mode_still_uses_static_images(self):
        manifest = animated_manifest()
        manifest.pop("animation")
        for scene in manifest["scenes"]:
            scene.pop("animation")
        storyboard = cartoon_studio.parse_storyboard(manifest)
        rendered = []

        def fake_images(project_dir, _storyboard, **_kwargs):
            directory = Path(project_dir) / "images"
            directory.mkdir(parents=True, exist_ok=True)
            records = []
            for scene in _storyboard.scenes:
                path = directory / f"{scene.id}.png"
                path.write_bytes(b"png")
                records.append({"id": scene.id, "path": str(path)})
            return records

        def fake_clip(image_path, seconds, image_motion=None):
            rendered.append((image_path, seconds))
            clip = Path(image_path).with_suffix(".mp4")
            clip.write_bytes(b"mp4")
            return str(clip)

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            cartoon_studio, "generate_scene_images", side_effect=fake_images
        ), patch.object(
            cartoon_studio,
            "narrate_scenes",
            return_value={"scene-1": ("a.mp3", 2.0)},
        ), patch.object(
            cartoon_studio.video_project, "VideoProject", FakeProject
        ):
            result = cartoon_studio.build(
                temporary,
                storyboard,
                render_clip=fake_clip,
                render_animation_clip=self._fake_renderer([]),
            )
        self.assertNotIn("mode", result)
        self.assertEqual(result["images"][0]["id"], "scene-1")
        self.assertEqual(len(rendered), 3)


class TestAnimationCli(unittest.TestCase):
    def test_validate_character_reports_parts_and_animations(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary, "cartoon.json")
            manifest.write_text(
                json.dumps(animated_manifest()), encoding="utf-8"
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = cartoon_studio.main(
                    ["--project", temporary, "validate-character", "--preset", "tiko"]
                )
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["id"], "tiko")
        self.assertIn("head", [part["name"] for part in result["parts"]])
        self.assertIn("celebrate", result["animations"])

    def test_preview_rejects_times_outside_the_scene(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary, "cartoon.json")
            manifest.write_text(
                json.dumps(animated_manifest()), encoding="utf-8"
            )
            with self.assertRaises(SystemExit) as context:
                cartoon_studio.main(
                    [
                        "--project",
                        temporary,
                        "preview",
                        "--scene",
                        "scene-1",
                        "--time",
                        "99",
                    ]
                )
        self.assertEqual(context.exception.code, 1)

    def test_render_settings_follow_the_project_aspect(self):
        portrait = cartoon_studio.animation_render_settings(VideoAspect.portrait)
        landscape = cartoon_studio.animation_render_settings(VideoAspect.landscape)
        square = cartoon_studio.animation_render_settings(VideoAspect.square)
        self.assertEqual((portrait.width, portrait.height), (720, 1280))
        self.assertEqual((landscape.width, landscape.height), (1280, 720))
        self.assertEqual((square.width, square.height), (960, 960))
        self.assertEqual(
            (landscape.output_width, landscape.output_height), (1920, 1080)
        )


if __name__ == "__main__":
    unittest.main()
