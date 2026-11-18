import asyncio
import os
import shutil
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import redis
from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.controllers.manager.base_manager import TaskQueueFullError
from app.controllers.manager.redis_manager import RedisTaskManager
from app.controllers.v1 import video as video_controller
from app.models import const
from app.models.exception import HttpException
from app.models.schema import (
    TaskDeletionResponse,
    TaskListResponse,
    TaskQueryResponse,
    TaskVideoRequest,
)
from app.services import material_upload
from app.services import state as sm
from app.utils import utils


class TestVideoControllerHelpers(unittest.TestCase):
    @staticmethod
    def _request(range_header=None):
        headers = {"x-task-id": "request-123"}
        if range_header is not None:
            headers["Range"] = range_header
        return SimpleNamespace(headers=headers, method="GET")

    def test_sanitize_upload_filename_removes_client_path(self):
        """For both Windows and POSIX client paths, only the last safe filename segment may be kept."""
        for filename, expected in (
            (r"C:\videos\clip.MOV", "clip.MOV"),
            ("../../images/photo.png", "photo.png"),
        ):
            with self.subTest(filename=filename):
                self.assertEqual(
                    video_controller._sanitize_upload_filename(filename, "request-123"),
                    expected,
                )

    def test_local_material_list_skips_broken_and_external_symlinks(self):
        """One stale link must not 500 the picker or reveal external file metadata."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            material_dir = root / "materials"
            material_dir.mkdir()
            (material_dir / "clip.mp4").write_bytes(b"video")
            external = root / "private.mp4"
            external.write_bytes(b"private contents")
            try:
                (material_dir / "external.mp4").symlink_to(external)
                (material_dir / "broken.mp4").symlink_to(root / "missing.mp4")
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlinks are unavailable: {exc}")

            with patch.object(
                video_controller.utils, "storage_dir", return_value=str(material_dir)
            ):
                response = video_controller.get_video_materials_list(self._request())

        self.assertEqual(response["data"]["files"], [
            {"name": "clip.mp4", "size": 5, "file": "clip.mp4"}
        ])

    def test_local_material_list_includes_supported_uppercase_extensions(self):
        """Manually copied materials should be listed like uploads on any OS."""
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "photo.PNG").write_bytes(b"image")
            with patch.object(
                video_controller.utils, "storage_dir", return_value=temp_dir
            ):
                response = video_controller.get_video_materials_list(self._request())

        self.assertEqual(response["data"]["files"], [
            {"name": "photo.PNG", "size": 5, "file": "photo.PNG"}
        ])

    def test_fastapi_startup_recovers_interrupted_cross_posts(self):
        """When the API process starts, leftover publish state recovery must run once."""
        from app.services import task as task_service

        with patch.object(task_service, "recover_interrupted_cross_posts") as recover:

            async def run_lifespan():
                async with asgi.application_lifespan(asgi.app):
                    recover.assert_called_once_with()

            asyncio.run(run_lifespan())

    def test_fastapi_startup_resumes_persisted_redis_queue(self):
        """A restart must dispatch queued Redis work before serving requests."""
        from app.services import task as task_service

        with patch("app.controllers.manager.redis_manager.redis.Redis.from_url"):
            manager = RedisTaskManager(2, "redis://localhost:6379/0")

        with (
            patch.object(video_controller, "task_manager", manager),
            patch.object(manager, "check_queue") as check_queue,
            patch.object(manager, "start_queue_dispatcher") as start_dispatcher,
            patch.object(manager, "stop_queue_dispatcher") as stop_dispatcher,
            patch.object(task_service, "recover_interrupted_cross_posts"),
        ):
            async def run_lifespan():
                async with asgi.application_lifespan(asgi.app):
                    self.assertEqual(check_queue.call_count, 2)

            asyncio.run(run_lifespan())

        start_dispatcher.assert_called_once_with()
        stop_dispatcher.assert_called_once_with()

    def test_sanitize_upload_filename_rejects_empty_name(self):
        """Empty filenames and directory placeholders must not enter the server storage path."""
        for filename in ("", ".", "..", "/"):
            with self.subTest(filename=filename):
                with self.assertRaises(HttpException) as raised:
                    video_controller._sanitize_upload_filename(filename, "request-123")
                self.assertEqual(raised.exception.status_code, 400)

    def test_resolve_path_maps_missing_and_unsafe_files(self):
        """Nonexistent files return 404, and invalid paths such as directory traversal return 403."""
        for error, expected_status in (
            ("file does not exist", 404),
            ("path escapes base directory", 403),
        ):
            with self.subTest(error=error):
                with patch.object(
                    video_controller.file_security,
                    "resolve_path_within_directory",
                    side_effect=ValueError(error),
                ):
                    with self.assertRaises(HttpException) as raised:
                        video_controller._resolve_path_within_directory(
                            "/tasks", "../secret", "request-123"
                        )
                self.assertEqual(raised.exception.status_code, expected_status)

    def test_parse_byte_range_supports_common_player_requests(self):
        """The closed, open-ended and suffix ranges common in players should all get accurate boundaries."""
        cases = (
            (None, (0, 9)),
            ("bytes=2-5", (2, 5)),
            ("bytes=4-", (4, 9)),
            ("bytes=-4", (6, 9)),
            ("bytes=2-50", (2, 9)),
        )
        for header, expected in cases:
            with self.subTest(header=header):
                self.assertEqual(
                    video_controller._parse_byte_range(header, 10, "request-123"),
                    expected,
                )

    def test_parse_byte_range_rejects_malformed_or_out_of_bounds_requests(self):
        """Invalid Range must return 416 rather than becoming a 500 because of split or int conversion errors."""
        invalid_headers = (
            "items=0-1",
            "bytes=",
            "bytes=10-",
            "bytes=5-2",
            "bytes=0-1,3-4",
        )
        for header in invalid_headers:
            with self.subTest(header=header):
                with self.assertRaises(HttpException) as raised:
                    video_controller._parse_byte_range(header, 10, "request-123")
                self.assertEqual(raised.exception.status_code, 416)


class TestVideoControllerTasks(unittest.TestCase):
    @staticmethod
    def _request():
        return SimpleNamespace(headers={"x-task-id": "request-123"}, method="GET")

    def test_video_task_rejects_font_outside_font_directory_before_queueing(self):
        """An invalid font path must return 403 before the task is enqueued, without creating a paid background task."""
        with tempfile.TemporaryDirectory() as temp_dir:
            font_dir = Path(temp_dir, "fonts")
            font_dir.mkdir()
            outside = Path(temp_dir, "outside.ttf")
            outside.write_bytes(b"not a font")

            for font_name in (str(outside), "../outside.ttf"):
                with (
                    self.subTest(font_name=font_name),
                    patch.object(video_controller.utils, "font_dir", return_value=str(font_dir)),
                    patch.object(video_controller.sm.state, "update_task") as update_task,
                    patch.object(video_controller.task_manager, "add_task") as add_task,
                ):
                    body = TaskVideoRequest(video_subject="Coffee", font_name=font_name)
                    with self.assertRaises(HttpException) as raised:
                        video_controller.create_task(self._request(), body, stop_at="video")

                    self.assertEqual(raised.exception.status_code, 403)
                    update_task.assert_not_called()
                    add_task.assert_not_called()

    def test_video_task_rejects_font_symlink_outside_font_directory(self):
        """Even if the path string is inside the font directory, a symlink must not be used to read files outside it."""
        with tempfile.TemporaryDirectory() as temp_dir:
            font_dir = Path(temp_dir, "fonts")
            font_dir.mkdir()
            outside = Path(temp_dir, "outside.ttf")
            outside.write_bytes(b"not a font")
            try:
                (font_dir / "linked.ttf").symlink_to(outside)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlinks are unavailable: {exc}")

            with (
                patch.object(video_controller.utils, "font_dir", return_value=str(font_dir)),
                patch.object(video_controller.sm.state, "update_task") as update_task,
                patch.object(video_controller.task_manager, "add_task") as add_task,
            ):
                body = TaskVideoRequest(video_subject="Coffee", font_name="linked.ttf")
                with self.assertRaises(HttpException) as raised:
                    video_controller.create_task(self._request(), body, stop_at="video")

            self.assertEqual(raised.exception.status_code, 403)
            update_task.assert_not_called()
            add_task.assert_not_called()

    def test_video_task_accepts_font_inside_directory_and_ignores_disabled_subtitles(self):
        """Normal fonts can still be enqueued, and with subtitles off the existing compatibility behavior for unused fonts is kept."""
        with tempfile.TemporaryDirectory() as temp_dir:
            font_dir = Path(temp_dir, "fonts")
            font_dir.mkdir()
            (font_dir / "custom.ttf").write_bytes(b"font file")
            cases = (
                TaskVideoRequest(video_subject="Coffee", font_name="custom.ttf"),
                TaskVideoRequest(
                    video_subject="Coffee", subtitle_enabled=False, font_name="../unused.ttf"
                ),
            )
            for body in cases:
                with (
                    self.subTest(font_name=body.font_name, enabled=body.subtitle_enabled),
                    patch.object(video_controller.utils, "font_dir", return_value=str(font_dir)),
                    patch.object(video_controller.sm.state, "update_task") as update_task,
                    patch.object(video_controller.task_manager, "add_task") as add_task,
                ):
                    response = video_controller.create_task(
                        self._request(), body, stop_at="video"
                    )

                self.assertEqual(response["status"], 200)
                update_task.assert_called_once()
                add_task.assert_called_once()

    def test_create_task_queues_requested_pipeline_stage(self):
        """Creating a task should persist the initial state and hand the original request model and stop stage to the queue."""
        body = MagicMock()
        body.model_dump.return_value = {"video_subject": "Coffee"}

        with (
            patch.object(video_controller.utils, "get_uuid", return_value="task-123"),
            patch.object(video_controller.sm.state, "update_task") as update_task,
            patch.object(video_controller.task_manager, "add_task") as add_task,
        ):
            response = video_controller.create_task(
                self._request(), body, stop_at="audio"
            )

        self.assertEqual(response["status"], 200)
        self.assertEqual(response["data"]["task_id"], "task-123")
        self.assertEqual(response["data"]["request_id"], "request-123")
        update_task.assert_called_once_with("task-123")
        add_task.assert_called_once_with(
            video_controller.tm.start,
            task_id="task-123",
            params=body,
            stop_at="audio",
        )

    def test_create_task_removes_state_when_queue_is_full(self):
        """When the queue is full, the just-created state must be rolled back and 429 returned to the caller."""
        body = MagicMock()
        body.model_dump.return_value = {"video_subject": "Coffee"}

        with (
            patch.object(video_controller.utils, "get_uuid", return_value="task-123"),
            patch.object(video_controller.sm.state, "update_task"),
            patch.object(
                video_controller.task_manager,
                "add_task",
                side_effect=TaskQueueFullError("queue full"),
            ),
            patch.object(video_controller.sm.state, "delete_task") as delete_task,
        ):
            with self.assertRaises(HttpException) as raised:
                video_controller.create_task(self._request(), body, stop_at="video")

        self.assertEqual(raised.exception.status_code, 429)
        delete_task.assert_called_once_with("task-123")

    def test_create_task_removes_state_when_scheduler_fails(self):
        """When the scheduler fails to take over the task, no state stuck in processing forever may be left behind."""
        body = MagicMock()
        body.model_dump.return_value = {"video_subject": "Coffee"}
        scheduling_error = RuntimeError("can't start new thread")
        state = sm.MemoryState()

        with (
            patch.object(video_controller.utils, "get_uuid", return_value="task-123"),
            patch.object(video_controller.sm, "state", state),
            patch.object(
                video_controller.task_manager,
                "add_task",
                side_effect=scheduling_error,
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                video_controller.create_task(self._request(), body, stop_at="video")

        self.assertIs(raised.exception, scheduling_error)
        self.assertIsNone(state.get_task("task-123"))

    def test_get_all_tasks_preserves_pagination(self):
        """The task list response must include the total returned by the state layer and the requested pagination parameters."""
        with patch.object(
            video_controller.sm.state,
            "get_all_tasks",
            return_value=([{"id": "task-1", "cross_post_owner": "internal"}], 21),
        ) as get_all:
            response = video_controller.get_all_tasks(
                self._request(), page=2, page_size=10
            )

        self.assertEqual(
            response["data"],
            {
                "tasks": [{"id": "task-1"}],
                "total": 21,
                "page": 2,
                "page_size": 10,
            },
        )
        get_all.assert_called_once_with(2, 10)

    def test_task_list_returns_download_urls_without_mutating_state(self):
        """List and detail endpoints must expose the same usable video URLs."""
        task_id = "listed-task-url"
        task_dir = utils.task_dir(task_id)
        video_path = os.path.join(task_dir, "final-1.mp4")
        audio_path = os.path.join(task_dir, "audio.mp3")
        subtitle_path = os.path.join(task_dir, "subtitle.srt")
        Path(video_path).write_bytes(b"fake-video")
        Path(audio_path).write_bytes(b"fake-audio")
        Path(subtitle_path).write_text("subtitle", encoding="utf-8")
        stored_task = {
            "task_id": task_id,
            "state": const.TASK_STATE_COMPLETE,
            "videos": [video_path],
            "combined_videos": [video_path],
            "audio_file": audio_path,
            "subtitle_path": subtitle_path,
        }

        try:
            with (
                patch.object(
                    video_controller.sm.state,
                    "get_all_tasks",
                    return_value=([stored_task], 1),
                ),
                patch.dict(config.app, {"endpoint": ""}),
            ):
                response = video_controller.get_all_tasks(
                    self._request(), page=1, page_size=10
                )

            listed = response["data"]["tasks"][0]
            expected_url = f"/tasks/{task_id}/final-1.mp4"
            self.assertEqual(listed["videos"], [expected_url])
            self.assertEqual(listed["combined_videos"], [expected_url])
            self.assertEqual(listed["audio_file"], f"/tasks/{task_id}/audio.mp3")
            self.assertEqual(listed["subtitle_path"], f"/tasks/{task_id}/subtitle.srt")
            self.assertEqual(stored_task["videos"], [video_path])
            self.assertEqual(stored_task["audio_file"], audio_path)
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_task_query_returns_relative_url_without_mutating_state(self):
        """
        When endpoint isn't configured, relative task URLs should be returned, and the display URLs must not be written back to the state,
        otherwise later requests might join paths repeatedly on top of rewritten data.
        """
        task_id = "controller-task-url"
        task_dir = utils.task_dir(task_id)
        video_path = os.path.join(task_dir, "final-1.mp4")
        audio_path = os.path.join(task_dir, "audio.mp3")
        subtitle_path = os.path.join(task_dir, "subtitle.srt")
        Path(video_path).write_bytes(b"fake-video")
        Path(audio_path).write_bytes(b"fake-audio")
        Path(subtitle_path).write_text("subtitle", encoding="utf-8")

        try:
            sm.state.update_task(
                task_id,
                state=const.TASK_STATE_COMPLETE,
                videos=[video_path],
                combined_videos=[video_path],
                audio_file=audio_path,
                subtitle_path=subtitle_path,
                cross_post_owner="localhost:123:internal",
            )
            with patch.dict(config.app, {"endpoint": ""}):
                response = video_controller.get_task(
                    self._request(), task_id=task_id, query=MagicMock()
                )

            self.assertEqual(
                response["data"]["videos"],
                [f"/tasks/{task_id}/final-1.mp4"],
            )
            self.assertEqual(response["data"]["audio_file"], f"/tasks/{task_id}/audio.mp3")
            self.assertEqual(response["data"]["subtitle_path"], f"/tasks/{task_id}/subtitle.srt")
            self.assertNotIn("cross_post_owner", response["data"])
            self.assertIn("cross_post_owner", sm.state.get_task(task_id))
            self.assertEqual(sm.state.get_task(task_id)["videos"], [video_path])
        finally:
            sm.state.delete_task(task_id)
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_task_query_preserves_structured_failure_details(self):
        """The failed stage and error message must be returned as-is through the task query endpoint."""
        failed_task = {
            "task_id": "failed-task",
            "state": const.TASK_STATE_FAILED,
            "progress": 30,
            "failed_stage": "audio",
            "error": "TTS request timed out",
        }

        with patch.object(
            video_controller.sm.state,
            "get_task",
            return_value=failed_task,
        ):
            response = video_controller.get_task(
                self._request(), task_id="failed-task", query=MagicMock()
            )

        self.assertEqual(response["data"], failed_task)

    def test_task_query_schema_documents_success_and_failure_states(self):
        """OpenAPI model examples must cover both the publish-success and generation-failure states."""
        examples = TaskQueryResponse.model_json_schema()["examples"]

        self.assertEqual(examples[0]["data"]["cross_post_state"], "complete")
        self.assertEqual(examples[1]["data"]["failed_stage"], "audio")
        self.assertTrue(examples[1]["data"]["error"])

        task_data_schema = TaskQueryResponse.model_json_schema()["$defs"][
            "TaskStatusData"
        ]
        self.assertIn("failed_stage", task_data_schema["properties"])
        self.assertIn("cross_post_state", task_data_schema["properties"])

        list_schema = TaskListResponse.model_json_schema()
        self.assertIn("TaskListData", list_schema["$defs"])
        self.assertIn("TaskStatusData", list_schema["$defs"])

    def test_task_deletion_schema_defines_null_data_contract(self):
        """The OpenAPI schema of TaskDeletionResponse must explicitly declare data as the null type."""
        schema = TaskDeletionResponse.model_json_schema()
        data_property = schema["properties"]["data"]

        self.assertEqual(data_property.get("type"), "null")
        self.assertIsNone(data_property.get("default"))

    def test_delete_rejects_generation_and_cross_posting_tasks(self):
        """Tasks that are generating or publishing are reading their directory, so the delete endpoint must return 409."""
        busy_tasks = (
            {
                "task_id": "generating-task",
                "state": const.TASK_STATE_PROCESSING,
                "progress": 30,
            },
            {
                "task_id": "publishing-task",
                "state": const.TASK_STATE_COMPLETE,
                "progress": 100,
                "cross_post_state": const.CROSS_POST_STATE_PROCESSING,
            },
        )

        for task in busy_tasks:
            with (
                self.subTest(task_id=task["task_id"]),
                patch.object(
                    video_controller.sm.state,
                    "get_task",
                    return_value=task,
                ),
                patch.object(video_controller.sm.state, "delete_task") as delete_task,
            ):
                with self.assertRaises(HttpException) as raised:
                    video_controller.delete_video(
                        self._request(), task_id=task["task_id"]
                    )

                self.assertEqual(raised.exception.status_code, 409)
                delete_task.assert_not_called()

    def test_delete_allows_completed_task(self):
        """Ordinary completed tasks should keep the existing delete behavior."""
        completed_task = {
            "task_id": "completed-task",
            "state": const.TASK_STATE_COMPLETE,
            "progress": 100,
            "cross_post_state": const.CROSS_POST_STATE_COMPLETE,
        }

        with (
            patch.object(
                video_controller.sm.state,
                "get_task",
                return_value=completed_task,
            ),
            patch.object(
                video_controller.utils,
                "task_dir",
                return_value="/tmp/mpt-completed-task-test",
            ),
            patch.object(video_controller.os.path, "exists", return_value=False),
            patch.object(video_controller.sm.state, "delete_task") as delete_task,
        ):
            response = video_controller.delete_video(
                self._request(), task_id="completed-task"
            )

        self.assertEqual(response["status"], 200)
        delete_task.assert_called_once_with("completed-task")

    def test_get_and_delete_missing_task_return_404(self):
        """Querying or deleting an unknown task should consistently return 404, not an empty success response."""
        with patch.object(video_controller.sm.state, "get_task", return_value=None):
            for operation in (
                lambda: video_controller.get_task(
                    self._request(), task_id="missing", query=MagicMock()
                ),
                lambda: video_controller.delete_video(
                    self._request(), task_id="missing"
                ),
            ):
                with self.subTest(operation=operation):
                    with self.assertRaises(HttpException) as raised:
                        operation()
                    self.assertEqual(raised.exception.status_code, 404)


class TestVideoControllerCreateHTTP(unittest.TestCase):
    """Verify out-of-bounds fonts return 403/404 at the real HTTP entry instead of creating a background task.

    Behavior change (PR #1664): create_task's font precheck now goes through the file service wrapper
    `_resolve_path_within_directory`, so out-of-bounds/traversal returns 403 and a missing font returns
    404, consistent with the error codes of the task output endpoints in the same file; 400 is reserved for request body
    ValueError cases such as numeric validation.
    """

    def setUp(self):
        self.original_app_config = dict(config.app)
        config.app["api_key"] = ""
        self.client = TestClient(asgi.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def test_video_request_rejects_font_path_traversal(self):
        with patch.object(video_controller.task_manager, "add_task") as add_task:
            response = self.client.post(
                "/api/v1/videos",
                json={"video_subject": "Coffee", "font_name": "../../README.md"},
            )

        self.assertEqual(response.status_code, 403)
        add_task.assert_not_called()


class TestVideoControllerListHTTP(unittest.TestCase):
    def test_task_page_size_is_bounded_before_state_scan(self):
        """A client cannot request an unbounded Redis scan and response body."""
        with (
            patch.dict(config.app, {"api_key": ""}),
            patch.object(
                video_controller.sm.state,
                "get_all_tasks",
                return_value=([], 0),
            ) as get_all,
        ):
            client = TestClient(asgi.app)
            allowed = client.get("/api/v1/tasks?page_size=1000")
            rejected = client.get("/api/v1/tasks?page_size=1001")

        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(rejected.status_code, 400)
        get_all.assert_called_once_with(1, 1000)


class TestVideoControllerDeleteHTTP(unittest.TestCase):
    """Real HTTP-level regression tests for DELETE /api/v1/tasks/{task_id}."""

    def setUp(self):
        self.original_app_config = dict(config.app)
        # These cases only verify the task deletion protocol; auth behavior is covered by separate tests.
        config.app["api_key"] = ""
        self.client = TestClient(asgi.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def _seed_completed_task(self, task_id: str) -> str:
        """Create a completed task and return its storage directory path."""

        task_dir = utils.task_dir(task_id)
        video_path = os.path.join(task_dir, "final-1.mp4")
        Path(video_path).write_bytes(b"fake-video")
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            videos=[video_path],
            combined_videos=[video_path],
            cross_post_state=const.CROSS_POST_STATE_COMPLETE,
        )
        return task_dir

    def test_delete_completed_task_returns_success_response(self):
        """A successful delete should return 200, and the response body must be the controller's real output (status/message/data)"""

        task_id = "http-delete-success-task"
        task_dir = self._seed_completed_task(task_id)

        try:
            response = self.client.delete(f"/api/v1/tasks/{task_id}")
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)
            sm.state.delete_task(task_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": 200, "message": "success", "data": None},
        )

    def test_deleted_task_lookup_returns_404(self):
        """Querying again after deletion must return 404, confirming the task was really removed from the state store,
        and not just that the delete endpoint's response format is correct."""

        task_id = "http-delete-lookup-task"
        task_dir = self._seed_completed_task(task_id)

        try:
            delete_response = self.client.delete(f"/api/v1/tasks/{task_id}")
            self.assertEqual(delete_response.status_code, 200)

            lookup_response = self.client.get(f"/api/v1/tasks/{task_id}")
        finally:
            # The task should already be deleted by now; only clean up a possibly leftover directory.
            shutil.rmtree(task_dir, ignore_errors=True)

        self.assertEqual(lookup_response.status_code, 404)


class TestVideoControllerFiles(unittest.TestCase):
    @staticmethod
    def _request(range_header=None):
        headers = {"x-task-id": "request-123"}
        if range_header is not None:
            headers["Range"] = range_header
        return SimpleNamespace(headers=headers, method="GET")

    def test_upload_video_material_validates_complete_extension(self):
        """Valid uppercase extensions should be accepted, and pseudo-extensions without a dot rejected."""
        upload = SimpleNamespace(
            filename=r"C:\videos\clip.MOV",
            file=BytesIO(b"video"),
        )
        with patch.object(
            material_upload,
            "save_material_upload",
            return_value="4fca18fce7344f3aa824777a40d45c8c.mov",
        ) as save_material:
            response = video_controller.upload_video_material_file(
                self._request(), upload
            )

        self.assertEqual(
            response["data"]["file"],
            "4fca18fce7344f3aa824777a40d45c8c.mov",
        )
        save_material.assert_called_once_with("clip.MOV", upload.file)

        invalid_upload = SimpleNamespace(
            filename="photojpg",
            file=BytesIO(b"not-an-image"),
        )
        with patch.object(
            material_upload,
            "save_material_upload",
            side_effect=material_upload.MaterialUploadError("unsupported format"),
        ):
            with self.assertRaises(HttpException) as raised:
                video_controller.upload_video_material_file(
                    self._request(), invalid_upload
                )
        self.assertEqual(raised.exception.status_code, 400)

    def test_upload_video_material_maps_service_failure_to_stable_500(self):
        upload = SimpleNamespace(filename="clip.mp4", file=BytesIO(b"video"))
        with patch.object(
            material_upload,
            "save_material_upload",
            side_effect=material_upload.MaterialServiceError(
                "C:\\sensitive\\storage is unavailable"
            ),
        ):
            with self.assertRaises(HttpException) as raised:
                video_controller.upload_video_material_file(self._request(), upload)

        self.assertEqual(raised.exception.status_code, 500)
        self.assertNotIn("sensitive", raised.exception.message)

    def test_stream_video_returns_requested_bytes(self):
        """The body and Content-Range of a Range response must match the computed range."""

        async def consume(response):
            return b"".join([chunk async for chunk in response.body_iterator])

        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "clip.mp4").write_bytes(b"0123456789")
            with patch.object(
                video_controller.utils,
                "task_dir",
                return_value=temp_dir,
            ):
                response = asyncio.run(
                    video_controller.stream_video(
                        self._request("bytes=2-5"), "clip.mp4"
                    )
                )
                body = asyncio.run(consume(response))

        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.headers["content-range"], "bytes 2-5/10")
        self.assertEqual(response.headers["content-length"], "4")
        self.assertEqual(body, b"2345")

    def test_stream_video_without_range_returns_complete_response(self):
        """A normal GET must return the whole video as 200, not partial content."""

        async def consume(response):
            return b"".join([chunk async for chunk in response.body_iterator])

        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "clip.mp4").write_bytes(b"0123456789")
            with patch.object(video_controller.utils, "task_dir", return_value=temp_dir):
                response = asyncio.run(
                    video_controller.stream_video(self._request(), "clip.mp4")
                )
                body = asyncio.run(consume(response))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("content-range", response.headers)
        self.assertEqual(response.headers["accept-ranges"], "bytes")
        self.assertEqual(response.headers["content-length"], "10")
        self.assertEqual(body, b"0123456789")

    def test_stream_video_keeps_file_open_after_response_is_created(self):
        """Streaming must not reopen a file after sending the headers."""

        async def consume(response):
            return b"".join([chunk async for chunk in response.body_iterator])

        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "clip.mp4").write_bytes(b"0123456789")
            with patch.object(video_controller.utils, "task_dir", return_value=temp_dir):
                response = asyncio.run(
                    video_controller.stream_video(self._request("bytes=2-5"), "clip.mp4")
                )
                with patch("builtins.open", side_effect=OSError("file vanished")):
                    body = asyncio.run(consume(response))

        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.headers["content-range"], "bytes 2-5/10")
        self.assertEqual(body, b"2345")

    def test_stream_video_returns_404_if_file_disappears_before_open(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "clip.mp4").write_bytes(b"video")
            with (
                patch.object(video_controller.utils, "task_dir", return_value=temp_dir),
                patch("builtins.open", side_effect=FileNotFoundError),
            ):
                with self.assertRaises(HttpException) as raised:
                    asyncio.run(video_controller.stream_video(self._request(), "clip.mp4"))

        self.assertEqual(raised.exception.status_code, 404)

    def test_download_video_uses_resolved_file(self):
        """The download response should use the real path resolved within the allowlisted directory and the original filename."""
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir, "final-1.mp4")
            video_path.write_bytes(b"video")
            with patch.object(
                video_controller.utils,
                "task_dir",
                return_value=temp_dir,
            ):
                response = asyncio.run(
                    video_controller.download_video(self._request(), "final-1.mp4")
                )

        # On macOS /var is a symlink to /private/var, so safe resolution returns the real path.
        self.assertEqual(response.path, os.path.realpath(video_path))
        self.assertEqual(response.filename, "final-1.mp4")
        self.assertEqual(response.media_type, "video/mp4")

    def test_download_video_encodes_content_disposition_filename(self):
        """
        Download filenames must be encoded according to the HTTP standard.

        Plain ASCII filenames keep using the more compatible filename parameter; as soon as a name contains
        spaces, Chinese or characters sensitive in response headers, UTF-8 filename* should be used instead, avoiding failed browser downloads,
        garbled filenames, or special characters breaking the Content-Disposition header structure.
        """
        cases = (
            ("final-1.mp4", 'attachment; filename="final-1.mp4"'),
            ("video name.mp4", "attachment; filename*=utf-8''video%20name.mp4"),
            (
                "中文 视频.mp4",
                "attachment; filename*=utf-8''%E4%B8%AD%E6%96%87%20"
                "%E8%A7%86%E9%A2%91.mp4",
            ),
            (
                "name=draft;v1(test).mp4",
                "attachment; filename*=utf-8''name%3Ddraft%3Bv1%28test%29.mp4",
            ),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(
                video_controller.utils,
                "task_dir",
                return_value=temp_dir,
            ):
                for filename, expected_header in cases:
                    with self.subTest(filename=filename):
                        Path(temp_dir, filename).write_bytes(b"video")
                        response = asyncio.run(
                            video_controller.download_video(self._request(), filename)
                        )

                        self.assertEqual(
                            response.headers["content-disposition"],
                            expected_header,
                        )


class TestBuildRedisUrl(unittest.TestCase):
    def test_no_password_omits_auth_segment(self):
        """None and empty-string passwords must not embed a literal 'None' or ':@'."""
        from app.controllers.v1.video import _build_redis_url

        self.assertEqual(
            _build_redis_url("localhost", 6379, 0, None),
            "redis://localhost:6379/0",
        )
        self.assertEqual(
            _build_redis_url("localhost", 6379, 0, ""),
            "redis://localhost:6379/0",
        )

    def test_password_is_included_in_url(self):
        from app.controllers.v1.video import _build_redis_url

        self.assertEqual(
            _build_redis_url("redis-host", 6380, 1, "s3cr3t"),
            "redis://:s3cr3t@redis-host:6380/1",
        )

    def test_reserved_characters_in_password_round_trip_through_redis_url(self):
        from app.controllers.v1.video import _build_redis_url

        password = "p@ss:/?#% word"
        url = _build_redis_url("redis-host", 6380, 1, password)

        self.assertEqual(
            redis.Redis.from_url(url).connection_pool.connection_kwargs["password"],
            password,
        )

    def test_ipv6_host_round_trips_through_redis_url(self):
        from app.controllers.v1.video import _build_redis_url

        url = _build_redis_url("::1", 6380, 1, None)
        connection = redis.Redis.from_url(url).connection_pool.connection_kwargs

        self.assertEqual(connection["host"], "::1")
        self.assertEqual(connection["port"], 6380)
        self.assertEqual(connection["db"], 1)


if __name__ == "__main__":
    unittest.main()
