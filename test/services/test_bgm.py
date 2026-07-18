import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from fastapi import UploadFile

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import bgm
from app.controllers.v1 import video as video_controller
from app.models.exception import HttpException


class _FakeRequest:
    def __init__(self):
        self.headers = {"x-task-id": "bgm-upload-test"}


class _UnseekableUpload(io.BytesIO):
    def seek(self, *args, **kwargs):
        raise OSError("stream is not seekable")


class _TextUpload(io.BytesIO):
    def read(self, *args, **kwargs):
        return "not binary"


class TestBackgroundMusicService(unittest.TestCase):
    def test_should_use_bgm_is_provider_independent(self):
        """通用开关必须覆盖当前来源和未来提供商，不能再写提供商特判。"""
        test_cases = [
            ("random", 0.2, True),
            ("custom", 0.2, True),
            ("sonilo", 0.2, True),
            ("elevenlabs", 0.2, True),
            ("future_provider", 0.2, True),
            ("random", 0.0, False),
            ("custom", -0.1, False),
            ("sonilo", None, False),
            ("future_provider", float("nan"), False),
            ("future_provider", "invalid", False),
            ("", 0.2, False),
            (None, 0.2, False),
        ]
        for bgm_type, bgm_volume, expected in test_cases:
            with self.subTest(bgm_type=bgm_type, bgm_volume=bgm_volume):
                self.assertEqual(
                    bgm.should_use_bgm(bgm_type, bgm_volume), expected
                )

    def test_sanitize_upload_filename_strips_directory_components(self):
        self.assertEqual(
            bgm.sanitize_upload_filename("../../用户音乐.mp3"), "用户音乐.mp3"
        )
        self.assertEqual(
            bgm.sanitize_upload_filename("windows\\path\\song.MP3"), "song.MP3"
        )

    def test_sanitize_upload_filename_accepts_common_audio_formats(self):
        # WebUI 与 API 共用同一格式白名单；这里覆盖大小写和常见容器，避免未来
        # 修改上传控件时只支持界面展示、服务层却拒绝文件。
        for extension in bgm.SUPPORTED_BGM_EXTENSIONS:
            filename = f"background{extension.upper()}"
            with self.subTest(filename=filename):
                self.assertEqual(bgm.sanitize_upload_filename(filename), filename)

    def test_sanitize_upload_filename_rejects_invalid_names_and_extensions(self):
        for filename in (
            "",
            "   ",
            ".",
            "..",
            "song.mp4",
            "song.mp3\x00",
            "CON.mp3",
            "lpt1.wav",
            "bad:name.mp3",
            "bad?.flac",
            ".bgm-upload-user.m4a",
            "song.mp3.",
            "aux.extra.ogg",
        ):
            with self.subTest(filename=filename):
                with self.assertRaises(bgm.BgmUploadError):
                    bgm.sanitize_upload_filename(filename)

    def test_save_bgm_upload_uses_atomic_storage_directory_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = io.BytesIO(b"valid-mp3-placeholder")
            with (
                patch.object(bgm, "uploaded_bgm_dir", return_value=temp_dir),
                patch.object(bgm, "_validate_audio", return_value=None),
                patch.object(
                    bgm,
                    "uuid4",
                    return_value=UUID("4fca18fc-e734-4f3a-a824-777a40d45c8c"),
                ),
            ):
                saved_name = bgm.save_bgm_upload("music.mp3", source)

            self.assertEqual(saved_name, "4fca18fce7344f3aa824777a40d45c8c.mp3")
            self.assertEqual(
                Path(temp_dir, saved_name).read_bytes(), b"valid-mp3-placeholder"
            )
            self.assertEqual(
                [name for name in os.listdir(temp_dir) if name.startswith(".bgm-upload-")],
                [],
            )
            # 服务会把文件指针恢复到开头，同一个 UploadedFile 仍可供 Streamlit
            # 试听或后续 rerun 使用，不会因为保存操作变成空文件。
            self.assertEqual(source.tell(), 0)

    def test_validate_bgm_upload_checks_audio_without_persisting_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = io.BytesIO(b"valid-audio-placeholder")
            with (
                patch.object(bgm, "uploaded_bgm_dir", return_value=temp_dir),
                patch.object(bgm, "_validate_audio", return_value=None),
            ):
                validated_name = bgm.validate_bgm_upload("preview.m4a", source)

            self.assertEqual(validated_name, "preview.m4a")
            # WebUI 预检只允许短暂使用临时文件，用户尚未点击生成时不能把文件
            # 留在持久化 BGM 目录，也不能改变后续试听所需的文件指针。
            self.assertEqual(os.listdir(temp_dir), [])

    def test_staging_rejects_empty_unseekable_and_non_binary_uploads(self):
        invalid_sources = (
            (io.BytesIO(b""), "background music file is empty"),
            (_UnseekableUpload(b"audio"), "not seekable"),
            (_TextUpload(b"audio"), "must be binary"),
        )
        for source, expected_error in invalid_sources:
            with self.subTest(expected_error=expected_error):
                with tempfile.TemporaryDirectory() as temp_dir:
                    with patch.object(
                        bgm, "uploaded_bgm_dir", return_value=temp_dir
                    ):
                        with self.assertRaisesRegex(
                            bgm.BgmUploadError, expected_error
                        ):
                            bgm.save_bgm_upload("invalid.mp3", source)
                    self.assertEqual(os.listdir(temp_dir), [])
            self.assertEqual(source.tell(), 0)

    def test_validate_bgm_upload_rejects_invalid_audio_and_cleans_temp_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(bgm, "uploaded_bgm_dir", return_value=temp_dir),
                patch.object(
                    bgm,
                    "_validate_audio",
                    side_effect=bgm.BgmUploadError("invalid audio"),
                ),
            ):
                with self.assertRaises(bgm.BgmUploadError):
                    bgm.validate_bgm_upload("invalid.m4a", io.BytesIO(b"invalid"))

            # 失败的预检同样不能在持久化目录留下临时音频，避免随后被随机 BGM
            # 枚举逻辑选中，也避免长期运行时逐步堆积无效文件。
            self.assertEqual(os.listdir(temp_dir), [])

    def test_save_bgm_upload_rejects_oversized_file_and_cleans_temp_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(bgm, "uploaded_bgm_dir", return_value=temp_dir),
                patch.object(bgm, "MAX_BGM_UPLOAD_BYTES", 4),
            ):
                with self.assertRaises(bgm.BgmUploadError):
                    bgm.save_bgm_upload("large.mp3", io.BytesIO(b"12345"))

            self.assertEqual(os.listdir(temp_dir), [])

    def test_save_bgm_upload_rejects_invalid_audio_before_replacing_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir, "music.mp3")
            target.write_bytes(b"existing-valid-file")
            with (
                patch.object(bgm, "uploaded_bgm_dir", return_value=temp_dir),
                patch.object(
                    bgm,
                    "_validate_audio",
                    side_effect=bgm.BgmUploadError("invalid audio"),
                ),
            ):
                with self.assertRaises(bgm.BgmUploadError):
                    bgm.save_bgm_upload("music.mp3", io.BytesIO(b"broken-file"))

            # 校验失败发生在原子替换之前，已有用户文件不能被损坏。
            self.assertEqual(target.read_bytes(), b"existing-valid-file")
            self.assertEqual(os.listdir(temp_dir), ["music.mp3"])

    def test_same_original_filename_creates_immutable_storage_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            generated_uuids = [
                UUID("11111111-1111-4111-8111-111111111111"),
                UUID("22222222-2222-4222-8222-222222222222"),
            ]
            with (
                patch.object(bgm, "uploaded_bgm_dir", return_value=temp_dir),
                patch.object(bgm, "_validate_audio", return_value=None),
                patch.object(bgm, "uuid4", side_effect=generated_uuids),
            ):
                first_name = bgm.save_bgm_upload(
                    "shared.mp3", io.BytesIO(b"first-user-audio")
                )
                second_name = bgm.save_bgm_upload(
                    "shared.mp3", io.BytesIO(b"second-user-audio")
                )

            self.assertNotEqual(first_name, second_name)
            self.assertEqual(Path(temp_dir, first_name).read_bytes(), b"first-user-audio")
            self.assertEqual(
                Path(temp_dir, second_name).read_bytes(), b"second-user-audio"
            )

    def test_audio_validation_uses_only_configured_ffmpeg(self):
        completed = SimpleNamespace(returncode=0)
        with (
            patch.object(
                bgm.utils,
                "get_ffmpeg_binary",
                return_value="/portable/imageio/ffmpeg",
            ),
            patch.object(bgm.subprocess, "run", return_value=completed) as run,
        ):
            bgm._validate_audio("/tmp/background.m4a")

        command = run.call_args.args[0]
        self.assertEqual(command[0], "/portable/imageio/ffmpeg")
        self.assertNotIn("ffprobe", " ".join(command).lower())
        self.assertIn("0:a:0", command)

    def test_audio_validation_distinguishes_service_failure_from_invalid_audio(self):
        with patch.object(
            bgm.subprocess,
            "run",
            side_effect=OSError("ffmpeg missing"),
        ):
            with self.assertRaises(bgm.BgmServiceError):
                bgm._validate_audio("/tmp/background.mp3")

        with patch.object(
            bgm.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=1),
        ):
            with self.assertRaises(bgm.BgmUploadError):
                bgm._validate_audio("/tmp/background.mp3")

        with patch.object(
            bgm.subprocess,
            "run",
            side_effect=bgm.subprocess.TimeoutExpired("ffmpeg", 30),
        ):
            with self.assertRaises(bgm.BgmServiceError):
                bgm._validate_audio("/tmp/background.mp3")

    def test_save_normalizes_extension_and_maps_storage_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(bgm, "uploaded_bgm_dir", return_value=temp_dir),
                patch.object(bgm, "_validate_audio", return_value=None),
                patch.object(
                    bgm,
                    "uuid4",
                    return_value=UUID("4fca18fc-e734-4f3a-a824-777a40d45c8c"),
                ),
            ):
                saved_name = bgm.save_bgm_upload(
                    "UPPER.FLAC", io.BytesIO(b"valid-audio")
                )
            self.assertTrue(saved_name.endswith(".flac"))

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(bgm, "uploaded_bgm_dir", return_value=temp_dir),
                patch.object(bgm, "_validate_audio", return_value=None),
                patch.object(bgm.os, "replace", side_effect=OSError("disk full")),
            ):
                with self.assertRaises(bgm.BgmServiceError):
                    bgm.save_bgm_upload("music.mp3", io.BytesIO(b"valid-audio"))
            self.assertEqual(os.listdir(temp_dir), [])

    def test_upload_controller_returns_uuid_and_maps_errors(self):
        request = _FakeRequest()
        upload = UploadFile(filename="music.mp3", file=io.BytesIO(b"audio"))
        with patch.object(
            bgm,
            "save_bgm_upload",
            return_value="4fca18fce7344f3aa824777a40d45c8c.mp3",
        ):
            response = video_controller.upload_bgm_file(request, upload)
        self.assertEqual(response["status"], 200)
        self.assertEqual(
            response["data"]["file"],
            "4fca18fce7344f3aa824777a40d45c8c.mp3",
        )

        for service_error, expected_status in (
            (bgm.BgmUploadError("invalid audio"), 400),
            (bgm.BgmServiceError("FFmpeg unavailable"), 500),
        ):
            with self.subTest(expected_status=expected_status):
                with patch.object(
                    bgm, "save_bgm_upload", side_effect=service_error
                ):
                    with self.assertRaises(HttpException) as context:
                        video_controller.upload_bgm_file(request, upload)
                self.assertEqual(context.exception.status_code, expected_status)

    def test_resolve_and_list_prefer_uploaded_file_with_same_name(self):
        with (
            tempfile.TemporaryDirectory() as builtin_dir,
            tempfile.TemporaryDirectory() as uploaded_dir,
        ):
            Path(builtin_dir, "same.mp3").write_bytes(b"builtin")
            Path(builtin_dir, "builtin.mp3").write_bytes(b"builtin")
            Path(uploaded_dir, "same.mp3").write_bytes(b"uploaded")
            Path(uploaded_dir, "user.flac").write_bytes(b"uploaded")
            Path(uploaded_dir, ".bgm-upload-pending.m4a").write_bytes(b"pending")

            with (
                patch.object(bgm, "uploaded_bgm_dir", return_value=uploaded_dir),
                patch.object(bgm.utils, "song_dir", return_value=builtin_dir),
            ):
                resolved = bgm.resolve_bgm_file("same.mp3")
                listed = bgm.list_bgm_files()

            self.assertEqual(
                resolved, os.path.realpath(os.path.join(uploaded_dir, "same.mp3"))
            )
            self.assertEqual(
                [os.path.basename(file_path) for file_path in listed],
                ["builtin.mp3", "same.mp3", "user.flac"],
            )
            same_file = next(path for path in listed if path.endswith("same.mp3"))
            self.assertEqual(
                same_file, os.path.realpath(os.path.join(uploaded_dir, "same.mp3"))
            )


if __name__ == "__main__":
    unittest.main()
