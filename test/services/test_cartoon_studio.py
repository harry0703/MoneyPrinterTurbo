# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import cartoon_studio


def manifest(**overrides):
    base = {
        "project_id": "test-cartoon",
        "title": "The paper boat",
        "style": "flat-2d",
        "aspect": "9:16",
        "characters": [
            {"name": "Mia", "description": "a girl with a red scarf and short black hair"},
            {"name": "Pip", "description": "a small orange cat"},
        ],
        "scenes": [
            {
                "id": "opening",
                "visual": "Mia folds a paper boat at a kitchen table",
                "narration": "Mia had one sheet of paper left.",
                "duration": 4,
                "characters": ["Mia"],
            },
            {
                "id": "river",
                "visual": "the boat drifts down a rain-filled gutter",
                "characters": ["Pip"],
            },
        ],
    }
    base.update(overrides)
    return base


class TestCartoonManifest(unittest.TestCase):
    def test_builds_prompts_with_style_and_only_scene_characters(self):
        storyboard = cartoon_studio.parse_storyboard(manifest())
        opening = cartoon_studio.scene_prompt(storyboard, storyboard.scenes[0])
        river = cartoon_studio.scene_prompt(storyboard, storyboard.scenes[1])

        self.assertIn("flat 2D vector cartoon", opening)
        self.assertIn("red scarf", opening)
        self.assertNotIn("orange cat", opening)
        self.assertIn("orange cat", river)
        self.assertNotIn("red scarf", river)
        self.assertIn("no watermark", river)
        self.assertIn("Avoid: 3D render", river)

    def test_defaults_duration_and_title(self):
        data = manifest()
        data.pop("title")
        data["scenes"] = [{"id": "one", "visual": "a quiet street"}]
        storyboard = cartoon_studio.parse_storyboard(data)

        self.assertEqual(storyboard.title, "test-cartoon")
        self.assertEqual(storyboard.scenes[0].duration, 5)
        self.assertEqual(storyboard.scenes[0].characters, ())

    def test_accepts_custom_style_object(self):
        storyboard = cartoon_studio.parse_storyboard(
            manifest(style={"name": "ink", "prompt": "black ink on cream paper", "negative": "color"})
        )

        self.assertEqual(storyboard.style_name, "ink")
        self.assertIn("black ink on cream paper", cartoon_studio.scene_prompt(storyboard, storyboard.scenes[0]))

    def test_rejects_unknown_style(self):
        with self.assertRaisesRegex(cartoon_studio.CartoonStudioError, "style must be one of"):
            cartoon_studio.parse_storyboard(manifest(style="oil-painting"))

    def test_rejects_unknown_character_reference(self):
        data = manifest()
        data["scenes"][0]["characters"] = ["Nobody"]
        with self.assertRaisesRegex(cartoon_studio.CartoonStudioError, "unknown character"):
            cartoon_studio.parse_storyboard(data)

    def test_rejects_duplicate_scene_ids(self):
        data = manifest()
        data["scenes"][1]["id"] = "opening"
        with self.assertRaisesRegex(cartoon_studio.CartoonStudioError, "unique"):
            cartoon_studio.parse_storyboard(data)

    def test_rejects_unknown_fields_and_bad_duration(self):
        with self.assertRaisesRegex(cartoon_studio.CartoonStudioError, "unknown manifest fields"):
            cartoon_studio.parse_storyboard(manifest(camera="dolly"))

        data = manifest()
        data["scenes"][0]["duration"] = True
        with self.assertRaisesRegex(cartoon_studio.CartoonStudioError, "duration"):
            cartoon_studio.parse_storyboard(data)

    def test_rejects_narration_without_visual(self):
        data = manifest()
        data["scenes"][0]["visual"] = " "
        with self.assertRaisesRegex(cartoon_studio.CartoonStudioError, "visual"):
            cartoon_studio.parse_storyboard(data)

    def test_rejects_bad_aspect(self):
        with self.assertRaisesRegex(cartoon_studio.CartoonStudioError, "aspect"):
            cartoon_studio.parse_storyboard(manifest(aspect="4:3"))

    def test_write_storyboard_records_every_prompt(self):
        storyboard = cartoon_studio.parse_storyboard(manifest())
        with tempfile.TemporaryDirectory() as temporary:
            path = cartoon_studio.write_storyboard(temporary, storyboard)
            document = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual([scene["id"] for scene in document["scenes"]], ["opening", "river"])
        self.assertIn("paper boat", document["scenes"][0]["visual"])
        self.assertIn("2D cartoon frame", document["scenes"][0]["prompt"])


class TestCartoonImages(unittest.TestCase):
    def _fake_request(self, calls):
        def request(prompt, aspect, save_dir):
            calls.append(prompt)
            save_dir.mkdir(parents=True, exist_ok=True)
            path = save_dir / f"generated-{len(calls)}.png"
            path.write_bytes(b"not-a-real-png")
            return str(path), 32, 32

        return request

    def test_generates_one_frame_per_scene_and_reuses_unchanged_prompts(self):
        storyboard = cartoon_studio.parse_storyboard(manifest())
        calls = []
        with tempfile.TemporaryDirectory() as temporary:
            first = cartoon_studio.generate_scene_images(
                temporary, storyboard, request_image=self._fake_request(calls)
            )
            second = cartoon_studio.generate_scene_images(
                temporary, storyboard, request_image=self._fake_request(calls)
            )

            self.assertEqual(len(calls), 2)
            self.assertEqual([record["status"] for record in first], ["generated", "generated"])
            self.assertEqual([record["status"] for record in second], ["reused", "reused"])
            for record in first:
                self.assertTrue(Path(record["path"]).is_file())

    def test_aspect_change_invalidates_frames_and_same_aspect_reuses_them(self):
        portrait = cartoon_studio.parse_storyboard(manifest())
        landscape = cartoon_studio.parse_storyboard(manifest(aspect="16:9"))
        calls = []
        with tempfile.TemporaryDirectory() as temporary:
            cartoon_studio.generate_scene_images(
                temporary, portrait, request_image=self._fake_request(calls)
            )
            cartoon_studio.generate_scene_images(
                temporary, landscape, request_image=self._fake_request(calls)
            )
            again = cartoon_studio.generate_scene_images(
                temporary, portrait, request_image=self._fake_request(calls)
            )

            self.assertEqual(len(calls), 4)
            self.assertEqual([record["status"] for record in again], ["reused", "reused"])

    def test_changed_visual_creates_a_new_frame(self):
        storyboard = cartoon_studio.parse_storyboard(manifest())
        calls = []
        with tempfile.TemporaryDirectory() as temporary:
            cartoon_studio.generate_scene_images(
                temporary, storyboard, request_image=self._fake_request(calls)
            )
            changed = manifest()
            changed["scenes"][0]["visual"] = "Mia sails the boat across a puddle"
            cartoon_studio.generate_scene_images(
                temporary,
                cartoon_studio.parse_storyboard(changed),
                request_image=self._fake_request(calls),
            )

            self.assertEqual(len(calls), 3)


class TestCartoonNarration(unittest.TestCase):
    def test_relative_project_directory_yields_usable_absolute_paths(self):
        storyboard = cartoon_studio.parse_storyboard(manifest())
        written = []
        previous = os.getcwd()

        def fake_tts(text, voice_name, voice_rate, path):
            Path(path).write_bytes(b"mp3")
            written.append(Path(path))

        with tempfile.TemporaryDirectory() as temporary:
            try:
                os.chdir(temporary)
                with patch.object(cartoon_studio.voice, "tts", side_effect=fake_tts), patch.object(
                    cartoon_studio.voice, "get_audio_duration", return_value=2.5
                ):
                    narration = cartoon_studio.narrate_scenes(
                        "episode", storyboard, voice_name="en-US-AriaNeural"
                    )

                self.assertEqual(set(narration), {"opening"})
                path, duration = narration["opening"]
                self.assertTrue(Path(path).is_absolute())
                self.assertTrue(Path(path).is_file())
                self.assertEqual(duration, 2.5)
                # The project prefix must appear exactly once.
                self.assertEqual(Path(path).parts.count("episode"), 1)
                self.assertEqual(len(written), 1)
            finally:
                os.chdir(previous)


class TestCartoonBuild(unittest.TestCase):
    def test_episode_uses_narration_duration_and_audio_only_when_present(self):
        storyboard = cartoon_studio.parse_storyboard(manifest())
        request = cartoon_studio.episode_request(
            storyboard,
            footage={"opening": "opening.mp4", "river": "river.mp4"},
            narration={"opening": ("opening.mp3", 6.4)},
        )

        self.assertEqual(
            request["settings"],
            {
                "width": 1080,
                "height": 1920,
                "fps": 30,
                "subtitles": False,
                "subtitle_font_size": 56,
            },
        )
        self.assertEqual(request["scenes"][0]["duration"], 6.4)
        self.assertEqual(request["scenes"][0]["audio"], "opening.mp3")
        self.assertEqual(request["scenes"][1]["duration"], 5)
        self.assertNotIn("audio", request["scenes"][1])

    def test_episode_carries_burned_subtitles_and_background_music(self):
        storyboard = cartoon_studio.parse_storyboard(manifest())
        request = cartoon_studio.episode_request(
            storyboard,
            footage={"opening": "opening.mp4", "river": "river.mp4"},
            narration={},
            bgm="music.mp3",
            bgm_volume=0.2,
            subtitles=True,
            subtitle_font_size=48,
        )

        self.assertEqual(request["bgm"], "music.mp3")
        self.assertEqual(request["settings"]["bgm_volume"], 0.2)
        self.assertTrue(request["settings"]["subtitles"])
        self.assertEqual(request["settings"]["subtitle_font_size"], 48)

    def test_build_requires_existing_background_music(self):
        storyboard = cartoon_studio.parse_storyboard(manifest())
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                cartoon_studio.CartoonStudioError, "background music not found"
            ):
                cartoon_studio.build(
                    temporary, storyboard, bgm=str(Path(temporary, "missing.mp3"))
                )

    def test_build_accepts_relative_project_and_music_paths(self):
        storyboard = cartoon_studio.parse_storyboard(manifest())
        created = {}
        previous = os.getcwd()

        class FakeProject:
            def __init__(self, directory):
                created["directory"] = directory

            def create_revision(self, request, *, relative_to):
                created["request"] = request
                created["relative_to"] = relative_to
                return {"revision_id": "revision-1"}

            def render(self, revision, *, retry, stage_timeout):
                return {"state": "succeeded", "revision_id": revision}

        def fake_images(project_dir, _storyboard, **_kwargs):
            directory = Path(project_dir) / "images"
            directory.mkdir(parents=True, exist_ok=True)
            records = []
            for scene in _storyboard.scenes:
                path = directory / f"{scene.id}.png"
                path.write_bytes(b"png")
                records.append({"id": scene.id, "path": str(path), "status": "generated"})
            return records

        def fake_render_clip(image_path, seconds, image_motion=None):
            clip = Path(image_path).with_suffix(".mp4")
            clip.write_bytes(b"mp4")
            return str(clip)

        def fake_tts(text, voice_name, voice_rate, path):
            Path(path).write_bytes(b"mp3")

        with tempfile.TemporaryDirectory() as temporary:
            try:
                os.chdir(temporary)
                Path("music.mp3").write_bytes(b"mp3")
                with patch.object(
                    cartoon_studio, "generate_scene_images", side_effect=fake_images
                ), patch.object(cartoon_studio.voice, "tts", side_effect=fake_tts), patch.object(
                    cartoon_studio.voice, "get_audio_duration", return_value=3.0
                ), patch.object(cartoon_studio.video_project, "VideoProject", FakeProject):
                    cartoon_studio.build(
                        "episode",
                        storyboard,
                        voice_name="en-US-AriaNeural",
                        bgm="music.mp3",
                        render_clip=fake_render_clip,
                    )

                request = created["request"]
                self.assertTrue(Path(created["relative_to"]).is_absolute())
                self.assertTrue(Path(request["bgm"]).is_absolute())
                self.assertTrue(Path(request["bgm"]).is_file())
                for scene in request["scenes"]:
                    self.assertTrue(Path(scene["footage"]).is_absolute())
                    self.assertTrue(Path(scene["footage"]).is_file())
                    if "audio" in scene:
                        self.assertTrue(Path(scene["audio"]).is_absolute())
                        self.assertTrue(Path(scene["audio"]).is_file())
            finally:
                os.chdir(previous)

    def test_build_renders_clips_and_hands_the_episode_to_video_project(self):
        storyboard = cartoon_studio.parse_storyboard(manifest())
        rendered = []
        created = {}

        class FakeProject:
            def __init__(self, directory):
                created["directory"] = directory

            def create_revision(self, request, *, relative_to):
                created["request"] = request
                return {"revision_id": "revision-1"}

            def render(self, revision, *, retry, stage_timeout):
                created["render"] = (revision, retry, stage_timeout)
                return {"state": "succeeded", "revision_id": revision}

        def fake_images(project_dir, _storyboard, **_kwargs):
            directory = Path(project_dir) / "images"
            directory.mkdir(parents=True, exist_ok=True)
            records = []
            for scene in _storyboard.scenes:
                path = directory / f"{scene.id}.png"
                path.write_bytes(b"png")
                records.append({"id": scene.id, "path": str(path), "status": "generated"})
            return records

        def fake_render_clip(image_path, seconds, image_motion=None):
            rendered.append((image_path, seconds))
            clip = Path(image_path).with_suffix(".mp4")
            clip.write_bytes(b"mp4")
            return str(clip)

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            cartoon_studio, "generate_scene_images", side_effect=fake_images
        ), patch.object(
            cartoon_studio,
            "narrate_scenes",
            return_value={"opening": ("opening.mp3", 6.4)},
        ), patch.object(cartoon_studio.video_project, "VideoProject", FakeProject):
            result = cartoon_studio.build(
                temporary,
                storyboard,
                voice_name="en-US-AriaNeural",
                retry=True,
                render_clip=fake_render_clip,
            )

            self.assertTrue(Path(temporary, "storyboard.json").is_file())

        self.assertEqual(result["revision"], "revision-1")
        self.assertEqual(created["render"], ("revision-1", True, 600))
        self.assertEqual(rendered[0][1], 7)
        self.assertEqual(rendered[1][1], 5)
        scenes = created["request"]["scenes"]
        self.assertEqual(scenes[0]["audio"], "opening.mp3")
        self.assertEqual(scenes[0]["narration"], "Mia had one sheet of paper left.")
        self.assertNotIn("audio", scenes[1])


if __name__ == "__main__":
    unittest.main()
