
import unittest
import os
import shutil
import sys
import tempfile
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
from app.config import config
from app.controllers.manager.base_manager import TaskQueueFullError
from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.controllers.v1 import video as video_controller
from app.models import const
from app.models.schema import MaterialInfo
from app.services import state as sm
from app.services import video as vd
from app.utils import utils

resources_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")


class _FakeRequest:
    def __init__(self):
        self.headers = {"x-task-id": "test-request"}


class TestSecurityControls(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def test_task_query_returns_relative_task_url_without_mutating_state(self):
        """
        endpoint 가 명시적으로 설정되지 않은 경우, 작업 조회 인터페이스는 Host 에서 파생된 절대 URL 을 사용해서는 안 되며,
        표시용 URL 을 작업 상태에 다시 기록해서도 안 됩니다. 그렇지 않으면 서로 다른 Host 의 조회가 결과를 오염시킵니다.
        """
        task_id = "security-task-url"
        task_dir = utils.task_dir(task_id)
        video_path = os.path.join(task_dir, "final-1.mp4")
        Path(video_path).write_bytes(b"fake-video")
        config.app["endpoint"] = ""

        try:
            sm.state.update_task(
                task_id,
                state=const.TASK_STATE_COMPLETE,
                videos=[video_path],
                combined_videos=[video_path],
            )

            response = video_controller.get_task(_FakeRequest(), task_id=task_id)

            self.assertEqual(response["data"]["videos"], [f"/tasks/{task_id}/final-1.mp4"])
            self.assertEqual(sm.state.get_task(task_id)["videos"], [video_path])
        finally:
            sm.state.delete_task(task_id)
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_in_memory_task_manager_rejects_when_queue_is_full(self):
        """
        동시 실행 수가 모두 소진되면 대기 큐에는 반드시 하드 상한이 있어야 합니다. 여기서는 max_concurrent_tasks=0 으로
        작업을 강제로 큐에 넣고, max_queued_tasks 를 초과하면 추가 큐 진입이 거부되는지 검증합니다.
        """
        manager = InMemoryTaskManager(max_concurrent_tasks=0, max_queued_tasks=1)

        manager.add_task(lambda: None)

        with self.assertRaises(TaskQueueFullError):
            manager.add_task(lambda: None)

class TestVideoService(unittest.TestCase):
    def setUp(self):
        self.test_img_path = os.path.join(resources_dir, "1.png")
    
    def tearDown(self):
        pass
    
    def test_preprocess_video(self):
        if not os.path.exists(self.test_img_path):
            self.fail(f"test image not found: {self.test_img_path}")

        local_videos_dir = utils.storage_dir("local_videos", create=True)
        safe_img_path = os.path.join(local_videos_dir, "test-preprocess-1.png")
        shutil.copy2(self.test_img_path, safe_img_path)

        # test preprocess_video function
        m = MaterialInfo()
        m.url = os.path.basename(safe_img_path)
        m.provider = "local"
        print(m)

        try:
            materials = vd.preprocess_video([m], clip_duration=4)
            print(materials)

            # verify result
            self.assertIsNotNone(materials)
            self.assertEqual(len(materials), 1)
            self.assertTrue(materials[0].url.endswith(".mp4"))

            # moviepy get video info
            clip = VideoFileClip(materials[0].url)
            try:
                print(clip)
            finally:
                clip.close()

            # clean generated test video file
            if os.path.exists(materials[0].url):
                os.remove(materials[0].url)
        finally:
            if os.path.exists(safe_img_path):
                os.remove(safe_img_path)

    def test_preprocess_video_rejects_material_outside_local_videos(self):
        """
        local 소재 경로는 API 파라미터에서 오므로, 임의의 절대 경로가 MoviePy 로 들어가는 것을 허용해서는 안 됩니다.
        여기서는 local_videos 화이트리스트 디렉터리 밖의 경로가 건너뛰어져 임의 파일 읽기를 방지하는지 검증합니다.
        """
        m = MaterialInfo(provider="local", url=self.test_img_path)

        materials = vd.preprocess_video([m], clip_duration=4)

        self.assertEqual(materials, [])

    def test_get_bgm_file_accepts_song_directory_filename(self):
        """
        BGM 목록 인터페이스는 이제 파일 이름만 노출합니다. 영상 생성 시 파일 이름을 resource/songs 화이트리스트
        디렉터리로 안전하게 다시 해석할 수 있어야 하며, 정상적인 사용 경로를 유지해야 합니다.
        """
        song_dir = utils.song_dir()
        bgm_path = os.path.join(song_dir, "test-safe-bgm.mp3")
        Path(bgm_path).write_bytes(b"fake-mp3")

        try:
            self.assertEqual(vd.get_bgm_file(bgm_file="test-safe-bgm.mp3"), bgm_path)
        finally:
            if os.path.exists(bgm_path):
                os.remove(bgm_path)

    def test_get_bgm_file_accepts_project_relative_song_path(self):
        """
        사용자가 WebUI 에서 ./resource/songs/xxx.mp3 를 직접 입력할 수 있습니다. 이 경로는 프로젝트 루트 기준
        상대 경로이지만 실제 파일은 여전히 resource/songs 화이트리스트 디렉터리 안에 있으므로,
        이를 허용하여 사용자 지정 배경 음악이 존재하지 않는 것으로 잘못 판정되지 않도록 해야 합니다.
        """
        song_dir = utils.song_dir()
        bgm_path = os.path.join(song_dir, "test-relative-bgm.mp3")
        Path(bgm_path).write_bytes(b"fake-mp3")

        try:
            self.assertEqual(
                vd.get_bgm_file(bgm_file="./resource/songs/test-relative-bgm.mp3"),
                bgm_path,
            )
        finally:
            if os.path.exists(bgm_path):
                os.remove(bgm_path)

    def test_get_bgm_file_rejects_path_outside_song_directory(self):
        """
        사용자가 전달한 bgm_file 을 로컬 경로로 직접 열어서는 안 됩니다. 그렇지 않으면 시스템 파일을 읽을 수 있습니다.
        외부 파일이 존재하더라도 songs 디렉터리 안에 없다면 반드시 거부되어야 합니다.
        """
        with tempfile.NamedTemporaryFile(suffix=".mp3") as temp_bgm:
            self.assertEqual(vd.get_bgm_file(bgm_file=temp_bgm.name), "")

    def test_get_ffmpeg_binary_uses_configured_env_path(self):
        """설정에서 ffmpeg 를 명시적으로 지정한 경우, 해당 경로를 우선 사용해야 합니다."""
        with patch.dict(os.environ, {"IMAGEIO_FFMPEG_EXE": "/tmp/custom-ffmpeg"}, clear=True):
            self.assertEqual(vd.get_ffmpeg_binary(), "/tmp/custom-ffmpeg")

    def test_get_ffmpeg_binary_falls_back_to_imageio_ffmpeg(self):
        """
        Windows 포터블 패키지에서는 시스템 PATH 에 ffmpeg 가 없을 수 있지만, moviepy 가 의존하는
        imageio-ffmpeg 가 보통 실행 파일을 제공합니다. 여기서는 이 폴백 경로가 동작하는지 검증합니다.
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
        MoviePy 2.1.x 의 FFMPEG_VideoReader 는 metadata 와 ffmpeg 명령을 stdout 으로 직접 출력합니다.
        프로젝트 서비스 계층은 이러한 의존 라이브러리 노이즈를 차단하여, 사용자가
        `audio_found: False` 를 최종 영상에 오디오가 없는 것으로 오판하지 않도록 해야 합니다.
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
        `combine_videos()` 는 내레이션 오디오의 길이만 읽으면 됩니다. duration 을 읽는 중
        예외가 발생하더라도 반드시 AudioFileClip 을 닫아 파일 핸들 누수를 방지해야 합니다.
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

    def test_combine_videos_handles_none_transition_mode(self):
        """
        Ensure `combine_videos` safely handles
        `video_transition_mode=None`.
        """
        class _FakeAudioClip:
            @property
            def duration(self):
                return 10.0

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            combined_video_path = os.path.join(temp_dir, "combined.mp4")
            audio_file = os.path.join(temp_dir, "audio.mp3")

            with patch.object(vd, "AudioFileClip", return_value=_FakeAudioClip()):
                # Use empty video_paths to avoid heavy video processing while
                # still exercising transition mode normalization logic.
                result = vd.combine_videos(
                    combined_video_path=combined_video_path,
                    video_paths=[],
                    audio_file=audio_file,
                    video_transition_mode=None,
                )
                self.assertEqual(result, combined_video_path)
    
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
