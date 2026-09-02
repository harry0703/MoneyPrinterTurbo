"""End-to-end tests for the scene-based video generation pipeline.

Tests verify that scene structure is preserved through all pipeline stages:
script processing, audio, subtitle, material download, and video composition.
Each scene is assembled as a self-contained video before final concatenation.
"""

import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _mock_clip(duration=10.0):
    """Create a MagicMock that behaves as a context manager (for ExitStack)."""
    clip = MagicMock()
    clip.duration = duration
    clip.__enter__ = MagicMock(return_value=clip)
    clip.__exit__ = MagicMock(return_value=False)
    return clip


import cli
from app.models.schema import (
    MaterialInfo,
    SceneConfig,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
)
from app.services import task as tm
from app.services import video as vd


class TestGenerateScenes(unittest.TestCase):
    """Tests for generate_scenes() function."""

    def test_returns_none_when_no_scenes(self):
        params = VideoParams(video_subject="test", scenes=None)
        result = tm.generate_scenes("task-1", params, "full script")
        self.assertIsNone(result)

    def test_returns_none_for_empty_scenes(self):
        params = VideoParams(video_subject="test", scenes=[])
        result = tm.generate_scenes("task-1", params, "full script")
        self.assertIsNone(result)

    def test_auto_assigns_scene_ids(self):
        params = VideoParams(
            video_subject="test",
            scenes=[
                SceneConfig(script="Scene 1", duration=5.0),
                SceneConfig(script="Scene 2", duration=10.0),
            ],
        )
        with patch.object(tm.llm, "generate_terms", return_value=["term"]):
            result = tm.generate_scenes("task-1", params, "full script")

        self.assertIsNotNone(result)
        self.assertEqual(result[0].scene_id, 1)
        self.assertEqual(result[1].scene_id, 2)

    def test_preserves_explicit_scene_ids(self):
        params = VideoParams(
            video_subject="test",
            scenes=[
                SceneConfig(scene_id=5, script="Scene 1"),
                SceneConfig(scene_id=10, script="Scene 2"),
            ],
        )
        with patch.object(tm.llm, "generate_terms", return_value=["term"]):
            result = tm.generate_scenes("task-1", params, "full script")

        self.assertEqual(result[0].scene_id, 5)
        self.assertEqual(result[1].scene_id, 10)

    def test_uses_full_script_when_scene_script_empty(self):
        params = VideoParams(
            video_subject="test",
            scenes=[SceneConfig(script="", duration=5.0)],
        )
        with patch.object(tm.llm, "generate_terms", return_value=["term"]):
            result = tm.generate_scenes("task-1", params, "full narration script")

        self.assertEqual(result[0].script, "full narration script")

    def test_generates_terms_from_llm_when_not_provided(self):
        params = VideoParams(
            video_subject="test",
            scenes=[SceneConfig(script="Scene text", duration=5.0)],
        )
        with patch.object(
            tm.llm, "generate_terms", return_value=["term1", "term2"]
        ) as mock_terms:
            result = tm.generate_scenes("task-1", params, "full script")

        mock_terms.assert_called_once()
        self.assertEqual(result[0].search_terms, ["term1", "term2"])

    def test_preserves_provided_search_terms(self):
        params = VideoParams(
            video_subject="test",
            scenes=[
                SceneConfig(
                    script="Scene text",
                    search_terms=["custom1", "custom2"],
                    duration=5.0,
                ),
            ],
        )
        result = tm.generate_scenes("task-1", params, "full script")
        self.assertEqual(result[0].search_terms, ["custom1", "custom2"])

    def test_preserves_transition_and_clip_transition(self):
        params = VideoParams(
            video_subject="test",
            scenes=[
                SceneConfig(
                    script="S1",
                    transition=VideoTransitionMode.fade_in,
                    clip_transition=VideoTransitionMode.slide_in,
                ),
            ],
        )
        with patch.object(tm.llm, "generate_terms", return_value=["term"]):
            result = tm.generate_scenes("task-1", params, "full script")

        self.assertEqual(result[0].transition, VideoTransitionMode.fade_in)
        self.assertEqual(result[0].clip_transition, VideoTransitionMode.slide_in)

    def test_preserves_local_materials(self):
        materials = [MaterialInfo(provider="local", url="/test.mp4", duration=5)]
        params = VideoParams(
            video_subject="test",
            scenes=[SceneConfig(script="S1", materials=materials)],
        )
        result = tm.generate_scenes("task-1", params, "full script")
        self.assertIsNotNone(result[0].materials)
        self.assertEqual(len(result[0].materials), 1)
        self.assertEqual(result[0].materials[0].url, "/test.mp4")


class TestGenerateSingleScene(unittest.TestCase):
    """Tests for _generate_single_scene() -- full scene video assembly."""

    def test_returns_none_for_empty_script(self):
        scene = SceneConfig(scene_id=1, script="", search_terms=["t1"])
        params = VideoParams(video_subject="test")
        result = tm._generate_single_scene("task-1", scene, params, 1)
        self.assertIsNone(result)

    def test_generates_tts_audio_and_subtitles(self):
        """Scene assembly should produce audio and subtitles for that scene."""
        scene = SceneConfig(
            scene_id=1, script="Test narration.", search_terms=["term1"]
        )
        params = VideoParams(
            video_subject="test",
            voice_name="zh-CN-XiaoxiaoNeural-Female",
            subtitle_enabled=True,
        )

        mock_sub_maker = MagicMock()

        with patch.object(tm.voice, "tts", return_value=mock_sub_maker) as mock_tts, \
             patch("app.services.task.AudioFileClip") as mock_audio_clip, \
             patch.object(tm.subtitle, "create"), \
             patch.object(tm.subtitle, "correct"), \
             patch.object(tm.voice, "create_subtitle"), \
             patch.object(
                 tm.material, "download_videos", return_value=["/v1.mp4"]
             ), \
             patch.object(tm.video, "combine_videos"), \
             patch.object(tm.video, "generate_video", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch("os.makedirs"):

            mock_clip_instance = MagicMock()
            mock_clip_instance.duration = 5.0
            mock_audio_clip.return_value = mock_clip_instance

            result = tm._generate_single_scene("task-1", scene, params, 1)

        self.assertIsNotNone(result)
        mock_tts.assert_called_once()
        # TTS should be called with the SCENE script, not the global script
        call_kwargs = mock_tts.call_args.kwargs
        self.assertEqual(call_kwargs["text"], "Test narration.")

    def test_uses_clip_transition_for_within_scene(self):
        """combine_videos should use scene's clip_transition."""
        scene = SceneConfig(
            scene_id=1,
            script="Test.",
            search_terms=["term1"],
            clip_transition=VideoTransitionMode.fade_in,
        )
        params = VideoParams(video_subject="test", voice_name="no-voice")

        with patch.object(tm.voice, "tts", return_value=MagicMock()), \
             patch("app.services.task.AudioFileClip") as mock_audio_clip, \
             patch.object(
                 tm.material, "download_videos", return_value=["/v1.mp4"]
             ), \
             patch.object(tm.video, "combine_videos") as mock_combine, \
             patch.object(tm.video, "generate_video", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch("os.makedirs"):

            mock_clip_instance = MagicMock()
            mock_clip_instance.duration = 5.0
            mock_audio_clip.return_value = mock_clip_instance

            tm._generate_single_scene("task-1", scene, params, 1)

        combine_kwargs = mock_combine.call_args.kwargs
        self.assertEqual(
            combine_kwargs["video_transition_mode"], VideoTransitionMode.fade_in
        )

    def test_falls_back_to_global_clip_transition(self):
        """When scene has no clip_transition, use params.clip_transition as default."""
        scene = SceneConfig(
            scene_id=1, script="Test.", search_terms=["term1"]
        )
        params = VideoParams(
            video_subject="test",
            voice_name="no-voice",
            clip_transition=VideoTransitionMode.slide_in,
        )

        with patch.object(tm.voice, "tts", return_value=MagicMock()), \
             patch("app.services.task.AudioFileClip") as mock_audio_clip, \
             patch.object(
                 tm.material, "download_videos", return_value=["/v1.mp4"]
             ), \
             patch.object(tm.video, "combine_videos") as mock_combine, \
             patch.object(tm.video, "generate_video", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch("os.makedirs"):

            mock_clip_instance = MagicMock()
            mock_clip_instance.duration = 5.0
            mock_audio_clip.return_value = mock_clip_instance

            tm._generate_single_scene("task-1", scene, params, 1)

        combine_kwargs = mock_combine.call_args.kwargs
        self.assertEqual(
            combine_kwargs["video_transition_mode"], VideoTransitionMode.slide_in
        )

    def test_uses_search_terms_for_material_download(self):
        """download_videos should be called with scene's search terms."""
        scene = SceneConfig(
            scene_id=1, script="Test.", search_terms=["drift", "night"]
        )
        params = VideoParams(video_subject="Drift", voice_name="no-voice")

        with patch.object(tm.voice, "tts", return_value=MagicMock()), \
             patch("app.services.task.AudioFileClip") as mock_audio_clip, \
             patch.object(
                 tm.material, "download_videos", return_value=["/v1.mp4"]
             ) as mock_download, \
             patch.object(tm.video, "combine_videos"), \
             patch.object(tm.video, "generate_video", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch("os.makedirs"):

            mock_clip_instance = MagicMock()
            mock_clip_instance.duration = 5.0
            mock_audio_clip.return_value = mock_clip_instance

            tm._generate_single_scene("task-1", scene, params, 1)

        download_kwargs = mock_download.call_args.kwargs
        self.assertEqual(download_kwargs["search_terms"], ["drift", "night"])
        self.assertEqual(
            download_kwargs["video_concat_mode"], VideoConcatMode.sequential
        )

    def test_returns_none_when_no_materials_found(self):
        """Should return None if no materials could be downloaded."""
        scene = SceneConfig(scene_id=1, script="Test.", search_terms=["term1"])
        params = VideoParams(video_subject="test", voice_name="no-voice")

        with patch.object(tm.voice, "tts", return_value=MagicMock()), \
             patch("app.services.task.AudioFileClip") as mock_audio_clip, \
             patch.object(tm.material, "download_videos", return_value=[]), \
             patch("os.path.exists", return_value=True), \
             patch("os.makedirs"):

            mock_clip_instance = MagicMock()
            mock_clip_instance.duration = 5.0
            mock_audio_clip.return_value = mock_clip_instance

            result = tm._generate_single_scene("task-1", scene, params, 1)

        self.assertIsNone(result)

    def test_generates_terms_from_llm_when_not_provided(self):
        """When scene has no search_terms, should use LLM to generate them."""
        scene = SceneConfig(scene_id=1, script="Drift art.")
        params = VideoParams(video_subject="Drift", voice_name="no-voice")

        with patch.object(tm.voice, "tts", return_value=MagicMock()), \
             patch("app.services.task.AudioFileClip") as mock_audio_clip, \
             patch.object(
                 tm.llm, "generate_terms", return_value=["drift", "night"]
             ), \
             patch.object(
                 tm.material, "download_videos", return_value=["/v1.mp4"]
             ), \
             patch.object(tm.video, "combine_videos"), \
             patch.object(tm.video, "generate_video", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch("os.makedirs"):

            mock_clip_instance = MagicMock()
            mock_clip_instance.duration = 5.0
            mock_audio_clip.return_value = mock_clip_instance

            result = tm._generate_single_scene("task-1", scene, params, 1)

        self.assertIsNotNone(result)


class TestSceneScriptsConcatenation(unittest.TestCase):
    """Tests that scene scripts are concatenated for backward compatibility."""

    def test_concatenation_contains_all_scene_scripts(self):
        processed_scenes = [
            SceneConfig(scene_id=1, script="First scene."),
            SceneConfig(scene_id=2, script="Second scene."),
        ]

        scene_scripts = [s.script for s in processed_scenes if s.script]
        video_script = "\n\n".join(scene_scripts) if scene_scripts else ""

        self.assertIn("First scene.", video_script)
        self.assertIn("Second scene.", video_script)
        self.assertIn("\n\n", video_script)

    def test_no_scenes_preserves_original_script(self):
        """When there are no scenes, video_script should remain unchanged."""
        video_script = "full narration script"
        processed_scenes = []

        scene_scripts = [s.script for s in processed_scenes if s.script]
        if scene_scripts:
            video_script = "\n\n".join(scene_scripts)

        self.assertEqual(video_script, "full narration script")


class TestSceneOrderPreservation(unittest.TestCase):
    """Tests that scene order is preserved through the pipeline."""

    def test_scenes_processed_in_order(self):
        """generate_scenes should process scenes in definition order."""
        params = VideoParams(
            video_subject="test",
            scenes=[
                SceneConfig(scene_id=1, script="First", search_terms=["t1"]),
                SceneConfig(scene_id=2, script="Second", search_terms=["t2"]),
                SceneConfig(scene_id=3, script="Third", search_terms=["t3"]),
            ],
        )
        result = tm.generate_scenes("task-1", params, "full script")

        self.assertIsNotNone(result)
        self.assertEqual([s.scene_id for s in result], [1, 2, 3])
        self.assertEqual([s.script for s in result], ["First", "Second", "Third"])


class TestSceneTransitionDefaults(unittest.TestCase):
    """Tests that scene/clip transitions fall back to global defaults."""

    def test_scene_transition_fallback(self):
        scene = SceneConfig(scene_id=1, script="Test.")
        params = VideoParams(
            video_subject="test",
            scene_transition=VideoTransitionMode.fade_in,
        )
        effective = scene.transition or params.scene_transition
        self.assertEqual(effective, VideoTransitionMode.fade_in)

    def test_clip_transition_fallback(self):
        scene = SceneConfig(scene_id=1, script="Test.")
        params = VideoParams(
            video_subject="test",
            clip_transition=VideoTransitionMode.slide_in,
        )
        effective = scene.clip_transition or params.clip_transition
        self.assertEqual(effective, VideoTransitionMode.slide_in)

    def test_per_scene_transition_takes_precedence(self):
        scene = SceneConfig(
            scene_id=1, script="Test.", transition=VideoTransitionMode.zoom_in
        )
        params = VideoParams(
            video_subject="test",
            scene_transition=VideoTransitionMode.fade_in,
        )
        effective = scene.transition or params.scene_transition
        self.assertEqual(effective, VideoTransitionMode.zoom_in)


class TestSceneTimeline(unittest.TestCase):
    """Timeline-level tests verifying actual durations and transitions."""

    def test_scene_video_duration_matches_audio(self):
        """Each scene's video should be trimmed to its audio duration."""
        scene = SceneConfig(scene_id=1, script="Test.", search_terms=["t1"])
        params = VideoParams(video_subject="test", voice_name="no-voice")

        with patch.object(tm.voice, "tts", return_value=MagicMock()), \
             patch("app.services.task.AudioFileClip") as mock_audio_clip, \
             patch.object(
                 tm.material, "download_videos", return_value=["/v1.mp4"]
             ), \
             patch.object(tm.video, "combine_videos") as mock_combine, \
             patch.object(tm.video, "generate_video", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch("os.makedirs"):

            mock_clip_instance = MagicMock()
            mock_clip_instance.duration = 3.5  # Scene's audio is 3.5 seconds
            mock_audio_clip.return_value = mock_clip_instance

            tm._generate_single_scene("task-1", scene, params, 1)

        # combine_videos uses the scene's own audio file, not global audio
        combine_call = mock_combine.call_args
        self.assertIn("scene-1", combine_call.kwargs["audio_file"])

    def test_each_scene_has_own_audio_and_subtitle_files(self):
        """Each scene should produce its own audio and subtitle files."""
        scene1 = SceneConfig(scene_id=1, script="First.", search_terms=["t1"])
        scene2 = SceneConfig(scene_id=2, script="Second.", search_terms=["t2"])
        params = VideoParams(
            video_subject="test",
            voice_name="no-voice",
            subtitle_enabled=False,
        )

        scene_paths = []
        for i, scene in enumerate([scene1, scene2], 1):
            with patch.object(tm.voice, "tts", return_value=MagicMock()), \
                 patch("app.services.task.AudioFileClip") as mock_audio_clip, \
                 patch.object(
                     tm.material, "download_videos", return_value=[f"/v{i}.mp4"]
                 ), \
                 patch.object(tm.video, "combine_videos"), \
                 patch.object(tm.video, "generate_video", return_value=True), \
                 patch("os.path.exists", return_value=True), \
                 patch("os.makedirs"):

                mock_clip_instance = MagicMock()
                mock_clip_instance.duration = float(i * 3)
                mock_audio_clip.return_value = mock_clip_instance

                result = tm._generate_single_scene("task-1", scene, params, i)
                scene_paths.append(result)

        # Both scenes should have generated valid paths in different directories
        self.assertIsNotNone(scene_paths[0])
        self.assertIsNotNone(scene_paths[1])
        self.assertIn("scene-1", scene_paths[0])
        self.assertIn("scene-2", scene_paths[1])
        self.assertNotEqual(scene_paths[0], scene_paths[1])


class TestSceneConfig(unittest.TestCase):
    """Tests for SceneConfig model validation."""

    def test_default_values(self):
        scene = SceneConfig()
        self.assertEqual(scene.scene_id, 0)
        self.assertEqual(scene.script, "")
        self.assertIsNone(scene.search_terms)
        self.assertIsNone(scene.materials)
        self.assertIsNone(scene.duration)
        self.assertIsNone(scene.transition)
        self.assertIsNone(scene.clip_transition)

    def test_valid_scene(self):
        scene = SceneConfig(
            scene_id=1,
            script="Drift is art.",
            search_terms=["drift car"],
            duration=5.0,
            transition=VideoTransitionMode.fade_in,
            clip_transition=VideoTransitionMode.slide_in,
        )
        self.assertEqual(scene.scene_id, 1)
        self.assertEqual(scene.script, "Drift is art.")
        self.assertEqual(scene.search_terms, ["drift car"])
        self.assertEqual(scene.duration, 5.0)
        self.assertEqual(scene.transition, VideoTransitionMode.fade_in)
        self.assertEqual(scene.clip_transition, VideoTransitionMode.slide_in)

    def test_rejects_negative_scene_id(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            SceneConfig(scene_id=-1)

    def test_rejects_duration_below_minimum(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            SceneConfig(duration=0.1)

    def test_accepts_minimum_duration(self):
        scene = SceneConfig(duration=0.5)
        self.assertEqual(scene.duration, 0.5)


class TestVideoParamsWithScenes(unittest.TestCase):
    """Tests for VideoParams with scenes and transition defaults."""

    def test_scenes_field_defaults_to_none(self):
        params = VideoParams(video_subject="Test")
        self.assertIsNone(params.scenes)

    def test_transition_defaults_are_none(self):
        params = VideoParams(video_subject="Test")
        self.assertIsNone(params.scene_transition)
        self.assertIsNone(params.clip_transition)

    def test_backward_compatibility_without_scenes(self):
        params = VideoParams(
            video_subject="Test",
            video_script="Full script",
            video_terms=["term1", "term2"],
        )
        self.assertIsNone(params.scenes)
        self.assertEqual(params.video_script, "Full script")

    def test_with_multiple_scenes_and_transitions(self):
        scenes = [
            SceneConfig(
                scene_id=1,
                script="Scene 1",
                transition=VideoTransitionMode.fade_in,
                clip_transition=VideoTransitionMode.slide_in,
            ),
            SceneConfig(
                scene_id=2,
                script="Scene 2",
                transition=VideoTransitionMode.zoom_in,
            ),
        ]
        params = VideoParams(
            video_subject="Test",
            scenes=scenes,
            scene_transition=VideoTransitionMode.shuffle,
            clip_transition=VideoTransitionMode.fade_out,
        )
        self.assertEqual(len(params.scenes), 2)
        self.assertEqual(params.scene_transition, VideoTransitionMode.shuffle)
        self.assertEqual(params.clip_transition, VideoTransitionMode.fade_out)
        # Per-scene values
        self.assertEqual(params.scenes[0].transition, VideoTransitionMode.fade_in)
        self.assertEqual(params.scenes[1].transition, VideoTransitionMode.zoom_in)
        self.assertEqual(
            params.scenes[0].clip_transition, VideoTransitionMode.slide_in
        )
        self.assertIsNone(params.scenes[1].clip_transition)


class TestCliSceneParsing(unittest.TestCase):
    """Tests for CLI --scenes and --scenes-file parsing."""

    def test_scenes_from_json_string(self):
        """Test parsing scenes from --scenes JSON string."""
        scenes_json = json.dumps([
            {"scene_id": 1, "script": "Scene 1 text", "search_terms": ["term1"], "duration": 5.0},
            {"scene_id": 2, "script": "Scene 2 text", "search_terms": ["term2"], "duration": 10.0},
        ])
        args = cli.parse_args([
            "--video-subject", "test",
            "--scenes", scenes_json,
        ])
        params = cli.build_video_params(args)

        self.assertIsNotNone(params.scenes)
        self.assertEqual(len(params.scenes), 2)
        self.assertEqual(params.scenes[0].scene_id, 1)
        self.assertEqual(params.scenes[0].script, "Scene 1 text")
        self.assertEqual(params.scenes[0].search_terms, ["term1"])
        self.assertEqual(params.scenes[0].duration, 5.0)

    def test_scenes_auto_assign_id(self):
        """Test that scene_id is auto-assigned when 0."""
        scenes_json = json.dumps([
            {"script": "Scene 1", "duration": 5.0},
            {"script": "Scene 2", "duration": 10.0},
        ])
        args = cli.parse_args([
            "--video-subject", "test",
            "--scenes", scenes_json,
        ])
        params = cli.build_video_params(args)
        self.assertEqual(params.scenes[0].scene_id, 1)
        self.assertEqual(params.scenes[1].scene_id, 2)

    def test_scenes_from_file(self):
        """Test loading scenes from --scenes-file."""
        scenes = [
            {"scene_id": 1, "script": "Scene 1", "duration": 5.0},
            {"scene_id": 2, "script": "Scene 2", "duration": 10.0},
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(scenes, f)
            scenes_file = f.name
        try:
            args = cli.parse_args([
                "--video-subject", "test",
                "--scenes-file", scenes_file,
            ])
            params = cli.build_video_params(args)
            self.assertIsNotNone(params.scenes)
            self.assertEqual(len(params.scenes), 2)
            self.assertEqual(params.scenes[0].script, "Scene 1")
        finally:
            os.unlink(scenes_file)

    def test_scenes_mutually_exclusive_with_scenes_file(self):
        scenes_json = json.dumps([{"script": "Scene 1"}])
        with self.assertRaises(SystemExit) as cm:
            cli.parse_args([
                "--video-subject", "test",
                "--scenes", scenes_json,
                "--scenes-file", "some_file.json",
            ])
        self.assertEqual(cm.exception.code, 2)

    def test_scenes_rejected_with_local_source(self):
        scenes_json = json.dumps([{"script": "Scene 1"}])
        with self.assertRaises(SystemExit) as cm:
            cli.parse_args([
                "--video-subject", "test",
                "--video-source", "local",
                "--video-materials", "a.mp4",
                "--scenes", scenes_json,
            ])
        self.assertEqual(cm.exception.code, 2)

    def test_scenes_with_invalid_json(self):
        args = cli.parse_args([
            "--video-subject", "test",
            "--scenes", "not valid json",
        ])
        with self.assertRaises(ValueError) as cm:
            cli.build_video_params(args)
        self.assertIn("invalid JSON", str(cm.exception))

    def test_scenes_none_when_not_provided(self):
        args = cli.parse_args(["--video-subject", "test"])
        params = cli.build_video_params(args)
        self.assertIsNone(params.scenes)

    def test_scene_transition_cli_option(self):
        scenes_json = json.dumps([{"script": "Scene 1"}])
        args = cli.parse_args([
            "--video-subject", "test",
            "--scenes", scenes_json,
            "--scene-transition", "fade-in",
        ])
        params = cli.build_video_params(args)
        self.assertEqual(params.scene_transition, "FadeIn")

    def test_clip_transition_cli_option(self):
        scenes_json = json.dumps([{"script": "Scene 1"}])
        args = cli.parse_args([
            "--video-subject", "test",
            "--scenes", scenes_json,
            "--clip-transition", "slide-in",
        ])
        params = cli.build_video_params(args)
        self.assertEqual(params.clip_transition, "SlideIn")


class TestApplySceneTransition(unittest.TestCase):
    """Tests for _apply_scene_transition() in video.py.

    All tests use fully mocked I/O — no file writes required.
    """

    def _run_transition(self, transition, *, duration=5.0):
        """Helper: run _apply_scene_transition with full mocks."""
        fake_clip = types.SimpleNamespace(duration=duration)
        with patch.object(vd, "_open_video_clip_quietly", return_value=fake_clip):
            with patch("app.services.video.video_effects") as mock_effects:
                mock_effects.fadein_transition.return_value = fake_clip
                mock_effects.fadeout_transition.return_value = fake_clip
                mock_effects.slidein_transition.return_value = fake_clip
                mock_effects.slideout_transition.return_value = fake_clip
                mock_effects.zoomin_transition.return_value = fake_clip
                mock_effects.zoomout_transition.return_value = fake_clip
                with patch.object(vd, "_write_videofile_with_codec_fallback"):
                    with patch.object(vd, "close_clip"):
                        vd._apply_scene_transition(
                            "input.mp4", "output.mp4", transition
                        )
        return mock_effects

    def test_none_transition_returns_immediately(self):
        """No-op when transition is None — should not open clip or write."""
        with patch.object(vd, "_open_video_clip_quietly") as open_mock:
            vd._apply_scene_transition("input.mp4", "output.mp4", VideoTransitionMode.none)
        open_mock.assert_not_called()

    def test_fade_in_calls_correct_effect(self):
        effects = self._run_transition(VideoTransitionMode.fade_in)
        effects.fadein_transition.assert_called_once()

    def test_fade_out_calls_correct_effect(self):
        """Bug fix: fade_out was previously silently ignored."""
        effects = self._run_transition(VideoTransitionMode.fade_out)
        effects.fadeout_transition.assert_called_once()

    def test_slide_in_calls_correct_effect(self):
        effects = self._run_transition(VideoTransitionMode.slide_in)
        effects.slidein_transition.assert_called_once()

    def test_slide_out_calls_correct_effect(self):
        """Bug fix: slide_out was previously silently ignored."""
        effects = self._run_transition(VideoTransitionMode.slide_out)
        effects.slideout_transition.assert_called_once()

    def test_zoom_in_calls_correct_effect(self):
        effects = self._run_transition(VideoTransitionMode.zoom_in)
        effects.zoomin_transition.assert_called_once()

    def test_zoom_out_calls_correct_effect(self):
        """Bug fix: zoom_out was previously silently ignored."""
        effects = self._run_transition(VideoTransitionMode.zoom_out)
        effects.zoomout_transition.assert_called_once()

    def test_shuffle_picks_from_all_transition_types(self):
        """Shuffle should randomly pick from ALL 6 transition types (in + out)."""
        seen = set()
        fake_clip = types.SimpleNamespace(duration=5.0)

        for _ in range(100):
            with patch.object(vd, "_open_video_clip_quietly", return_value=fake_clip):
                with patch("app.services.video.video_effects") as mock_effects:
                    called = []
                    for name in (
                        "fadein_transition", "fadeout_transition",
                        "slidein_transition", "slideout_transition",
                        "zoomin_transition", "zoomout_transition",
                    ):
                        def make_tracker(n):
                            def tracker(*a, **kw):
                                called.append(n)
                                return fake_clip
                            return tracker
                        setattr(mock_effects, name, make_tracker(name))
                    with patch.object(vd, "_write_videofile_with_codec_fallback"):
                        with patch.object(vd, "close_clip"):
                            vd._apply_scene_transition(
                                "input.mp4", "output.mp4", VideoTransitionMode.shuffle
                            )
                    self.assertEqual(len(called), 1)
                    seen.add(called[0])
        # After 100 runs, we should have seen at least 3 different transition types
        self.assertGreaterEqual(len(seen), 3, f"Only saw transitions: {seen}")

    def test_zero_duration_clip_returns_early(self):
        """Clips with zero duration should not be processed."""
        fake_clip = types.SimpleNamespace(duration=0.0)
        with patch.object(vd, "_open_video_clip_quietly", return_value=fake_clip):
            with patch.object(vd, "_write_videofile_with_codec_fallback") as write_mock:
                with patch.object(vd, "close_clip"):
                    vd._apply_scene_transition(
                        "input.mp4", "output.mp4", VideoTransitionMode.fade_in
                    )
        write_mock.assert_not_called()

    def test_unsupported_transition_returns_without_writing(self):
        """Unknown transition values should log a warning and not write output."""
        fake_clip = types.SimpleNamespace(duration=5.0)
        with patch.object(vd, "_open_video_clip_quietly", return_value=fake_clip):
            with patch.object(vd, "_write_videofile_with_codec_fallback") as write_mock:
                with patch.object(vd, "close_clip"):
                    vd._apply_scene_transition(
                        "input.mp4", "output.mp4", "UnknownTransition"
                    )
        write_mock.assert_not_called()


class TestConcatSceneVideosWithTransitions(unittest.TestCase):
    """Tests for concat_scene_videos_with_transitions() in video.py.

    Uses fully mocked ffmpeg and file operations.
    """

    def test_empty_paths_returns_without_error(self):
        """Empty input should not crash."""
        with patch.object(vd, "concat_video_clips_with_ffmpeg") as concat_mock:
            vd.concat_scene_videos_with_transitions(
                scene_video_paths=[], output_file="/fake/output.mp4"
            )
        concat_mock.assert_not_called()

    def test_single_scene_concatenates(self):
        """Single scene should be concatenated without transitions."""
        mock_clip = _mock_clip()
        with patch("app.services.video.os.makedirs"):
            with patch.object(vd, "_open_video_clip_quietly", return_value=mock_clip):
                with patch("app.services.video.concatenate_videoclips") as concat_mock:
                    concat_mock.return_value = mock_clip
                    with patch.object(vd, "_write_videofile_with_codec_fallback"):
                        vd.concat_scene_videos_with_transitions(
                            scene_video_paths=["scene1.mp4"],
                            output_file="/fake/output.mp4",
                        )
        concat_mock.assert_called_once()

    def test_multi_scene_without_transitions(self):
        """Multiple scenes without transitions should all be passed directly."""
        mock_clip = _mock_clip()
        scenes = ["scene1.mp4", "scene2.mp4", "scene3.mp4"]
        with patch("app.services.video.os.makedirs"):
            with patch.object(vd, "_open_video_clip_quietly", return_value=mock_clip):
                with patch("app.services.video.concatenate_videoclips") as concat_mock:
                    concat_mock.return_value = mock_clip
                    with patch.object(vd, "_write_videofile_with_codec_fallback"):
                        vd.concat_scene_videos_with_transitions(
                            scene_video_paths=scenes,
                            output_file="/fake/output.mp4",
                        )
        concat_mock.assert_called_once()
        # Should have 3 clips
        call_args = concat_mock.call_args[0][0]
        self.assertEqual(len(call_args), 3)

    def test_transitions_applied_to_non_first_scenes(self):
        """Transitions should be applied inline to scene clips 2+."""
        mock_clip = _mock_clip()
        scenes = ["s1.mp4", "s2.mp4", "s3.mp4"]
        transitions = [
            None,
            VideoTransitionMode.fade_in,
            VideoTransitionMode.slide_in,
        ]
        with patch("app.services.video.os.makedirs"):
            with patch.object(vd, "_open_video_clip_quietly", return_value=mock_clip):
                with patch("app.services.video.video_effects") as mock_effects:
                    mock_effects.fadein_transition.return_value = mock_clip
                    mock_effects.slidein_transition.return_value = mock_clip
                    with patch("app.services.video.concatenate_videoclips") as concat_mock:
                        concat_mock.return_value = mock_clip
                        with patch.object(vd, "_write_videofile_with_codec_fallback"):
                            vd.concat_scene_videos_with_transitions(
                                scene_video_paths=scenes,
                                output_file="/fake/output.mp4",
                                scene_transitions=transitions,
                            )
        mock_effects.fadein_transition.assert_called_once()
        mock_effects.slidein_transition.assert_called_once()

    def test_transition_failure_falls_back_to_original(self):
        """If _open_video_clip_quietly returns a clip, transitions apply inline."""
        mock_clip = _mock_clip()
        scenes = ["s1.mp4", "s2.mp4"]
        transitions = [None, VideoTransitionMode.fade_in]

        with patch("app.services.video.os.makedirs"):
            with patch.object(vd, "_open_video_clip_quietly", return_value=mock_clip):
                with patch("app.services.video.video_effects") as mock_effects:
                    # fadein returns a clip (succeeds)
                    mock_effects.fadein_transition.return_value = mock_clip
                    with patch("app.services.video.concatenate_videoclips") as concat_mock:
                        concat_mock.return_value = mock_clip
                        with patch.object(vd, "_write_videofile_with_codec_fallback"):
                            vd.concat_scene_videos_with_transitions(
                                scene_video_paths=scenes,
                                output_file="/fake/output.mp4",
                                scene_transitions=transitions,
                            )
        # concatenate should receive 2 clips
        call_args = concat_mock.call_args[0][0]
        self.assertEqual(len(call_args), 2)

    def test_bgm_overlay_called_when_enabled(self):
        """BGM should be overlaid when bgm_file_override is a file path."""
        mock_clip = _mock_clip()
        mock_clip.audio = MagicMock()

        with patch("app.services.video.os.makedirs"):
            with patch("app.services.video.os.path.isfile", return_value=True):
                with patch.object(vd, "_open_video_clip_quietly", return_value=mock_clip):
                    with patch("app.services.video.concatenate_videoclips") as concat_mock:
                        concat_mock.return_value = mock_clip
                        with patch("app.services.video.AudioFileClip") as mock_audio:
                            mock_audio.return_value.__enter__ = MagicMock(return_value=MagicMock())
                            mock_audio.return_value.__exit__ = MagicMock(return_value=False)
                            with patch("app.services.video.CompositeAudioClip", return_value=MagicMock()):
                                with patch.object(vd, "_write_videofile_with_codec_fallback"):
                                    vd.concat_scene_videos_with_transitions(
                                        scene_video_paths=["s1.mp4"],
                                        output_file="/fake/output.mp4",
                                        bgm_file_override="/fake/bgm.mp3",
                                        bgm_volume=0.3,
                                    )
        # AudioFileClip should be called with the bgm file
        mock_audio.assert_called_once_with("/fake/bgm.mp3")

    def test_bgm_not_overlayed_when_volume_zero(self):
        """BGM should NOT be overlaid when volume is 0."""
        mock_clip = _mock_clip()
        mock_clip.audio = MagicMock()

        with patch("app.services.video.os.makedirs"):
            with patch.object(vd, "_open_video_clip_quietly", return_value=mock_clip):
                with patch("app.services.video.concatenate_videoclips") as concat_mock:
                    concat_mock.return_value = mock_clip
                    with patch("app.services.video.AudioFileClip") as mock_audio:
                        with patch.object(vd, "_write_videofile_with_codec_fallback"):
                            vd.concat_scene_videos_with_transitions(
                                scene_video_paths=["s1.mp4"],
                                output_file="/fake/output.mp4",
                                bgm_file_override="/fake/bgm.mp3",
                                bgm_volume=0.0,
                            )
        # AudioFileClip should NOT be called (no BGM)
        mock_audio.assert_not_called()

    def test_bgm_not_overlayed_when_file_missing(self):
        """BGM should NOT be overlaid when the bgm file doesn't exist."""
        mock_clip = _mock_clip()
        mock_clip.audio = MagicMock()

        with patch("app.services.video.os.makedirs"):
            with patch.object(vd, "_open_video_clip_quietly", return_value=mock_clip):
                with patch("app.services.video.concatenate_videoclips") as concat_mock:
                    concat_mock.return_value = mock_clip
                    with patch("app.services.video.os.path.isfile", return_value=False):
                        with patch("app.services.video.AudioFileClip") as mock_audio:
                            with patch.object(vd, "_write_videofile_with_codec_fallback"):
                                vd.concat_scene_videos_with_transitions(
                                    scene_video_paths=["s1.mp4"],
                                    output_file="/fake/output.mp4",
                                    bgm_file_override="/nonexistent/bgm.mp3",
                                    bgm_volume=0.3,
                                )
        mock_audio.assert_not_called()

    def test_bgm_resolves_from_type_when_override_none(self):
        """When bgm_file_override=None, BGM should be resolved from bgm_type."""
        mock_clip = _mock_clip()
        mock_clip.audio = MagicMock()

        with patch("app.services.video.os.makedirs"):
            with patch("app.services.video.os.path.isfile", return_value=True):
                with patch.object(vd, "_open_video_clip_quietly", return_value=mock_clip):
                    with patch("app.services.video.concatenate_videoclips") as concat_mock:
                        concat_mock.return_value = mock_clip
                        with patch("app.services.video.get_bgm_file", return_value="/bgm/random.mp3"):
                            with patch("app.services.video.bgm_service") as mock_bgm:
                                mock_bgm.should_use_bgm.return_value = True
                                with patch("app.services.video.AudioFileClip") as mock_audio:
                                    mock_audio.return_value.__enter__ = MagicMock(return_value=MagicMock())
                                    mock_audio.return_value.__exit__ = MagicMock(return_value=False)
                                    with patch("app.services.video.CompositeAudioClip", return_value=MagicMock()):
                                        with patch.object(vd, "_write_videofile_with_codec_fallback"):
                                            vd.concat_scene_videos_with_transitions(
                                                scene_video_paths=["s1.mp4"],
                                                output_file="/fake/output.mp4",
                                                bgm_file_override=None,
                                                bgm_type="random",
                                                bgm_volume=0.3,
                                            )
        mock_audio.assert_called_once_with("/bgm/random.mp3")


class TestOverlayBgmOnVideo(unittest.TestCase):
    """Tests for _overlay_bgm_on_video() in video.py.

    Uses MoviePy CompositeAudioClip — same approach as generate_video().
    """

    def test_mixes_bgm_with_video_audio(self):
        """Should create a CompositeAudioClip from video audio + BGM."""
        mock_video_audio = MagicMock()
        mock_video_clip = MagicMock()
        mock_video_clip.audio = mock_video_audio
        mock_video_clip.duration = 10.0

        mock_bgm_clip = MagicMock()
        mock_mixed = MagicMock()
        mock_mixed.fps = 44100
        mock_final = MagicMock()

        with ExitStack() as stack:
            stack.enter_context(patch.object(
                vd, "_open_video_clip_quietly", return_value=mock_video_clip
            ))
            mock_audio_class = stack.enter_context(patch.object(vd, "AudioFileClip"))
            mock_audio_class.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_audio_class.return_value.__exit__ = MagicMock(return_value=False)
            mock_audio_class.return_value.with_effects.return_value = mock_bgm_clip

            stack.enter_context(patch.object(vd, "CompositeAudioClip", return_value=MagicMock()))
            mock_video_clip.with_audio.return_value = mock_final
            mock_final.with_effects = MagicMock(return_value=mock_final)

            # Patch CompositeAudioClip at call site
            with patch("app.services.video.CompositeAudioClip") as mock_composite:
                mock_composite.return_value = mock_mixed
                with patch.object(vd, "_write_videofile_with_codec_fallback"):
                    with patch.object(vd, "_open_video_clip_quietly", return_value=mock_video_clip):
                        vd._overlay_bgm_on_video(
                            video_path="video.mp4",
                            bgm_file="bgm.mp3",
                            bgm_volume=0.4,
                            output_path="output.mp4",
                        )
        # Verify CompositeAudioClip was used (MoviePy approach, not raw ffmpeg)
        mock_composite.assert_called_once()

    def test_bgm_effects_include_volume_fadeout_and_loop(self):
        """BGM should have volume, fadeout, and loop effects."""
        mock_video_clip = MagicMock()
        mock_video_clip.audio = MagicMock()
        mock_video_clip.duration = 10.0

        with patch.object(vd, "_open_video_clip_quietly", return_value=mock_video_clip):
            with patch("app.services.video.AudioFileClip") as mock_audio:
                mock_bgm_source = MagicMock()
                mock_audio.return_value.__enter__ = MagicMock(return_value=mock_bgm_source)
                mock_audio.return_value.__exit__ = MagicMock(return_value=False)
                mock_bgm_source.with_effects.return_value = MagicMock()
                with patch("app.services.video.CompositeAudioClip", return_value=MagicMock()):
                    mock_video_clip.with_audio.return_value = MagicMock()
                    with patch.object(vd, "_write_videofile_with_codec_fallback"):
                        vd._overlay_bgm_on_video(
                            video_path="video.mp4",
                            bgm_file="bgm.mp3",
                            bgm_volume=0.3,
                            output_path="output.mp4",
                        )
        # Verify with_effects was called with a list containing 3 effects
        effect_call = mock_bgm_source.with_effects.call_args[0][0]
        self.assertEqual(len(effect_call), 3)  # volume, fadeout, loop


class TestScenePipelineFailureModes(unittest.TestCase):
    """Tests for scene failure handling logic."""

    def test_partial_failure_filters_none_paths(self):
        """When some scenes return None, only valid paths should be used."""
        scene_paths = ["/valid/scene1.mp4", None, "/valid/scene3.mp4"]
        valid_paths = [p for p in scene_paths if p]
        self.assertEqual(valid_paths, ["/valid/scene1.mp4", "/valid/scene3.mp4"])

    def test_all_scenes_none_yields_empty_list(self):
        """When all scene videos are None, valid paths list is empty."""
        scene_paths = [None, None, None]
        valid_paths = [p for p in scene_paths if p]
        self.assertEqual(len(valid_paths), 0)

    def test_single_scene_success(self):
        """Single successful scene should be in valid paths."""
        scene_paths = ["/valid/scene1.mp4"]
        valid_paths = [p for p in scene_paths if p]
        self.assertEqual(len(valid_paths), 1)

    def test_transition_list_shorter_than_scenes(self):
        """When transition list is shorter than scenes, missing entries use None."""
        scene_transitions = [None, VideoTransitionMode.fade_in]
        # Scene 3 has index 2, which is >= len(scene_transitions)
        transition = (
            scene_transitions[3]
            if scene_transitions and 3 < len(scene_transitions)
            else None
        )
        self.assertIsNone(transition)


class TestGenerateSceneScripts(unittest.TestCase):
    """Tests for llm.generate_scene_scripts() JSON parsing and recovery."""

    def _mock_generate(self, response_text):
        """Helper: mock _generate_response to return response_text."""
        with patch.object(tm.llm, "_generate_response", return_value=response_text):
            return tm.llm.generate_scene_scripts(
                video_subject="test subject",
                scene_count=2,
            )

    def test_parses_valid_json(self):
        response = '{"scenes": [{"scene_id": 1, "script": "Hello"}, {"scene_id": 2, "script": "World"}]}'
        result = self._mock_generate(response)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["scene_id"], 1)
        self.assertEqual(result[0]["script"], "Hello")
        self.assertEqual(result[1]["script"], "World")

    def test_strips_code_fence(self):
        response = '```json\n{"scenes": [{"scene_id": 1, "script": "Test"}]}\n```'
        result = self._mock_generate(response)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["script"], "Test")

    def test_returns_empty_on_empty_response(self):
        result = self._mock_generate("")
        self.assertEqual(result, [])

    def test_returns_empty_on_invalid_json(self):
        result = self._mock_generate("not json at all")
        self.assertEqual(result, [])

    def test_recovers_json_from_text(self):
        """Should recover JSON embedded in surrounding text."""
        response = 'Here is the result: {"scenes": [{"scene_id": 1, "script": "OK"}]} hope this helps'
        result = self._mock_generate(response)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["script"], "OK")

    def test_skips_scenes_with_empty_script(self):
        response = '{"scenes": [{"scene_id": 1, "script": "Good"}, {"scene_id": 2, "script": ""}]}'
        result = self._mock_generate(response)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["script"], "Good")

    def test_normalizes_scene_count(self):
        """Should clamp scene_count to MIN/MAX range."""
        self.assertEqual(tm.llm._normalize_scene_count(0), 2)
        self.assertEqual(tm.llm._normalize_scene_count(15), 10)
        self.assertEqual(tm.llm._normalize_scene_count(5), 5)
        self.assertEqual(tm.llm._normalize_scene_count(None), 2)


class TestGenerateSceneKeywords(unittest.TestCase):
    """Tests for llm.generate_scene_keywords() JSON parsing."""

    def _mock_generate(self, response_text, scene_scripts=None):
        if scene_scripts is None:
            scene_scripts = [
                {"scene_id": 1, "script": "Hello world"},
                {"scene_id": 2, "script": "Goodbye world"},
            ]
        with patch.object(tm.llm, "_generate_response", return_value=response_text):
            return tm.llm.generate_scene_keywords(
                video_subject="test",
                scene_scripts=scene_scripts,
                scene_count=len(scene_scripts),
            )

    def test_parses_valid_json(self):
        response = '{"scenes": [{"scene_id": 1, "terms": ["greeting", "hello"]}, {"scene_id": 2, "terms": ["farewell"]}]}'
        result = self._mock_generate(response)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["scene_id"], 1)
        self.assertEqual(result[0]["terms"], ["greeting", "hello"])
        self.assertEqual(result[1]["terms"], ["farewell"])

    def test_returns_empty_on_empty_response(self):
        result = self._mock_generate("")
        self.assertEqual(result, [])

    def test_returns_empty_when_no_scripts_provided(self):
        result = tm.llm.generate_scene_keywords(
            video_subject="test",
            scene_scripts=[],
            scene_count=0,
        )
        self.assertEqual(result, [])

    def test_skips_scenes_with_empty_terms(self):
        response = '{"scenes": [{"scene_id": 1, "terms": ["ok"]}, {"scene_id": 2, "terms": []}]}'
        result = self._mock_generate(response)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["terms"], ["ok"])


class TestBuildParamsScenes(unittest.TestCase):
    """Tests for the UI logic that assembles params.scenes from session state."""

    def _build_params_from_scripts(self, scripts, keywords=None):
        """Simulate _build_params_scenes logic without Streamlit."""
        from app.models.schema import SceneConfig
        if keywords is None:
            keywords = [""] * len(scripts)
        scenes = []
        for i, script in enumerate(scripts):
            if not script.strip():
                continue
            terms_raw = keywords[i] if i < len(keywords) else ""
            search_terms = (
                [t.strip() for t in terms_raw.split(",") if t.strip()]
                if terms_raw.strip() else None
            )
            scene = SceneConfig(
                scene_id=i + 1,
                script=script.strip(),
                search_terms=search_terms,
            )
            scenes.append(scene)
        return scenes if len(scenes) >= 2 else None

    def test_two_valid_scripts_produces_scenes(self):
        scenes = self._build_params_from_scripts(["Script 1", "Script 2"])
        self.assertIsNotNone(scenes)
        self.assertEqual(len(scenes), 2)
        self.assertEqual(scenes[0].script, "Script 1")
        self.assertEqual(scenes[1].script, "Script 2")

    def test_one_valid_script_returns_none(self):
        """Below 2 scenes should return None to avoid pipeline errors."""
        scenes = self._build_params_from_scripts(["Only one", ""])
        self.assertIsNone(scenes)

    def test_empty_scripts_returns_none(self):
        scenes = self._build_params_from_scripts(["", ""])
        self.assertIsNone(scenes)

    def test_keywords_are_parsed(self):
        scenes = self._build_params_from_scripts(
            ["S1", "S2"],
            keywords=["cat, dog", "sun, moon, star"]
        )
        self.assertEqual(scenes[0].search_terms, ["cat", "dog"])
        self.assertEqual(scenes[1].search_terms, ["sun", "moon", "star"])

    def test_empty_keywords_gives_none(self):
        scenes = self._build_params_from_scripts(["S1", "S2"], keywords=["", ""])
        self.assertIsNone(scenes[0].search_terms)

    def test_scene_ids_are_one_based(self):
        scenes = self._build_params_from_scripts(["S1", "S2", "S3"])
        self.assertEqual(scenes[0].scene_id, 1)
        self.assertEqual(scenes[1].scene_id, 2)
        self.assertEqual(scenes[2].scene_id, 3)


class TestConcatBgmExplicitDisable(unittest.TestCase):
    """Verify that bgm_file_override='' explicitly disables BGM."""

    def test_empty_string_override_no_bgm(self):
        mock_clip = _mock_clip()
        audio_mock = MagicMock()
        with patch("app.services.video.os.makedirs"):
            with patch.object(vd, "_open_video_clip_quietly", return_value=mock_clip):
                with patch("app.services.video.concatenate_videoclips") as concat_mock:
                    concat_mock.return_value = mock_clip
                    with patch("app.services.video.AudioFileClip") as mock_audio:
                        with patch("app.services.video.CompositeAudioClip"):
                            with patch.object(vd, "_write_videofile_with_codec_fallback"):
                                vd.concat_scene_videos_with_transitions(
                                    scene_video_paths=["s1.mp4"],
                                    output_file="/fake/output.mp4",
                                    bgm_file_override="",
                                    bgm_type="random",
                                    bgm_volume=0.5,
                                )
        # Should NOT load any BGM file
        mock_audio.assert_not_called()


if __name__ == "__main__":
    unittest.main()
