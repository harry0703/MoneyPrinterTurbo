import ast
import os
import re
import threading
import time
from collections.abc import Mapping
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from loguru import logger

from app.models import const
from app.models.schema import VideoParams
from app.services import webui_task
from app.utils import logging_utils


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


def _attribute_name(node):
    """Reconstruct an AST call of the form ``module.function`` into a stable string."""
    names = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        names.append(node.id)
    return ".".join(reversed(names))


def _log_record(file_path, message="generation finished"):
    """Build the minimal loguru record ``format_log_record`` needs."""
    return {
        "file": SimpleNamespace(name=os.path.basename(file_path), path=file_path),
        "message": message,
    }


def test_generation_controls_submit_background_task_instead_of_blocking_page():
    """
    The WebUI generate button must not call the synchronous pipeline directly again.

    This is the core regression protection for the Issue #1120 blank screen: as long as the full page script blocks on
    ``tm.start`` again, users who refresh during generation may still receive deltas pointing to an old render tree.
    """
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_render_generation_controls"
    )
    calls = {
        _attribute_name(node.func)
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    }

    assert "webui_task.submit_generation" in calls
    assert "tm.start" not in calls


def test_webui_runtime_config_updates_do_not_use_blocking_writes():
    """
    Ordinary widget reruns during generation must not wait again for the config lock held by the long task.

    All WebUI config writes must go through the non-blocking helpers; the LLM connection test and voice preview may
    use try-lock to return quickly, but page code must not call blocking locks or blocking save functions directly.
    """
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    calls = {
        _attribute_name(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "config.runtime_config_lock" not in calls
    assert "config.save_config" not in calls
    assert not calls.intersection(
        {
            "config.app.clear",
            "config.app.pop",
            "config.app.setdefault",
            "config.app.update",
            "config.azure.clear",
            "config.azure.pop",
            "config.azure.setdefault",
            "config.azure.update",
            "config.chatterbox.clear",
            "config.chatterbox.pop",
            "config.chatterbox.setdefault",
            "config.chatterbox.update",
            "config.elevenlabs.clear",
            "config.elevenlabs.pop",
            "config.elevenlabs.setdefault",
            "config.elevenlabs.update",
            "config.siliconflow.clear",
            "config.siliconflow.pop",
            "config.siliconflow.setdefault",
            "config.siliconflow.update",
            "config.ui.clear",
            "config.ui.pop",
            "config.ui.setdefault",
            "config.ui.update",
        }
    )

    synchronized_sections = {
        "app",
        "azure",
        "chatterbox",
        "elevenlabs",
        "siliconflow",
        "ui",
    }
    direct_writes = []
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]

        for target in targets:
            if not isinstance(target, ast.Subscript):
                continue
            section = target.value
            if (
                isinstance(section, ast.Attribute)
                and isinstance(section.value, ast.Name)
                and section.value.id == "config"
                and section.attr in synchronized_sections
            ):
                direct_writes.append(node.lineno)

    assert direct_writes == []


def test_webui_delete_keeps_task_state_when_file_removal_fails(tmp_path):
    """A failed directory removal must leave the task available for retry."""
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_delete_task"
    )
    task_path = tmp_path / "tasks" / "completed-task"
    task_path.mkdir(parents=True)
    state = SimpleNamespace(
        get_task=MagicMock(
            return_value={"task_id": "completed-task", "state": const.TASK_STATE_COMPLETE}
        ),
        delete_task=MagicMock(),
    )
    remove_directory = MagicMock(side_effect=OSError("video file is locked"))
    namespace = {
        "_active_generation_tasks": lambda: {},
        "sm": SimpleNamespace(state=state),
        "tm": SimpleNamespace(is_task_busy=lambda _task: False),
        "utils": SimpleNamespace(task_dir=lambda: str(tmp_path / "tasks")),
        "shutil": SimpleNamespace(rmtree=remove_directory),
        "logger": MagicMock(),
        "os": os,
        "const": const,
    }
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    exec(compile(module, str(WEBUI_MAIN), "exec"), namespace)

    assert namespace["_delete_task"](
        "completed-task", str(task_path), const.TASK_STATE_COMPLETE
    ) is False
    remove_directory.assert_called_once_with(str(task_path))
    state.delete_task.assert_not_called()


def test_active_task_uses_terminal_state_when_outside_runtime_page(tmp_path):
    """An active session marker must not hide a finished task past page one."""
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_collect_task_summaries"
    )
    namespace = {
        "_scan_history_tasks": lambda limit: [],
        "_active_generation_tasks": lambda: {
            "new-task": {"subject": "Latest video", "mtime": 1000}
        },
        "_task_state_filter_key": lambda task: (
            "failed" if task["state"] == const.TASK_STATE_FAILED else "processing"
        ),
        "sm": SimpleNamespace(
            state=SimpleNamespace(
                get_all_tasks=lambda page, page_size: (
                    [
                        {
                            "task_id": f"old-{index}",
                            "state": const.TASK_STATE_COMPLETE,
                        }
                        for index in range(50)
                    ],
                    51,
                ),
                get_task=MagicMock(
                    return_value={
                        "task_id": "new-task",
                        "state": const.TASK_STATE_FAILED,
                        "progress": 70,
                    }
                ),
            )
        ),
        "utils": SimpleNamespace(task_dir=lambda: str(tmp_path)),
        "os": os,
        "const": const,
        "logger": MagicMock(),
    }
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    exec(compile(module, str(WEBUI_MAIN), "exec"), namespace)

    tasks = namespace["_collect_task_summaries"](limit=20)

    latest = next(task for task in tasks if task["task_id"] == "new-task")
    assert latest["state"] == const.TASK_STATE_FAILED
    assert latest["progress"] == 70
    assert latest["mtime"] == 1000
    namespace["sm"].state.get_task.assert_called_once_with("new-task")


def test_task_summary_tolerates_directory_removed_during_scan():
    """A concurrent deletion between isdir and stat must not crash the panel."""
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_collect_task_summaries"
    )
    getmtime = MagicMock(side_effect=FileNotFoundError("task directory removed"))
    namespace = {
        "_scan_history_tasks": lambda limit: [],
        "_active_generation_tasks": lambda: {},
        "sm": SimpleNamespace(
            state=SimpleNamespace(
                get_all_tasks=lambda page, page_size: (
                    [{"task_id": "removed-task", "state": const.TASK_STATE_COMPLETE}],
                    1,
                )
            )
        ),
        "utils": SimpleNamespace(task_dir=lambda: "/tasks"),
        "os": SimpleNamespace(
            path=SimpleNamespace(
                join=os.path.join,
                isdir=lambda _path: True,
                getmtime=getmtime,
            )
        ),
        "logger": MagicMock(),
    }
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    exec(compile(module, str(WEBUI_MAIN), "exec"), namespace)

    tasks = namespace["_collect_task_summaries"]()

    assert tasks[0]["task_id"] == "removed-task"
    assert tasks[0]["mtime"] == 0
    getmtime.assert_called_once_with(os.path.join("/tasks", "removed-task"))


@pytest.mark.parametrize(
    ("ui_config", "expected_open_count"),
    [
        ({}, 1),
        ({"open_task_folder_on_completion": True}, 1),
        ({"open_task_folder_on_completion": False}, 0),
    ],
)
@pytest.mark.parametrize(
    ("task_state", "has_video"),
    [
        (const.TASK_STATE_COMPLETE, True),
        (const.TASK_STATE_FAILED, True),
        (const.TASK_STATE_FAILED, False),
    ],
)
def test_terminal_task_renders_subject_named_video_download(
    tmp_path, ui_config, expected_open_count, task_state, has_video
):
    """A completed task should offer the video download and decide whether to auto-open the folder based on WebUI config."""
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    selected_nodes = []
    target_names = {
        "_DOWNLOAD_FILENAME_INVALID_PATTERN",
        "_WINDOWS_RESERVED_FILENAMES",
        "_build_video_download_name",
        "_normalize_task_state",
        "_render_generation_task_snapshot",
    }
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in target_names
            for target in node.targets
        ):
            selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in target_names:
            selected_nodes.append(node)

    class FakeColumn:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeStreamlit:
        def __init__(self):
            self.session_state = {}
            self.downloads = []
            self.videos = []
            self.warnings = []
            self.errors = []
            self.successes = []

        def columns(self, count):
            return [FakeColumn() for _ in range(count)]

        def video(self, video_path):
            self.videos.append(video_path)

        def download_button(self, label, data, **kwargs):
            self.downloads.append((label, data.read(), kwargs))

        def success(self, message):
            self.successes.append(message)

        def warning(self, message):
            self.warnings.append(message)

        def error(self, message):
            self.errors.append(message)

    video_path = tmp_path / "final-1.mp4"
    video_path.write_bytes(b"video-content")
    fake_st = FakeStreamlit()
    open_task_folder = MagicMock()
    namespace = {
        "Mapping": Mapping,
        "config": SimpleNamespace(ui=ui_config),
        "const": const,
        "logger": MagicMock(),
        "mimetypes": __import__("mimetypes"),
        "open_task_folder": open_task_folder,
        "os": os,
        "re": re,
        "st": fake_st,
        "tr": lambda key: (
            "Video {index} reused {count} source clips."
            if key == "Batch Material Reuse Warning" else key
        ),
        "_render_generation_logs": lambda _task_id: None,
    }
    module = ast.fix_missing_locations(ast.Module(body=selected_nodes, type_ignores=[]))
    exec(compile(module, str(WEBUI_MAIN), "exec"), namespace)

    namespace["_render_generation_task_snapshot"](
        "download-test",
        {
            "state": task_state,
            "progress": 100,
            "videos": [str(video_path)] if has_video else [],
            "error": "OSError: second encoder failed",
            "warnings": [
                {"code": "batch_materials_reused", "video_index": 2, "count": 3}
            ],
            "video_subject": "A day: in / Shanghai?",
        },
    )

    if task_state == const.TASK_STATE_FAILED:
        expected_open_count = 0
        assert fake_st.errors == ["Video Generation Failed: OSError: second encoder failed"]
        assert fake_st.successes == []
    else:
        assert fake_st.errors == []
        assert fake_st.successes == ["Video Generation Completed"]
    if not has_video:
        assert fake_st.downloads == []
        assert fake_st.videos == []
        open_task_folder.assert_not_called()
        return
    assert fake_st.videos == [str(video_path)]
    assert fake_st.warnings == ["Video 2 reused 3 source clips."]
    assert fake_st.downloads == [
        (
            "Download Video",
            b"video-content",
            {
                "file_name": "A day in Shanghai.mp4",
                "mime": "video/mp4",
                "key": "download_generated_video_download-test_0",
                "icon": ":material/download:",
                "on_click": "ignore",
                "use_container_width": True,
            },
        )
    ]
    assert open_task_folder.call_count == expected_open_count
    if expected_open_count:
        open_task_folder.assert_called_once_with("download-test")


def test_submit_generation_returns_while_pipeline_is_still_running():
    """While the background pipeline hasn't finished, the submit function must have already returned so Streamlit can finish this render."""
    task_id = "background-submit-test"
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocking_start(**_kwargs):
        started.set()
        release.wait(timeout=5)
        finished.set()
        return {"videos": ["/tmp/final-1.mp4"]}

    params = VideoParams(video_subject="异步生成测试")
    try:
        with (
            patch.object(webui_task.tm, "start", side_effect=blocking_start),
            patch.object(
                webui_task.config,
                "runtime_config_lock",
                return_value=nullcontext(),
            ),
        ):
            started_at = time.monotonic()
            webui_task.submit_generation(task_id, params, capture_logs=False)
            elapsed = time.monotonic() - started_at

            assert started.wait(timeout=2)
            assert elapsed < 0.5
            assert not finished.is_set()
            task = webui_task.sm.state.get_task(task_id)
            assert task["state"] == const.TASK_STATE_PROCESSING
    finally:
        release.set()
        assert finished.wait(timeout=2)
        webui_task.sm.state.delete_task(task_id)


def test_submit_generation_copies_params_before_starting_worker():
    """Later page reruns or parameter changes inside the pipeline must not pollute the current form object in reverse."""
    params = VideoParams(video_subject="参数隔离测试")
    with patch.object(webui_task._task_manager, "add_task") as add_task:
        webui_task.submit_generation("copied-params-test", params, capture_logs=False)

    submitted_params = add_task.call_args.kwargs["params"]
    assert submitted_params == params
    assert submitted_params is not params
    webui_task.sm.state.delete_task("copied-params-test")


def test_submit_generation_keeps_voxcpm_reference_audio_out_of_params():
    """Reference audio belongs only to the current in-memory request and must not enter persistable task parameters."""
    params = VideoParams(video_subject="task isolation")
    reference_audio = b"bounded-reference-wav"
    prompt_audio = b"bounded-prompt-wav"
    prompt_text = "delivery transcript"
    with patch.object(webui_task._task_manager, "add_task") as add_task:
        webui_task.submit_generation(
            "reference-audio-isolation",
            params,
            capture_logs=False,
            voxcpm_reference_audio=reference_audio,
            voxcpm_prompt_audio=prompt_audio,
            voxcpm_prompt_text=prompt_text,
        )

    submitted_params = add_task.call_args.kwargs["params"]
    serialized_params = submitted_params.model_dump_json()
    assert "voxcpm_reference_audio" not in serialized_params
    assert "voxcpm_prompt_audio" not in serialized_params
    assert "voxcpm_prompt_text" not in serialized_params
    assert reference_audio.decode("ascii") not in serialized_params
    assert prompt_audio.decode("ascii") not in serialized_params
    assert prompt_text not in serialized_params
    assert add_task.call_args.kwargs["voxcpm_reference_audio"] == reference_audio
    assert add_task.call_args.kwargs["voxcpm_prompt_audio"] == prompt_audio
    assert add_task.call_args.kwargs["voxcpm_prompt_text"] == prompt_text
    webui_task.sm.state.delete_task("reference-audio-isolation")


def test_scheduling_failure_is_saved_as_terminal_task_state():
    """When the queue or thread start fails, the task manager must not stay on "generating" forever."""
    task_id = "scheduling-failure-test"
    params = VideoParams(video_subject="调度失败测试")
    with patch.object(
        webui_task._task_manager,
        "add_task",
        side_effect=RuntimeError("worker unavailable"),
    ):
        with pytest.raises(RuntimeError, match="worker unavailable"):
            webui_task.submit_generation(task_id, params, capture_logs=False)

    task = webui_task.sm.state.get_task(task_id)
    assert task["state"] == const.TASK_STATE_FAILED
    assert task["failed_stage"] == "scheduling"
    assert task["error"] == "RuntimeError: worker unavailable"
    webui_task.sm.state.delete_task(task_id)


def test_worker_logs_are_available_without_streamlit_session_state():
    """Background logs are written to a thread-safe cache, and the page only needs to poll snapshots to restore live logs."""
    task_id = "captured-log-test"
    with webui_task._task_logs_lock:
        webui_task._task_logs.pop(task_id, None)

    def logged_start(**_kwargs):
        logger.info("unique background task log")
        return {"videos": ["/tmp/final-1.mp4"]}

    with (
        patch.object(webui_task.tm, "start", side_effect=logged_start),
        patch.object(
            webui_task.config,
            "runtime_config_lock",
            return_value=nullcontext(),
        ),
    ):
        result = webui_task._run_generation(
            task_id,
            VideoParams(video_subject="日志测试"),
            capture_logs=True,
        )

    assert result == {"videos": ["/tmp/final-1.mp4"]}
    records = webui_task.get_task_logs(task_id)
    assert len(records) == 1
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| INFO \| "
        r'"\./test/services/test_webui_task\.py:\d+": logged_start '
        r"- unique background task log",
        records[0],
    )


def test_bound_helper_thread_logs_reach_the_task_log():
    """
    Parallel downloads, clip encoding and ffmpeg heartbeats all log from helper threads started by the task. Filtering only by worker
    thread ID drops these records, leaving the WebUI with no output during the slowest stages.
    Helper threads bound via bind_log_scope must count toward their task, while unbound threads are still excluded,
    otherwise logs from concurrently running API tasks would mix in.
    """
    task_id = "helper-thread-log-test"
    with webui_task._task_logs_lock:
        webui_task._task_logs.pop(task_id, None)

    def logged_start(**_kwargs):
        bound = threading.Thread(
            target=logging_utils.bind_log_scope(
                lambda: logger.info("bound helper thread log")
            )
        )
        unrelated = threading.Thread(
            target=lambda: logger.info("unrelated thread log")
        )
        for thread in (bound, unrelated):
            thread.start()
        for thread in (bound, unrelated):
            thread.join()
        return {"videos": []}

    with (
        patch.object(webui_task.tm, "start", side_effect=logged_start),
        patch.object(
            webui_task.config,
            "runtime_config_lock",
            return_value=nullcontext(),
        ),
    ):
        webui_task._run_generation(
            task_id,
            VideoParams(video_subject="辅助线程日志"),
            capture_logs=True,
        )

    messages = "\n".join(webui_task.get_task_logs(task_id))
    assert "bound helper thread log" in messages
    assert "unrelated thread log" not in messages


def test_bind_log_scope_follows_nested_helpers_and_is_released():
    """
    Threads started by helper threads (e.g. heartbeats inside parallel clips) must also be attributed to the original task thread.
    The binding must be removed after the thread ends: thread IDs are reused by the system, and a leftover mapping would wrongly
    count logs from later unrelated threads toward the old task.
    """
    root_thread_id = threading.get_ident()
    seen = {}

    def inner():
        seen["inner_scope"] = logging_utils.log_scope_thread_id()

    def outer():
        seen["outer_thread_id"] = threading.get_ident()
        seen["outer_scope"] = logging_utils.log_scope_thread_id()
        nested = threading.Thread(target=logging_utils.bind_log_scope(inner))
        nested.start()
        nested.join()

    helper = threading.Thread(target=logging_utils.bind_log_scope(outer))
    helper.start()
    helper.join()

    assert seen["outer_scope"] == root_thread_id
    assert seen["inner_scope"] == root_thread_id
    assert (
        logging_utils.log_scope_thread_id(seen["outer_thread_id"])
        == seen["outer_thread_id"]
    )
    assert logging_utils.log_scope_thread_id() == root_thread_id


def test_bind_log_scope_runs_inline_calls_without_rebinding():
    """Calling the wrapped function directly in the same thread returns the value unchanged and doesn't alter the scope."""
    bound = logging_utils.bind_log_scope(lambda value: value * 2)

    assert bound(21) == 42
    assert logging_utils.log_scope_thread_id() == threading.get_ident()


def test_webui_worker_forwards_reference_audio_to_pipeline():
    reference_audio = b"task-local-reference-wav"
    prompt_audio = b"task-local-prompt-wav"
    prompt_text = "task-local transcript"
    with (
        patch.object(webui_task.tm, "start", return_value={"videos": []}) as start,
        patch.object(
            webui_task.config,
            "runtime_config_lock",
            return_value=nullcontext(),
        ),
    ):
        webui_task._run_generation(
            "reference-audio-forwarding",
            VideoParams(video_subject="reference forwarding"),
            capture_logs=False,
            voxcpm_reference_audio=reference_audio,
            voxcpm_prompt_audio=prompt_audio,
            voxcpm_prompt_text=prompt_text,
        )

    assert start.call_args.kwargs["voxcpm_reference_audio"] == reference_audio
    assert start.call_args.kwargs["voxcpm_prompt_audio"] == prompt_audio
    assert start.call_args.kwargs["voxcpm_prompt_text"] == prompt_text


def test_log_paths_stay_posix_style_on_every_platform():
    """
    The call site must always show as ``./app/services/task.py``.

    On Windows ``os.path.relpath`` returns backslash-separated paths, and joining directly would output
    ``./app\\services\\task.py``, so the same log would be formatted differently on different systems and couldn't
    line up with the background log regression test above that asserts forward slashes.
    """
    record = _log_record(
        os.path.join(logging_utils.PROJECT_ROOT, "app", "services", "task.py")
    )

    logging_utils.format_log_record(record)

    assert record["file"].path == "./app/services/task.py"


def test_log_messages_shorten_only_the_complete_project_root():
    """
    Sibling directories (e.g. ``<root>-backup``, ``<root>2``) only share a prefix with the project root path
    and must not be rewritten into wrong paths like ``.-backup``; paths inside the project should still be shortened.
    """
    root = logging_utils.PROJECT_ROOT
    record = _log_record(
        os.path.join(root, "app", "services", "task.py"),
        message=(
            f"saved {root}{os.sep}storage{os.sep}a.mp4, "
            f"backup {root}-backup{os.sep}final.mp4, copy {root}2{os.sep}b.mp4, "
            f"root {root}"
        ),
    )

    logging_utils.format_log_record(record)

    assert record["message"] == (
        f"saved .{os.sep}storage{os.sep}a.mp4, "
        f"backup {root}-backup{os.sep}final.mp4, copy {root}2{os.sep}b.mp4, "
        "root ."
    )


def test_log_paths_on_another_mount_do_not_discard_the_record():
    """
    Launching from a mapped drive or a ``subst`` drive must not make whole log entries disappear.

    In such deployments paths in the call stack are still on ``X:``, while ``PROJECT_ROOT`` has been resolved by realpath
    back to ``C:``, and ``os.path.relpath`` raises ``ValueError``. loguru catches
    the formatting exception and drops the record, so the terminal and the WebUI log panel both go blank.
    """
    absolute_path = os.path.join(
        logging_utils.PROJECT_ROOT, "app", "services", "task.py"
    )
    record = _log_record(absolute_path)

    with patch.object(
        logging_utils.os.path,
        "relpath",
        side_effect=ValueError("path is on mount 'X:', start on mount 'C:'"),
    ):
        log_format = logging_utils.format_log_record(record)

    assert log_format == logging_utils.LOG_RECORD_FORMAT
    assert record["file"].path == absolute_path


def test_log_paths_outside_the_project_keep_the_absolute_path():
    """Files outside the project directory keep their absolute path, avoiding backtracking output like ``./../..``."""
    outside_path = os.path.join(
        os.path.dirname(logging_utils.PROJECT_ROOT), "site-packages", "worker.py"
    )
    record = _log_record(outside_path)

    logging_utils.format_log_record(record)

    assert record["file"].path == outside_path


def test_generation_log_fragment_refreshes_within_half_a_second():
    """The log polling interval must not regress to second-level refreshes that lag noticeably behind terminal output."""
    assert webui_task.TASK_LOG_REFRESH_INTERVAL_SECONDS <= 0.5

    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_render_running_generation_task"
    )
    decorator = function.decorator_list[0]
    assert isinstance(decorator, ast.Call)
    assert _attribute_name(decorator.func) == "st.fragment"
    run_every = next(
        keyword.value for keyword in decorator.keywords if keyword.arg == "run_every"
    )
    assert ast.unparse(run_every) == ("webui_task.TASK_LOG_REFRESH_INTERVAL_SECONDS")


def test_generation_submit_skips_duplicate_config_save():
    """
    After submitting a task, the end of the page must not wait for the config lock again.

    The background task holds runtime_config_lock for the whole generation. The generate branch already requested
    a non-blocking save, so the end of the page needn't repeat it; ordinary interactions keep saving through the same non-blocking helper
    and must not regress to config.save_config.
    """
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    controls = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_render_generation_controls"
    )
    application = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_render_application"
    )

    assert isinstance(controls.body[-1], ast.Return)
    assert ast.unparse(controls.body[-1].value) == "start_button"

    submitted_assignment = next(
        node
        for node in application.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "generation_submitted"
            for target in node.targets
        )
    )
    assert isinstance(submitted_assignment.value, ast.Call)
    assert _attribute_name(submitted_assignment.value.func) == (
        "_render_generation_controls"
    )

    guarded_save = next(
        node
        for node in application.body
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "not generation_submitted"
    )
    guarded_calls = {
        _attribute_name(node.func)
        for node in ast.walk(guarded_save)
        if isinstance(node, ast.Call)
    }
    assert guarded_calls == {"_save_runtime_config"}


def test_terminal_logger_reload_preserves_task_log_handler():
    """Hot reload may only replace the terminal handler and must not clear the background task's log sink."""
    previous_handler_id = logging_utils._terminal_handler_id
    try:
        with (
            patch.object(logging_utils.logger, "remove") as remove,
            patch.object(logging_utils.logger, "add", return_value=456) as add,
        ):
            logging_utils._terminal_handler_id = 123
            handler_id = logging_utils.configure_terminal_logger(
                sink=object(),
                level="DEBUG",
                colorize=True,
            )

        assert handler_id == 456
        remove.assert_called_once_with(123)
        add.assert_called_once()
        assert logging_utils._terminal_handler_id == 456
    finally:
        logging_utils._terminal_handler_id = previous_handler_id


def test_worker_wrapper_failure_is_saved_instead_of_leaving_processing_state():
    """Exceptions in the logging or config wrapper layer must also be converted into a queryable failed final state."""
    task_id = "worker-wrapper-failure-test"
    with (
        patch.object(webui_task.tm, "start", side_effect=RuntimeError("lock failed")),
        patch.object(
            webui_task.config,
            "runtime_config_lock",
            return_value=nullcontext(),
        ),
    ):
        result = webui_task._run_generation(
            task_id,
            VideoParams(video_subject="工作线程失败测试"),
            capture_logs=False,
        )

    assert result["state"] == const.TASK_STATE_FAILED
    assert result["failed_stage"] == "webui_worker"
    task = webui_task.sm.state.get_task(task_id)
    assert task["state"] == const.TASK_STATE_FAILED
    assert task["error"] == "RuntimeError: lock failed"
    webui_task.sm.state.delete_task(task_id)
