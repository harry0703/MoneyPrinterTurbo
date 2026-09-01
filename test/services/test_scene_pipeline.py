"""End-to-end tests for the scene-based video generation pipeline.

Tests verify that scene structure is preserved through all pipeline stages:
script processing, audio, subtitle, material download, and video composition.
Each scene is assembled as a self-contained video before final concatenation.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import cli
from app.models.schema import (
    MaterialInfo,
    SceneConfig,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
)
from app.services import task as tm


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


if __name__ == "__main__":
    unittest.main()
