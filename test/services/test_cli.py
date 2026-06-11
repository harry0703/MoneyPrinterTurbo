import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import cli


class TestCli(unittest.TestCase):
    def test_build_video_params_with_local_materials(self):
        args = cli.parse_args(
            [
                "--video-subject",
                "测试主题",
                "--video-source",
                "local",
                "--video-materials",
                "a.mp4, ,b.jpg,",
                "--video-terms",
                "foo, bar",
            ]
        )

        params = cli.build_video_params(args)
        materials = params.video_materials

        self.assertEqual(params.video_subject, "测试主题")
        self.assertEqual(params.video_source, "local")
        self.assertEqual([m.url for m in materials], ["a.mp4", "b.jpg"])
        self.assertTrue(all(m.provider == "local" for m in materials))
        self.assertEqual(params.video_terms, ["foo", "bar"])

    def test_run_cli_dispatches_task_start(self):
        with patch.object(cli.tm, "start", return_value={"script": "ok"}) as start, patch.object(
            cli.utils, "get_uuid", return_value="task-123"
        ), patch("builtins.print") as print_mock:
            code = cli.run_cli(["--video-subject", "命令行测试", "--stop-at", "script"])

        self.assertEqual(code, 0)
        self.assertTrue(start.called)
        kwargs = start.call_args.kwargs
        self.assertEqual(kwargs["task_id"], "task-123")
        self.assertEqual(kwargs["stop_at"], "script")
        self.assertEqual(kwargs["params"].video_subject, "命令行测试")
        print_mock.assert_called_once()

    def test_run_cli_returns_error_when_task_fails(self):
        with patch.object(cli.tm, "start", return_value=None), patch.object(
            cli.utils, "get_uuid", return_value="task-456"
        ), patch.object(cli.logger, "error") as log_error:
            code = cli.run_cli(["--video-subject", "失败场景"])

        self.assertEqual(code, 1)
        log_error.assert_called_once()

    def test_subtitle_enabled_by_default(self):
        args = cli.parse_args(["--video-subject", "test"])
        params = cli.build_video_params(args)
        self.assertTrue(params.subtitle_enabled)

    def test_subtitle_disabled_with_no_flag(self):
        args = cli.parse_args(["--video-subject", "test", "--no-subtitle-enabled"])
        params = cli.build_video_params(args)
        self.assertFalse(params.subtitle_enabled)

    def test_coverr_video_source_accepted(self):
        args = cli.parse_args(["--video-subject", "test", "--video-source", "coverr"])
        params = cli.build_video_params(args)
        self.assertEqual(params.video_source, "coverr")

    def test_local_material_filename_resolved_to_absolute_path(self):
        """After preprocess_video, material.url should be an absolute path, not a bare filename."""
        import os
        import tempfile
        from app.utils import utils
        from app.services import video as vd
        from app.models.schema import MaterialInfo

        local_videos_dir = utils.storage_dir("local_videos", create=True)
        # Create a minimal valid video file for testing
        test_filename = "_cli_test_resolve.mp4"
        test_filepath = os.path.join(local_videos_dir, test_filename)
        # We need a real video file; use a tiny one via moviepy
        try:
            from moviepy import ColorClip
            clip = ColorClip(size=(640, 640), color=(0, 0, 0), duration=1)
            clip.write_videofile(test_filepath, fps=1, logger=None)
            clip.close()
        except Exception:
            self.skipTest("moviepy not available for creating test video")

        try:
            materials = [MaterialInfo(provider="local", url=test_filename, duration=0)]
            result = vd.preprocess_video(materials=materials, clip_duration=4)
            self.assertTrue(len(result) > 0, "preprocess_video should return valid materials")
            self.assertTrue(
                os.path.isabs(result[0].url),
                f"material url should be absolute path, got: {result[0].url}",
            )
            self.assertEqual(result[0].url, test_filepath)
        finally:
            if os.path.exists(test_filepath):
                os.remove(test_filepath)


if __name__ == "__main__":
    unittest.main()
