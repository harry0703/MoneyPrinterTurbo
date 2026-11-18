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
        """The generic switch must cover the current source and future providers, without provider special cases."""
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
        # The WebUI and API share the same format allowlist; this covers case and common containers, so a future
        # change to the upload widget can't support something in the UI while the service layer rejects the file.
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
            "COM¹.mp3",
            "lpt².wav",
            "com³.flac",
            "bad:name.mp3",
            "bad?.flac",
            ".bgm-upload-user.m4a",
            "song.mp3.",
            "aux.extra.ogg",
        ):
            with self.subTest(filename=filename):
                with self.assertRaises(bgm.BgmUploadError):
                    bgm.sanitize_upload_filename(filename)

        # Only the first segment before the extension is treated as a device name by Win32; superscript digits elsewhere don't matter.
        self.assertEqual(bgm.sanitize_upload_filename("song¹.mp3"), "song¹.mp3")

    def test_sanitize_upload_filename_rejects_control_and_bidi_characters(self):
        """Control characters and bidirectional controls break filename display in logs and the UI, so they must be rejected."""
        for filename in (
            # C0 controls (existing behavior, only regression protection here)
            "song\x00.mp3",
            "song\n.mp3",
            "song\t.mp3",
            # C1 controls: U+0085 is rendered as a newline by some log viewers
            "song\x7f.mp3",
            "song\x85.mp3",
            "song\x9b.mp3",
            # Bidirectional text controls: text after U+202E is rendered reversed
            "photo\u202egnp.mp3",
            "song\u200e.mp3",
            "song\u2069.mp3",
            # Unicode line/paragraph separators
            "song\u2028.mp3",
            "song\u2029.mp3",
        ):
            with self.subTest(filename=filename):
                with self.assertRaises(bgm.BgmUploadError):
                    bgm.sanitize_upload_filename(filename)

    def test_sanitize_upload_filename_keeps_printable_unicode_names(self):
        """Only control and bidirectional control characters are blocked, without affecting normal filenames with Chinese, combining marks and so on."""
        for filename in (
            "用户音乐.mp3",
            "backing track.mp3",
            "song .mp3",  # No-break space: can be typed directly and doesn't change display order
            "étude.mp3",  # Combining acute accent
            "let’s-go.mp3",  # Curly apostrophe
            "song️.mp3",  # Variation selector (Cf, but doesn't affect display order)
            "family‍.mp3",  # ZWJ (Cf, emoji sequences depend on it)
        ):
            with self.subTest(filename=filename):
                self.assertEqual(bgm.sanitize_upload_filename(filename), filename)

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
            # The service restores the file pointer to the start, so the same UploadedFile can still be used by Streamlit
            # for previews or later reruns and doesn't become empty because of the save.
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
            # WebUI preflight may only use temp files briefly; before the user clicks generate the file must not be left
            # in the persistent BGM directory, nor may the file pointer needed by later previews change.
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

            # A failed preflight also must not leave temp audio in the persistent directory, so it's not later picked by the random BGM
            # enumeration logic and invalid files don't gradually pile up over long runs.
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

            # Validation fails before the atomic replace, so the existing user file must not be corrupted.
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
        completed = SimpleNamespace(returncode=0, stdout=b"out_time_us=100000\nprogress=end\n")
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
                builtin_listed = bgm.list_builtin_bgm_files()

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
            self.assertEqual(
                [os.path.basename(file_path) for file_path in builtin_listed],
                ["builtin.mp3", "same.mp3"],
            )
            with patch.object(bgm.utils, "song_dir", return_value=builtin_dir):
                self.assertEqual(
                    bgm.resolve_builtin_bgm_file("same.mp3"),
                    os.path.realpath(os.path.join(builtin_dir, "same.mp3")),
                )

                for invalid_path in (
                    "../same.mp3",
                    str(Path(uploaded_dir, "user.flac")),
                ):
                    with self.subTest(invalid_path=invalid_path):
                        with self.assertRaises(ValueError):
                            bgm.resolve_builtin_bgm_file(invalid_path)

    def test_resolve_rejects_staged_upload_left_by_an_interrupted_write(self):
        """Staging intermediate files left by an interrupted write must not resolve to usable background music.

        ``_list_bgm_files`` already excludes these not-yet-validated intermediate files from random BGM,
        but the ``bgm_file`` passed by the API and CLI goes through ``resolve_bgm_file``:
        the same file must reach the same conclusion at both entry points, otherwise clients could make a task reference
        an incomplete, undecodable intermediate file.
        """

        with tempfile.TemporaryDirectory() as uploaded_dir:
            staged_name = f"{bgm._INTERNAL_UPLOAD_PREFIX}pending.m4a"
            Path(uploaded_dir, staged_name).write_bytes(b"partial")
            Path(uploaded_dir, "user.flac").write_bytes(b"uploaded")

            with patch.object(bgm, "uploaded_bgm_dir", return_value=uploaded_dir):
                for candidate in (
                    staged_name,
                    os.path.join(uploaded_dir, staged_name),
                    # Windows and macOS file systems are case-insensitive, and the staging prefix check
                    # must be too, otherwise the same file would come back to life through different casing.
                    staged_name.upper(),
                ):
                    with self.subTest(candidate=candidate):
                        with self.assertRaises(ValueError):
                            bgm.resolve_bgm_file(candidate)

                # Ordinary uploaded files still resolve normally (the reverse control).
                self.assertEqual(
                    bgm.resolve_bgm_file("user.flac"),
                    os.path.realpath(os.path.join(uploaded_dir, "user.flac")),
                )


if __name__ == "__main__":
    unittest.main()
