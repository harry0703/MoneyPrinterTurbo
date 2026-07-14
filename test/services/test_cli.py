import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import cli


class TestCli(unittest.TestCase):
    def test_default_voice_is_valid_edge_tts_voice(self):
        args = cli.parse_args(["--video-subject", "测试主题"])
        params = cli.build_video_params(args)

        self.assertEqual(params.voice_name, "zh-CN-XiaoxiaoNeural-Female")

    def test_complete_script_can_replace_video_subject(self):
        args = cli.parse_args(["--video-script", "完整的视频文案"])
        params = cli.build_video_params(args)

        self.assertEqual(params.video_subject, "")
        self.assertEqual(params.video_script, "完整的视频文案")

    def test_subject_or_script_is_required(self):
        with self.assertRaises(SystemExit) as cm:
            cli.parse_args([])

        self.assertEqual(cm.exception.code, 2)

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
        with patch("app.services.task.start", return_value={"script": "ok"}) as start, patch(
            "app.utils.utils.get_uuid", return_value="task-123"
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
        with patch("app.services.task.start", return_value=None), patch(
            "app.utils.utils.get_uuid", return_value="task-456"
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

    def test_build_video_params_with_script_video_and_audio_options(self):
        args = cli.parse_args(
            [
                "--video-subject",
                "test",
                "--video-language",
                "en",
                "--paragraph-number",
                "3",
                "--video-script-prompt",
                "use a lighter tone",
                "--custom-system-prompt",
                "write concise short-form scripts",
                "--video-concat-mode",
                "sequential",
                "--video-transition-mode",
                "fade-in",
                "--video-clip-duration",
                "4",
                "--match-materials-to-script",
                "--voice-volume",
                "1.2",
                "--voice-rate",
                "1.1",
                "--bgm-type",
                "custom",
                "--bgm-file",
                "output001.mp3",
                "--bgm-volume",
                "0.3",
                "--n-threads",
                "4",
            ]
        )

        params = cli.build_video_params(args)

        self.assertEqual(params.video_language, "en")
        self.assertEqual(params.paragraph_number, 3)
        self.assertEqual(params.video_script_prompt, "use a lighter tone")
        self.assertEqual(params.custom_system_prompt, "write concise short-form scripts")
        self.assertEqual(params.video_concat_mode, "sequential")
        self.assertEqual(params.video_transition_mode, "FadeIn")
        self.assertEqual(params.video_clip_duration, 4)
        self.assertTrue(params.match_materials_to_script)
        self.assertEqual(params.voice_volume, 1.2)
        self.assertEqual(params.voice_rate, 1.1)
        self.assertEqual(params.bgm_type, "custom")
        self.assertEqual(params.bgm_file, "output001.mp3")
        self.assertEqual(params.bgm_volume, 0.3)
        self.assertEqual(params.n_threads, 4)

    def test_custom_audio_file_maps_to_video_params(self):
        args = cli.parse_args(
            [
                "--video-subject",
                "test",
                "--custom-audio-file",
                "voiceover.mp3",
            ]
        )
        params = cli.build_video_params(args)

        self.assertEqual(params.custom_audio_file, "voiceover.mp3")

    def test_build_video_params_with_subtitle_style_options(self):
        args = cli.parse_args(
            [
                "--video-subject",
                "test",
                "--font-name",
                "MicrosoftYaHeiBold.ttc",
                "--subtitle-position",
                "custom",
                "--custom-position",
                "42.5",
                "--text-fore-color",
                "#AABBCC",
                "--font-size",
                "72",
                "--stroke-color",
                "#112233",
                "--stroke-width",
                "2.5",
                "--subtitle-background-color",
                "#000001",
                "--rounded-subtitle-background",
            ]
        )

        params = cli.build_video_params(args)

        self.assertEqual(params.font_name, "MicrosoftYaHeiBold.ttc")
        self.assertEqual(params.subtitle_position, "custom")
        self.assertEqual(params.custom_position, 42.5)
        self.assertEqual(params.text_fore_color, "#AABBCC")
        self.assertEqual(params.font_size, 72)
        self.assertEqual(params.stroke_color, "#112233")
        self.assertEqual(params.stroke_width, 2.5)
        self.assertEqual(params.text_background_color, "#000001")
        self.assertTrue(params.rounded_subtitle_background)

    def test_disabled_subtitle_background_rejects_rounding(self):
        with self.assertRaises(SystemExit) as cm:
            cli.parse_args(
                [
                    "--video-subject",
                    "test",
                    "--no-subtitle-background-enabled",
                    "--rounded-subtitle-background",
                ]
            )

        self.assertEqual(cm.exception.code, 2)

    def test_bgm_type_none_maps_to_disabled_background_music(self):
        args = cli.parse_args(["--video-subject", "test", "--bgm-type", "none"])
        params = cli.build_video_params(args)
        self.assertEqual(params.bgm_type, "")

    def test_sonilo_prompt_implies_sonilo_bgm_mode(self):
        args = cli.parse_args(
            [
                "--video-subject",
                "test",
                "--sonilo-bgm-prompt",
                "warm acoustic",
            ]
        )
        params = cli.build_video_params(args)
        self.assertEqual(params.bgm_type, "sonilo")
        self.assertEqual(params.sonilo_bgm_prompt, "warm acoustic")

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


    def test_local_source_requires_video_materials(self):
        with self.assertRaises(SystemExit) as cm:
            cli.parse_args(["--video-subject", "test", "--video-source", "local"])
        self.assertNotEqual(cm.exception.code, 0)

    def test_local_source_does_not_require_materials_before_material_stage(self):
        for stop_at in ("script", "audio", "subtitle"):
            with self.subTest(stop_at=stop_at):
                args = cli.parse_args(
                    [
                        "--video-subject",
                        "test",
                        "--video-source",
                        "local",
                        "--stop-at",
                        stop_at,
                    ]
                )
                self.assertEqual(args.stop_at, stop_at)

    def test_local_source_stop_at_terms_rejected(self):
        with self.assertRaises(SystemExit) as cm:
            cli.parse_args([
                "--video-subject", "test",
                "--video-source", "local",
                "--video-materials", "a.mp4",
                "--stop-at", "terms",
            ])
        self.assertNotEqual(cm.exception.code, 0)

    def test_video_materials_rejected_for_online_source(self):
        with self.assertRaises(SystemExit) as cm:
            cli.parse_args(
                [
                    "--video-subject",
                    "test",
                    "--video-source",
                    "pexels",
                    "--video-materials",
                    "a.mp4",
                ]
            )

        self.assertEqual(cm.exception.code, 2)

    def test_positive_volume_custom_bgm_requires_file_before_task_start(self):
        """启用自定义 BGM 时仍必须在任务启动前报告缺少文件。"""
        with (
            patch("app.services.task.start") as start,
            patch.object(cli.logger, "error") as log_error,
        ):
            code = cli.run_cli(
                [
                    "--video-subject",
                    "test",
                    "--bgm-type",
                    "custom",
                    "--stop-at",
                    "script",
                ]
            )

        self.assertEqual(code, 2)
        start.assert_not_called()
        self.assertIn(
            "--bgm-file is required",
            str(log_error.call_args),
        )

    def test_bgm_file_implies_custom_mode(self):
        args = cli.parse_args(
            ["--video-subject", "test", "--bgm-file", "output001.mp3"]
        )
        self.assertEqual(args.bgm_type, "custom")

    def test_zero_volume_custom_bgm_skips_file_requirement_and_resolution(self):
        """0 音量应忽略缺失或无效文件，与 WebUI 和视频服务保持一致。"""
        file_arguments = [[], ["--bgm-file", "missing-background.mp3"]]
        for extra_arguments in file_arguments:
            with self.subTest(extra_arguments=extra_arguments):
                args = cli.parse_args(
                    [
                        "--video-subject",
                        "test",
                        "--bgm-type",
                        "custom",
                        "--bgm-volume",
                        "0",
                        *extra_arguments,
                    ]
                )
                params = cli.build_video_params(args)
                with patch(
                    "app.services.bgm.resolve_bgm_file",
                    side_effect=AssertionError(
                        "zero-volume BGM must not resolve a file"
                    ),
                ) as resolver:
                    cli.prepare_cli_files(params, stop_at="script")

                resolver.assert_not_called()
                self.assertEqual(params.bgm_file, "")

    def test_custom_bgm_reuses_service_formats_and_managed_path_resolution(self):
        """CLI 必须跟随 BGM 服务的格式白名单，不能继续单独限制为 MP3。"""
        from app.services import bgm as bgm_service

        for extension in bgm_service.SUPPORTED_BGM_EXTENSIONS:
            with self.subTest(extension=extension):
                filename = f"uploaded{extension}"
                resolved_path = f"/managed/storage/bgm/{filename}"
                args = cli.parse_args(
                    [
                        "--video-subject",
                        "test",
                        "--bgm-type",
                        "custom",
                        "--bgm-file",
                        filename,
                    ]
                )
                params = cli.build_video_params(args)
                with patch.object(
                    bgm_service,
                    "resolve_bgm_file",
                    return_value=resolved_path,
                ) as resolver:
                    cli.prepare_cli_files(params, stop_at="script")

                resolver.assert_called_once_with(filename)
                self.assertEqual(params.bgm_file, resolved_path)

    def test_custom_bgm_reports_service_resolution_failure_before_task_start(self):
        """非法格式或越界路径应转换为包含统一格式范围的 CLI 错误。"""
        from app.services import bgm as bgm_service

        args = cli.parse_args(
            [
                "--video-subject",
                "test",
                "--bgm-type",
                "custom",
                "--bgm-file",
                "unsafe.exe",
            ]
        )
        params = cli.build_video_params(args)
        with (
            patch.object(
                bgm_service,
                "resolve_bgm_file",
                side_effect=ValueError("unsupported background music path"),
            ),
            self.assertRaisesRegex(ValueError, "storage/bgm or resource/songs"),
        ):
            cli.prepare_cli_files(params, stop_at="script")

    def test_invalid_aspect_and_non_finite_numbers_are_argument_errors(self):
        invalid_argvs = [
            ["--video-subject", "test", "--video-aspect", "invalid"],
            ["--video-subject", "test", "--custom-position", "nan"],
            ["--video-subject", "test", "--voice-rate", "inf"],
        ]
        for argv in invalid_argvs:
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as cm:
                cli.parse_args(argv)
            self.assertEqual(cm.exception.code, 2)

    def test_custom_position_requires_custom_subtitle_position(self):
        with self.assertRaises(SystemExit) as cm:
            cli.parse_args(
                ["--video-subject", "test", "--custom-position", "50"]
            )

        self.assertEqual(cm.exception.code, 2)

    def test_task_id_must_be_uuid(self):
        task_id = str(uuid4())
        args = cli.parse_args(
            ["--video-subject", "test", "--task-id", task_id]
        )
        self.assertEqual(args.task_id, task_id)

        with self.assertRaises(SystemExit) as cm:
            cli.parse_args(
                ["--video-subject", "test", "--task-id", "../../escape"]
            )
        self.assertEqual(cm.exception.code, 2)

    def test_prepare_cli_files_accepts_relative_and_absolute_materials(self):
        with (
            tempfile.TemporaryDirectory() as source_dir,
            tempfile.TemporaryDirectory() as managed_dir,
        ):
            relative_file = Path(source_dir) / "relative.mp4"
            absolute_file = Path(source_dir) / "absolute.jpg"
            relative_file.write_bytes(b"relative-video")
            absolute_file.write_bytes(b"absolute-image")
            old_cwd = os.getcwd()
            try:
                os.chdir(source_dir)
                args = cli.parse_args(
                    [
                        "--video-subject",
                        "test",
                        "--video-source",
                        "local",
                        "--video-materials",
                        f"relative.mp4,{absolute_file}",
                    ]
                )
                params = cli.build_video_params(args)
                with patch("app.utils.utils.storage_dir", return_value=managed_dir):
                    cli.prepare_cli_files(params, stop_at="video")
            finally:
                os.chdir(old_cwd)

            prepared_paths = [Path(item.url) for item in params.video_materials]
            self.assertTrue(all(path.parent == Path(managed_dir) for path in prepared_paths))
            self.assertEqual(
                {path.read_bytes() for path in prepared_paths},
                {b"relative-video", b"absolute-image"},
            )

    def test_prepare_cli_files_rejects_missing_material_before_task_start(self):
        args = cli.parse_args(
            [
                "--video-subject",
                "test",
                "--video-source",
                "local",
                "--video-materials",
                "missing.mp4",
            ]
        )
        params = cli.build_video_params(args)

        with tempfile.TemporaryDirectory() as managed_dir, patch(
            "app.utils.utils.storage_dir", return_value=managed_dir
        ):
            with self.assertRaisesRegex(ValueError, "does not exist"):
                cli.prepare_cli_files(params, stop_at="video")

    def test_run_cli_rejects_missing_material_before_starting_task(self):
        with patch("app.services.task.start") as start:
            code = cli.run_cli(
                [
                    "--video-subject",
                    "test",
                    "--video-source",
                    "local",
                    "--video-materials",
                    "missing.mp4",
                ]
            )

        self.assertEqual(code, 2)
        start.assert_not_called()

    def test_prepare_cli_files_resolves_relative_custom_audio(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_file = Path(temp_dir) / "voiceover.mp3"
            audio_file.write_bytes(b"audio")
            old_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)
                args = cli.parse_args(
                    [
                        "--video-subject",
                        "test",
                        "--custom-audio-file",
                        "voiceover.mp3",
                        "--stop-at",
                        "audio",
                    ]
                )
                params = cli.build_video_params(args)
                cli.prepare_cli_files(params, stop_at="audio")
            finally:
                os.chdir(old_cwd)

            self.assertEqual(params.custom_audio_file, str(audio_file.resolve()))

    def test_help_documents_defaults_paths_stages_and_exit_codes(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as cm:
            cli.parse_args(["--help"])

        self.assertEqual(cm.exception.code, 0)
        help_text = output.getvalue()
        self.assertIn("zh-CN-XiaoxiaoNeural-Female", help_text)
        self.assertIn("current working directory", help_text)
        self.assertIn("Pipeline stages:", help_text)
        self.assertIn("exit with 2", help_text)

    def test_help_does_not_initialize_application_or_write_logs(self):
        """帮助命令应独立于业务配置加载，便于用户查看和脚本采集。"""
        project_root = Path(__file__).parent.parent.parent
        result = subprocess.run(
            [sys.executable, str(project_root / "cli.py"), "--help"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("Generate MoneyPrinterTurbo videos", result.stdout)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
