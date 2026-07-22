import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models.schema import VideoAspect, VideoParams
from app.services import hyperframes


class TestHyperframesService(unittest.TestCase):
    def test_is_requested_defaults_to_false(self):
        with patch.object(hyperframes.config, "app", {"video_renderer": "moviepy"}):
            self.assertFalse(hyperframes.is_requested())

        with patch.object(hyperframes.config, "app", {"video_renderer": "hyperframes"}):
            self.assertTrue(hyperframes.is_requested())

        with patch.object(hyperframes.config, "app", {}):
            self.assertFalse(hyperframes.is_requested())

    def test_parse_srt_cues(self):
        with tempfile.TemporaryDirectory() as tmp:
            srt_path = Path(tmp) / "subtitle.srt"
            srt_path.write_text(
                "1\n"
                "00:00:00,000 --> 00:00:01,500\n"
                "Hello world\n"
                "\n"
                "2\n"
                "00:00:01,500 --> 00:00:03,000\n"
                "Second line\n",
                encoding="utf-8",
            )
            cues = hyperframes.parse_srt_cues(str(srt_path))

        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0]["text"], "Hello world")
        self.assertAlmostEqual(cues[0]["start"], 0.0)
        self.assertAlmostEqual(cues[0]["duration"], 1.5)
        self.assertEqual(cues[1]["text"], "Second line")

    def test_scaffold_project_writes_expected_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_id = "hf-scaffold-task"
            task_dir = Path(tmp) / "tasks" / task_id
            task_dir.mkdir(parents=True)

            video_path = task_dir / "combined-1.mp4"
            audio_path = task_dir / "audio.mp3"
            subtitle_path = task_dir / "subtitle.srt"
            video_path.write_bytes(b"fake-video")
            audio_path.write_bytes(b"fake-audio")
            subtitle_path.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHi\n",
                encoding="utf-8",
            )

            params = VideoParams(
                video_subject="Demo",
                video_aspect=VideoAspect.portrait.value,
                subtitle_enabled=True,
                font_size=48,
                text_fore_color="#FFFFFF",
            )

            with (
                patch.object(hyperframes, "ensure_ready"),
                patch.object(hyperframes.utils, "task_dir", return_value=str(task_dir)),
                patch.object(
                    hyperframes.utils,
                    "font_dir",
                    return_value=str(Path(tmp) / "missing-fonts"),
                ),
            ):
                project_path = hyperframes.scaffold_project(
                    task_id=task_id,
                    index=1,
                    params=params,
                    video_path=str(video_path),
                    audio_path=str(audio_path),
                    subtitle_path=str(subtitle_path),
                    duration=2.5,
                    bgm_path="",
                )

            project = Path(project_path)
            self.assertTrue((project / "index.html").is_file())
            self.assertTrue((project / "hyperframes.json").is_file())
            self.assertTrue((project / "meta.json").is_file())
            self.assertTrue((project / "assets" / "video.mp4").exists())
            self.assertTrue((project / "assets" / "narration.mp3").exists())
            self.assertTrue((project / "README.md").is_file())

            html = (project / "index.html").read_text(encoding="utf-8")
            self.assertIn('data-composition-id="moneyprinter-video"', html)
            self.assertIn("assets/video.mp4", html)
            self.assertIn("Hi", html)
            self.assertIn("1080", html)
            self.assertIn("1920", html)

    def test_generate_final_videos_uses_hyperframes_when_requested(self):
        from app.services import task as tm

        params = VideoParams(video_subject="test", video_count=1)

        with (
            patch.object(tm.hyperframes, "is_requested", return_value=True),
            patch.object(tm.video, "combine_videos"),
            patch.object(
                tm.hyperframes,
                "scaffold_project",
                return_value="/tmp/hyperframes-1",
            ) as scaffold,
            patch.object(tm.hyperframes, "render_project") as render,
            patch.object(tm.video, "generate_video") as generate_video,
            patch.object(tm.sm.state, "update_task"),
        ):
            finals, combined, warnings, projects = tm.generate_final_videos(
                task_id="hf-task",
                params=params,
                downloaded_videos=["material.mp4"],
                audio_file="audio.mp3",
                subtitle_path="subtitle.srt",
                audio_duration=5,
            )

        self.assertEqual(len(finals), 1)
        self.assertEqual(len(combined), 1)
        self.assertEqual(warnings, [])
        self.assertEqual(projects, ["/tmp/hyperframes-1"])
        scaffold.assert_called_once()
        render.assert_called_once()
        generate_video.assert_not_called()

    def test_generate_final_videos_moviepy_default_skips_hyperframes(self):
        from app.services import task as tm

        params = VideoParams(video_subject="test", video_count=1)

        with (
            patch.object(tm.hyperframes, "is_requested", return_value=False),
            patch.object(tm.video, "combine_videos"),
            patch.object(tm.video, "generate_video", return_value=True),
            patch.object(tm.hyperframes, "scaffold_project") as scaffold,
            patch.object(tm.sm.state, "update_task"),
        ):
            finals, combined, warnings, projects = tm.generate_final_videos(
                task_id="moviepy-task",
                params=params,
                downloaded_videos=["material.mp4"],
                audio_file="audio.mp3",
                subtitle_path="",
                audio_duration=5,
            )

        self.assertEqual(len(finals), 1)
        self.assertEqual(len(combined), 1)
        self.assertEqual(warnings, [])
        self.assertEqual(projects, [])
        scaffold.assert_not_called()

    def test_ensure_ready_raises_when_missing_deps(self):
        with (
            patch.object(hyperframes, "is_requested", return_value=True),
            patch.object(hyperframes, "_node_available", return_value=False),
            patch.object(hyperframes, "_ffmpeg_available", return_value=True),
            patch.object(hyperframes, "_template_available", return_value=True),
        ):
            with self.assertRaises(hyperframes.HyperframesNotReadyError):
                hyperframes.ensure_ready()


if __name__ == "__main__":
    unittest.main()
