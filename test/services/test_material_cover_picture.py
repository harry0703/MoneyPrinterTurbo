import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.services import material_upload


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required for media fixtures")
class TestMaterialCoverPicture(unittest.TestCase):
    def test_audio_album_cover_is_not_a_video_material(self):
        with tempfile.TemporaryDirectory() as directory:
            cover = Path(directory) / "cover.jpg"
            Image.new("RGB", (32, 32), "red").save(cover)
            media = Path(directory) / "audio-with-cover.mp4"
            subprocess.run([
                shutil.which("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i",
                "anullsrc=r=8000:cl=mono", "-i", str(cover), "-t", "0.2", "-map", "0:a",
                "-map", "1:v", "-c:a", "aac", "-c:v", "copy", "-disposition:v", "attached_pic", str(media),
            ], check=True, capture_output=True, timeout=20)
            with patch.object(material_upload.utils, "get_ffmpeg_binary", return_value=shutil.which("ffmpeg")):
                with self.assertRaises(material_upload.MaterialUploadError):
                    material_upload._validate_video(str(media))

    def test_video_with_an_attached_cover_remains_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            cover = Path(directory) / "cover.jpg"
            Image.new("RGB", (32, 32), "red").save(cover)
            media = Path(directory) / "video-with-cover.mp4"
            subprocess.run([
                shutil.which("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i",
                "color=c=blue:s=32x32:r=10:d=0.2", "-i", str(cover), "-map", "0:v", "-map", "1:v",
                "-c:v:0", "libx264", "-pix_fmt", "yuv420p", "-c:v:1", "copy",
                "-disposition:v:1", "attached_pic", str(media),
            ], check=True, capture_output=True, timeout=20)
            with patch.object(material_upload.utils, "get_ffmpeg_binary", return_value=shutil.which("ffmpeg")):
                material_upload._validate_video(str(media))
