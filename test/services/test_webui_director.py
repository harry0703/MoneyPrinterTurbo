import ast
import json
import os
import tempfile
import tomllib
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).parent.parent.parent
DIRECTOR_MODULE = ROOT_DIR / "webui" / "director.py"

DIRECTOR_CONSTANTS = {
    "API_BASE",
    "CONFIG_PATH",
    "STATE_FAILED",
    "STATE_COMPLETE",
    "STATE_PROCESSING",
    "STATE_WAITING_FOR_DIRECTOR",
    "STAGES",
    "DONE",
    "ACTIVE",
    "PENDING",
    "ERROR",
    "NA",
    "STATUS_MARKS",
    "_STATE_LABELS",
}

DIRECTOR_FUNCTIONS = {
    "api_url",
    "_api",
    "file_url",
    "task_file_path",
    "asset_url",
    "list_tasks",
    "get_task",
    "get_rough_cut",
    "get_shot_plan",
    "_config_voice",
    "build_creative_params",
    "submit_creative_task",
    "approve_task",
    "resume_task",
    "reorder_shots",
    "set_shot_duration",
    "replace_shot_asset",
    "delete_shot",
    "regenerate_shot",
    "stage_statuses",
}


class _FakeRequestException(Exception):
    pass


class _FakeResponse:
    def __init__(self, status_code, json_body=None):
        self.status_code = status_code
        self._json = json_body
        self.text = json.dumps(json_body) if json_body is not None else ""

    def json(self):
        if self._json is None:
            raise ValueError("No JSON object")
        return self._json


class _FakeRequests:
    RequestException = _FakeRequestException

    def __init__(self):
        self.scripted = []
        self.calls = []

    def script(self, *items):
        self.scripted.extend(items)

    def request(self, method, url, json=None, timeout=None):
        self.calls.append(
            {"method": method, "url": url, "json": json, "timeout": timeout}
        )
        if self.scripted:
            item = self.scripted.pop(0)
        else:
            item = _FakeResponse(200, {"status": 200, "message": "success", "data": None})
        if isinstance(item, Exception):
            raise item
        return item


def _load_director_namespace():
    """隔离加载 Director 模块的纯函数，不启动 Streamlit 运行时。"""
    tree = ast.parse(DIRECTOR_MODULE.read_text(encoding="utf-8"))
    selected_nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in DIRECTOR_CONSTANTS
            for target in node.targets
        ):
            selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in DIRECTOR_FUNCTIONS:
            selected_nodes.append(node)
    fake_requests = _FakeRequests()
    namespace = {"os": os, "requests": fake_requests, "tomllib": tomllib}
    module = ast.fix_missing_locations(ast.Module(body=selected_nodes, type_ignores=[]))
    exec(compile(module, str(DIRECTOR_MODULE), "exec"), namespace)
    namespace["fake_requests"] = fake_requests
    return namespace


os.environ["MPT_CREATIVE_API_BASE"] = "http://director-test-api:9"
CONFIG_FIXTURE = os.path.join(tempfile.gettempdir(), "mpt-director-test-config.toml")
os.environ["MPT_CONFIG_PATH"] = CONFIG_FIXTURE
NAMESPACE = _load_director_namespace()

API_BASE = NAMESPACE["API_BASE"]
api_url = NAMESPACE["api_url"]
_api = NAMESPACE["_api"]
file_url = NAMESPACE["file_url"]
task_file_path = NAMESPACE["task_file_path"]
asset_url = NAMESPACE["asset_url"]
list_tasks = NAMESPACE["list_tasks"]
get_rough_cut = NAMESPACE["get_rough_cut"]
get_shot_plan = NAMESPACE["get_shot_plan"]
_config_voice = NAMESPACE["_config_voice"]
build_creative_params = NAMESPACE["build_creative_params"]
submit_creative_task = NAMESPACE["submit_creative_task"]
reorder_shots = NAMESPACE["reorder_shots"]
set_shot_duration = NAMESPACE["set_shot_duration"]
replace_shot_asset = NAMESPACE["replace_shot_asset"]
delete_shot = NAMESPACE["delete_shot"]
regenerate_shot = NAMESPACE["regenerate_shot"]
stage_statuses = NAMESPACE["stage_statuses"]

STATE_PROCESSING = NAMESPACE["STATE_PROCESSING"]
STATE_FAILED = NAMESPACE["STATE_FAILED"]
STATE_COMPLETE = NAMESPACE["STATE_COMPLETE"]
STATE_WAITING_FOR_DIRECTOR = NAMESPACE["STATE_WAITING_FOR_DIRECTOR"]
STAGES = NAMESPACE["STAGES"]
DONE = NAMESPACE["DONE"]
ACTIVE = NAMESPACE["ACTIVE"]
PENDING = NAMESPACE["PENDING"]
ERROR = NAMESPACE["ERROR"]

FAKE = NAMESPACE["fake_requests"]


def _write_config(body):
    with open(CONFIG_FIXTURE, "w", encoding="utf-8") as handle:
        handle.write(body)


def _remove_config():
    if os.path.exists(CONFIG_FIXTURE):
        os.remove(CONFIG_FIXTURE)


@pytest.fixture(autouse=True)
def _clean_config_fixture():
    _remove_config()
    yield
    _remove_config()


def _ok(data):
    return _FakeResponse(200, {"status": 200, "message": "success", "data": data})


def _timeline():
    return {"shots": [{"index": 1}], "total_duration": 4.0}


def _plan():
    return {"version": 1, "shots": [{"index": 1}]}


class TestApiUrl:
    def test_joins_path_with_leading_slash(self):
        assert api_url("/api/v1/tasks") == f"{API_BASE}/api/v1/tasks"

    def test_adds_missing_leading_slash(self):
        assert api_url("tasks/t1/x.mp4") == f"{API_BASE}/tasks/t1/x.mp4"

    def test_file_url_points_into_task_dir(self):
        assert file_url("t1", "rough_cut.mp4") == f"{API_BASE}/tasks/t1/rough_cut.mp4"


class TestAssetUrls:
    def test_absolute_container_path_maps_under_tasks(self):
        path = task_file_path(
            "t1", "/MoneyPrinterTurbo/storage/tasks/t1/assets/shot_001/a.png"
        )
        assert path == "/tasks/t1/assets/shot_001/a.png"

    def test_relative_path_stays_relative(self):
        assert task_file_path("t1", "assets/shot_001/a.png") == "/tasks/t1/assets/shot_001/a.png"

    def test_asset_url_keeps_explicit_tasks_prefix(self):
        assert asset_url("t1", "/tasks/t1/final-1.mp4") == f"{API_BASE}/tasks/t1/final-1.mp4"

    def test_asset_url_resolves_absolute_container_path(self):
        url = asset_url("t1", "/MoneyPrinterTurbo/storage/tasks/t1/final-1.mp4")
        assert url == f"{API_BASE}/tasks/t1/final-1.mp4"

    def test_asset_url_empty_path_is_none(self):
        assert asset_url("t1", "") is None


class TestBuildCreativeParams:
    def test_payload_enables_creative_mode(self):
        params = build_creative_params(
            "topic", "script", "16:9", 4, "en-US-AriaNeural", True, 0.2
        )
        assert params["creative_mode"] is True
        assert params["video_subject"] == "topic"
        assert params["video_script"] == "script"
        assert params["video_clip_duration"] == 4
        assert params["video_concat_mode"] == "sequential"
        assert params["voice_name"] == "en-US-AriaNeural"
        assert params["subtitle_enabled"] is True
        assert params["bgm_volume"] == 0.2

    def test_empty_voice_falls_back_to_config_voice(self):
        _write_config('[ui]\nvoice_name = "mimo:mimo_default-Female"\n')
        params = build_creative_params("topic", "", "9:16", 5, "", False, 0.0)
        assert params["video_script"] == ""
        assert params["voice_name"] == "mimo:mimo_default-Female"
        assert params["subtitle_enabled"] is False

    def test_empty_voice_without_config_omits_voice_name(self):
        params = build_creative_params("topic", "", "9:16", 5, "", False, 0.0)
        assert "voice_name" not in params


class TestConfigVoice:
    def test_reads_ui_voice_name(self):
        _write_config('[ui]\nvoice_name = "mimo:mimo_default-Female"\n')
        assert _config_voice() == "mimo:mimo_default-Female"

    def test_missing_file_returns_empty(self):
        assert _config_voice() == ""

    def test_invalid_toml_returns_empty(self):
        _write_config("not [valid toml")
        assert _config_voice() == ""

    def test_non_string_voice_returns_empty(self):
        _write_config("[ui]\nvoice_name = 42\n")
        assert _config_voice() == ""


class TestStageStatuses:
    def test_fresh_processing_task_activates_script(self):
        statuses = stage_statuses({"state": STATE_PROCESSING, "progress": 10}, None, None)
        assert statuses["Brief"] == DONE
        assert statuses["Script"] == ACTIVE
        assert statuses["Shot Plan"] == PENDING
        assert statuses["Rough Cut"] == PENDING
        assert statuses["Final"] == PENDING

    def test_waiting_for_director(self):
        task = {"state": STATE_WAITING_FOR_DIRECTOR, "script": "s"}
        statuses = stage_statuses(task, _plan(), _timeline())
        assert statuses["Brief"] == DONE
        assert statuses["Script"] == DONE
        assert statuses["Shot Plan"] == DONE
        assert statuses["Assets"] == DONE
        assert statuses["Rough Cut"] == ACTIVE
        assert statuses["Review"] == PENDING
        assert statuses["Final"] == PENDING

    def test_complete_task_all_done(self):
        task = {
            "state": STATE_COMPLETE,
            "script": "s",
            "videos": ["/tasks/t1/final-1.mp4"],
            "combined_videos": ["/tasks/t1/combined-1.mp4"],
        }
        statuses = stage_statuses(task, _plan(), _timeline())
        assert all(statuses[stage] == DONE for stage in STAGES)

    def test_failed_task_marks_first_open_stage(self):
        task = {
            "state": STATE_FAILED,
            "script": "s",
            "failed_stage": "script",
            "error": "llm down",
        }
        statuses = stage_statuses(task, None, None)
        assert statuses["Script"] == DONE
        assert statuses["Shot Plan"] == ERROR
        assert statuses["Rough Cut"] == PENDING


class TestApiClient:
    def test_list_tasks_parses_wrapped_data(self):
        FAKE.script(_ok({"tasks": [{"task_id": "a", "state": 4}], "total": 1}))
        tasks = list_tasks()
        assert tasks == [{"task_id": "a", "state": 4}]
        call = FAKE.calls[-1]
        assert call["method"] == "GET"
        assert call["url"].endswith("/api/v1/tasks?page=1&page_size=100")

    def test_list_tasks_returns_empty_on_error(self):
        FAKE.script(_FakeResponse(500, None))
        assert list_tasks() == []

    def test_get_rough_cut_extracts_timeline(self):
        FAKE.script(_ok({"task_id": "t1", "rough_cut": {"shots": []}}))
        assert get_rough_cut("t1") == {"shots": []}

    def test_get_rough_cut_none_on_not_found(self):
        FAKE.script(_FakeResponse(404, None))
        assert get_rough_cut("t1") is None

    def test_get_shot_plan_reads_raw_static_json(self):
        FAKE.script(_FakeResponse(200, {"version": 1, "shots": []}))
        assert get_shot_plan("t1") == {"version": 1, "shots": []}

    def test_submit_creative_task_returns_task_id(self):
        FAKE.script(_ok({"task_id": "new-1", "state": 4}))
        task_id, error = submit_creative_task({"creative_mode": True})
        assert task_id == "new-1"
        assert error is None
        call = FAKE.calls[-1]
        assert call["method"] == "POST"
        assert call["url"].endswith("/api/v1/videos")
        assert call["json"] == {"creative_mode": True}

    def test_submit_creative_task_reports_error(self):
        FAKE.script(_FakeResponse(500, None))
        task_id, error = submit_creative_task({})
        assert task_id is None
        assert "500" in error

    def test_reorder_posts_explicit_order(self):
        FAKE.script(_ok({"task_id": "t1", "rough_cut": _timeline()}))
        ok, _ = reorder_shots("t1", [2, 1])
        assert ok
        call = FAKE.calls[-1]
        assert call["method"] == "POST"
        assert call["url"].endswith("/creative/tasks/t1/shots/reorder")
        assert call["json"] == {"order": [2, 1]}

    def test_set_duration_serializes_float(self):
        FAKE.script(_ok({"task_id": "t1", "rough_cut": _timeline()}))
        ok, _ = set_shot_duration("t1", 2, "3.5")
        assert ok
        call = FAKE.calls[-1]
        assert call["url"].endswith("/creative/tasks/t1/shots/2/duration")
        assert call["json"] == {"duration": 3.5}

    def test_delete_shot_uses_delete_method(self):
        FAKE.script(_ok({"task_id": "t1", "rough_cut": _timeline()}))
        ok, _ = delete_shot("t1", 1)
        assert ok
        call = FAKE.calls[-1]
        assert call["method"] == "DELETE"
        assert call["url"].endswith("/creative/tasks/t1/shots/1")

    def test_replace_shot_puts_asset_path(self):
        FAKE.script(_ok({"task_id": "t1", "rough_cut": _timeline()}))
        ok, _ = replace_shot_asset("t1", 1, "assets/shot_001/b.png")
        assert ok
        call = FAKE.calls[-1]
        assert call["method"] == "PUT"
        assert call["url"].endswith("/creative/tasks/t1/shots/1")
        assert call["json"] == {"asset_path": "assets/shot_001/b.png"}

    def test_regenerate_omits_blank_prompt(self):
        FAKE.script(_ok({"task_id": "t1", "rough_cut": _timeline()}))
        ok, _ = regenerate_shot("t1", 3)
        assert ok
        call = FAKE.calls[-1]
        assert call["url"].endswith("/creative/tasks/t1/shots/3/regenerate")
        assert call["json"] is None

    def test_regenerate_sends_prompt_when_present(self):
        FAKE.script(_ok({"task_id": "t1", "rough_cut": _timeline()}))
        regenerate_shot("t1", 3, prompt="new prompt")
        assert FAKE.calls[-1]["json"] == {"prompt": "new prompt"}

    def test_unreachable_api_returns_message(self):
        FAKE.script(_FakeRequestException("connection refused"))
        ok, message = _api("GET", "/api/v1/tasks/t1")
        assert ok is False
        assert API_BASE in message
        assert "connection refused" in message

    def test_http_error_returns_status_and_text(self):
        FAKE.script(_FakeResponse(409, None))
        ok, message = _api("POST", "/api/v1/creative/tasks/t1/approve")
        assert ok is False
        assert "409" in message
