import hashlib
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from moviepy import ColorClip, VideoFileClip
from PIL import Image

from app.models.scene_media import (
    CandidateScores,
    SceneMediaAssignment,
    SceneMediaCandidate,
    SceneMediaManifest,
    SceneVisualAssessment,
)
from app.models.scene_timeline import SceneTimeline
from app.models.schema import VideoAspect
from app.models.video_plan import Scene, SceneTiming, Shot, VideoPlan, VisualBrief
from app.services import scene_timeline, video


def _plan(script="Primera escena. Segunda escena."):
    scene_texts = ["Primera escena.", "Segunda escena."]
    return VideoPlan(
        script_sha256=hashlib.sha256(script.encode()).hexdigest(),
        subject="test",
        scenes=[
            Scene(
                scene_id=f"scene-{index:03d}",
                order=index - 1,
                narration_text=text,
                timing=SceneTiming(estimated_duration_ms=index * 1000, confidence=0.5),
                visual=VisualBrief(
                    subject=["test"], action="moves", description="test scene",
                    visual_prompt="test", search_queries=["test"],
                    recommended_material_type=["stock_video"],
                ),
                shots=[Shot(shot_id=f"shot-{index:03d}")],
            )
            for index, text in enumerate(scene_texts, start=1)
        ],
    )


def _manifest(plan, asset_paths, durations=(3.0, 3.0)):
    assignments = []
    for index, (asset_path, duration) in enumerate(zip(asset_paths, durations), start=1):
        candidate = SceneMediaCandidate(
            provider="fixture",
            original_asset_id=str(index),
            resource_fingerprint=f"{index:064x}",
            local_path=str(asset_path),
            material_type="stock_video",
            search_query="test scene",
            duration_seconds=duration,
            scores=CandidateScores(retrieval=1, resolution=1, duration=1, aspect=1),
            visual_validation="passed",
            selected=True,
        )
        assignments.append(SceneMediaAssignment(
            scene_id=f"scene-{index:03d}",
            status="selected",
            selected_candidate=candidate,
            candidates=[candidate],
        ))
    return SceneMediaManifest(
        plan_id=plan.plan_id,
        script_sha256=plan.script_sha256,
        assignments=assignments,
    )


class TestSceneTimeline(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        temp_root.mkdir(exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=temp_root)
        self.directory = Path(self.temp_dir.name)
        self.assets = [self.directory / "one.mp4", self.directory / "two.mp4"]
        for asset in self.assets:
            asset.touch()
        self.plan = _plan()
        self.manifest = _manifest(self.plan, self.assets)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_uses_timed_subtitles_as_scene_boundaries(self):
        subtitles = self.directory / "subtitle.srt"
        subtitles.write_text(
            "1\n00:00:00,200 --> 00:00:01,400\nPrimera escena.\n\n"
            "2\n00:00:02,000 --> 00:00:03,200\nSegunda escena.\n",
            encoding="utf-8",
        )
        result = scene_timeline.build_scene_timeline(
            self.plan, self.manifest, audio_duration=4.0, subtitle_path=str(subtitles)
        )
        self.assertEqual(result.alignment_source, "subtitles")
        self.assertAlmostEqual(result.items[0].timeline_start, 0)
        self.assertAlmostEqual(result.items[0].timeline_end, 2.0)
        self.assertAlmostEqual(result.items[1].timeline_start, 2.0)
        self.assertAlmostEqual(result.items[1].timeline_end, 4.0)
        self.assertEqual([item.scene_id for item in result.items], ["scene-001", "scene-002"])
        self.assertEqual(result.items[0].scene_label, "test")

    def test_uses_tts_cues_when_subtitles_are_unavailable(self):
        cues = SimpleNamespace(cues=[
            SimpleNamespace(
                content="Primera escena.", start=timedelta(seconds=0.1),
                end=timedelta(seconds=1.3),
            ),
            SimpleNamespace(
                content="Segunda escena.", start=timedelta(seconds=2.2),
                end=timedelta(seconds=3.5),
            ),
        ])
        result = scene_timeline.build_scene_timeline(
            self.plan, self.manifest, audio_duration=4.0, sub_maker=cues
        )
        self.assertEqual(result.alignment_source, "tts_cues")
        self.assertAlmostEqual(result.items[0].timeline_end, 2.2)

    def test_interpolates_scene_boundary_inside_a_shared_caption_cue(self):
        subtitles = self.directory / "shared.srt"
        subtitles.write_text(
            "1\n00:00:00,000 --> 00:00:04,000\nPrimera escena. Segunda escena.\n",
            encoding="utf-8",
        )
        result = scene_timeline.build_scene_timeline(
            self.plan, self.manifest, audio_duration=4.0, subtitle_path=str(subtitles)
        )
        self.assertAlmostEqual(result.items[0].timeline_end, 2.0, delta=0.3)

    def test_estimates_boundaries_only_when_no_timed_source_exists(self):
        result = scene_timeline.build_scene_timeline(
            self.plan, _manifest(self.plan, self.assets, durations=(10, 10)), audio_duration=6.0
        )
        self.assertEqual(result.synchronization, "estimated")
        self.assertAlmostEqual(result.items[0].duration, 2.0)
        self.assertAlmostEqual(result.items[1].duration, 4.0)

    def test_rejects_unmatched_narration_and_missing_assets(self):
        subtitles = self.directory / "bad.srt"
        subtitles.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nUnrelated words.\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "does not match"):
            scene_timeline.build_scene_timeline(
                self.plan, self.manifest, audio_duration=4, subtitle_path=str(subtitles)
            )
        missing = self.directory / "missing.mp4"
        invalid_manifest = _manifest(self.plan, [self.assets[0], missing])
        with self.assertRaisesRegex(ValueError, "unavailable"):
            scene_timeline.build_scene_timeline(
                self.plan, invalid_manifest, audio_duration=4
            )

    def test_resolves_task_relative_scene_media_paths(self):
        task_root = self.directory / "task"
        task_root.mkdir()
        first, second = task_root / "one.mp4", task_root / "two.mp4"
        first.touch()
        second.touch()
        manifest = _manifest(self.plan, ["one.mp4", "two.mp4"])
        result = scene_timeline.build_scene_timeline(
            self.plan, manifest, audio_duration=4, asset_root=task_root
        )
        self.assertEqual(result.items[0].asset_path, str(first.resolve()))

    def test_rejects_non_contiguous_or_wrong_duration_timeline(self):
        raw = {
            "plan_id": self.plan.plan_id,
            "script_sha256": self.plan.script_sha256,
            "audio_duration": 2.0,
            "alignment_source": "estimated",
            "synchronization": "estimated",
            "items": [{
                "scene_id": "scene-001", "asset_path": str(self.assets[0]),
                "material_type": "stock_video", "provider": "fixture",
                "timeline_start": 0, "timeline_end": 1, "source_start": 0,
                "source_end": 1, "synchronization": "estimated",
                "narration_text": "one", "shot_id": "shot-001",
            }],
        }
        with self.assertRaises(ValueError):
            SceneTimeline.model_validate(raw)

    def test_ffmpeg_renders_scene_order_and_exact_audio_duration(self):
        self.plan.scenes[0].timing.estimated_duration_ms = 1000
        self.plan.scenes[1].timing.estimated_duration_ms = 1000
        sources = []
        for index, color in enumerate([(220, 20, 20), (20, 20, 220)]):
            source_path = self.directory / f"source-{index}.mp4"
            with ColorClip(size=(160, 90), color=color, duration=1.0) as source:
                source.write_videofile(
                    str(source_path), fps=8, codec="libx264", audio=False, logger=None
                )
            sources.append(source_path)
        manifest = _manifest(self.plan, sources, durations=(1, 1))
        timeline = scene_timeline.build_scene_timeline(
            self.plan, manifest, audio_duration=2.0, fps=8
        )
        output = self.directory / "combined.mp4"
        with patch.object(VideoAspect, "to_resolution", return_value=(160, 90)):
            video.combine_scene_timeline(
                combined_video_path=str(output), timeline=timeline,
                video_aspect=VideoAspect.landscape, threads=1,
                show_scene_labels=True, font_name="STHeitiMedium.ttc",
            )
        with VideoFileClip(str(output), audio=False) as rendered:
            self.assertEqual(rendered.size, [160, 90])
            self.assertAlmostEqual(rendered.duration, 2.0, delta=0.15)
            first = rendered.get_frame(0.2)
            second = rendered.get_frame(1.2)
            self.assertGreater(first[:, :, 0].mean(), first[:, :, 2].mean())
            self.assertGreater(second[:, :, 2].mean(), second[:, :, 0].mean())
            self.assertLess(first[15, 15].mean(), 100)

    def test_ffmpeg_renders_assigned_image_as_a_scene(self):
        self.plan.scenes[0].timing.estimated_duration_ms = 1000
        self.plan.scenes[1].timing.estimated_duration_ms = 1000
        source_path = self.directory / "video.mp4"
        with ColorClip(size=(160, 90), color=(220, 20, 20), duration=1.0) as source:
            source.write_videofile(
                str(source_path), fps=8, codec="libx264", audio=False, logger=None
            )
        image_path = self.directory / "image.png"
        Image.new("RGB", (160, 90), (20, 220, 20)).save(image_path)
        manifest = _manifest(self.plan, [source_path, image_path], durations=(1, 0))
        candidate = manifest.assignments[1].selected_candidate
        candidate.material_type = "generated_image"
        manifest.assignments[1].material_type = "generated_image"
        timeline = scene_timeline.build_scene_timeline(
            self.plan, manifest, audio_duration=2.0, fps=8
        )
        output = self.directory / "combined-image.mp4"
        with patch.object(VideoAspect, "to_resolution", return_value=(160, 90)):
            video.combine_scene_timeline(
                combined_video_path=str(output), timeline=timeline,
                video_aspect=VideoAspect.landscape, threads=1,
            )
        with VideoFileClip(str(output), audio=False) as rendered:
            self.assertEqual(rendered.size, [160, 90])
            self.assertAlmostEqual(rendered.duration, 2.0, delta=0.15)
            image_frame = rendered.get_frame(1.2)
            self.assertGreater(image_frame[:, :, 1].mean(), image_frame[:, :, 0].mean())


if __name__ == "__main__":
    unittest.main()
