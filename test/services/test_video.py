import os
import shutil
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from moviepy import (
    ImageClip,
    VideoFileClip,
)

# add project root to python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.models.schema import MaterialInfo
from app.services import video as vd
from app.utils import utils

resources_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")


class _FakeMoviePyClip:
    """Provide a minimal MoviePy interface for final-mix unit tests so CI never really encodes large videos."""

    def __init__(self, *, duration=5, fps=44100):
        self.duration = duration
        self.fps = fps
        self.close_calls = 0
        self.with_audio_result = self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self):
        self.close_calls += 1

    def with_effects(self, _effects):
        return self

    def with_audio(self, _audio):
        return self.with_audio_result


class TestVideoService(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.test_img_path = os.path.join(resources_dir, "1.png")
        vd._runtime_disabled_video_codecs.clear()
        vd._ffmpeg_encoder_exists.cache_clear()

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        vd._runtime_disabled_video_codecs.clear()
        vd._ffmpeg_encoder_exists.cache_clear()

    def test_delete_files_deduplicates_paths_and_ignores_missing_files(self):
        """
        Looped footage makes the same path appear repeatedly in the concat list; cleanup must delete
        each path only once.

        Files that no longer exist are normal idempotent-cleanup states and must not produce
        misleading failure logs.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            existing_file = os.path.join(temp_dir, "temp-clip-1.mp4")
            missing_file = os.path.join(temp_dir, "already-removed.mp4")
            Path(existing_file).write_bytes(b"temporary clip")

            original_remove = os.remove
            with (
                patch.object(vd.os, "remove", wraps=original_remove) as remove,
                patch.object(vd.logger, "warning") as warning,
            ):
                vd.delete_files(
                    [
                        existing_file,
                        existing_file,
                        missing_file,
                        missing_file,
                    ]
                )

        self.assertEqual(
            [item.args[0] for item in remove.call_args_list],
            [existing_file, missing_file],
        )
        warning.assert_not_called()

    def test_delete_files_logs_actionable_os_errors(self):
        """Real cleanup failures like permissions must keep the path and system error for locating leftover files."""
        with (
            patch.object(
                vd.os,
                "remove",
                side_effect=PermissionError("permission denied"),
            ),
            patch.object(vd.logger, "warning") as warning,
        ):
            vd.delete_files(["protected-temp-clip.mp4"])

        warning.assert_called_once()
        message = warning.call_args.args[0]
        self.assertIn("protected-temp-clip.mp4", message)
        self.assertIn("permission denied", message)

    def test_generate_video_reports_successful_bgm_mix_and_closes_sources(self):
        """After a successful BGM mix, return True and release every original file reader."""
        params = vd.VideoParams(
            video_subject="test",
            subtitle_enabled=False,
            bgm_type="sonilo",
        )
        source_video = _FakeMoviePyClip()
        voice_source = _FakeMoviePyClip()
        bgm_source = _FakeMoviePyClip()
        mixed_audio = _FakeMoviePyClip(fps=48000)
        final_video = _FakeMoviePyClip()
        source_video.with_audio_result = final_video

        with (
            patch.object(
                vd, "_open_video_clip_quietly", return_value=source_video
            ),
            patch.object(
                vd, "AudioFileClip", side_effect=[voice_source, bgm_source]
            ),
            patch.object(vd, "CompositeAudioClip", return_value=mixed_audio),
            patch.object(vd, "_write_videofile_with_codec_fallback") as writer,
            patch.object(vd, "_get_configured_video_codec", return_value="libx264"),
        ):
            result = vd.generate_video(
                video_path="combined.mp4",
                audio_path="voice.mp3",
                subtitle_path="",
                output_file="final.mp4",
                params=params,
                bgm_file_override="sonilo.m4a",
            )

        self.assertTrue(result)
        writer.assert_called_once()
        self.assertEqual(writer.call_args.kwargs["audio_fps"], 48000)
        self.assertEqual(source_video.close_calls, 1)
        self.assertEqual(voice_source.close_calls, 1)
        self.assertEqual(bgm_source.close_calls, 1)
        self.assertEqual(final_video.close_calls, 1)

    def test_generate_video_keeps_output_and_reports_failed_bgm_mix(self):
        """When opening the BGM fails, still write the BGM-free video exactly once and return False."""
        params = vd.VideoParams(
            video_subject="test",
            subtitle_enabled=False,
            bgm_type="sonilo",
        )
        source_video = _FakeMoviePyClip()
        voice_source = _FakeMoviePyClip()
        final_video = _FakeMoviePyClip()
        source_video.with_audio_result = final_video

        with (
            patch.object(
                vd, "_open_video_clip_quietly", return_value=source_video
            ),
            patch.object(
                vd,
                "AudioFileClip",
                side_effect=[voice_source, RuntimeError("invalid BGM")],
            ),
            patch.object(vd, "CompositeAudioClip") as composite_audio,
            patch.object(vd, "_write_videofile_with_codec_fallback") as writer,
            patch.object(vd, "_get_configured_video_codec", return_value="libx264"),
            patch.object(vd.logger, "exception") as log_exception,
        ):
            result = vd.generate_video(
                video_path="combined.mp4",
                audio_path="voice.mp3",
                subtitle_path="",
                output_file="final.mp4",
                params=params,
                bgm_file_override="broken.m4a",
            )

        self.assertFalse(result)
        writer.assert_called_once()
        composite_audio.assert_not_called()
        log_exception.assert_called_once()
        self.assertEqual(source_video.close_calls, 1)
        self.assertEqual(voice_source.close_calls, 1)
        self.assertEqual(final_video.close_calls, 1)

    def test_generate_video_skips_every_bgm_source_when_volume_is_zero(self):
        """Volume 0 must short-circuit the current source and future providers uniformly before parsing any file."""
        test_cases = [
            ("random", None),
            ("custom", None),
            ("sonilo", "sonilo.m4a"),
            ("future_provider", "future-provider.wav"),
        ]
        for bgm_type, bgm_override in test_cases:
            with self.subTest(bgm_type=bgm_type):
                params = vd.VideoParams(
                    video_subject="test",
                    subtitle_enabled=False,
                    bgm_type=bgm_type,
                    bgm_file="missing-background.mp3",
                    bgm_volume=0.0,
                )
                source_video = _FakeMoviePyClip()
                voice_source = _FakeMoviePyClip()
                final_video = _FakeMoviePyClip()
                source_video.with_audio_result = final_video

                with (
                    patch.object(
                        vd,
                        "_open_video_clip_quietly",
                        return_value=source_video,
                    ),
                    patch.object(
                        vd, "AudioFileClip", return_value=voice_source
                    ) as audio_file_clip,
                    patch.object(vd, "get_bgm_file") as get_bgm_file,
                    patch.object(vd, "CompositeAudioClip") as composite_audio,
                    patch.object(
                        vd, "_write_videofile_with_codec_fallback"
                    ) as writer,
                    patch.object(
                        vd, "_get_configured_video_codec", return_value="libx264"
                    ),
                ):
                    result = vd.generate_video(
                        video_path="combined.mp4",
                        audio_path="voice.mp3",
                        subtitle_path="",
                        output_file="final.mp4",
                        params=params,
                        bgm_file_override=bgm_override,
                    )

                self.assertTrue(result)
                audio_file_clip.assert_called_once_with("voice.mp3")
                get_bgm_file.assert_not_called()
                composite_audio.assert_not_called()
                writer.assert_called_once()
                self.assertEqual(source_video.close_calls, 1)
                self.assertEqual(voice_source.close_calls, 1)
                self.assertEqual(final_video.close_calls, 1)

    def test_generate_video_chooses_looping_by_bgm_file_source(self):
        """The default library needs looping; duration-matched files from the task layer must not depend on provider names."""
        test_cases = [
            ("random", None, True),
            ("custom", None, True),
            ("sonilo", "sonilo.m4a", False),
            ("future_provider", "future-provider.wav", False),
        ]
        for bgm_type, bgm_override, should_loop in test_cases:
            with self.subTest(bgm_type=bgm_type, bgm_override=bgm_override):
                params = vd.VideoParams(
                    video_subject="test",
                    subtitle_enabled=False,
                    bgm_type=bgm_type,
                    bgm_file="library.mp3",
                    bgm_volume=0.2,
                )
                source_video = _FakeMoviePyClip()
                voice_source = _FakeMoviePyClip()
                bgm_source = _FakeMoviePyClip()
                mixed_audio = _FakeMoviePyClip()
                final_video = _FakeMoviePyClip()
                source_video.with_audio_result = final_video

                with (
                    patch.object(
                        vd,
                        "_open_video_clip_quietly",
                        return_value=source_video,
                    ),
                    patch.object(
                        vd,
                        "AudioFileClip",
                        side_effect=[voice_source, bgm_source],
                    ),
                    patch.object(vd, "get_bgm_file", return_value="library.mp3"),
                    patch.object(vd, "CompositeAudioClip", return_value=mixed_audio),
                    patch.object(vd.afx, "AudioLoop") as audio_loop,
                    patch.object(vd, "_write_videofile_with_codec_fallback"),
                    patch.object(
                        vd, "_get_configured_video_codec", return_value="libx264"
                    ),
                ):
                    result = vd.generate_video(
                        video_path="combined.mp4",
                        audio_path="voice.mp3",
                        subtitle_path="",
                        output_file="final.mp4",
                        params=params,
                        bgm_file_override=bgm_override,
                    )

                self.assertTrue(result)
                if should_loop:
                    audio_loop.assert_called_once_with(duration=source_video.duration)
                else:
                    audio_loop.assert_not_called()

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
        local footage paths come from API parameters; arbitrary absolute paths must never reach MoviePy.
        Verify paths outside the local_videos whitelist directory are skipped to prevent arbitrary
        file reads.
        """
        m = MaterialInfo(provider="local", url=self.test_img_path)

        materials = vd.preprocess_video([m], clip_duration=4)

        self.assertEqual(materials, [])

    def test_get_bgm_file_accepts_song_directory_filename(self):
        """
        The BGM list endpoint now exposes only file names; verify video generation resolves them
        safely back into the resource/songs whitelist so the normal usage path keeps working.
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
        A user may type ./resource/songs/xxx.mp3 in the WebUI. Although relative to the project root,
        the actual file still lives inside the resource/songs whitelist and must be accepted so custom
        background music is not wrongly reported missing.
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
        A user-supplied bgm_file must never be opened as a raw local path, or system files could be read.
        Even if an outside file exists, it must be rejected for not being inside the songs directory.
        """
        with tempfile.NamedTemporaryFile(suffix=".mp3") as temp_bgm:
            self.assertEqual(vd.get_bgm_file(bgm_file=temp_bgm.name), "")

    def test_get_ffmpeg_binary_uses_configured_env_path(self):
        """When ffmpeg is set explicitly in configuration, that path wins."""
        with patch.dict(os.environ, {"IMAGEIO_FFMPEG_EXE": "/tmp/custom-ffmpeg"}, clear=True):
            self.assertEqual(utils.get_ffmpeg_binary(), "/tmp/custom-ffmpeg")

    def test_get_ffmpeg_binary_falls_back_to_imageio_ffmpeg(self):
        """
        In the Windows portable package the system PATH may lack ffmpeg, but imageio-ffmpeg
        (a moviepy dependency) usually ships one. Verify that fallback path works.
        """
        fake_imageio_ffmpeg = types.SimpleNamespace(
            get_ffmpeg_exe=lambda: "/tmp/bundled-ffmpeg"
        )

        with patch.dict(os.environ, {}, clear=True), patch.object(
            utils.shutil, "which", return_value=None
        ), patch.dict(sys.modules, {"imageio_ffmpeg": fake_imageio_ffmpeg}):
            self.assertEqual(utils.get_ffmpeg_binary(), "/tmp/bundled-ffmpeg")

    def test_get_effective_video_codec_falls_back_when_encoder_missing(self):
        """
        A user-selected hardware encoder must pass the FFmpeg encoder-list check first. When not
        detected, fall straight back to libx264 instead of failing at the file-writing stage.
        """
        config.app["video_codec"] = "h264_nvenc"

        with patch.object(vd, "_ffmpeg_encoder_exists", return_value=False):
            self.assertEqual(vd._get_effective_video_codec(), "libx264")

    def test_get_configured_video_codec_uses_stable_default_when_unset(self):
        """
        The WebUI's "default" mode does not persist video_codec. With the setting absent, the
        backend must keep returning libx264 explicitly, never handing an empty value to MoviePy or
        FFmpeg to decide.
        """
        config.app.pop("video_codec", None)

        self.assertEqual(vd._get_configured_video_codec(), "libx264")

    def test_get_configured_video_codec_preserves_explicit_libx264(self):
        """
        An explicit libx264 choice must stick. It currently matches the project default, but the
        configuration semantics differ; future default changes must not affect explicit choices.
        """
        config.app["video_codec"] = "libx264"

        self.assertEqual(vd._get_configured_video_codec(), "libx264")

    def test_ffmpeg_encoder_exists_falls_back_when_probe_fails(self):
        """
        On Windows, a user-configured ffmpeg may fail to run because of a broken path, permissions,
        or antivirus. Encoder probing must return False so the layer above falls back to libx264
        reliably.
        """
        with patch.object(
            vd.subprocess,
            "run",
            side_effect=OSError("permission denied"),
        ):
            self.assertFalse(vd._ffmpeg_encoder_exists("C:/ffmpeg/bin/ffmpeg.exe", "h264_nvenc"))

    def test_write_videofile_falls_back_after_runtime_encoder_failure(self):
        """
        FFmpeg declaring support for a hardware encoder does not mean the GPU or driver actually works.
        After the first real encode failure, retry with libx264 immediately and disable that encoder
        for this process.
        """

        class _FakeClip:
            def __init__(self):
                self.codecs = []

            def write_videofile(self, output_file, codec, **kwargs):
                self.codecs.append(codec)
                if codec == "h264_nvenc":
                    raise RuntimeError("nvenc device not available")

        fake_clip = _FakeClip()

        with patch.object(vd, "_ffmpeg_encoder_exists", return_value=True):
            used_codec = vd._write_videofile_with_codec_fallback(
                fake_clip,
                "/tmp/fake.mp4",
                codec="h264_nvenc",
                logger=None,
                fps=30,
            )

        self.assertEqual(used_codec, "libx264")
        self.assertEqual(fake_clip.codecs, ["h264_nvenc", "libx264"])
        self.assertIn("h264_nvenc", vd._runtime_disabled_video_codecs)

    def test_write_videofile_does_not_disable_codec_when_fallback_also_fails(self):
        """
        If the libx264 fallback also fails, the cause is more likely a generic problem — output path,
        permissions, or a locked file — and the hardware encoder must not be marked unusable.
        """

        class _FakeClip:
            def write_videofile(self, output_file, codec, **kwargs):
                raise RuntimeError(f"{codec} cannot write output")

        with patch.object(vd, "_ffmpeg_encoder_exists", return_value=True):
            with self.assertRaises(RuntimeError):
                vd._write_videofile_with_codec_fallback(
                    _FakeClip(),
                    "/tmp/fake.mp4",
                    codec="h264_nvenc",
                    logger=None,
                    fps=30,
                )

        self.assertNotIn("h264_nvenc", vd._runtime_disabled_video_codecs)

    def test_format_ffmpeg_concat_path_normalizes_windows_path(self):
        """
        The concat demuxer's file list is sensitive to Windows backslashes; convert to forward slashes
        uniformly before writing the list, keeping the single-quote escaping.
        """
        with patch.object(
            vd.os.path,
            "abspath",
            return_value=r"C:\Users\Test User's Videos\clip.mp4",
        ):
            self.assertEqual(
                vd._format_ffmpeg_concat_path(
                    r"C:\Users\Test User's Videos\clip.mp4"
                ),
                "C:/Users/Test User'\\''s Videos/clip.mp4",
            )

    def test_concat_video_clips_falls_back_after_runtime_encoder_failure(self):
        """
        The final ffmpeg concat stage needs the same fallback. Mock an h264_nvenc failure and confirm
        it automatically runs once more with libx264.
        """
        config.app["video_codec"] = "h264_nvenc"

        def fake_run(command, capture_output, text, check):
            codec_index = command.index("-c:v") + 1
            codec = command[codec_index]
            if codec == "h264_nvenc":
                return types.SimpleNamespace(
                    returncode=1,
                    stdout="",
                    stderr="nvenc device not available",
                )
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as temp_dir:
            clip_file = os.path.join(temp_dir, "clip.mp4")
            output_file = os.path.join(temp_dir, "combined.mp4")
            Path(clip_file).write_bytes(b"fake")

            with patch.object(vd, "_ffmpeg_encoder_exists", return_value=True):
                with patch.object(vd.subprocess, "run", side_effect=fake_run) as run:
                    vd.concat_video_clips_with_ffmpeg(
                        clip_files=[clip_file],
                        output_file=output_file,
                        threads=1,
                        output_dir=temp_dir,
                    )

        used_codecs = [
            call.args[0][call.args[0].index("-c:v") + 1]
            for call in run.call_args_list
        ]
        self.assertEqual(used_codecs, ["h264_nvenc", "libx264"])
        self.assertIn("h264_nvenc", vd._runtime_disabled_video_codecs)

    def test_concat_video_clips_does_not_disable_codec_when_fallback_also_fails(self):
        """
        If the concat stage also fails with libx264, the problem is likely the input list, paths, or
        output permissions; do not add the hardware encoder to the runtime disable list.
        """
        config.app["video_codec"] = "h264_nvenc"

        def fake_run(command, capture_output, text, check):
            codec_index = command.index("-c:v") + 1
            codec = command[codec_index]
            return types.SimpleNamespace(
                returncode=1,
                stdout="",
                stderr=f"{codec} cannot write output",
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            clip_file = os.path.join(temp_dir, "clip.mp4")
            output_file = os.path.join(temp_dir, "combined.mp4")
            Path(clip_file).write_bytes(b"fake")

            with patch.object(vd, "_ffmpeg_encoder_exists", return_value=True):
                with patch.object(vd.subprocess, "run", side_effect=fake_run):
                    with self.assertRaises(RuntimeError):
                        vd.concat_video_clips_with_ffmpeg(
                            clip_files=[clip_file],
                            output_file=output_file,
                            threads=1,
                            output_dir=temp_dir,
                        )

        self.assertNotIn("h264_nvenc", vd._runtime_disabled_video_codecs)

    def test_open_video_clip_quietly_suppresses_moviepy_stdout(self):
        """
        MoviePy 2.1.x's FFMPEG_VideoReader prints metadata and the ffmpeg command straight to stdout.
        The service layer must suppress this dependency noise so users never mistake
        `audio_found: False` for a silent final video.
        """
        # The test only cares whether the service layer suppresses MoviePy read noise; it should not keep a binary
        # MP4 fixture encoded from a PNG long-term. Generating a short video at runtime keeps the test independent
        # and avoids the fixture being misused for visual verification after frame flicker from changed encode parameters.
        image_path = os.path.join(resources_dir, "1.png")
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = os.path.join(temp_dir, "image-fixture.mp4")
            source_clip = ImageClip(image_path).with_duration(0.2)
            try:
                source_clip.write_videofile(
                    video_path,
                    codec="libx264",
                    fps=5,
                    audio=False,
                    logger=None,
                )
            finally:
                source_clip.close()

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
        `combine_videos()` only needs the voiceover audio duration. Even if reading the duration
        raises, the AudioFileClip must be closed so file handles never leak.
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

    def _capture_source_ranges_for_clip_speed(
        self,
        *,
        source_duration,
        audio_duration,
        clip_speed,
        max_clip_duration=3,
    ):
        """Record the source time ranges actually read by combine_videos using lightweight fake videos."""

        source_ranges = []
        written_durations = []

        class _FakeAudioClip:
            duration = audio_duration

            def close(self):
                pass

        class _FakeVideoClip:
            def __init__(self, duration, records_source_range=False):
                self.duration = duration
                self.size = (1080, 1920)
                self.w = 1080
                self.h = 1920
                self.records_source_range = records_source_range

            def subclipped(self, start_time, end_time):
                # Record only ranges read directly from the source file. The post-speed-change safety trim also
                # calls subclipped, but it is not a new source interval and must not contaminate gap detection.
                if self.records_source_range:
                    source_ranges.append((start_time, end_time))
                return _FakeVideoClip(end_time - start_time)

            def with_speed_scaled(self, factor):
                return _FakeVideoClip(self.duration / factor)

            def close(self):
                pass

        def _open_fake_video_clip(_video_path):
            return _FakeVideoClip(source_duration, records_source_range=True)

        def _capture_written_clip(clip, *_args, **_kwargs):
            written_durations.append(clip.duration)

        with tempfile.TemporaryDirectory() as temp_dir:
            combined_video_path = os.path.join(temp_dir, "combined.mp4")
            with (
                patch.object(vd, "AudioFileClip", return_value=_FakeAudioClip()),
                patch.object(
                    vd,
                    "_open_video_clip_quietly",
                    side_effect=_open_fake_video_clip,
                ),
                patch.object(
                    vd,
                    "_write_videofile_with_codec_fallback",
                    side_effect=_capture_written_clip,
                ),
                # Random mode shuffles slices of the same source video by default. Keep generation order here
                # so adjacency of source intervals can be verified precisely.
                patch.object(
                    vd,
                    "_prioritize_unique_source_clips",
                    side_effect=lambda subclipped_items, concat_mode: subclipped_items,
                ),
                patch.object(vd, "concat_video_clips_with_ffmpeg"),
                patch.object(vd, "delete_files"),
            ):
                vd.combine_videos(
                    combined_video_path=combined_video_path,
                    video_paths=["clip.mp4"],
                    audio_file="audio.mp3",
                    video_concat_mode=vd.VideoConcatMode.random,
                    max_clip_duration=max_clip_duration,
                    clip_speed=clip_speed,
                )

        return source_ranges, written_durations

    def test_combine_videos_slow_speed_keeps_source_timeline_continuous(self):
        """0.5x slow motion should read 1.5-second source segments continuously without skipping picture."""

        source_ranges, written_durations = self._capture_source_ranges_for_clip_speed(
            source_duration=4.0,
            audio_duration=5.9,
            clip_speed=0.5,
        )

        self.assertEqual(source_ranges, [(0, 1.5), (1.5, 3.0)])
        self.assertEqual(written_durations, [3.0, 3.0])

    def test_combine_videos_fast_speed_reads_enough_source_content(self):
        """2x fast motion should read 6 seconds of source so the final segment stays 3 seconds."""

        source_ranges, written_durations = self._capture_source_ranges_for_clip_speed(
            source_duration=8.0,
            audio_duration=2.9,
            clip_speed=2.0,
        )

        self.assertEqual(source_ranges, [(0, 6.0)])
        self.assertEqual(written_durations, [3.0])

    def test_combine_videos_keeps_small_duration_safety_margin(self):
        """
        When accumulated audio and footage durations are exactly equal, keep appending one short
        segment as a safety margin.

        FFmpeg's frame-rate concatenation can end tens of milliseconds short of the theoretical
        duration. Stopping at 10.0s == 10.0s could leave the audio still playing after the footage
        runs out at the end of the cut.
        """

        class _FakeAudioClip:
            duration = 10.0

            def close(self):
                pass

        class _FakeVideoClip:
            def __init__(self, duration):
                self.duration = duration
                self.size = (1080, 1920)
                self.w = 1080
                self.h = 1920

            def subclipped(self, start_time, end_time):
                return _FakeVideoClip(end_time - start_time)

        video_durations = {
            "clip-1.mp4": 3.0,
            "clip-2.mp4": 4.0,
            "clip-3.mp4": 3.0,
            "clip-4.mp4": 2.0,
        }

        def _open_fake_video_clip(video_path):
            return _FakeVideoClip(video_durations[video_path])

        with tempfile.TemporaryDirectory() as temp_dir:
            combined_video_path = os.path.join(temp_dir, "combined.mp4")

            with patch.object(vd, "AudioFileClip", return_value=_FakeAudioClip()):
                with patch.object(
                    vd, "_open_video_clip_quietly", side_effect=_open_fake_video_clip
                ):
                    with patch.object(
                        vd, "_write_videofile_with_codec_fallback"
                    ) as write_mock:
                        with patch.object(vd, "concat_video_clips_with_ffmpeg") as concat_mock:
                            with patch.object(vd, "delete_files"):
                                result = vd.combine_videos(
                                    combined_video_path=combined_video_path,
                                    video_paths=list(video_durations.keys()),
                                    audio_file=os.path.join(temp_dir, "audio.mp3"),
                                    video_aspect=vd.VideoAspect.portrait,
                                    video_concat_mode=vd.VideoConcatMode.sequential,
                                    video_transition_mode=None,
                                    max_clip_duration=10,
                                )

        self.assertEqual(result, combined_video_path)
        self.assertEqual(write_mock.call_count, 4)
        self.assertEqual(concat_mock.call_args.kwargs["max_duration"], 10.0)

    def test_concat_video_clips_limits_output_to_audio_duration(self):
        """Trim to the audio duration at final concatenation so the safety margin does not add an audible silent tail."""

        def fake_run(command, capture_output, text, check):
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as temp_dir:
            clip_file = os.path.join(temp_dir, "clip.mp4")
            output_file = os.path.join(temp_dir, "combined.mp4")
            Path(clip_file).write_bytes(b"fake")

            with patch.object(vd.subprocess, "run", side_effect=fake_run) as run:
                vd.concat_video_clips_with_ffmpeg(
                    clip_files=[clip_file],
                    output_file=output_file,
                    threads=1,
                    output_dir=temp_dir,
                    max_duration=10.0,
                )

        command = run.call_args.args[0]
        self.assertEqual(command[command.index("-t") + 1], "10.000")
        self.assertLess(command.index("-t"), command.index(output_file))

    def test_prioritize_unique_source_clips_uses_each_source_before_reuse(self):
        """
        In random mode a long piece of footage is split into several segments. The scheduler should
        let every source appear at least once before reusing other slices of the same source, reducing
        perceived repetition.
        """
        clips = [
            vd.SubClippedVideoClip("a.mp4", 0, 4, source_file_path="a.mp4"),
            vd.SubClippedVideoClip("a.mp4", 4, 8, source_file_path="a.mp4"),
            vd.SubClippedVideoClip("b.mp4", 0, 4, source_file_path="b.mp4"),
            vd.SubClippedVideoClip("b.mp4", 4, 8, source_file_path="b.mp4"),
            vd.SubClippedVideoClip("c.mp4", 0, 4, source_file_path="c.mp4"),
        ]

        ordered_clips = vd._prioritize_unique_source_clips(
            subclipped_items=clips,
            concat_mode=vd.VideoConcatMode.random,
        )

        self.assertCountEqual(ordered_clips, clips)
        first_round_sources = [clip.source_file_path for clip in ordered_clips[:3]]
        self.assertCountEqual(first_round_sources, ["a.mp4", "b.mp4", "c.mp4"])

    def test_prioritize_unique_source_clips_keeps_sequential_order(self):
        """
        Sequential mode itself takes only each footage's first segment; random scheduling must not
        reorder it.
        """
        clips = [
            vd.SubClippedVideoClip("a.mp4", 0, 4, source_file_path="a.mp4"),
            vd.SubClippedVideoClip("b.mp4", 0, 4, source_file_path="b.mp4"),
            vd.SubClippedVideoClip("c.mp4", 0, 4, source_file_path="c.mp4"),
        ]

        ordered_clips = vd._prioritize_unique_source_clips(
            subclipped_items=clips,
            concat_mode=vd.VideoConcatMode.sequential,
        )

        self.assertEqual(ordered_clips, clips)

    def test_prioritize_unique_source_clips_prefers_long_primary_clip(self):
        """
        The last slice of a source may be shorter than the target segment duration. The first
        deduplication round should prefer longer segments, or footage gets reused early because the
        accumulated duration falls short.
        """
        short_tail = vd.SubClippedVideoClip(
            "a.mp4", 6, 6.5, source_file_path="a.mp4"
        )
        full_clip = vd.SubClippedVideoClip(
            "a.mp4", 0, 3, source_file_path="a.mp4"
        )
        other_source = vd.SubClippedVideoClip(
            "b.mp4", 0, 3, source_file_path="b.mp4"
        )

        ordered_clips = vd._prioritize_unique_source_clips(
            subclipped_items=[short_tail, full_clip, other_source],
            concat_mode=vd.VideoConcatMode.random,
        )

        first_a_clip = next(
            clip for clip in ordered_clips if clip.source_file_path == "a.mp4"
        )
        self.assertEqual(first_a_clip, full_clip)
    
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

    def test_rounded_subtitle_background_clip_has_transparent_corners(self):
        """
        The rounded subtitle background is used only when explicitly enabled. Verify directly that
        the generated RGBA background has transparent rounded corners and a semi-transparent center,
        so later changes never degrade it into a solid rectangle.
        """
        clip = vd._rounded_subtitle_background_clip(
            width=120,
            height=48,
            color="#123456",
            alpha=140,
            radius=16,
        )
        try:
            frame = clip.get_frame(0)
            mask = clip.mask.get_frame(0)

            self.assertEqual(frame.shape[0:2], (48, 120))
            self.assertEqual(tuple(frame[24, 60]), (18, 52, 86))
            self.assertEqual(mask[0, 0], 0)
            self.assertGreater(mask[24, 60], 0.5)
            self.assertLess(mask[24, 60], 0.6)
        finally:
            clip.close()

    def test_get_temp_audio_dir_returns_system_temp_on_windows(self):
        with patch("sys.platform", "win32"):
            result = vd._get_temp_audio_dir("/some/output/dir")
            self.assertEqual(result, tempfile.gettempdir())

    def test_get_temp_audio_dir_returns_output_dir_on_non_windows(self):
        for platform in ("linux", "darwin"):
            with self.subTest(platform=platform):
                with patch("sys.platform", platform):
                    result = vd._get_temp_audio_dir("/some/output/dir")
                    self.assertEqual(result, "/some/output/dir")


class TestMaterialResolutionTolerance(unittest.TestCase):
    def test_accepts_material_at_the_nominal_minimum(self):
        self.assertTrue(vd.is_material_resolution_acceptable(480, 480))

    def test_accepts_whatsapp_recompressed_portrait_clip(self):
        # WhatsApp delivers 9:16 clips as 478x850, two pixels under the
        # nominal 480 minimum. Rejecting them fails the whole task.
        self.assertTrue(vd.is_material_resolution_acceptable(478, 850))

    def test_accepts_material_exactly_at_the_tolerance_bound(self):
        bound = vd._MIN_MATERIAL_DIMENSION - vd._MIN_DIMENSION_TOLERANCE
        self.assertTrue(vd.is_material_resolution_acceptable(bound, bound))

    def test_rejects_material_just_below_the_tolerance_bound(self):
        bound = vd._MIN_MATERIAL_DIMENSION - vd._MIN_DIMENSION_TOLERANCE
        self.assertFalse(vd.is_material_resolution_acceptable(bound - 1, 850))
        self.assertFalse(vd.is_material_resolution_acceptable(850, bound - 1))

    def test_rejects_genuinely_low_resolution_material(self):
        self.assertFalse(vd.is_material_resolution_acceptable(320, 240))


if __name__ == "__main__":
    unittest.main()
