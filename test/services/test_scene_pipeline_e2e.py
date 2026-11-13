"""Offline end-to-end exercise of scene timing, composition, audio, export, and QA."""

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from moviepy import ColorClip, VideoFileClip

from app.models.scene_media import (
    CandidateScores,
    SceneMediaAssignment,
    SceneMediaCandidate,
    SceneMediaManifest,
)
from app.models.schema import SoundEffectCue, VideoAspect, VideoParams
from app.models.video_plan import Scene, SceneTiming, Shot, VideoPlan, VisualBrief
from app.services import scene_quality, scene_timeline, video


class TestScenePipelineEndToEnd(unittest.TestCase):
    def test_local_scene_plan_to_final_mp4_with_audio_subtitles_and_quality_scan(self):
        root = Path(__file__).resolve().parents[2] / ".test-tmp"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temp:
            directory = Path(temp)
            script = "The Sun shines brightly. Saturn has bright rings."
            scene_specs = [
                ("scene-001", "The Sun shines brightly.", "Sun", (210, 130, 20)),
                ("scene-002", "Saturn has bright rings.", "Saturn", (170, 120, 45)),
            ]
            scenes = [
                Scene(
                    scene_id=scene_id,
                    order=index,
                    narration_text=text,
                    timing=SceneTiming(estimated_duration_ms=1000, confidence=0.8),
                    visual=VisualBrief(
                        subject=[subject],
                        action="appears in frame",
                        description=f"Test card labeled {subject}",
                        visual_prompt=f"Test card labeled {subject}",
                        search_queries=[subject],
                        recommended_material_type=["stock_video"],
                    ),
                    shots=[Shot(shot_id=f"shot-{index + 1:03d}")],
                )
                for index, (scene_id, text, subject, _color) in enumerate(scene_specs)
            ]
            plan = VideoPlan(
                subject="Synthetic astronomy test cards",
                script_sha256=hashlib.sha256(script.encode()).hexdigest(),
                scenes=scenes,
            )

            assets = []
            assignments = []
            for index, (scene_id, _text, _subject, color) in enumerate(scene_specs):
                asset = directory / f"scene-{index + 1}.mp4"
                with ColorClip(size=(640, 360), color=color, duration=1.0) as clip:
                    clip.write_videofile(
                        str(asset), fps=8, codec="libx264", audio=False, logger=None
                    )
                assets.append(asset)
                candidate = SceneMediaCandidate(
                    provider="local-test-fixture",
                    original_asset_id=f"fixture-{index + 1}",
                    resource_fingerprint=f"{index + 1:064x}",
                    local_path=str(asset),
                    material_type="stock_video",
                    search_query=scene_specs[index][2],
                    duration_seconds=1,
                    scores=CandidateScores(
                        retrieval=1, resolution=1, duration=1, aspect=1
                    ),
                    visual_validation="passed",
                    selected=True,
                )
                assignments.append(SceneMediaAssignment(
                    scene_id=scene_id,
                    status="selected",
                    selected_candidate=candidate,
                    candidates=[candidate],
                ))

            manifest = SceneMediaManifest(
                plan_id=plan.plan_id,
                script_sha256=plan.script_sha256,
                assignments=assignments,
            )
            subtitle = directory / "narration.srt"
            subtitle.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nThe Sun shines brightly.\n\n"
                "2\n00:00:01,000 --> 00:00:02,000\nSaturn has bright rings.\n",
                encoding="utf-8",
            )
            narration = directory / "narration.wav"
            music = directory / "music.wav"
            effect = directory / "chime.wav"
            ffmpeg = video.utils.get_ffmpeg_binary()
            for frequency, duration, output in (
                (440, 2, narration), (180, 2, music), (880, 0.5, effect)
            ):
                subprocess.run(
                    [
                        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i",
                        f"sine=frequency={frequency}:duration={duration}",
                        "-c:a", "pcm_s16le", str(output),
                    ],
                    check=True, capture_output=True, timeout=30,
                )

            timeline = scene_timeline.build_scene_timeline(
                plan,
                manifest,
                audio_duration=2.0,
                asset_root=directory,
                subtitle_path=str(subtitle),
                fps=8,
                video_fit_mode="cover",
                image_motion="static",
            )
            self.assertEqual(
                [item.scene_id for item in timeline.items],
                ["scene-001", "scene-002"],
            )
            self.assertEqual(timeline.alignment_source, "subtitles")
            self.assertAlmostEqual(timeline.items[0].timeline_end, 1.0, delta=0.05)
            self.assertAlmostEqual(timeline.items[1].timeline_end, 2.0, delta=0.05)

            combined = directory / "combined.mp4"
            final = directory / "final.mp4"
            with patch.object(VideoAspect, "to_resolution", return_value=(640, 360)):
                video.combine_scene_timeline(
                    combined_video_path=str(combined),
                    timeline=timeline,
                    video_aspect=VideoAspect.landscape,
                    threads=1,
                    show_scene_labels=True,
                )
            params = VideoParams(
                video_subject="Synthetic astronomy test",
                video_aspect=VideoAspect.landscape,
                video_export_profile="fast",
                subtitle_enabled=True,
                subtitle_preset="modern",
                bgm_type="custom",
                bgm_volume=0.15,
                audio_ducking_enabled=True,
                audio_normalization_enabled=True,
                audio_peak_guard_enabled=True,
                sound_effects=[
                    SoundEffectCue(
                        file_name="chime.wav", scene_id="scene-002",
                        start_seconds=0.1, volume=0.2,
                    )
                ],
            )
            metrics = {}
            with patch.object(video.utils, "storage_dir", return_value=str(directory)):
                with patch.object(VideoAspect, "to_resolution", return_value=(640, 360)):
                    video.generate_video(
                        str(combined),
                        str(narration),
                        str(subtitle),
                        str(final),
                        params,
                        bgm_file_override=str(music),
                        scene_timeline=timeline,
                        render_metrics=metrics,
                    )

            self.assertTrue(final.is_file())
            self.assertEqual(metrics["sound_effect_count"], 1)
            self.assertTrue(metrics["audio_ducking"])
            self.assertGreater(metrics["output_bytes"], 0)
            with VideoFileClip(str(final)) as rendered:
                self.assertEqual(rendered.size, [640, 360])
                self.assertIsNotNone(rendered.audio)
                self.assertAlmostEqual(rendered.duration, 2.0, delta=0.15)
            report = scene_quality.inspect_media_file(
                str(final),
                target_width=640,
                target_height=360,
                expected_duration=2.0,
                require_audio=True,
            )
            self.assertIn(report.result, {"accepted", "review"})
            self.assertEqual(report.width, 640)
            self.assertEqual(report.height, 360)


if __name__ == "__main__":
    unittest.main()
