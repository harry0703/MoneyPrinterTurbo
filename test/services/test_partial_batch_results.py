"""Preserve usable results when a later video in the same task fails."""

import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from app.models.schema import VideoParams
from app.services import task as tm
from app.services.state import MemoryState


class TestPartialBatchResults(unittest.TestCase):
    def _run_batch(
        self, directory, state, fail_at=None, failure_stage="render", stop_at="video",
    ):
        task_id = "partial-batch"
        task_directory = Path(directory) / task_id
        task_directory.mkdir(exist_ok=True)
        params = VideoParams(
            video_subject="Coffee", video_count=3, video_source="local",
            subtitle_enabled=False, bgm_type="", match_materials_to_script=False,
        )
        checkpoints = []

        def combine(**kwargs):
            index = int(Path(kwargs["combined_video_path"]).stem.split("-")[-1])
            checkpoints.append(state.get_task(task_id))
            if index == fail_at and failure_stage == "combine":
                raise OSError("simulated combine failure")
            Path(kwargs["combined_video_path"]).write_bytes(b"combined video")
            kwargs["used_video_paths"].append("material.mp4")
            kwargs["progress_callback"](1.0)

        def render(**kwargs):
            output = Path(kwargs["output_file"])
            index = int(output.stem.split("-")[-1])
            if index == fail_at and failure_stage == "render":
                # A leftover file must not be discovered as a completed result.
                output.write_bytes(b"incomplete encoder output")
                raise OSError("simulated render failure")
            output.write_bytes(b"complete encoder output")
            return True

        with ExitStack() as stack:
            for owner, name, options in (
                (tm.sm, "state", {"new": state}),
                (tm.utils, "task_dir", {"side_effect": lambda task=None: os.path.join(directory, task) if task else directory}),
                (tm.utils, "check_ffmpeg_ready", {"return_value": True}),
                (tm, "generate_script", {"return_value": "Coffee script"}),
                (tm, "save_script_data", {}),
                (tm, "generate_audio", {"return_value": (
                    ("", 0, None) if failure_stage == "audio" else ("audio.mp3", 5, None)
                )}),
                (tm, "generate_subtitle", {"return_value": ""}),
                (tm, "get_video_materials", {"return_value": ["material.mp4"]}),
                (tm.task_artifacts, "patch_script_data", {}),
                (tm.video, "combine_videos", {"side_effect": combine}),
                (tm.video, "generate_video", {"side_effect": render}),
                (tm.upload_post.upload_post_service, "is_configured", {"return_value": False}),
            ):
                stack.enter_context(patch.object(owner, name, **options))
            schedule = stack.enter_context(patch.object(tm, "_schedule_cross_post"))
            result = tm.start(task_id, params, stop_at=stop_at)
            schedule.assert_not_called()
        return result, checkpoints

    def test_failure_returns_only_completed_videos_and_the_failed_index(self):
        for stage in ("combine", "render"):
            for fail_at in (1, 2, 3):
                with self.subTest(stage=stage, fail_at=fail_at), tempfile.TemporaryDirectory() as directory:
                    state = MemoryState()
                    result, _ = self._run_batch(directory, state, fail_at, stage)
                    expected_videos = [
                        os.path.join(directory, "partial-batch", f"final-{index}.mp4")
                        for index in range(1, fail_at)
                    ]
                    self.assertEqual(result["videos"], expected_videos)
                    self.assertEqual(result["combined_videos"], [
                        os.path.join(directory, "partial-batch", f"combined-{index}.mp4")
                        for index in range(1, fail_at)
                    ])
                    self.assertEqual(result["failed_video_index"], fail_at)
                    self.assertEqual(result["state"], tm.const.TASK_STATE_FAILED)
                    self.assertEqual(result["failed_stage"], "video")
                    self.assertEqual(result["error"], f"OSError: simulated {stage} failure")
                    self.assertLess(result["progress"], 100)
                    self.assertEqual(result, state.get_task("partial-batch"))
                    self.assertTrue(all(Path(video).is_file() for video in result["videos"]))
                    self.assertTrue(all(
                        warning["video_index"] < fail_at
                        for warning in result.get("warnings") or []
                    ))

    def test_completed_video_is_queryable_before_the_next_video_starts(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MemoryState()
            result, checkpoints = self._run_batch(directory, state)
            self.assertEqual(len(result["videos"]), 3)
            self.assertEqual(state.get_task("partial-batch")["state"], tm.const.TASK_STATE_COMPLETE)
            self.assertEqual(checkpoints[1]["videos"], result["videos"][:1])
            self.assertEqual(checkpoints[2]["videos"], result["videos"][:2])
            self.assertEqual(checkpoints[1]["state"], tm.const.TASK_STATE_PROCESSING)
            self.assertNotIn("failed_video_index", result)

    def test_retry_does_not_return_videos_from_an_earlier_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MemoryState()
            first, _ = self._run_batch(directory, state, fail_at=3)
            self.assertEqual(len(first["videos"]), 2)
            second, _ = self._run_batch(directory, state, fail_at=1)
            self.assertEqual(second["videos"], [])
            self.assertEqual(second["combined_videos"], [])
            self.assertEqual(second["failed_video_index"], 1)
            self.assertIsNone(second.get("warnings"))
            self.assertEqual(second, state.get_task("partial-batch"))

    def test_failed_task_query_returns_download_urls_for_completed_videos(self):
        from app.controllers.v1 import video as controller
        from app.models.schema import TaskQueryResponse

        with tempfile.TemporaryDirectory() as directory:
            state = MemoryState()
            result, _ = self._run_batch(directory, state, fail_at=2)
            public_result = controller._task_response_data(result, "", directory, "request")
            response = TaskQueryResponse(data=public_result).model_dump()
        data = response["data"]
        self.assertEqual(data["state"], tm.const.TASK_STATE_FAILED)
        self.assertEqual(data["failed_video_index"], 2)
        self.assertEqual(data["videos"], ["/tasks/partial-batch/final-1.mp4"])
        self.assertEqual(data["combined_videos"], ["/tasks/partial-batch/combined-1.mp4"])

    def test_checkpoint_error_still_returns_the_completed_file(self):
        class FailOnceState(MemoryState):
            failed_checkpoint = False

            def update_task(self, task_id, *args, **kwargs):
                if (
                    kwargs.get("videos")
                    and kwargs.get("state", tm.const.TASK_STATE_PROCESSING)
                    == tm.const.TASK_STATE_PROCESSING
                    and not self.failed_checkpoint
                ):
                    self.failed_checkpoint = True
                    raise OSError("checkpoint unavailable")
                return super().update_task(task_id, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            state = FailOnceState()
            result, checkpoints = self._run_batch(directory, state)
            self.assertEqual(len(checkpoints), 1)
            self.assertEqual(result["videos"], [
                os.path.join(directory, "partial-batch", "final-1.mp4"),
            ])
            self.assertEqual(result["state"], tm.const.TASK_STATE_FAILED)
            self.assertEqual(result["error"], "OSError: checkpoint unavailable")
            self.assertEqual(result, state.get_task("partial-batch"))

    def test_audio_retry_does_not_return_an_earlier_batchs_videos(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MemoryState()
            first, _ = self._run_batch(directory, state, fail_at=3)
            self.assertEqual(len(first["videos"]), 2)
            second, _ = self._run_batch(
                directory, state, failure_stage="audio", stop_at="audio",
            )
            self.assertEqual(second["failed_stage"], "audio")
            self.assertEqual(second["videos"], [])
            self.assertEqual(second["combined_videos"], [])
            self.assertIsNone(second.get("failed_video_index"))

    def test_repeated_state_errors_do_not_discard_the_completed_snapshot(self):
        class RecoveringState(MemoryState):
            failed_writes = 0

            def update_task(self, task_id, *args, **kwargs):
                if kwargs.get("videos") and self.failed_writes < 2:
                    self.failed_writes += 1
                    raise OSError("state temporarily unavailable")
                return super().update_task(task_id, *args, **kwargs)

            def patch_task(self, task_id, **kwargs):
                if kwargs.get("videos") and self.failed_writes < 2:
                    self.failed_writes += 1
                    raise OSError("state temporarily unavailable")
                return super().patch_task(task_id, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            state = RecoveringState()
            result, checkpoints = self._run_batch(directory, state)
            self.assertEqual(len(checkpoints), 1)
            self.assertEqual(result["videos"], [
                os.path.join(directory, "partial-batch", "final-1.mp4"),
            ])
            self.assertEqual(result["state"], tm.const.TASK_STATE_FAILED)
            self.assertEqual(result["error"], "OSError: state temporarily unavailable")
            self.assertEqual(result, state.get_task("partial-batch"))


if __name__ == "__main__":
    unittest.main()
