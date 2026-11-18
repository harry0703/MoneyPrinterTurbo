import unittest
import os
import shutil
import sys
import tempfile
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from uuid import uuid4

# add project root to python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import task as tm
from app.models.schema import MaterialInfo, VideoParams
from app.services.state import MemoryState, RedisState
from app.utils import utils

resources_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
RUN_INTEGRATION_TESTS = os.environ.get("MPT_RUN_INTEGRATION_TESTS", "").lower() in {
    "1",
    "true",
    "yes",
}


class TestTaskService(unittest.TestCase):
    def setUp(self):
        # The publish Future registry is process-level state. Cleaning it between tests keeps a mocked Future from
        # affecting later recovery tests, without touching production tasks in the real thread pool.
        with tm._cross_post_registry_lock:
            tm._cross_post_futures.clear()

    def tearDown(self):
        with tm._cross_post_registry_lock:
            tm._cross_post_futures.clear()

    def test_is_task_busy_covers_generation_and_cross_posting(self):
        """The delete entry must recognize active states of both video generation and cross-platform publishing."""
        busy_tasks = (
            {"state": tm.const.TASK_STATE_PROCESSING},
            {
                "state": tm.const.TASK_STATE_COMPLETE,
                "cross_post_state": tm.const.CROSS_POST_STATE_PENDING,
            },
            {
                "state": tm.const.TASK_STATE_COMPLETE,
                "cross_post_state": tm.const.CROSS_POST_STATE_PROCESSING,
            },
        )
        for task in busy_tasks:
            with self.subTest(task=task):
                self.assertTrue(tm.is_task_busy(task))

        self.assertFalse(
            tm.is_task_busy(
                {
                    "state": tm.const.TASK_STATE_COMPLETE,
                    "cross_post_state": tm.const.CROSS_POST_STATE_COMPLETE,
                }
            )
        )
        self.assertFalse(tm.is_task_busy(None))

    def test_generate_script_forwards_advanced_prompt_options(self):
        """
        The task generation entry shares VideoParams with the WebUI/API. This verifies that when the script is generated automatically,
        advanced prompt parameters are still passed to the LLM service layer, rather than only taking effect on the /scripts endpoint.
        """
        params = VideoParams(
            video_subject="咖啡",
            video_script="",
            video_language="zh-CN",
            paragraph_number=2,
            video_script_prompt="语气轻松",
            custom_system_prompt="Only write short narration.",
        )

        with patch.object(
            tm.llm, "generate_script", return_value="生成的文案"
        ) as generate:
            result = tm.generate_script("task-id", params)

        self.assertEqual(result, "生成的文案")
        generate.assert_called_once_with(
            video_subject="咖啡",
            language="zh-CN",
            paragraph_number=2,
            video_script_prompt="语气轻松",
            custom_system_prompt="Only write short narration.",
        )

    def test_generate_final_videos_forwards_clip_speed_and_fit_mode(self):
        """The task orchestration layer must pass frame speed and fit mode to the video composition service."""
        params = VideoParams(
            video_subject="test",
            video_count=1,
            video_clip_speed=1.25,
            video_fit_mode="contain",
        )

        with (
            patch.object(tm.video, "combine_videos") as combine_videos,
            patch.object(tm.video, "generate_video"),
            patch.object(tm.sm.state, "update_task"),
        ):
            tm.generate_final_videos(
                task_id="clip-speed-task",
                params=params,
                downloaded_videos=["material.mp4"],
                audio_file="audio.mp3",
                subtitle_path="",
                audio_duration=5,
            )

        self.assertEqual(combine_videos.call_args.kwargs["clip_speed"], 1.25)
        self.assertEqual(
            combine_videos.call_args.kwargs["video_fit_mode"],
            params.video_fit_mode,
        )

    def test_stage_progress_reporter_maps_fraction_into_stage_range(self):
        """
        A 0~1 completion ratio within a stage must be converted into the progress range the stage occupies, keeping the task's
        other existing fields. Out-of-range or unparseable ratios must not push progress outside the range.
        """
        state = MemoryState()
        state.update_task("stage-progress", progress=40, video_subject="咖啡")

        with patch.object(tm.sm, "state", state):
            report = tm._stage_progress_reporter("stage-progress", 40, 50)
            for fraction, expected in (
                (0.0, 40),
                (0.55, 45),
                (1.0, 50),
                (3.0, 50),
                (-1.0, 40),
            ):
                with self.subTest(fraction=fraction):
                    report(fraction)
                    self.assertEqual(
                        state.get_task("stage-progress")["progress"], expected
                    )

            report(0.5)
            report("not a number")
            task = state.get_task("stage-progress")

        self.assertEqual(task["progress"], 45)
        self.assertEqual(task["state"], tm.const.TASK_STATE_PROCESSING)
        self.assertEqual(task["video_subject"], "咖啡")

    def test_stage_progress_reporter_survives_state_backend_failure(self):
        """Progress is only display info; when the state backend is temporarily unavailable, download or composition must not fail."""
        with (
            patch.object(
                tm.sm.state, "update_task", side_effect=RuntimeError("redis down")
            ),
            patch.object(tm.logger, "warning") as warning,
        ):
            tm._stage_progress_reporter("stage-progress", 40, 50)(0.5)

        warning.assert_called_once()
        self.assertIn("redis down", str(warning.call_args.args[0]))

    def test_material_download_moves_progress_between_40_and_50(self):
        """
        Material download is the slowest stage on slow networks, and progress used to sit at 40% until everything finished and then
        jump to 50%. The completion ratio reported during download must be reflected in the task progress.
        """
        params = VideoParams(video_subject="test", video_source="pexels")
        state = MemoryState()
        state.update_task("download-progress", progress=40)
        observed = []

        def fake_download_videos(**kwargs):
            for fraction in (0.25, 0.5, 1.0):
                kwargs["progress_callback"](fraction)
                observed.append(state.get_task("download-progress")["progress"])
            return ["a.mp4"]

        with (
            patch.object(tm.sm, "state", state),
            patch.object(
                tm.material, "download_videos", side_effect=fake_download_videos
            ),
        ):
            result = tm.get_video_materials(
                "download-progress", params, ["scene"], 10
            )

        self.assertEqual(result, ["a.mp4"])
        self.assertEqual(observed, [42, 45, 50])

    def test_clip_processing_moves_progress_through_the_combine_half(self):
        """
        Progress used to be fixed at 50% during clip processing. Composition takes the first half of each video's progress share:
        50%~75% for a single video, and with two videos the second starts at 75%.
        """
        for video_count, expected in (
            (1, [[62, 75]]),
            (2, [[56, 62], [81, 87]]),
        ):
            with self.subTest(video_count=video_count):
                params = VideoParams(video_subject="test", video_count=video_count)
                state = MemoryState()
                state.update_task("combine-progress", progress=50)
                observed = []

                def fake_combine_videos(**kwargs):
                    seen = []
                    for fraction in (0.5, 1.0):
                        kwargs["progress_callback"](fraction)
                        seen.append(
                            state.get_task("combine-progress")["progress"]
                        )
                    observed.append(seen)

                with (
                    patch.object(tm.sm, "state", state),
                    patch.object(
                        tm.video, "combine_videos", side_effect=fake_combine_videos
                    ),
                    patch.object(tm.video, "generate_video"),
                    patch.object(tm.task_artifacts, "patch_script_data"),
                ):
                    tm.generate_final_videos(
                        task_id="combine-progress",
                        params=params,
                        downloaded_videos=["material.mp4"],
                        audio_file="audio.mp3",
                        subtitle_path="",
                        audio_duration=5,
                    )

                self.assertEqual(observed, expected)
                self.assertEqual(
                    state.get_task("combine-progress")["progress"], 100
                )

    def test_generate_final_videos_uses_generated_sonilo_music(self):
        """Sonilo must generate music for each concatenated video and pass it to the final mix."""
        params = VideoParams(
            video_subject="test",
            video_count=1,
            bgm_type="sonilo",
            sonilo_bgm_prompt="warm acoustic",
        )

        with (
            patch.object(tm.video, "combine_videos"),
            patch.object(
                tm.sonilo,
                "generate_bgm",
                side_effect=lambda **kwargs: kwargs["output_path"],
            ) as generate_bgm,
            patch.object(tm.video, "generate_video") as generate_video,
            patch.object(tm.sm.state, "update_task"),
        ):
            _, _, warnings = tm.generate_final_videos(
                task_id="sonilo-task",
                params=params,
                downloaded_videos=["material.mp4"],
                audio_file="audio.mp3",
                subtitle_path="",
                audio_duration=5,
            )

        self.assertEqual(warnings, [])
        self.assertEqual(generate_bgm.call_args.kwargs["video_duration"], 5)
        self.assertEqual(generate_bgm.call_args.kwargs["prompt"], "warm acoustic")
        self.assertTrue(
            generate_video.call_args.kwargs["bgm_file_override"].endswith(
                "sonilo-bgm-1.m4a"
            )
        )

    def test_generate_final_videos_uses_generated_elevenlabs_music(self):
        """ElevenLabs should reuse the video music orchestration and use the generic style prompt."""
        params = VideoParams(
            video_subject="test",
            video_count=1,
            bgm_type="elevenlabs",
            video_music_prompt="gentle documentary",
        )

        with (
            patch.object(tm.video, "combine_videos"),
            patch.object(
                tm.elevenlabs_music,
                "generate_bgm",
                side_effect=lambda **kwargs: kwargs["output_path"],
            ) as generate_bgm,
            patch.object(tm.video, "generate_video") as generate_video,
            patch.object(tm.sm.state, "update_task"),
        ):
            _, _, warnings = tm.generate_final_videos(
                task_id="elevenlabs-task",
                params=params,
                downloaded_videos=["material.mp4"],
                audio_file="audio.mp3",
                subtitle_path="",
                audio_duration=5,
            )

        self.assertEqual(warnings, [])
        self.assertEqual(generate_bgm.call_args.kwargs["video_duration"], 5)
        self.assertEqual(generate_bgm.call_args.kwargs["prompt"], "gentle documentary")
        self.assertTrue(
            generate_video.call_args.kwargs["bgm_file_override"].endswith(
                "elevenlabs-bgm-1.mp3"
            )
        )

    def test_generate_final_videos_falls_back_on_elevenlabs_failure(self):
        """When ElevenLabs fails temporarily, the video without music and a structured warning must be kept."""
        params = VideoParams(video_subject="test", bgm_type="elevenlabs")

        with (
            patch.object(tm.video, "combine_videos"),
            patch.object(
                tm.elevenlabs_music,
                "generate_bgm",
                side_effect=tm.elevenlabs_music.ElevenLabsMusicError(
                    "temporary outage"
                ),
            ),
            patch.object(tm.video, "generate_video") as generate_video,
            patch.object(tm.sm.state, "update_task"),
        ):
            final_paths, _, warnings = tm.generate_final_videos(
                task_id="elevenlabs-fallback",
                params=params,
                downloaded_videos=["material.mp4"],
                audio_file="audio.mp3",
                subtitle_path="",
                audio_duration=5,
            )

        self.assertEqual(len(final_paths), 1)
        self.assertEqual(
            warnings,
            [{"code": "elevenlabs_bgm_failed", "video_index": 1}],
        )
        self.assertEqual(generate_video.call_args.kwargs["bgm_file_override"], "")

    def test_generate_final_videos_falls_back_without_bgm_on_sonilo_failure(self):
        """When third-party music fails, the video should be completed with a visible warning, rather than discarding all outputs."""
        params = VideoParams(video_subject="test", bgm_type="sonilo")

        with (
            patch.object(tm.video, "combine_videos"),
            patch.object(
                tm.sonilo,
                "generate_bgm",
                side_effect=tm.sonilo.SoniloError("temporary outage"),
            ),
            patch.object(tm.video, "generate_video") as generate_video,
            patch.object(tm.sm.state, "update_task"),
        ):
            final_paths, _, warnings = tm.generate_final_videos(
                task_id="sonilo-fallback",
                params=params,
                downloaded_videos=["material.mp4"],
                audio_file="audio.mp3",
                subtitle_path="",
                audio_duration=5,
            )

        self.assertEqual(len(final_paths), 1)
        self.assertEqual(warnings, [{"code": "sonilo_bgm_failed", "video_index": 1}])
        self.assertEqual(generate_video.call_args.kwargs["bgm_file_override"], "")

    def test_generate_final_videos_skips_sonilo_when_volume_is_zero(self):
        """0 volume must skip Sonilo generation entirely and explicitly disable leftover background music."""
        params = VideoParams(
            video_subject="test",
            bgm_type="sonilo",
            bgm_volume=0.0,
            bgm_file="stale-custom-bgm.mp3",
        )

        with (
            patch.object(tm.video, "combine_videos"),
            patch.object(tm.sonilo, "generate_bgm") as generate_bgm,
            patch.object(tm.video, "generate_video", return_value=True) as generate,
            patch.object(tm.sm.state, "update_task"),
        ):
            final_paths, _, warnings = tm.generate_final_videos(
                task_id="sonilo-zero-volume",
                params=params,
                downloaded_videos=["material.mp4"],
                audio_file="audio.mp3",
                subtitle_path="",
                audio_duration=5,
            )

        self.assertEqual(len(final_paths), 1)
        self.assertEqual(warnings, [])
        generate_bgm.assert_not_called()
        self.assertEqual(generate.call_args.kwargs["bgm_file_override"], "")

    def test_generate_final_videos_warns_when_sonilo_mix_fails(self):
        """When Sonilo generation succeeds but the final mix fails, the task must keep the video and return a warning."""
        params = VideoParams(video_subject="test", bgm_type="sonilo")

        with (
            patch.object(tm.video, "combine_videos"),
            patch.object(
                tm.sonilo,
                "generate_bgm",
                side_effect=lambda **kwargs: kwargs["output_path"],
            ),
            patch.object(tm.video, "generate_video", return_value=False) as generate,
            patch.object(tm.sm.state, "update_task"),
        ):
            final_paths, _, warnings = tm.generate_final_videos(
                task_id="sonilo-mix-fallback",
                params=params,
                downloaded_videos=["material.mp4"],
                audio_file="audio.mp3",
                subtitle_path="",
                audio_duration=5,
            )

        self.assertEqual(len(final_paths), 1)
        self.assertEqual(warnings, [{"code": "sonilo_bgm_failed", "video_index": 1}])
        self.assertTrue(generate.call_args.kwargs["bgm_file_override"].endswith(".m4a"))

    def test_run_pipeline_fails_fast_when_ffmpeg_is_not_ready(self):
        """The full video pipeline must confirm FFmpeg is available before the LLM/TTS/material services."""
        params = VideoParams(video_subject="test")
        state = MemoryState()
        with (
            patch.object(tm.utils, "check_ffmpeg_ready", return_value=False),
            patch.object(tm, "generate_script") as generate_script,
            patch.object(tm, "generate_audio") as generate_audio,
            patch.object(tm, "get_video_materials") as get_materials,
            patch.object(tm.sm, "state", state),
        ):
            result = tm.start("ffmpeg-missing", params)

        generate_script.assert_not_called()
        generate_audio.assert_not_called()
        get_materials.assert_not_called()
        self.assertEqual(result["state"], tm.const.TASK_STATE_FAILED)
        self.assertEqual(result["failed_stage"], "preflight")
        self.assertIn("ffmpeg", result["error"])

    def test_run_pipeline_skips_ffmpeg_check_for_script_stage(self):
        """The script stage involves no audio/video composition and shouldn't be rejected for missing FFmpeg."""
        params = VideoParams(video_subject="test")
        state = MemoryState()
        with (
            patch.object(tm.utils, "check_ffmpeg_ready", return_value=False) as check,
            patch.object(tm, "generate_script", return_value="脚本") as generate_script,
            patch.object(tm.sm, "state", state),
        ):
            result = tm.start("ffmpeg-missing-script-stage", params, stop_at="script")

        check.assert_not_called()
        generate_script.assert_called_once()
        self.assertEqual(result, {"script": "脚本"})

    def test_custom_script_keeps_literal_error_text(self):
        """A user's narration about errors is not an LLM provider failure."""
        scripts = (
            "The server logged Error: 404 before the page loaded.",
            "Error: 404 is the status shown when a page is missing.",
        )
        for index, script in enumerate(scripts):
            with self.subTest(script=script):
                task_id = f"literal-error-script-{index}"
                state = MemoryState()
                params = VideoParams(video_subject="debugging", video_script=script)
                with patch.object(tm.sm, "state", state):
                    result = tm.start(task_id, params, stop_at="script")

                self.assertEqual(result, {"script": script})
                self.assertEqual(
                    state.get_task(task_id)["state"], tm.const.TASK_STATE_COMPLETE
                )

    def test_generated_script_still_rejects_provider_error_prefix(self):
        """The provider's error sentinel must still stop generated scripts."""
        state = MemoryState()
        params = VideoParams(video_subject="debugging")
        with (
            patch.object(tm, "generate_script", return_value="Error: invalid API key"),
            patch.object(tm.sm, "state", state),
        ):
            result = tm.start("generated-script-error", params, stop_at="script")

        self.assertEqual(result["state"], tm.const.TASK_STATE_FAILED)
        self.assertEqual(result["failed_stage"], "script")
        self.assertEqual(result["error"], "invalid API key")

    def test_run_pipeline_skips_ffmpeg_check_for_terms_stage(self):
        """The search term stage doesn't need FFmpeg either and shouldn't trigger probing."""
        params = VideoParams(video_subject="test")
        state = MemoryState()
        with (
            patch.object(tm.utils, "check_ffmpeg_ready", return_value=False) as check,
            patch.object(tm, "generate_script", return_value="脚本"),
            patch.object(tm, "generate_terms", return_value=["term"]),
            patch.object(tm, "save_script_data"),
            patch.object(tm.sm, "state", state),
        ):
            result = tm.start("ffmpeg-missing-terms-stage", params, stop_at="terms")

        check.assert_not_called()
        self.assertEqual(result, {"script": "脚本", "terms": ["term"]})

    def test_run_pipeline_proceeds_past_ffmpeg_preflight_when_ready(self):
        """When FFmpeg is available, probing shouldn't block later script generation."""
        params = VideoParams(video_subject="test")
        state = MemoryState()
        with (
            patch.object(tm.utils, "check_ffmpeg_ready", return_value=True) as check,
            patch.object(tm, "generate_script", return_value="脚本") as generate_script,
            patch.object(tm.sm, "state", state),
        ):
            result = tm.start("ffmpeg-ready", params, stop_at="script")

        # Even though the script stage doesn't require FFmpeg, verify here that the probe function is skipped,
        # consistent with the convention of "only checking in stages other than script/terms".
        check.assert_not_called()
        generate_script.assert_called_once()
        self.assertEqual(result, {"script": "脚本"})

    def test_start_rejects_missing_sonilo_key_before_costly_pipeline_steps(self):
        """A full task missing the Sonilo Key must not call the LLM, TTS or material services first."""
        params = VideoParams(video_subject="test", bgm_type="sonilo")
        state = MemoryState()
        with (
            patch.object(tm.sonilo, "is_enabled", return_value=False),
            patch.object(tm, "generate_script") as generate_script,
            patch.object(tm, "generate_audio") as generate_audio,
            patch.object(tm, "get_video_materials") as get_materials,
            patch.object(tm.sm, "state", state),
        ):
            result = tm.start("missing-sonilo-key", params)

        generate_script.assert_not_called()
        generate_audio.assert_not_called()
        get_materials.assert_not_called()
        failed_task = state.get_task("missing-sonilo-key")
        self.assertEqual(result, failed_task)
        self.assertEqual(failed_task["state"], tm.const.TASK_STATE_FAILED)
        self.assertEqual(failed_task["failed_stage"], "preflight")
        self.assertIn("API key", failed_task["error"])

    def test_start_does_not_require_sonilo_key_when_volume_is_zero(self):
        """0 volume doesn't use Sonilo, so a missing Key should still enter the normal task pipeline."""
        params = VideoParams(
            video_subject="test",
            bgm_type="sonilo",
            bgm_volume=0.0,
        )
        state = MemoryState()
        with (
            patch.object(tm.sonilo, "is_enabled", return_value=False),
            patch.object(tm, "generate_script", return_value="") as generate_script,
            patch.object(tm.sm, "state", state),
        ):
            result = tm.start("zero-volume-without-key", params)

        generate_script.assert_called_once_with("zero-volume-without-key", params)
        self.assertEqual(result["failed_stage"], "script")

    def test_loomloom_material_failure_keeps_remote_run_id(self):
        """When a remote run fails after being created, the task state must keep the LoomLoom run ID."""
        params = VideoParams(video_subject="AI 办公", video_source="loomloom")
        settings = tm.loomloom.LoomLoomSettings(
            base_url="https://example.test/loom/v1",
            api_token="test-token",
            market_listing_id=tm.loomloom.DEFAULT_SCRIPT_MARKET_LISTING_ID,
        )
        batch = tm.loomloom.LoomLoomVideoBatch(
            input_rows=(
                {
                    "scenePrompt": "office worker",
                    "aspectRatio": "9:16",
                    "sceneIndex": "1",
                },
            ),
        )
        request = tm.loomloom.LoomLoomConfirmedVideoRequest(
            settings=settings,
            batch=batch,
            listing_version_id="version-1",
            client_request_id="mpt-video-1",
        )
        backend = MagicMock()
        backend.execute.return_value = tm.loomloom.LoomLoomExecution(
            run_id="run-1",
            transaction_id="transaction-1",
            transaction_status="running",
            listing_version_id="version-1",
        )
        backend.wait_for_run.side_effect = tm.loomloom.LoomLoomRunError(
            "remote run timeout"
        )
        state = MemoryState()
        state.update_task(
            "loomloom-material-timeout",
            state=tm.const.TASK_STATE_PROCESSING,
            progress=40,
        )

        with (
            patch.object(tm.sm, "state", state),
            patch.object(
                tm.loomloom,
                "LoomLoomVideoBackend",
                return_value=backend,
            ),
        ):
            result = tm.get_video_materials(
                "loomloom-material-timeout",
                params,
                ["office worker"],
                10,
                loomloom_video_request=request,
            )

        self.assertIsNone(result)
        failed_task = state.get_task("loomloom-material-timeout")
        self.assertEqual(failed_task["state"], tm.const.TASK_STATE_FAILED)
        self.assertEqual(failed_task["failed_stage"], "materials")
        self.assertEqual(failed_task["loomloom_run_id"], "run-1")
        self.assertEqual(failed_task["loomloom_listing_version_id"], "version-1")

    def test_wavespeed_paid_material_failure_keeps_prediction_id(self):
        """Tasks that are unconfirmed, or paid but failed to download, should keep the recovery ID in their state."""
        params = VideoParams(video_subject="test", video_source="wavespeed")
        for error_type in (
            tm.material.WaveSpeedUnconfirmedTaskError,
            tm.material.WaveSpeedDownloadError,
        ):
            with self.subTest(error_type=error_type):
                state = MemoryState()
                state.update_task("wavespeed-paid-failure", progress=40)
                with (
                    patch.object(tm.sm, "state", state),
                    patch.object(
                        tm.material,
                        "download_videos",
                        side_effect=error_type(
                            "paid run unavailable", prediction_id="pred-123"
                        ),
                    ),
                ):
                    result = tm.get_video_materials(
                        "wavespeed-paid-failure", params, ["scene"], 10
                    )

                self.assertIsNone(result)
                failed_task = state.get_task("wavespeed-paid-failure")
                self.assertEqual(failed_task["state"], tm.const.TASK_STATE_FAILED)
                self.assertEqual(failed_task["failed_stage"], "materials")
                self.assertEqual(failed_task["wavespeed_prediction_id"], "pred-123")

    def test_paid_openai_image_failure_stops_at_material_stage(self):
        """Ambiguous and unusable paid image results must stay visible as failures."""
        params = VideoParams(video_subject="test", video_source="openai_image")
        for error_type in (
            tm.material.OpenAIImageUnconfirmedError,
            tm.material.OpenAIImagePaidResultError,
        ):
            with self.subTest(error_type=error_type):
                state = MemoryState()
                state.update_task("openai-image-paid-failure", progress=40)
                with (
                    patch.object(tm.sm, "state", state),
                    patch.object(
                        tm.material,
                        "download_videos",
                        side_effect=error_type("paid image unavailable"),
                    ),
                ):
                    result = tm.get_video_materials(
                        "openai-image-paid-failure", params, ["scene"], 10
                    )

                self.assertIsNone(result)
                failed_task = state.get_task("openai-image-paid-failure")
                self.assertEqual(failed_task["state"], tm.const.TASK_STATE_FAILED)
                self.assertEqual(failed_task["failed_stage"], "materials")
                self.assertIn("paid image unavailable", failed_task["error"])

    def test_loomloom_state_failure_does_not_abandon_paid_remote_run(self):
        """When the state backend is unavailable, remote tasks that have started billing must still be waited on and downloaded."""
        params = VideoParams(video_subject="AI 办公", video_source="loomloom")
        settings = tm.loomloom.LoomLoomSettings(
            base_url="https://example.test/loom/v1",
            api_token="test-token",
            market_listing_id=tm.loomloom.DEFAULT_VIDEO_MARKET_LISTING_ID,
        )
        request = tm.loomloom.LoomLoomConfirmedVideoRequest(
            settings=settings,
            batch=tm.loomloom.LoomLoomVideoBatch(
                input_rows=(
                    {
                        "scenePrompt": "office worker",
                        "aspectRatio": "9:16",
                        "sceneIndex": "1",
                    },
                )
            ),
            listing_version_id="version-1",
            client_request_id="mpt-video-state-failure",
        )
        backend = MagicMock()
        backend.execute.return_value = tm.loomloom.LoomLoomExecution(
            run_id="paid-run-1",
            transaction_id="transaction-1",
            transaction_status="running",
            listing_version_id="version-1",
        )
        backend.download_video_results.return_value = ("clip.mp4",)
        unavailable_state = MagicMock()
        unavailable_state.patch_task.side_effect = RuntimeError("Redis unavailable")

        with (
            patch.object(tm.sm, "state", unavailable_state),
            patch.object(
                tm.loomloom,
                "LoomLoomVideoBackend",
                return_value=backend,
            ),
            patch.object(tm.time, "sleep") as sleep,
        ):
            result = tm.get_video_materials(
                "loomloom-state-failure",
                params,
                ["office worker"],
                10,
                loomloom_video_request=request,
            )

        self.assertEqual(result, ["clip.mp4"])
        self.assertEqual(
            unavailable_state.patch_task.call_count,
            tm._LOOMLOOM_STATE_WRITE_ATTEMPTS,
        )
        self.assertEqual(
            sleep.call_count,
            tm._LOOMLOOM_STATE_WRITE_ATTEMPTS - 1,
        )
        backend.wait_for_run.assert_called_once_with("paid-run-1")
        backend.download_video_results.assert_called_once()

    def test_mark_task_failed_preserves_a_specific_service_failure(self):
        """When the service layer already recorded a specific error, the orchestration layer must not overwrite it with a generic error."""
        state = MemoryState()
        state.update_task(
            "specific-service-failure",
            state=tm.const.TASK_STATE_FAILED,
            progress=40,
            failed_stage="materials",
            error="remote run timed out",
            loomloom_run_id="run-1",
        )

        with patch.object(tm.sm, "state", state):
            result = tm._mark_task_failed(
                "specific-service-failure",
                "materials",
                "failed to prepare video materials",
            )

        self.assertEqual(result["error"], "remote run timed out")
        self.assertEqual(result["loomloom_run_id"], "run-1")

    def test_start_rejects_missing_elevenlabs_key_before_pipeline_steps(self):
        """A full task missing the ElevenLabs Key must fail before any paid step."""
        params = VideoParams(video_subject="test", bgm_type="elevenlabs")
        state = MemoryState()
        with (
            patch.object(tm.elevenlabs_music, "is_enabled", return_value=False),
            patch.object(tm, "generate_script") as generate_script,
            patch.object(tm, "generate_audio") as generate_audio,
            patch.object(tm.sm, "state", state),
        ):
            result = tm.start("missing-elevenlabs-key", params)

        generate_script.assert_not_called()
        generate_audio.assert_not_called()
        self.assertEqual(result["state"], tm.const.TASK_STATE_FAILED)
        self.assertEqual(result["failed_stage"], "preflight")
        self.assertIn("ElevenLabs", result["error"])

    def test_start_rejects_free_elevenlabs_plan_before_pipeline_steps(self):
        """A confirmed free plan must not consume LLM, TTS or material service quota first."""
        params = VideoParams(video_subject="test", bgm_type="elevenlabs")
        state = MemoryState()
        with (
            patch.object(tm.elevenlabs_music, "is_enabled", return_value=True),
            patch.object(
                tm.elevenlabs_music,
                "validate_generation_access",
                side_effect=(
                    tm.elevenlabs_music.ElevenLabsPaidPlanRequiredError(
                        "ElevenLabs Music API requires a paid plan"
                    )
                ),
            ) as validate_access,
            patch.object(tm, "generate_script") as generate_script,
            patch.object(tm, "generate_audio") as generate_audio,
            patch.object(tm.sm, "state", state),
        ):
            result = tm.start("free-elevenlabs-plan", params)

        validate_access.assert_called_once_with()
        generate_script.assert_not_called()
        generate_audio.assert_not_called()
        self.assertEqual(result["failed_stage"], "preflight")
        self.assertIn("paid plan", result["error"])

    def test_start_rejects_oversized_elevenlabs_prompt_before_account_check(self):
        """When the API/CLI bypasses the WebUI, overly long prompts must also be rejected before expensive steps."""
        params = VideoParams(
            video_subject="test",
            bgm_type="elevenlabs",
            video_music_prompt="x" * 1001,
        )
        state = MemoryState()
        with (
            patch.object(tm.elevenlabs_music, "is_enabled", return_value=True),
            patch.object(
                tm.elevenlabs_music, "validate_generation_access"
            ) as validate_access,
            patch.object(tm, "generate_script") as generate_script,
            patch.object(tm.sm, "state", state),
        ):
            result = tm.start("oversized-elevenlabs-prompt", params)

        validate_access.assert_not_called()
        generate_script.assert_not_called()
        self.assertEqual(result["failed_stage"], "preflight")
        self.assertIn("1000", result["error"])

    def test_generate_terms_uses_script_order_mode_when_enabled(self):
        """
        The default mode is unaffected; only when the user explicitly enables script-order material matching does the task layer
        ask the LLM for ordered keywords and increase the keyword count appropriately to cover more script segments.
        """
        params = VideoParams(
            video_subject="城市通勤",
            video_script="",
            match_materials_to_script=True,
        )

        with patch.object(
            tm.llm, "generate_terms", return_value=["city", "train"]
        ) as generate:
            result = tm.generate_terms("task-id", params, "先城市，再地铁")

        self.assertEqual(result, ["city", "train"])
        generate.assert_called_once_with(
            video_subject="城市通勤",
            video_script="先城市，再地铁",
            amount=8,
            match_script_order=True,
        )

    def test_start_stops_before_materials_when_term_provider_fails(self):
        """
        After the keyword Provider fails, the task must end immediately and must not continue generating audio or downloading materials.

        This covers the full error propagation path from the task entry, so a future fix to only the service layer's return type
        can't have the task orchestration layer turn the empty list into some other truthy value and continue making external requests.
        """
        params = VideoParams(
            video_subject="startup story",
            video_script="A short startup story.",
        )
        state = MemoryState()

        with (
            patch.object(
                tm.llm,
                "_generate_response",
                return_value="Error: invalid API key",
            ),
            patch.object(tm, "generate_audio") as generate_audio,
            patch.object(tm, "get_video_materials") as get_video_materials,
            patch.object(tm.sm, "state", state),
        ):
            result = tm.start("term-provider-error", params)

        generate_audio.assert_not_called()
        get_video_materials.assert_not_called()
        failed_task = state.get_task("term-provider-error")
        self.assertEqual(result, failed_task)
        self.assertEqual(failed_task["state"], tm.const.TASK_STATE_FAILED)
        self.assertEqual(failed_task["failed_stage"], "terms")
        self.assertTrue(failed_task["error"])

    def test_generate_audio_uses_custom_file_inside_task_directory(self):
        task_id = "test-custom-audio-safe"
        task_dir = utils.task_dir(task_id)
        self.addCleanup(shutil.rmtree, task_dir, ignore_errors=True)
        custom_audio_file = os.path.join(task_dir, "custom-audio.mp3")
        with open(custom_audio_file, "wb") as audio:
            audio.write(b"fake audio")

        params = VideoParams(
            video_subject="custom audio",
            video_script="",
            custom_audio_file=custom_audio_file,
            voice_name="test-voice",
        )

        with (
            patch.object(tm.voice, "tts") as tts,
            patch.object(tm.voice, "get_audio_duration", return_value=7),
        ):
            audio_file, audio_duration, sub_maker = tm.generate_audio(
                task_id, params, "script"
            )

        self.assertEqual(audio_file, os.path.realpath(custom_audio_file))
        self.assertEqual(audio_duration, 7)
        self.assertIsNone(sub_maker)
        tts.assert_not_called()

    def test_generate_audio_rejects_server_side_custom_file_by_default(self):
        task_id = "test-custom-audio-untrusted-server-side"
        task_dir = utils.task_dir(task_id)
        self.addCleanup(shutil.rmtree, task_dir, ignore_errors=True)
        state = MemoryState()

        with tempfile.NamedTemporaryFile(suffix=".mp3") as server_audio:
            server_audio.write(b"fake audio")
            server_audio.flush()
            params = VideoParams(
                video_subject="custom audio",
                video_script="",
                custom_audio_file=server_audio.name,
                voice_name="test-voice",
            )

            with (
                patch.object(tm.voice, "tts") as tts,
                patch.object(tm.voice, "get_audio_duration") as get_duration,
                patch.object(tm.sm, "state", state),
            ):
                audio_file, audio_duration, result_sub_maker = tm.generate_audio(
                    task_id, params, "script"
                )

        self.assertIsNone(audio_file)
        self.assertIsNone(audio_duration)
        self.assertIsNone(result_sub_maker)
        tts.assert_not_called()
        get_duration.assert_not_called()
        failed_task = state.get_task(task_id)
        self.assertEqual(failed_task["failed_stage"], "audio")
        self.assertIn("current task directory", failed_task["error"])

    def test_external_custom_audio_error_does_not_reveal_file_existence(self):
        task_id = "test-custom-audio-existence-oracle"
        task_dir = utils.task_dir(task_id)
        self.addCleanup(shutil.rmtree, task_dir, ignore_errors=True)

        with tempfile.NamedTemporaryFile(suffix=".mp3") as server_audio:
            external_paths = [server_audio.name, f"{server_audio.name}.missing"]
            errors = []
            for external_path in external_paths:
                with self.assertRaises(ValueError) as raised:
                    tm.resolve_custom_audio_file(task_id, external_path)
                errors.append(str(raised.exception))

        self.assertEqual(errors[0], errors[1])
        self.assertIn("current task directory", errors[0])

    def test_generate_audio_accepts_server_side_custom_file_for_trusted_cli(self):
        task_id = "test-custom-audio-server-side"
        task_dir = utils.task_dir(task_id)
        self.addCleanup(shutil.rmtree, task_dir, ignore_errors=True)

        with tempfile.NamedTemporaryFile(suffix=".mp3") as server_audio:
            server_audio.write(b"fake audio")
            server_audio.flush()
            params = VideoParams(
                video_subject="custom audio",
                video_script="",
                custom_audio_file=server_audio.name,
                voice_name="test-voice",
            )

            with (
                patch.object(tm.voice, "tts") as tts,
                patch.object(tm.voice, "get_audio_duration", return_value=6),
            ):
                audio_file, audio_duration, result_sub_maker = tm.generate_audio(
                    task_id,
                    params,
                    "script",
                    allow_server_file_input=True,
                )

        self.assertEqual(audio_file, os.path.realpath(server_audio.name))
        self.assertEqual(audio_duration, 6)
        self.assertIsNone(result_sub_maker)
        tts.assert_not_called()

    def test_generate_audio_rejects_missing_custom_file_without_tts(self):
        task_id = "test-custom-audio-missing"
        task_dir = utils.task_dir(task_id)
        self.addCleanup(shutil.rmtree, task_dir, ignore_errors=True)
        missing_audio_file = os.path.join(task_dir, "missing.mp3")
        params = VideoParams(
            video_subject="custom audio",
            video_script="",
            custom_audio_file=missing_audio_file,
            voice_name="test-voice",
        )
        state = MemoryState()

        with (
            patch.object(tm.voice, "tts") as tts,
            patch.object(tm.sm, "state", state),
        ):
            audio_file, audio_duration, result_sub_maker = tm.generate_audio(
                task_id, params, "script"
            )

        self.assertIsNone(audio_file)
        self.assertIsNone(audio_duration)
        self.assertIsNone(result_sub_maker)
        tts.assert_not_called()
        failed_task = state.get_task(task_id)
        self.assertEqual(failed_task["failed_stage"], "audio")
        self.assertIn("does not exist", failed_task["error"])

    def test_generate_audio_prefers_file_duration_over_sub_maker(self):
        # Every fixture deliberately makes the file duration and the SubMaker
        # duration ceil to DIFFERENT integers. If someone "simplifies" them to
        # values that share a ceil, this test can no longer tell which source
        # the implementation used - it stops discriminating, silently.
        cases = (
            # The maintainer's own reproduction numbers from the PR discussion.
            (8.4, 7.8375, 9),
            # An exact-integer file duration: proves math.ceil() is really
            # used and rules out int()+1 style code that adds a spurious
            # second. The SubMaker value ceils to 7, so 8 can only come
            # from the file.
            (8.0, 6.2, 8),
            # File duration shorter than the SubMaker value: the only case
            # where this change makes audio_duration smaller than before (the
            # old code returned 8). The contract is "the file wins", not
            # "the larger value wins".
            (5.0, 7.8375, 5),
        )

        for file_duration, sub_maker_duration, expected in cases:
            with self.subTest(file_duration=file_duration):
                task_id = f"test-tts-audio-priority-{uuid4().hex}"
                task_dir = utils.task_dir(task_id)
                self.addCleanup(shutil.rmtree, task_dir, ignore_errors=True)
                audio_path = os.path.join(task_dir, "audio.mp3")
                params = VideoParams(
                    video_subject="tts audio",
                    video_script="",
                    voice_name="test-voice",
                )
                sub_maker = MagicMock()

                def fake_duration(target, _file=file_duration, _sub=sub_maker_duration):
                    # Dispatch on argument type, never on call order: a
                    # sequence side_effect would still pass against an
                    # implementation that measured the SubMaker first, which
                    # is exactly the regression this test exists to catch.
                    return _file if isinstance(target, str) else _sub

                with (
                    patch.object(tm.voice, "tts", return_value=sub_maker) as tts,
                    patch.object(
                        tm.voice, "get_audio_duration", side_effect=fake_duration
                    ) as get_duration,
                ):
                    audio_file, audio_duration, result_sub_maker = tm.generate_audio(
                        task_id, params, "script"
                    )

                self.assertEqual(audio_file, audio_path)
                self.assertEqual(audio_duration, expected)
                # Asserting the value alone would still pass an
                # implementation returning 9.0; the type assertion pins the
                # other side of the rounding contract, so a refactor cannot
                # drop math.ceil() and pass the float straight through.
                self.assertIsInstance(audio_duration, int)
                self.assertIs(result_sub_maker, sub_maker)
                tts.assert_called_once()
                # When file measurement succeeds the SubMaker must not be
                # measured at all: exactly one call, and that call's argument
                # is the audio file path. Both assertions together are what
                # prove the priority order.
                self.assertEqual(len(get_duration.call_args_list), 1)
                self.assertEqual(get_duration.call_args_list[0].args[0], audio_path)

    def test_generate_audio_falls_back_to_sub_maker_when_file_duration_is_zero(self):
        task_id = "test-tts-audio-fallback"
        task_dir = utils.task_dir(task_id)
        self.addCleanup(shutil.rmtree, task_dir, ignore_errors=True)
        audio_path = os.path.join(task_dir, "audio.mp3")
        params = VideoParams(
            video_subject="tts audio",
            video_script="",
            voice_name="test-voice",
        )
        sub_maker = MagicMock()

        def fake_duration(target):
            # voice.get_audio_duration() returns 0.0 when file measurement
            # fails (missing file or decode error); only then may the
            # SubMaker word-boundary duration be used.
            return 0.0 if isinstance(target, str) else 7.8375

        with (
            patch.object(tm.voice, "tts", return_value=sub_maker),
            patch.object(
                tm.voice, "get_audio_duration", side_effect=fake_duration
            ) as get_duration,
        ):
            audio_file, audio_duration, result_sub_maker = tm.generate_audio(
                task_id, params, "script"
            )

        self.assertEqual(audio_file, audio_path)
        self.assertEqual(audio_duration, 8)
        self.assertIsInstance(audio_duration, int)
        self.assertIs(result_sub_maker, sub_maker)
        self.assertEqual(len(get_duration.call_args_list), 2)
        self.assertEqual(get_duration.call_args_list[0].args[0], audio_path)
        self.assertIs(get_duration.call_args_list[1].args[0], sub_maker)

    def test_generate_audio_fails_when_file_and_sub_maker_durations_are_zero(self):
        # This change replaces the source of audio_duration, so the
        # pre-existing zero-duration guard must be proven to still fire
        # rather than be bypassed by the new file-measurement branch.
        task_id = "test-tts-audio-zero-duration"
        task_dir = utils.task_dir(task_id)
        params = VideoParams(
            video_subject="tts audio",
            video_script="",
            voice_name="test-voice",
        )
        sub_maker = MagicMock()

        try:
            with (
                patch.object(tm.voice, "tts", return_value=sub_maker),
                patch.object(tm.voice, "get_audio_duration", return_value=0.0),
                patch.object(tm, "_mark_task_failed") as mark_task_failed,
            ):
                audio_file, audio_duration, result_sub_maker = tm.generate_audio(
                    task_id, params, "script"
                )
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

        self.assertIsNone(audio_file)
        self.assertIsNone(audio_duration)
        self.assertIsNone(result_sub_maker)
        mark_task_failed.assert_called_once_with(
            task_id, "audio", "generated audio duration is zero"
        )

    def test_generate_subtitle_uses_whisper_for_custom_audio_without_sub_maker(self):
        """
        Custom audio doesn't go through TTS, so there's no sub_maker.
        Whisper can transcribe directly from the audio file, so it must not be skipped early by the guard for an empty sub_maker.
        """
        task_id = "test-custom-audio-whisper-subtitle"
        task_dir = utils.task_dir(task_id)
        audio_file = os.path.join(task_dir, "custom-audio.mp3")
        Path(audio_file).write_bytes(b"fake audio")
        params = VideoParams(
            video_subject="custom audio",
            video_script="Hello world.",
            subtitle_enabled=True,
            # When testing the whole-sentence correction path the mode must be specified explicitly, not inherited from the dev machine's WebUI preference.
            subtitle_display_mode="sentence",
        )

        def fake_whisper_create(audio_file, subtitle_file, word_level=False):
            self.assertFalse(word_level)
            Path(subtitle_file).write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello world.\n\n",
                encoding="utf-8",
            )

        try:
            with (
                patch.object(
                    tm.config,
                    "app",
                    dict(tm.config.app, subtitle_provider="whisper"),
                ),
                patch.object(
                    tm.subtitle, "create", side_effect=fake_whisper_create
                ) as create,
                patch.object(tm.subtitle, "correct") as correct,
            ):
                subtitle_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Hello world.",
                    sub_maker=None,
                    audio_file=audio_file,
                )
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

        self.assertTrue(subtitle_path.endswith("subtitle.srt"))
        created_path = create.call_args.kwargs["subtitle_file"]
        self.assertNotEqual(created_path, subtitle_path)
        self.assertEqual(Path(created_path).parent, Path(subtitle_path).parent)
        create.assert_called_once_with(
            audio_file=audio_file,
            subtitle_file=created_path,
            word_level=False,
        )
        correct.assert_called_once_with(
            subtitle_file=created_path, video_script="Hello world."
        )

    def test_generate_subtitle_uses_whisper_word_timing_without_correction(self):
        """
        Word-level mode must pass word_level to Whisper and skip whole-sentence correction against the script.

        If correct() still ran, the just-generated word entries would be re-aggregated, so although the UI chose
        word-level display, the final video would still show sentences.
        """
        task_id = "test-custom-audio-whisper-word-subtitle"
        task_dir = utils.task_dir(task_id)
        audio_file = os.path.join(task_dir, "custom-audio.mp3")
        Path(audio_file).write_bytes(b"fake audio")
        params = VideoParams(
            video_subject="custom audio",
            video_script="Hello world.",
            subtitle_enabled=True,
            subtitle_display_mode="word_by_word",
        )

        def fake_whisper_create(audio_file, subtitle_file, word_level=False):
            self.assertTrue(word_level)
            Path(subtitle_file).write_text(
                "1\n00:00:00,000 --> 00:00:00,500\nHello\n\n",
                encoding="utf-8",
            )

        try:
            with (
                patch.object(
                    tm.config,
                    "app",
                    dict(tm.config.app, subtitle_provider="whisper"),
                ),
                patch.object(
                    tm.subtitle, "create", side_effect=fake_whisper_create
                ) as create,
                patch.object(tm.subtitle, "correct") as correct,
            ):
                subtitle_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Hello world.",
                    sub_maker=None,
                    audio_file=audio_file,
                )
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

        self.assertTrue(subtitle_path.endswith("subtitle.srt"))
        created_path = create.call_args.kwargs["subtitle_file"]
        self.assertNotEqual(created_path, subtitle_path)
        self.assertEqual(Path(created_path).parent, Path(subtitle_path).parent)
        create.assert_called_once_with(
            audio_file=audio_file,
            subtitle_file=created_path,
            word_level=True,
        )
        correct.assert_not_called()

    def test_generate_subtitle_skips_edge_provider_without_sub_maker(self):
        """
        Edge subtitles rely on the sub_maker timeline returned by TTS.
        When custom audio lacks that object it should keep skipping, avoiding an untrustworthy subtitle timeline.
        """
        task_id = "test-custom-audio-edge-no-submaker"
        task_dir = utils.task_dir(task_id)
        audio_file = os.path.join(task_dir, "custom-audio.mp3")
        Path(audio_file).write_bytes(b"fake audio")
        params = VideoParams(
            video_subject="custom audio",
            video_script="Hello world.",
            subtitle_enabled=True,
        )

        try:
            with (
                patch.object(
                    tm.config,
                    "app",
                    dict(tm.config.app, subtitle_provider="edge"),
                ),
                patch.object(tm.voice, "create_subtitle") as create_subtitle,
                patch.object(tm.subtitle, "create") as whisper_create,
            ):
                subtitle_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Hello world.",
                    sub_maker=None,
                    audio_file=audio_file,
                )
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

        self.assertEqual(subtitle_path, "")
        create_subtitle.assert_not_called()
        whisper_create.assert_not_called()

    def test_generate_subtitle_does_not_fallback_to_whisper_when_edge_fails(self):
        """
        When Edge produces no subtitle file, the result without subtitles should be kept, and the Whisper model must not be downloaded automatically.

        This scenario can be triggered when the TTS timeline can't be matched with the original script. An automatic fallback would make users who didn't choose
        Whisper unexpectedly download a multi-GB model, so it must verify Whisper is never called.
        """
        task_id = "test-edge-subtitle-without-output"
        task_dir = utils.task_dir(task_id)
        params = VideoParams(
            video_subject="edge subtitle",
            video_script="Hello world.",
            subtitle_enabled=True,
        )
        sub_maker = object()

        try:
            with (
                patch.object(
                    tm.config,
                    "app",
                    dict(tm.config.app, subtitle_provider="edge"),
                ),
                patch.object(tm.voice, "create_subtitle") as create_subtitle,
                patch.object(tm.subtitle, "create") as whisper_create,
                patch.object(tm.subtitle, "correct") as whisper_correct,
            ):
                subtitle_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Hello world.",
                    sub_maker=sub_maker,
                    audio_file=os.path.join(task_dir, "audio.mp3"),
                )
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

        self.assertEqual(subtitle_path, "")
        create_subtitle.assert_called_once()
        whisper_create.assert_not_called()
        whisper_correct.assert_not_called()

    def test_start_returns_each_intermediate_result(self):
        """
        The API's script, terms, audio, subtitle and materials modes share the same task
        pipeline. Each early stop point must return its corresponding output without wrongly running later stages.
        """
        expected_results = {
            "script": {"script": "generated script"},
            "terms": {
                "script": "generated script",
                "terms": ["coffee", "morning"],
            },
            "audio": {"audio_file": "audio.mp3", "audio_duration": 5},
            "subtitle": {"subtitle_path": "subtitle.srt"},
            "materials": {"materials": ["clip.mp4"]},
        }

        for stop_at, expected in expected_results.items():
            with self.subTest(stop_at=stop_at):
                params = VideoParams(video_subject="Coffee")
                with (
                    patch.object(
                        tm, "generate_script", return_value="generated script"
                    ),
                    patch.object(
                        tm,
                        "generate_terms",
                        return_value=["coffee", "morning"],
                    ),
                    patch.object(tm, "save_script_data"),
                    patch.object(
                        tm,
                        "generate_audio",
                        return_value=("audio.mp3", 5, object()),
                    ),
                    patch.object(
                        tm,
                        "generate_subtitle",
                        return_value="subtitle.srt",
                    ),
                    patch.object(
                        tm,
                        "get_video_materials",
                        return_value=["clip.mp4"],
                    ),
                    patch.object(tm, "generate_final_videos") as generate_final,
                    patch.object(tm.sm.state, "update_task"),
                ):
                    result = tm.start(
                        f"intermediate-{stop_at}", params, stop_at=stop_at
                    )

                self.assertEqual(result, expected)
                generate_final.assert_not_called()

    def test_start_forwards_trusted_server_file_flag_to_audio_stage(self):
        params = VideoParams(video_subject="CLI custom audio")

        with (
            patch.object(tm.utils, "check_ffmpeg_ready", return_value=True),
            patch.object(tm, "generate_script", return_value="generated script"),
            patch.object(tm, "generate_terms", return_value=["audio"]),
            patch.object(tm, "save_script_data"),
            patch.object(
                tm,
                "generate_audio",
                return_value=("audio.mp3", 5, None),
            ) as generate_audio,
            patch.object(tm.sm.state, "update_task"),
        ):
            result = tm.start(
                "trusted-cli-audio",
                params,
                stop_at="audio",
                allow_server_file_input=True,
            )

        self.assertEqual(result, {"audio_file": "audio.mp3", "audio_duration": 5})
        generate_audio.assert_called_once_with(
            "trusted-cli-audio",
            params,
            "generated script",
            voice_preview=None,
            allow_server_file_input=True,
        )

    def test_start_completes_video_without_cross_posting(self):
        """
        A full task should still complete reliably when auto-publishing isn't configured, writing all intermediate outputs into the final
        state. This also covers the compatibility conversion of a string concat mode the API may pass.
        """
        params = VideoParams(video_subject="Coffee")
        params.video_concat_mode = "sequential"

        with (
            patch.object(tm, "generate_script", return_value="generated script"),
            patch.object(tm, "generate_terms", return_value=["coffee"]),
            patch.object(tm, "save_script_data"),
            patch.object(
                tm,
                "generate_audio",
                return_value=("audio.mp3", 5, object()),
            ),
            patch.object(tm, "generate_subtitle", return_value="subtitle.srt"),
            patch.object(
                tm,
                "get_video_materials",
                return_value=["clip.mp4"],
            ),
            patch.object(
                tm,
                "generate_final_videos",
                return_value=(["final.mp4"], ["combined.mp4"], []),
            ),
            patch.object(
                tm.upload_post.upload_post_service,
                "is_configured",
                return_value=False,
            ),
            patch.object(tm.upload_post, "cross_post_video") as cross_post,
            patch.object(tm.sm.state, "update_task") as update_task,
        ):
            result = tm.start("complete-video", params)

        self.assertEqual(result["videos"], ["final.mp4"])
        self.assertEqual(result["combined_videos"], ["combined.mp4"])
        self.assertEqual(result["cross_post_results"], None)
        self.assertEqual(params.video_concat_mode, tm.VideoConcatMode.sequential)
        cross_post.assert_not_called()
        update_task.assert_called_with(
            "complete-video",
            state=tm.const.TASK_STATE_COMPLETE,
            progress=100,
            **result,
        )

    def test_start_marks_pipeline_failures(self):
        """
        When any key output — audio, materials or the final video — is missing, the task must enter the failed state rather than
        misreporting an incomplete task as complete. The three scenarios reuse the same mocks, replacing only the failing stage.
        """
        failure_cases = {
            "audio": (
                (None, None, None),
                ["clip.mp4"],
                (["final.mp4"], ["combined.mp4"], []),
            ),
            "materials": (
                ("audio.mp3", 5, object()),
                None,
                (["final.mp4"], ["combined.mp4"], []),
            ),
            "video": (("audio.mp3", 5, object()), ["clip.mp4"], ([], [], [])),
        }

        for stage, failure_results in failure_cases.items():
            with self.subTest(stage=stage):
                audio_result, materials_result, videos_result = failure_results
                params = VideoParams(video_subject="Coffee")
                state = MemoryState()
                with (
                    patch.object(
                        tm, "generate_script", return_value="generated script"
                    ),
                    patch.object(tm, "generate_terms", return_value=["coffee"]),
                    patch.object(tm, "save_script_data"),
                    patch.object(tm, "generate_audio", return_value=audio_result),
                    patch.object(tm, "generate_subtitle", return_value="subtitle.srt"),
                    patch.object(
                        tm,
                        "get_video_materials",
                        return_value=materials_result,
                    ),
                    patch.object(
                        tm,
                        "generate_final_videos",
                        return_value=videos_result,
                    ),
                    patch.object(tm.sm, "state", state),
                ):
                    result = tm.start(f"failed-{stage}", params)

                failed_task = state.get_task(f"failed-{stage}")
                self.assertEqual(result, failed_task)
                self.assertEqual(failed_task["state"], tm.const.TASK_STATE_FAILED)
                self.assertEqual(failed_task["failed_stage"], stage)
                self.assertTrue(failed_task["error"])

    def test_start_records_unexpected_pipeline_exception(self):
        """Unexpected exceptions must also end the task and expose the original exception type and message to the API."""
        params = VideoParams(video_subject="Coffee")
        state = MemoryState()

        with (
            patch.object(
                tm,
                "generate_script",
                side_effect=RuntimeError("provider connection reset"),
            ),
            patch.object(tm.sm, "state", state),
        ):
            result = tm.start("unexpected-failure", params)

        failed_task = state.get_task("unexpected-failure")
        self.assertEqual(result, failed_task)
        self.assertEqual(failed_task["state"], tm.const.TASK_STATE_FAILED)
        self.assertEqual(failed_task["failed_stage"], "pipeline")
        self.assertEqual(
            failed_task["error"],
            "RuntimeError: provider connection reset",
        )

    def test_start_generates_youtube_metadata_for_each_cross_post(self):
        """
        When auto-publishing to YouTube, metadata is generated only once, but the same fields must be passed to every
        video, and the task result keeps the independent success or failure of each upload.
        """
        params = VideoParams(
            video_subject="Coffee",
            video_language="en",
        )
        metadata = {
            "title": "Morning Coffee",
            "caption": "A better morning.",
            "hashtags": ["coffee", "shorts"],
        }
        service = tm.upload_post.upload_post_service
        state = MemoryState()

        def run_immediately(function, *args):
            future = Future()
            try:
                function(*args)
            except Exception as exc:
                future.set_exception(exc)
            else:
                future.set_result(None)
            return future

        with (
            patch.object(tm, "generate_script", return_value="generated script"),
            patch.object(tm, "generate_terms", return_value=["coffee"]),
            patch.object(tm, "save_script_data"),
            patch.object(
                tm,
                "generate_audio",
                return_value=("audio.mp3", 5, object()),
            ),
            patch.object(tm, "generate_subtitle", return_value="subtitle.srt"),
            patch.object(
                tm,
                "get_video_materials",
                return_value=["clip.mp4"],
            ),
            patch.object(
                tm,
                "generate_final_videos",
                return_value=(
                    ["final-1.mp4", "final-2.mp4"],
                    ["combined-1.mp4", "combined-2.mp4"],
                    [],
                ),
            ),
            patch.object(service, "is_configured", return_value=True),
            patch.object(type(service), "auto_upload", new_callable=PropertyMock, return_value=True),
            patch.object(type(service), "platforms", new_callable=PropertyMock, return_value=["youtube"]),
            patch.object(type(service), "youtube_privacy_status", new_callable=PropertyMock, return_value="unlisted"),
            patch.object(type(service), "youtube_made_for_kids", new_callable=PropertyMock, return_value=True),
            patch.object(
                tm.llm,
                "generate_social_metadata",
                return_value=metadata,
            ) as generate_metadata,
            patch.object(
                tm.upload_post,
                "cross_post_video",
                side_effect=[
                    {"success": True},
                    {"success": False, "error": "upload failed"},
                ],
            ) as cross_post,
            patch.object(tm.sm, "state", state),
            patch.object(
                tm._cross_post_executor,
                "submit",
                side_effect=run_immediately,
            ),
        ):
            result = tm.start("youtube-cross-post", params)

        generate_metadata.assert_called_once_with(
            video_subject="Coffee",
            video_script="generated script",
            language="en",
            platform="youtube_shorts",
        )
        expected_extra = {
            "youtube_title": "Morning Coffee",
            "youtube_description": "A better morning.",
            "tags": ["coffee", "shorts"],
            "privacyStatus": "unlisted",
            "selfDeclaredMadeForKids": True,
            "containsSyntheticMedia": True,
        }
        self.assertEqual(cross_post.call_count, 2)
        for call in cross_post.call_args_list:
            self.assertEqual(call.kwargs["youtube_extra"], expected_extra)
            self.assertEqual(call.kwargs["platforms"], ["youtube"])

        # start() returns a stable snapshot as of video completion; background publish results are obtained via task queries.
        self.assertEqual(result["cross_post_state"], tm.const.CROSS_POST_STATE_PENDING)
        self.assertIsNone(result["cross_post_results"])
        published_task = state.get_task("youtube-cross-post")
        self.assertEqual(published_task["state"], tm.const.TASK_STATE_COMPLETE)
        self.assertEqual(
            published_task["cross_post_state"], tm.const.CROSS_POST_STATE_FAILED
        )
        self.assertEqual(
            published_task["cross_post_results"],
            [
                {"success": True},
                {"success": False, "error": "upload failed"},
            ],
        )
        self.assertEqual(published_task["cross_post_error"], "upload failed")

    def test_start_returns_before_cross_post_worker_runs(self):
        """When a video task completes it only submits the publish work and must not upload synchronously in the generation thread."""
        params = VideoParams(video_subject="Coffee")
        service = tm.upload_post.upload_post_service
        state = MemoryState()
        submitted = []

        def capture_submission(function, *args):
            submitted.append((function, args))
            return MagicMock(spec=Future)

        with (
            patch.object(tm, "generate_script", return_value="generated script"),
            patch.object(tm, "generate_terms", return_value=["coffee"]),
            patch.object(tm, "save_script_data"),
            patch.object(
                tm,
                "generate_audio",
                return_value=("audio.mp3", 5, object()),
            ),
            patch.object(tm, "generate_subtitle", return_value="subtitle.srt"),
            patch.object(tm, "get_video_materials", return_value=["clip.mp4"]),
            patch.object(
                tm,
                "generate_final_videos",
                return_value=(["final.mp4"], ["combined.mp4"], []),
            ),
            patch.object(service, "is_configured", return_value=True),
            patch.object(type(service), "auto_upload", new_callable=PropertyMock, return_value=True),
            patch.object(type(service), "platforms", new_callable=PropertyMock, return_value=["tiktok"]),
            patch.object(type(service), "youtube_privacy_status", new_callable=PropertyMock, return_value="private"),
            patch.object(tm.upload_post, "cross_post_video") as cross_post,
            patch.object(tm.sm, "state", state),
            patch.object(
                tm._cross_post_executor,
                "submit",
                side_effect=capture_submission,
            ) as submit,
        ):
            result = tm.start("deferred-cross-post", params)

        submit.assert_called_once()
        cross_post.assert_not_called()
        self.assertEqual(result["videos"], ["final.mp4"])
        self.assertEqual(result["cross_post_state"], tm.const.CROSS_POST_STATE_PENDING)
        completed_task = state.get_task("deferred-cross-post")
        self.assertEqual(completed_task["state"], tm.const.TASK_STATE_COMPLETE)
        self.assertEqual(completed_task["progress"], 100)

        worker, worker_args = submitted[0]
        with (
            patch.object(tm.sm, "state", state),
            patch.object(
                tm.upload_post,
                "cross_post_video",
                return_value={"success": True, "request_id": "upload-1"},
            ),
        ):
            worker(*worker_args)

        published_task = state.get_task("deferred-cross-post")
        self.assertEqual(published_task["videos"], ["final.mp4"])
        self.assertEqual(
            published_task["cross_post_state"], tm.const.CROSS_POST_STATE_COMPLETE
        )

    def test_cross_post_worker_failure_does_not_change_video_completion(self):
        """A publish thread exception may only update the publish state and must not damage the completed video result."""
        state = MemoryState()
        state.update_task(
            "cross-post-worker-failure",
            state=tm.const.TASK_STATE_COMPLETE,
            progress=100,
            videos=["final.mp4"],
            cross_post_state=tm.const.CROSS_POST_STATE_PENDING,
        )

        with (
            patch.object(tm.sm, "state", state),
            patch.object(
                tm.llm,
                "generate_social_metadata",
                side_effect=RuntimeError("metadata provider unavailable"),
            ),
            patch.object(tm.upload_post, "cross_post_video") as cross_post,
        ):
            tm._run_cross_post(
                "cross-post-worker-failure",
                ("final.mp4",),
                "Coffee",
                "A short coffee story.",
                "en",
                ("youtube",),
                "private",
            )

        cross_post.assert_not_called()
        task = state.get_task("cross-post-worker-failure")
        self.assertEqual(task["state"], tm.const.TASK_STATE_COMPLETE)
        self.assertEqual(task["videos"], ["final.mp4"])
        self.assertEqual(task["cross_post_state"], tm.const.CROSS_POST_STATE_FAILED)
        self.assertIn("metadata provider unavailable", task["cross_post_error"])

    def test_background_upload_request_id_is_saved_while_polling(self):
        """An interrupted worker must leave the remote upload ID in task state."""
        state = MemoryState()
        state.update_task(
            "background-upload",
            state=tm.const.TASK_STATE_COMPLETE,
            progress=100,
            videos=["final.mp4"],
            cross_post_state=tm.const.CROSS_POST_STATE_PENDING,
        )
        observed = {}

        def upload_with_background_start(**kwargs):
            kwargs["on_background_start"]("request-42")
            observed.update(state.get_task("background-upload"))
            return {"success": True, "request_id": "request-42"}

        with (
            patch.object(tm.sm, "state", state),
            patch.object(tm.llm, "generate_social_metadata", return_value={}),
            patch.object(
                tm.upload_post,
                "cross_post_video",
                side_effect=upload_with_background_start,
            ),
        ):
            tm._run_cross_post(
                "background-upload",
                ("final.mp4",),
                "Coffee",
                "Coffee script",
                "en",
                ("tiktok",),
                "public",
            )

        self.assertEqual(
            observed["cross_post_state"], tm.const.CROSS_POST_STATE_PROCESSING
        )
        self.assertEqual(
            observed["cross_post_results"][0]["request_id"], "request-42"
        )
        finished = state.get_task("background-upload")
        self.assertEqual(finished["cross_post_state"], tm.const.CROSS_POST_STATE_COMPLETE)
        self.assertEqual(finished["cross_post_results"], [{"success": True, "request_id": "request-42"}])

    def test_background_upload_request_id_survives_worker_error(self):
        """A polling exception must not erase the only remote recovery handle."""
        state = MemoryState()
        state.update_task(
            "background-upload-error",
            state=tm.const.TASK_STATE_COMPLETE,
            progress=100,
            videos=["final.mp4"],
            cross_post_state=tm.const.CROSS_POST_STATE_PENDING,
        )

        def interrupted_upload(**kwargs):
            kwargs["on_background_start"]("request-lost")
            raise RuntimeError("worker stopped during status polling")

        with (
            patch.object(tm.sm, "state", state),
            patch.object(tm.llm, "generate_social_metadata", return_value={}),
            patch.object(
                tm.upload_post,
                "cross_post_video",
                side_effect=interrupted_upload,
            ),
        ):
            tm._run_cross_post(
                "background-upload-error",
                ("final.mp4",),
                "Coffee",
                "Coffee script",
                "en",
                ("tiktok",),
                "public",
            )

        failed = state.get_task("background-upload-error")
        self.assertEqual(failed["cross_post_state"], tm.const.CROSS_POST_STATE_FAILED)
        self.assertEqual(
            failed["cross_post_results"][0]["request_id"], "request-lost"
        )

    def test_start_returns_cross_post_scheduling_failure(self):
        """A synchronous scheduling failure must be reflected in both the task state and the snapshot returned by start()."""
        params = VideoParams(video_subject="Coffee")
        service = tm.upload_post.upload_post_service
        state = MemoryState()

        with (
            patch.object(tm, "generate_script", return_value="generated script"),
            patch.object(tm, "generate_terms", return_value=["coffee"]),
            patch.object(tm, "save_script_data"),
            patch.object(
                tm,
                "generate_audio",
                return_value=("audio.mp3", 5, object()),
            ),
            patch.object(tm, "generate_subtitle", return_value="subtitle.srt"),
            patch.object(tm, "get_video_materials", return_value=["clip.mp4"]),
            patch.object(
                tm,
                "generate_final_videos",
                return_value=(["final.mp4"], ["combined.mp4"], []),
            ),
            patch.object(service, "is_configured", return_value=True),
            patch.object(type(service), "auto_upload", new_callable=PropertyMock, return_value=True),
            patch.object(type(service), "platforms", new_callable=PropertyMock, return_value=["tiktok"]),
            patch.object(type(service), "youtube_privacy_status", new_callable=PropertyMock, return_value="private"),
            patch.object(tm.sm, "state", state),
            patch.object(tm._cross_post_slots, "acquire", return_value=False),
            patch.object(tm._cross_post_executor, "submit") as submit,
        ):
            result = tm.start("cross-post-queue-full-result", params)

        submit.assert_not_called()
        self.assertEqual(result["cross_post_state"], tm.const.CROSS_POST_STATE_FAILED)
        self.assertIn("queue is full", result["cross_post_error"])
        persisted_task = state.get_task("cross-post-queue-full-result")
        self.assertEqual(
            persisted_task["cross_post_state"], tm.const.CROSS_POST_STATE_FAILED
        )
        self.assertEqual(
            persisted_task["cross_post_error"],
            result["cross_post_error"],
        )

    def test_cross_post_schedule_failure_is_recorded_separately(self):
        """When the thread pool rejects new tasks, the video should be kept and a queryable publish error provided."""
        state = MemoryState()
        slots = MagicMock()
        slots.acquire.return_value = True
        state.update_task(
            "cross-post-schedule-failure",
            state=tm.const.TASK_STATE_COMPLETE,
            progress=100,
            videos=["final.mp4"],
            cross_post_state=tm.const.CROSS_POST_STATE_PENDING,
        )

        with (
            patch.object(tm.sm, "state", state),
            patch.object(tm, "_cross_post_slots", slots),
            patch.object(
                tm._cross_post_executor,
                "submit",
                side_effect=RuntimeError("executor is shutting down"),
            ),
        ):
            scheduling_error = tm._schedule_cross_post(
                task_id="cross-post-schedule-failure",
                video_paths=["final.mp4"],
                params=VideoParams(video_subject="Coffee"),
                video_script="A short coffee story.",
                platforms=["tiktok"],
                youtube_privacy_status="private",
            )

        slots.release.assert_called_once_with()
        self.assertIn("executor is shutting down", scheduling_error)
        task = state.get_task("cross-post-schedule-failure")
        self.assertEqual(task["state"], tm.const.TASK_STATE_COMPLETE)
        self.assertEqual(task["videos"], ["final.mp4"])
        self.assertEqual(task["cross_post_state"], tm.const.CROSS_POST_STATE_FAILED)
        self.assertIn("executor is shutting down", task["cross_post_error"])

    def test_cross_post_worker_always_releases_queue_slot(self):
        """When publish work exits abnormally, capacity must still be returned, so later publishes aren't rejected forever."""
        slots = MagicMock()
        state = MemoryState()
        state.update_task(
            "task-id",
            state=tm.const.TASK_STATE_COMPLETE,
            progress=100,
            cross_post_state=tm.const.CROSS_POST_STATE_PENDING,
        )

        with (
            patch.object(tm, "_cross_post_slots", slots),
            patch.object(tm.sm, "state", state),
            patch.object(
                tm,
                "_run_cross_post",
                side_effect=RuntimeError("worker crashed"),
            ),
        ):
            tm._run_cross_post_with_slot("task-id")

        slots.release.assert_called_once_with()
        task = state.get_task("task-id")
        self.assertEqual(task["cross_post_state"], tm.const.CROSS_POST_STATE_FAILED)
        self.assertIn("worker crashed", task["cross_post_error"])

    def test_cross_post_state_backend_failure_is_logged_and_skips_upload(self):
        """When the first state write fails it must not exit silently, nor keep consuming publish quota."""
        state = MagicMock()
        state.patch_task.side_effect = RuntimeError("redis unavailable")

        with (
            patch.object(tm.sm, "state", state),
            patch.object(tm.upload_post, "cross_post_video") as cross_post,
            patch.object(tm.logger, "exception") as log_exception,
            patch.object(tm.time, "sleep") as sleep,
        ):
            tm._run_cross_post(
                "state-backend-failure",
                ("final.mp4",),
                "Coffee",
                "A short coffee story.",
                "en",
                ("tiktok",),
                "private",
            )

        cross_post.assert_not_called()
        self.assertEqual(state.patch_task.call_count, 6)
        self.assertEqual(sleep.call_count, 4)
        self.assertEqual(log_exception.call_count, 2)
        self.assertTrue(
            all(
                "redis unavailable" in call.args[0]
                for call in log_exception.call_args_list
            )
        )

    def test_cross_post_state_update_retries_transient_backend_failure(self):
        """After the state backend fails briefly once, publishing should continue and finally save the completed state."""

        class FlakyMemoryState(MemoryState):
            def __init__(self):
                super().__init__()
                self.patch_calls = 0

            def patch_task(self, task_id, **kwargs):
                self.patch_calls += 1
                if self.patch_calls == 1:
                    raise RuntimeError("temporary redis outage")
                return super().patch_task(task_id, **kwargs)

        state = FlakyMemoryState()
        state.update_task(
            "transient-state-failure",
            state=tm.const.TASK_STATE_COMPLETE,
            progress=100,
            videos=["final.mp4"],
            cross_post_state=tm.const.CROSS_POST_STATE_PENDING,
        )

        with (
            patch.object(tm.sm, "state", state),
            patch.object(
                tm.upload_post,
                "cross_post_video",
                return_value={"success": True, "request_id": "upload-1"},
            ) as cross_post,
            patch.object(tm.time, "sleep") as sleep,
        ):
            tm._run_cross_post(
                "transient-state-failure",
                ("final.mp4",),
                "Coffee",
                "A short coffee story.",
                "en",
                ("tiktok",),
                "private",
            )

        sleep.assert_called_once_with(tm._CROSS_POST_STATE_RETRY_DELAY_SECONDS)
        cross_post.assert_called_once()
        task = state.get_task("transient-state-failure")
        self.assertEqual(task["cross_post_state"], tm.const.CROSS_POST_STATE_COMPLETE)
        self.assertIsNone(task["cross_post_error"])

    def test_cross_post_generates_caption_for_non_youtube_platforms(self):
        """
        TikTok/Instagram publishing must also generate social copy once and use the caption as the shared publish title for all
        videos, rather than sending the raw subject directly.
        """
        metadata = {
            "title": "Coffee Hook",
            "caption": "Watch this coffee ritual.",
            "hashtags": ["#coffee"],
        }
        state = MemoryState()
        cases = {
            "tiktok-first": (("tiktok", "instagram"), "tiktok"),
            "instagram-first": (("instagram", "tiktok"), "instagram_reels"),
        }

        for case_name, (platforms, expected_platform) in cases.items():
            with self.subTest(case=case_name):
                task_id = f"caption-{case_name}"
                state.update_task(
                    task_id,
                    state=tm.const.TASK_STATE_COMPLETE,
                    progress=100,
                    videos=["final.mp4"],
                    cross_post_state=tm.const.CROSS_POST_STATE_PENDING,
                )
                with (
                    patch.object(tm.sm, "state", state),
                    patch.object(
                        tm.llm,
                        "generate_social_metadata",
                        return_value=metadata,
                    ) as generate_metadata,
                    patch.object(
                        tm.upload_post,
                        "cross_post_video",
                        return_value={"success": True},
                    ) as cross_post,
                ):
                    tm._run_cross_post(
                        task_id,
                        ("final.mp4",),
                        "Coffee",
                        "A short coffee story.",
                        "en",
                        platforms,
                        "private",
                    )

                generate_metadata.assert_called_once_with(
                    video_subject="Coffee",
                    video_script="A short coffee story.",
                    language="en",
                    platform=expected_platform,
                )
                cross_post.assert_called_once()
                call = cross_post.call_args
                self.assertEqual(call.kwargs["title"], "Watch this coffee ritual.")
                self.assertEqual(call.kwargs["platforms"], list(platforms))
                self.assertIsNone(call.kwargs["youtube_extra"])
                task = state.get_task(task_id)
                self.assertEqual(
                    task["cross_post_state"], tm.const.CROSS_POST_STATE_COMPLETE
                )

    def test_cross_post_shares_metadata_between_youtube_fields_and_title(self):
        """YouTube-specific fields and the shared publish title must come from the same metadata call."""
        metadata = {
            "title": "Morning Coffee",
            "caption": "A better morning.",
            "hashtags": ["#coffee", "#shorts"],
        }
        state = MemoryState()
        state.update_task(
            "shared-youtube-metadata",
            state=tm.const.TASK_STATE_COMPLETE,
            progress=100,
            videos=["final-1.mp4", "final-2.mp4"],
            cross_post_state=tm.const.CROSS_POST_STATE_PENDING,
        )

        with (
            patch.object(tm.sm, "state", state),
            patch.object(
                tm.llm,
                "generate_social_metadata",
                return_value=metadata,
            ) as generate_metadata,
            patch.object(
                tm.upload_post,
                "cross_post_video",
                return_value={"success": True},
            ) as cross_post,
        ):
            tm._run_cross_post(
                "shared-youtube-metadata",
                ("final-1.mp4", "final-2.mp4"),
                "Coffee",
                "A short coffee story.",
                "en",
                ("youtube",),
                "unlisted",
            )

        generate_metadata.assert_called_once_with(
            video_subject="Coffee",
            video_script="A short coffee story.",
            language="en",
            platform="youtube_shorts",
        )
        expected_extra = {
            "youtube_title": "Morning Coffee",
            "youtube_description": "A better morning.",
            "tags": ["#coffee", "#shorts"],
            "privacyStatus": "unlisted",
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        }
        self.assertEqual(cross_post.call_count, 2)
        for call in cross_post.call_args_list:
            self.assertEqual(call.kwargs["title"], "A better morning.")
            self.assertEqual(call.kwargs["youtube_extra"], expected_extra)

    def test_cross_post_empty_metadata_degrades_to_fallback_title(self):
        """When metadata is missing or empty, fall back step by step, finally keeping the old generic fallback title."""
        state = MemoryState()
        cases = {
            "legacy-string": ({}, "", "Check out this video! #shorts #viral"),
            "title-over-subject": (
                {"title": "Fallback Title", "caption": ""},
                "Coffee",
                "Fallback Title",
            ),
        }

        for case_name, (metadata, subject, expected_title) in cases.items():
            with self.subTest(case=case_name):
                task_id = f"fallback-title-{case_name}"
                state.update_task(
                    task_id,
                    state=tm.const.TASK_STATE_COMPLETE,
                    progress=100,
                    videos=["final.mp4"],
                    cross_post_state=tm.const.CROSS_POST_STATE_PENDING,
                )
                with (
                    patch.object(tm.sm, "state", state),
                    patch.object(
                        tm.llm,
                        "generate_social_metadata",
                        return_value=metadata,
                    ) as generate_metadata,
                    patch.object(
                        tm.upload_post,
                        "cross_post_video",
                        return_value={"success": True},
                    ) as cross_post,
                ):
                    tm._run_cross_post(
                        task_id,
                        ("final.mp4",),
                        subject,
                        "",
                        "",
                        ("tiktok",),
                        "private",
                    )

                generate_metadata.assert_called_once()
                cross_post.assert_called_once()
                self.assertEqual(cross_post.call_args.kwargs["title"], expected_title)

    def test_recover_interrupted_cross_posts_preserves_active_future(self):
        """Startup recovery only handles leftover state; publish tasks still held by the current process must not be affected."""
        state = MemoryState()
        for task_id in (
            "stale-pending",
            "active-processing",
            "inactive-current-owner",
            "remote-processing",
            "already-complete",
        ):
            cross_post_state = {
                "stale-pending": tm.const.CROSS_POST_STATE_PENDING,
                "active-processing": tm.const.CROSS_POST_STATE_PROCESSING,
                "inactive-current-owner": tm.const.CROSS_POST_STATE_PROCESSING,
                "remote-processing": tm.const.CROSS_POST_STATE_PROCESSING,
                "already-complete": tm.const.CROSS_POST_STATE_COMPLETE,
            }[task_id]
            state.update_task(
                task_id,
                state=tm.const.TASK_STATE_COMPLETE,
                progress=100,
                videos=["final.mp4"],
                cross_post_state=cross_post_state,
                cross_post_owner=(
                    "another-host:123:remote"
                    if task_id == "remote-processing"
                    else (
                        tm._cross_post_process_owner
                        if task_id == "inactive-current-owner"
                        else None
                    )
                ),
            )

        active_future = Future()
        tm._register_cross_post_future("active-processing", active_future)
        with patch.object(tm.sm, "state", state):
            recovered = tm.recover_interrupted_cross_posts(page_size=1)

        self.assertEqual(recovered, 2)
        stale_task = state.get_task("stale-pending")
        self.assertEqual(
            stale_task["cross_post_state"], tm.const.CROSS_POST_STATE_FAILED
        )
        self.assertEqual(
            stale_task["cross_post_error"], tm._INTERRUPTED_CROSS_POST_ERROR
        )
        self.assertEqual(
            state.get_task("active-processing")["cross_post_state"],
            tm.const.CROSS_POST_STATE_PROCESSING,
        )
        self.assertEqual(
            state.get_task("inactive-current-owner")["cross_post_state"],
            tm.const.CROSS_POST_STATE_FAILED,
        )
        self.assertEqual(
            state.get_task("remote-processing")["cross_post_state"],
            tm.const.CROSS_POST_STATE_PROCESSING,
        )
        self.assertEqual(
            state.get_task("already-complete")["cross_post_state"],
            tm.const.CROSS_POST_STATE_COMPLETE,
        )
        active_future.set_result(None)

    def test_recover_interrupted_cross_posts_scans_ids_only_once(self):
        """Startup recovery must not depend on the pagination order of multiple independent scans."""
        state = MemoryState()
        for task_id, cross_post_state in (
            ("stale-pending", tm.const.CROSS_POST_STATE_PENDING),
            ("stale-processing", tm.const.CROSS_POST_STATE_PROCESSING),
            ("already-complete", tm.const.CROSS_POST_STATE_COMPLETE),
        ):
            state.update_task(
                task_id,
                state=tm.const.TASK_STATE_COMPLETE,
                progress=100,
                videos=["final.mp4"],
                cross_post_state=cross_post_state,
            )

        with (
            patch.object(tm.sm, "state", state),
            patch.object(state, "list_task_ids", wraps=state.list_task_ids) as list_ids,
            patch.object(
                state, "get_all_tasks", side_effect=AssertionError("pagination used")
            ) as get_all_tasks,
        ):
            recovered = tm.recover_interrupted_cross_posts(page_size=1)

        self.assertEqual(recovered, 2)
        list_ids.assert_called_once_with(scan_count=1)
        get_all_tasks.assert_not_called()
        for task_id in ("stale-pending", "stale-processing"):
            task = state.get_task(task_id)
            self.assertEqual(task["cross_post_state"], tm.const.CROSS_POST_STATE_FAILED)
            self.assertEqual(task["videos"], ["final.mp4"])
        self.assertEqual(
            state.get_task("already-complete")["cross_post_state"],
            tm.const.CROSS_POST_STATE_COMPLETE,
        )

    def test_cross_post_owner_uses_future_registry_for_current_process(self):
        """When the current process has no active Future, both old and new owners with the same PID should be treated as interrupted."""
        stale_owner = f"{tm.socket.gethostname()}:{tm.os.getpid()}:old-instance"

        self.assertFalse(tm._is_cross_post_owner_alive(stale_owner))
        self.assertFalse(tm._is_cross_post_owner_alive(tm._cross_post_process_owner))

    def test_cross_post_owner_detection_handles_process_boundaries(self):
        """Owner probing should cover old records, other hosts and local process error boundaries."""
        hostname = tm.socket.gethostname()

        self.assertFalse(tm._is_cross_post_owner_alive(None))
        self.assertFalse(tm._is_cross_post_owner_alive("invalid-owner"))
        self.assertTrue(tm._is_cross_post_owner_alive("another-host:123:instance"))

        with (
            patch.object(tm.os, "name", "posix"),
            patch.object(tm.os, "kill", side_effect=ProcessLookupError),
        ):
            self.assertFalse(
                tm._is_cross_post_owner_alive(f"{hostname}:987654:dead-instance")
            )
        with (
            patch.object(tm.os, "name", "posix"),
            patch.object(tm.os, "kill", side_effect=PermissionError),
        ):
            self.assertTrue(
                tm._is_cross_post_owner_alive(f"{hostname}:987654:restricted")
            )
        with (
            patch.object(tm.os, "name", "posix"),
            patch.object(tm.os, "kill", side_effect=OSError("inspection failed")),
            patch.object(tm.logger, "warning") as log_warning,
        ):
            self.assertTrue(tm._is_cross_post_owner_alive(f"{hostname}:987654:unknown"))
        self.assertIn("inspection failed", log_warning.call_args.args[0])

        with (
            patch.object(tm.os, "name", "nt"),
            patch.object(tm, "_is_windows_process_alive", return_value=True) as probe,
        ):
            self.assertTrue(tm._is_cross_post_owner_alive(f"{hostname}:987654:windows"))
        probe.assert_called_once_with(987654)

    @unittest.skipUnless(os.name == "nt", "Windows process API test")
    def test_windows_process_probe_is_read_only_and_detects_liveness(self):
        """Windows CI should really verify read-only process probing, without falling back to os.kill."""
        self.assertTrue(tm._is_windows_process_alive(os.getpid()))
        self.assertFalse(tm._is_windows_process_alive(2_147_483_647))

    def test_cross_post_terminal_check_converts_active_state_to_failure(self):
        """When the worker has ended but the state is still active, the final callback must write the failed final state."""
        state = MemoryState()
        state.update_task(
            "unfinished-cross-post",
            state=tm.const.TASK_STATE_COMPLETE,
            progress=100,
            videos=["final.mp4"],
            cross_post_state=tm.const.CROSS_POST_STATE_PROCESSING,
        )

        with patch.object(tm.sm, "state", state):
            tm._ensure_cross_post_terminal_state("unfinished-cross-post")

        task = state.get_task("unfinished-cross-post")
        self.assertEqual(task["videos"], ["final.mp4"])
        self.assertEqual(task["cross_post_state"], tm.const.CROSS_POST_STATE_FAILED)
        self.assertIn("without persisting", task["cross_post_error"])

    def test_cross_post_recovery_reports_state_backend_failure(self):
        """When startup recovery fails to read state it should return None, allowing a later WebUI rerun to retry."""
        state = MagicMock()
        state.list_task_ids.side_effect = RuntimeError("redis unavailable")

        with (
            patch.object(tm.sm, "state", state),
            patch.object(tm.logger, "exception") as log_exception,
        ):
            recovered = tm.recover_interrupted_cross_posts()

        self.assertIsNone(recovered)
        self.assertIn("redis unavailable", log_exception.call_args.args[0])

    def test_cancelled_cross_post_future_releases_slot_and_records_failure(self):
        """When a queued Future is cancelled, capacity must also be released and the failed final state written."""
        state = MemoryState()
        state.update_task(
            "cancelled-cross-post",
            state=tm.const.TASK_STATE_COMPLETE,
            progress=100,
            cross_post_state=tm.const.CROSS_POST_STATE_PENDING,
        )
        slots = MagicMock()
        future = Future()
        tm._register_cross_post_future("cancelled-cross-post", future)
        self.assertTrue(future.cancel())

        with (
            patch.object(tm.sm, "state", state),
            patch.object(tm, "_cross_post_slots", slots),
        ):
            tm._finalize_cross_post_future("cancelled-cross-post", future)

        slots.release.assert_called_once_with()
        self.assertFalse(tm._is_cross_post_active_in_process("cancelled-cross-post"))
        task = state.get_task("cancelled-cross-post")
        self.assertEqual(task["cross_post_state"], tm.const.CROSS_POST_STATE_FAILED)
        self.assertIn("cancelled", task["cross_post_error"])

    @unittest.skipUnless(
        os.getenv("MPT_TEST_REDIS_HOST"),
        "MPT_TEST_REDIS_HOST not set",
    )
    def test_real_redis_recovers_interrupted_cross_post_state(self):
        """Multi-batch scans on a real Redis should recover all leftover publish states and keep the video."""
        state = RedisState(
            host=os.environ["MPT_TEST_REDIS_HOST"],
            port=int(os.getenv("MPT_TEST_REDIS_PORT", "6379")),
            db=int(os.getenv("MPT_TEST_REDIS_DB", "15")),
        )
        task_ids = [f"ci-cross-post-recovery-{uuid4()}" for _ in range(3)]
        for task_id, cross_post_state in zip(
            task_ids,
            (
                tm.const.CROSS_POST_STATE_PENDING,
                tm.const.CROSS_POST_STATE_PROCESSING,
                tm.const.CROSS_POST_STATE_COMPLETE,
            ),
        ):
            state.update_task(
                task_id,
                state=tm.const.TASK_STATE_COMPLETE,
                progress=100,
                videos=["final.mp4"],
                cross_post_state=cross_post_state,
                cross_post_owner="",
            )

        try:
            with patch.object(tm.sm, "state", state):
                recovered = tm.recover_interrupted_cross_posts(page_size=1)

            self.assertGreaterEqual(recovered, 2)
            for task_id in task_ids[:2]:
                task = state.get_task(task_id)
                self.assertEqual(task["videos"], ["final.mp4"])
                self.assertEqual(task["cross_post_state"], tm.const.CROSS_POST_STATE_FAILED)
                self.assertEqual(
                    task["cross_post_error"], tm._INTERRUPTED_CROSS_POST_ERROR
                )
            self.assertEqual(
                state.get_task(task_ids[2])["cross_post_state"],
                tm.const.CROSS_POST_STATE_COMPLETE,
            )
        finally:
            for task_id in task_ids:
                state.delete_task(task_id)

    def test_cross_post_future_exception_is_observed(self):
        """Exceptions raised by the thread pool itself must be logged and not stay in a Future nobody reads."""
        future = Future()
        future.set_exception(RuntimeError("executor worker failed"))

        with patch.object(tm.logger, "error") as log_error:
            tm._finalize_cross_post_future("future-failure", future)

        log_error.assert_called_once()
        self.assertIn("executor worker failed", log_error.call_args.args[0])

    def test_cross_post_queue_full_rejects_only_publishing(self):
        """When the publish queue is full, the video must be kept and no more tasks submitted to the thread pool."""
        state = MemoryState()
        state.update_task(
            "cross-post-queue-full",
            state=tm.const.TASK_STATE_COMPLETE,
            progress=100,
            videos=["final.mp4"],
            cross_post_state=tm.const.CROSS_POST_STATE_PENDING,
        )

        with (
            patch.object(tm.sm, "state", state),
            patch.object(
                tm._cross_post_slots,
                "acquire",
                return_value=False,
            ),
            patch.object(tm._cross_post_executor, "submit") as submit,
        ):
            scheduling_error = tm._schedule_cross_post(
                task_id="cross-post-queue-full",
                video_paths=["final.mp4"],
                params=VideoParams(video_subject="Coffee"),
                video_script="A short coffee story.",
                platforms=["tiktok"],
                youtube_privacy_status="private",
            )

        submit.assert_not_called()
        self.assertIn("queue is full", scheduling_error)
        task = state.get_task("cross-post-queue-full")
        self.assertEqual(task["state"], tm.const.TASK_STATE_COMPLETE)
        self.assertEqual(task["videos"], ["final.mp4"])
        self.assertEqual(task["cross_post_state"], tm.const.CROSS_POST_STATE_FAILED)
        self.assertIn("queue is full", task["cross_post_error"])

    @unittest.skipUnless(
        RUN_INTEGRATION_TESTS,
        "MPT_RUN_INTEGRATION_TESTS not set",
    )
    def test_task_local_materials(self):
        task_id = "00000000-0000-0000-0000-000000000000"
        video_materials = []
        for i in range(1, 4):
            video_materials.append(
                MaterialInfo(
                    provider="local",
                    url=os.path.join(resources_dir, f"{i}.png"),
                    duration=0,
                )
            )

        params = VideoParams(
            video_subject="金钱的作用",
            video_script="金钱不仅是交换媒介，更是社会资源的分配工具。它能满足基本生存需求，如食物和住房，也能提供教育、医疗等提升生活品质的机会。拥有足够的金钱意味着更多选择权，比如职业自由或创业可能。但金钱的作用也有边界，它无法直接购买幸福、健康或真诚的人际关系。过度追逐财富可能导致价值观扭曲，忽视精神层面的需求。理想的状态是理性看待金钱，将其作为实现目标的工具而非终极目的。",
            video_terms="money importance, wealth and society, financial freedom, money and happiness, role of money",
            video_aspect="9:16",
            video_concat_mode="random",
            video_transition_mode="None",
            video_clip_duration=3,
            video_count=1,
            video_source="local",
            video_materials=video_materials,
            video_language="",
            voice_name="zh-CN-XiaoxiaoNeural-Female",
            voice_volume=1.0,
            voice_rate=1.0,
            bgm_type="random",
            bgm_file="",
            bgm_volume=0.2,
            subtitle_enabled=True,
            subtitle_position="bottom",
            custom_position=70.0,
            font_name="MicrosoftYaHeiBold.ttc",
            text_fore_color="#FFFFFF",
            text_background_color=True,
            font_size=60,
            stroke_color="#000000",
            stroke_width=1.5,
            n_threads=2,
            paragraph_number=1,
        )
        result = tm.start(task_id=task_id, params=params)
        self.assertTrue(result.get("videos"))


if __name__ == "__main__":
    unittest.main()
