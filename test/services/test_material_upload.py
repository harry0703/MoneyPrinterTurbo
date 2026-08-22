import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from PIL import Image, UnidentifiedImageError

from app.services import material_upload


class _UnseekableUpload(io.BytesIO):
    def seek(self, *args, **kwargs):
        raise OSError("not seekable")


class _TextUpload(io.BytesIO):
    def read(self, *args, **kwargs):
        return "not binary"


def _image_bytes(image_format: str = "PNG") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (2, 2), color="red").save(output, format=image_format)
    return output.getvalue()


class TestMaterialUploadService(unittest.TestCase):
    def test_sanitize_filename_strips_paths_and_validates_complete_extension(self):
        self.assertEqual(
            material_upload.sanitize_material_filename(r"C:\videos\clip.MOV"),
            "clip.MOV",
        )
        self.assertEqual(
            material_upload.sanitize_material_filename("../../images/photo.png"),
            "photo.png",
        )

        for filename in ("", ".", "..", "photojpg", "clip.mp4\x00", "clip.exe"):
            with self.subTest(filename=filename):
                with self.assertRaises(material_upload.MaterialUploadError):
                    material_upload.sanitize_material_filename(filename)

    def test_video_upload_is_chunked_validated_and_atomically_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = io.BytesIO(b"decodable-video-placeholder")
            with (
                patch.object(
                    material_upload, "uploaded_material_dir", return_value=temp_dir
                ),
                patch.object(material_upload, "_validate_video") as validate_video,
                patch.object(
                    material_upload,
                    "uuid4",
                    return_value=UUID("4fca18fc-e734-4f3a-a824-777a40d45c8c"),
                ),
                patch.object(
                    material_upload.os, "replace", wraps=os.replace
                ) as replace,
            ):
                stored_name = material_upload.save_material_upload("clip.MOV", source)

            self.assertEqual(stored_name, "4fca18fce7344f3aa824777a40d45c8c.mov")
            self.assertEqual(
                Path(temp_dir, stored_name).read_bytes(),
                b"decodable-video-placeholder",
            )
            validate_video.assert_called_once()
            replace.assert_called_once()
            self.assertEqual(source.tell(), 0)
            self.assertFalse(
                any(
                    name.startswith(".material-upload-")
                    for name in os.listdir(temp_dir)
                )
            )

    def test_same_original_name_creates_immutable_storage_keys(self):
        generated_uuids = [
            UUID("11111111-1111-4111-8111-111111111111"),
            UUID("22222222-2222-4222-8222-222222222222"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(
                    material_upload, "uploaded_material_dir", return_value=temp_dir
                ),
                patch.object(material_upload, "_validate_video"),
                patch.object(material_upload, "uuid4", side_effect=generated_uuids),
            ):
                first = material_upload.save_material_upload(
                    "shared.mp4", io.BytesIO(b"first")
                )
                second = material_upload.save_material_upload(
                    "shared.mp4", io.BytesIO(b"second")
                )

            self.assertNotEqual(first, second)
            self.assertEqual(Path(temp_dir, first).read_bytes(), b"first")
            self.assertEqual(Path(temp_dir, second).read_bytes(), b"second")

    def test_image_upload_validates_content_and_extension(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(
                material_upload, "uploaded_material_dir", return_value=temp_dir
            ):
                stored_name = material_upload.save_material_upload(
                    "photo.PNG", io.BytesIO(_image_bytes("PNG"))
                )
                with self.assertRaisesRegex(
                    material_upload.MaterialUploadError, "does not match"
                ):
                    material_upload.save_material_upload(
                        "renamed.png", io.BytesIO(_image_bytes("JPEG"))
                    )
                with self.assertRaisesRegex(
                    material_upload.MaterialUploadError, "valid JPEG or PNG"
                ):
                    material_upload.save_material_upload(
                        "broken.jpg", io.BytesIO(b"not-an-image")
                    )

            self.assertTrue(stored_name.endswith(".png"))
            self.assertEqual(len(os.listdir(temp_dir)), 1)

    def test_renamed_image_is_not_accepted_as_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(
                    material_upload, "uploaded_material_dir", return_value=temp_dir
                ),
                patch.object(material_upload.subprocess, "run") as run,
            ):
                with self.assertRaisesRegex(
                    material_upload.MaterialUploadError, "not an image"
                ):
                    material_upload.save_material_upload(
                        "renamed.mp4", io.BytesIO(_image_bytes("JPEG"))
                    )

            run.assert_not_called()
            self.assertEqual(os.listdir(temp_dir), [])

    def test_empty_unseekable_and_non_binary_uploads_are_cleaned_up(self):
        invalid_sources = (
            (io.BytesIO(b""), "file is empty"),
            (_UnseekableUpload(b"video"), "not seekable"),
            (_TextUpload(b"video"), "must be binary"),
        )
        for source, expected_error in invalid_sources:
            with self.subTest(expected_error=expected_error):
                with tempfile.TemporaryDirectory() as temp_dir:
                    with patch.object(
                        material_upload,
                        "uploaded_material_dir",
                        return_value=temp_dir,
                    ):
                        with self.assertRaisesRegex(
                            material_upload.MaterialUploadError, expected_error
                        ):
                            material_upload.save_material_upload("clip.mp4", source)
                    self.assertEqual(os.listdir(temp_dir), [])
                self.assertEqual(source.tell(), 0)

    def test_per_media_size_limits_are_enforced_and_temp_files_removed(self):
        cases = (
            ("clip.mp4", "MAX_VIDEO_MATERIAL_UPLOAD_BYTES"),
            ("photo.png", "MAX_IMAGE_MATERIAL_UPLOAD_BYTES"),
        )
        for filename, limit_name in cases:
            with self.subTest(filename=filename):
                with tempfile.TemporaryDirectory() as temp_dir:
                    with (
                        patch.object(
                            material_upload,
                            "uploaded_material_dir",
                            return_value=temp_dir,
                        ),
                        patch.object(material_upload, limit_name, 4),
                    ):
                        with self.assertRaisesRegex(
                            material_upload.MaterialUploadError, "exceeds"
                        ):
                            material_upload.save_material_upload(
                                filename, io.BytesIO(b"12345")
                            )
                    self.assertEqual(os.listdir(temp_dir), [])

    def test_validation_failure_and_storage_failure_remove_temp_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(
                    material_upload, "uploaded_material_dir", return_value=temp_dir
                ),
                patch.object(
                    material_upload,
                    "_validate_video",
                    side_effect=material_upload.MaterialUploadError("invalid video"),
                ),
            ):
                with self.assertRaises(material_upload.MaterialUploadError):
                    material_upload.save_material_upload(
                        "clip.mp4", io.BytesIO(b"broken")
                    )
            self.assertEqual(os.listdir(temp_dir), [])

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(
                    material_upload, "uploaded_material_dir", return_value=temp_dir
                ),
                patch.object(material_upload, "_validate_video"),
                patch.object(
                    material_upload.os,
                    "replace",
                    side_effect=OSError("disk full"),
                ),
            ):
                with self.assertRaises(material_upload.MaterialServiceError):
                    material_upload.save_material_upload(
                        "clip.mp4", io.BytesIO(b"video")
                    )
            self.assertEqual(os.listdir(temp_dir), [])

    def test_video_validation_uses_configured_ffmpeg_and_video_stream(self):
        completed = SimpleNamespace(returncode=0)
        with (
            patch.object(
                material_upload.Image,
                "open",
                side_effect=UnidentifiedImageError("not an image"),
            ),
            patch.object(
                material_upload.utils,
                "get_ffmpeg_binary",
                return_value="/portable/imageio/ffmpeg",
            ),
            patch.object(
                material_upload.subprocess, "run", return_value=completed
            ) as run,
        ):
            material_upload._validate_video("/tmp/clip.mp4")

        command = run.call_args.args[0]
        self.assertEqual(command[0], "/portable/imageio/ffmpeg")
        self.assertIn("0:v:0", command)
        self.assertIn("-xerror", command)
        self.assertNotIn("ffprobe", " ".join(command).lower())

    def test_video_validation_distinguishes_invalid_media_from_tool_failure(self):
        image_error = UnidentifiedImageError("not an image")
        with patch.object(material_upload.Image, "open", side_effect=image_error):
            with patch.object(
                material_upload.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=1),
            ):
                with self.assertRaises(material_upload.MaterialUploadError):
                    material_upload._validate_video("/tmp/clip.mp4")

            with patch.object(
                material_upload.subprocess,
                "run",
                side_effect=OSError("ffmpeg missing"),
            ):
                with self.assertRaises(material_upload.MaterialServiceError):
                    material_upload._validate_video("/tmp/clip.mp4")

            with patch.object(
                material_upload.subprocess,
                "run",
                side_effect=material_upload.subprocess.TimeoutExpired("ffmpeg", 120),
            ):
                with self.assertRaises(material_upload.MaterialServiceError):
                    material_upload._validate_video("/tmp/clip.mp4")


if __name__ == "__main__":
    unittest.main()
