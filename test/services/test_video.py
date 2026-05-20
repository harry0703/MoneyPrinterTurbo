
import unittest
import os
import sys
import types
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from moviepy import (
    VideoFileClip,
)
# add project root to python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from app.models.schema import MaterialInfo
from app.services import video as vd
from app.utils import utils

resources_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")

class TestVideoService(unittest.TestCase):
    def setUp(self):
        self.test_img_path = os.path.join(resources_dir, "1.png")
    
    def tearDown(self):
        pass
    
    def test_preprocess_video(self):
        if not os.path.exists(self.test_img_path):
            self.fail(f"test image not found: {self.test_img_path}")
        
        # test preprocess_video function
        m = MaterialInfo()
        m.url = self.test_img_path
        m.provider = "local"
        print(m)
        
        materials = vd.preprocess_video([m], clip_duration=4)
        print(materials)
        
        # verify result
        self.assertIsNotNone(materials)
        self.assertEqual(len(materials), 1)
        self.assertTrue(materials[0].url.endswith(".mp4"))
        
        # moviepy get video info
        clip = VideoFileClip(materials[0].url)
        print(clip)
        
        # clean generated test video file
        if os.path.exists(materials[0].url):
            os.remove(materials[0].url)

    def test_get_ffmpeg_binary_uses_configured_env_path(self):
        """配置中显式指定 ffmpeg 时，应优先使用该路径。"""
        with patch.dict(os.environ, {"IMAGEIO_FFMPEG_EXE": "/tmp/custom-ffmpeg"}, clear=True):
            self.assertEqual(vd.get_ffmpeg_binary(), "/tmp/custom-ffmpeg")

    def test_get_ffmpeg_binary_falls_back_to_imageio_ffmpeg(self):
        """
        Windows 便携包里系统 PATH 可能没有 ffmpeg，但 moviepy 依赖的
        imageio-ffmpeg 通常会提供可执行文件。这里验证该兜底路径可用。
        """
        fake_imageio_ffmpeg = types.SimpleNamespace(
            get_ffmpeg_exe=lambda: "/tmp/bundled-ffmpeg"
        )

        with patch.dict(os.environ, {}, clear=True), patch.object(
            vd.shutil, "which", return_value=None
        ), patch.dict(sys.modules, {"imageio_ffmpeg": fake_imageio_ffmpeg}):
            self.assertEqual(vd.get_ffmpeg_binary(), "/tmp/bundled-ffmpeg")

    def test_open_video_clip_quietly_suppresses_moviepy_stdout(self):
        """
        MoviePy 2.1.x 的 FFMPEG_VideoReader 会直接向 stdout 打印 metadata
        和 ffmpeg 命令。项目服务层应屏蔽这类依赖库噪声，避免用户把
        `audio_found: False` 误判为最终视频没有音频。
        """
        video_path = os.path.join(resources_dir, "1.png.mp4")
        if not os.path.exists(video_path):
            self.fail(f"test video not found: {video_path}")

        stdout = StringIO()
        with redirect_stdout(stdout):
            clip = vd._open_video_clip_quietly(video_path)

        try:
            self.assertEqual(stdout.getvalue(), "")
            self.assertIsNone(clip.audio)
            self.assertGreater(clip.duration, 0)
        finally:
            vd.close_clip(clip)

    def test_combine_videos_closes_audio_clip_when_duration_read_fails(self):
        """
        `combine_videos()` 只需要读取旁白音频时长。即使读取 duration
        时发生异常，也必须关闭 AudioFileClip，避免文件句柄泄漏。
        """

        class _FakeAudioReader:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        class _BrokenAudioClip:
            def __init__(self):
                self.reader = _FakeAudioReader()

            @property
            def duration(self):
                raise RuntimeError("failed to read duration")

        fake_audio_clip = _BrokenAudioClip()

        with patch.object(vd, "AudioFileClip", return_value=fake_audio_clip):
            with self.assertRaises(RuntimeError):
                vd.combine_videos(
                    combined_video_path="/tmp/unused-combined.mp4",
                    video_paths=[],
                    audio_file="/tmp/unused-audio.mp3",
                )

        self.assertTrue(fake_audio_clip.reader.closed)
    
    def test_wrap_text(self):
        """test text wrapping function"""
        try:
            font_path = os.path.join(utils.font_dir(), "STHeitiMedium.ttc")
            if not os.path.exists(font_path):
                self.fail(f"font file not found: {font_path}")
                
            # test english text wrapping
            test_text_en = "This is a test text for wrapping long sentences in english language"
            
            wrapped_text_en, text_height_en = vd.wrap_text(
                text=test_text_en,
                max_width=300,
                font=font_path,
                fontsize=30
            )
            print(wrapped_text_en, text_height_en)
            # verify text is wrapped
            self.assertIn("\n", wrapped_text_en)
            
            # test chinese text wrapping
            test_text_zh = "这是一段用来测试中文长句换行的文本内容，应该会根据宽度限制进行换行处理"
            wrapped_text_zh, text_height_zh = vd.wrap_text(
                text=test_text_zh,
                max_width=300,
                font=font_path,
                fontsize=30
            )   
            print(wrapped_text_zh, text_height_zh)
            # verify chinese text is wrapped
            self.assertIn("\n", wrapped_text_zh)
        except Exception as e:
            self.fail(f"test wrap_text failed: {str(e)}")

if __name__ == "__main__":
    unittest.main() 
