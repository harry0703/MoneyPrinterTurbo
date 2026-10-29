"""验证长任务可观测性、跨线程隔离和重复提交的真实调度边界。"""

import threading
import time
import json
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from uuid import uuid4

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config
from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.models import const
from app.models.schema import VideoParams
from app.services import generation_progress as progress
from app.services import state as sm
from app.services import webui_task
from app.utils import utils


@pytest.fixture
def isolated_jobs(monkeypatch):
    store = sm.MemoryState()
    monkeypatch.setattr(sm, "state", store)
    monkeypatch.setattr(webui_task, "_active_submissions", {})
    monkeypatch.setattr(webui_task, "_task_manager", InMemoryTaskManager(1, 10))
    return store


@pytest.mark.parametrize("provider", [
    "jalapeno", "volcengine_seedance", "infistar", "ofox", "muapi",
    "metaso_minimax", "wavespeed", "loomloom",
])
def test_remote_status_keeps_identity_and_last_confirmation_during_retry(isolated_jobs, provider):
    isolated_jobs.update_task("job")
    with progress.task_scope("job"):
        progress.submitting(provider)
        progress.remote(provider, "paid-123", "running")
        before = isolated_jobs.get_task("job")["generation_activity"]
        progress.remote(provider, "paid-123", retrying=True)
        retry = isolated_jobs.get_task("job")["generation_activity"]
        assert retry["phase"] == "checking"
        assert retry["remote_status"] == "running"
        assert retry["confirmed_at"] == before["confirmed_at"]
        assert retry["remote_id"] == "paid-123"
        assert retry["provider"] == provider
        progress.remote(provider, "paid-123", "completed")
        progress.downloading(1024, 2048)
        progress.verifying()
    final = isolated_jobs.get_task("job")["generation_activity"]
    assert final["remote_id"] == "paid-123"
    assert final["phase"] == "verifying"
    assert final["remote_status"] == "succeeded"


def test_two_task_threads_do_not_mix_progress(isolated_jobs):
    gate = threading.Barrier(2)

    def run(task_id):
        isolated_jobs.update_task(task_id)
        with progress.task_scope(task_id):
            progress.submitting("ofox")
            gate.wait(timeout=5)
            progress.remote("ofox", task_id + "-remote", "running")

    with ThreadPoolExecutor(2) as pool:
        list(pool.map(run, ["first", "second"]))
    for task_id in ("first", "second"):
        assert isolated_jobs.get_task(task_id)["generation_activity"]["remote_id"] == task_id + "-remote"
    progress.submitting("outside-task")
    assert len(isolated_jobs.list_task_ids()) == 2


def test_progress_failure_cannot_abort_paid_work_or_recreate_deleted_task(isolated_jobs):
    with progress.task_scope("missing"):
        progress.remote("jalapeno", "paid-123", "running")
    assert isolated_jobs.get_task("missing") is None
    with patch.object(isolated_jobs, "patch_task", side_effect=OSError("unavailable")):
        with progress.task_scope("missing"):
            progress.remote("jalapeno", "paid-123", "running")


def test_progress_never_publishes_url_or_arbitrary_remote_status(isolated_jobs):
    isolated_jobs.update_task("job")
    with progress.task_scope("job"):
        progress.remote("jalapeno", "https://example.test/?key=secret", "secret response")
    activity = isolated_jobs.get_task("job")["generation_activity"]
    assert activity["remote_id"] == ""
    assert activity["remote_status"] == "unknown"
    assert "secret" not in str(activity)


@pytest.mark.parametrize("provider", ["jalapeno", "volcengine_seedance", "ofox", "muapi", "metaso_minimax", "infistar", "wavespeed"])
def test_provider_pollers_publish_real_http_retry_and_completion(isolated_jobs, monkeypatch, provider):
    """真实本地 HTTP 查询验证协议接入；与外部服务实测分开计数。"""
    from app.services import volcengine_seedance, ofox, muapi, metaso_minimax, infistar_video, material

    states = ["pending" if provider == "ofox" else "queued", "in_progress" if provider == "ofox" else "processing" if provider == "muapi" else "running", None,
              "in_progress" if provider == "ofox" else "processing" if provider == "muapi" else "running",
              "completed" if provider in {"ofox", "muapi", "infistar", "wavespeed"} else "succeeded"]
    requests_seen, activities = [], []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status = states[len(requests_seen)]
            requests_seen.append(self.path)
            self.send_response(503 if status is None else 200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            body = {"status": status}
            if provider == "metaso_minimax":
                body = {"task": body}
            elif provider == "wavespeed":
                body = {"code": 200, "data": body}
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *_args):
            pass

    publish = isolated_jobs.patch_task

    def record(task_id, **fields):
        activities.append(dict(fields["generation_activity"]))
        return publish(task_id, **fields)

    monkeypatch.setattr(isolated_jobs, "patch_task", record)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    args = {"task_id":"paid-123", "headers":{}, "api_key":"test-key"}
    isolated_jobs.update_task("job")
    try:
        with progress.task_scope("job"):
            progress.submitting(provider)
            if provider in {"jalapeno", "volcengine_seedance"}:
                volcengine_seedance._wait_for_task(tasks_url=base, **args)
            elif provider == "ofox":
                ofox._wait_for_task(videos_url=base, **args)
            elif provider == "muapi":
                muapi._wait_for_task(base_url=base, **args)
            elif provider == "metaso_minimax":
                metaso_minimax._wait_for_task(base_url=base, **args)
            elif provider == "infistar":
                infistar_video._wait("paid-123", base, {}, "test-key")
            else:
                monkeypatch.setattr(material, "WAVESPEED_API_BASE_URL", base)
                material._wait_for_wavespeed_prediction(prediction_id="paid-123",headers={},api_key="test-key")
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    assert len(requests_seen) == 5
    assert all("paid-123" in path for path in requests_seen)
    phases = [a["phase"] for a in activities]
    assert "remote_queued" in phases
    assert "generating" in phases
    assert phases.count("checking") >= 2  # 首次查询及 503 后重查。
    assert phases[-1] == "generated"
    assert activities[-1]["provider"] == provider


def test_simultaneous_identical_submissions_start_only_one_real_worker(isolated_jobs, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def generate(task_id, **kwargs):
        calls.append(task_id)
        entered.set()
        assert release.wait(10)
        isolated_jobs.update_task(task_id, state=const.TASK_STATE_COMPLETE, progress=100)

    monkeypatch.setattr(webui_task.tm, "start", generate)
    params = VideoParams(video_subject="same content")
    try:
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(
                lambda task_id: webui_task.submit_generation(task_id, params, capture_logs=False),
                ["first-click", "second-click"],
            ))
        assert entered.wait(5)
        assert results[0] == results[1]
        assert calls == [results[0]]
        assert webui_task._task_manager.queue_size() == 0
        assert webui_task.is_generation_active(results[0])
    finally:
        release.set()
        deadline = time.monotonic() + 5
        while webui_task._active_submissions and time.monotonic() < deadline:
            time.sleep(0.01)
    assert not webui_task._active_submissions
    # 完成之后同样的内容可以有意重新生成，不会永久去重。
    assert webui_task.submit_generation("intentional-new-job", params, capture_logs=False) == "intentional-new-job"


def test_failed_submission_releases_duplicate_reservation(isolated_jobs):
    params = VideoParams(video_subject="test")
    with patch.object(webui_task._task_manager, "add_task", side_effect=RuntimeError("queue unavailable")):
        with pytest.raises(RuntimeError):
            webui_task.submit_generation("failed-submit", params)
    assert not webui_task._active_submissions
    assert isolated_jobs.get_task("failed-submit")["state"] == const.TASK_STATE_FAILED


def test_changed_generation_settings_are_not_deduplicated(isolated_jobs):
    params = VideoParams(video_subject="test")
    with patch.object(webui_task._task_manager, "add_task") as enqueue:
        first = webui_task.submit_generation("first", params)
        second = webui_task.submit_generation("duplicate", params)
        with patch.dict(config.app, {"llm_provider": "different-provider"}):
            third = webui_task.submit_generation("changed", params)
    assert first == second == "first"
    assert third == "changed"
    assert enqueue.call_count == 2


def test_preview_staging_paths_do_not_bypass_duplicate_guard(isolated_jobs):
    preview = {"script":"same script", "voice_name":"test-voice", "duration":3,
               "voice_rate":1, "voice_volume":1, "audio_file":"/tasks/first/audio.mp3",
               "audio_digest":"a" * 64}
    params = VideoParams(video_subject="same content")
    with patch.object(webui_task._task_manager, "add_task") as enqueue:
        first = webui_task.submit_generation("first", params, voice_preview=preview)
        second = webui_task.submit_generation("second", params,
            voice_preview=dict(preview, audio_file="/tasks/second/audio.mp3"))
        third = webui_task.submit_generation("different-audio", params,
            voice_preview=dict(preview, duration=4))
    assert first == second
    assert third == "different-audio"
    assert enqueue.call_count == 2


@pytest.mark.parametrize("with_digest", [True, False])
def test_different_preview_audio_is_not_merged_even_with_matching_metadata(isolated_jobs, tmp_path, with_digest):
    """相同时长与文案不代表相同音频；用两个真实 MP3 复现错误合并。"""
    import hashlib
    import subprocess

    previews = []
    for frequency in (440, 880):
        audio = tmp_path / f"voice-{frequency}.mp3"
        subprocess.run([utils.get_ffmpeg_binary(), "-y", "-v", "error", "-f", "lavfi",
            "-i", f"sine=frequency={frequency}:duration=1", str(audio)], check=True)
        previews.append({"script":"same script", "voice_name":"test-voice", "duration":1,
            "voice_rate":1, "voice_volume":1, "audio_file":str(audio),
            "audio_digest":hashlib.sha256(audio.read_bytes()).hexdigest()})
    assert previews[0]["audio_digest"] != previews[1]["audio_digest"]
    if not with_digest:
        for preview in previews:
            preview.pop("audio_digest")
    params = VideoParams(video_subject="same content")
    with patch.object(webui_task._task_manager, "add_task") as enqueue:
        first = webui_task.submit_generation("first-audio", params, voice_preview=previews[0])
        second = webui_task.submit_generation("second-audio", params, voice_preview=previews[1])
    assert first != second
    assert enqueue.call_count == 2


def test_parallel_real_downloads_publish_activity_from_worker_threads(isolated_jobs, monkeypatch, tmp_path):
    """并发素材下载要携带任务上下文，验证真实 HTTP 下载和 FFmpeg 校验。"""
    import subprocess
    from app.models.schema import MaterialInfo
    from app.services import material

    source = tmp_path / "source.mp4"
    subprocess.run([utils.get_ffmpeg_binary(), "-y", "-v", "error", "-f", "lavfi",
        "-i", "color=c=blue:s=160x90:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True)
    payload = source.read_bytes()
    activities = []
    publish = isolated_jobs.patch_task

    def record(task_id, **fields):
        activities.append((task_id, dict(fields["generation_activity"])))
        return publish(task_id, **fields)

    monkeypatch.setattr(isolated_jobs, "patch_task", record)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    isolated_jobs.update_task("parallel")
    try:
        with patch.dict(config.app, {"material_concurrency":2}):
            with progress.task_scope("parallel"):
                progress.stage("materials")
                result = material._download_materials_in_parallel(
                    [("",MaterialInfo(url=f"{base}/a.mp4")),("",MaterialInfo(url=f"{base}/b.mp4"))],
                    str(tmp_path/"downloads"),
                )
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    assert len(result) == 2
    assert any(a["phase"] == "downloading" for _, a in activities)
    assert any(a["phase"] == "verifying" for _, a in activities)
    assert {task_id for task_id, _ in activities} == {"parallel"}


def test_first_status_read_failure_still_registers_automatic_refresh():
    """真实 Streamlit 运行时必须在首次状态读取失败后仍登记定时 Fragment。"""
    from pathlib import Path

    entry = Path(__file__).resolve().parents[2]/"webui"/"Main.py"
    script = f'''
import ast
from pathlib import Path
from types import SimpleNamespace
import streamlit as st
from loguru import logger
from app.models import const
from streamlit.runtime.scriptrunner import get_script_run_ctx
def unavailable(_task_id):
    raise OSError("state store temporarily unavailable")
sm = SimpleNamespace(state=SimpleNamespace(get_task=unavailable))
webui_task = SimpleNamespace(TASK_LOG_REFRESH_INTERVAL_SECONDS=.5, is_generation_active=lambda _id: True)
tr = lambda key: key
_current_generation_task_id = lambda: "recovering"
_normalize_task_state = lambda value: value
_remove_active_generation_task = lambda _id: None
_render_generation_task_snapshot = lambda *_args: st.info("running")
nodes = [n for n in ast.parse(Path({str(entry)!r}).read_text()).body
    if isinstance(n, ast.FunctionDef) and n.name in {{"_render_current_generation_task", "_render_running_generation_task"}}]
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), {str(entry)!r}, "exec"))
_render_current_generation_task()
st.session_state["refresh_fragment_count"] = len(get_script_run_ctx().fragment_storage._fragments)
'''
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception
    assert app.session_state["refresh_fragment_count"] == 1


def test_loomloom_new_client_request_id_does_not_bypass_active_job_deduplication(isolated_jobs):
    from dataclasses import replace
    from app.services.loomloom import LoomLoomConfirmedVideoRequest, LoomLoomSettings, LoomLoomVideoBatch

    request = LoomLoomConfirmedVideoRequest(
        settings=LoomLoomSettings("https://example.test", "test-key", "listing"),
        batch=LoomLoomVideoBatch(({"prompt":"same content", "modelChoice":"model-a"},)),
        listing_version_id="version-1", client_request_id="first-click",
    )
    params = VideoParams(video_subject="same content", video_source="loomloom")
    with patch.object(webui_task._task_manager, "add_task") as enqueue:
        first = webui_task.submit_generation("first", params, loomloom_video_request=request)
        second = webui_task.submit_generation("second", params,
            loomloom_video_request=replace(request, client_request_id="second-click"))
    assert first == second
    assert enqueue.call_count == 1


def test_browser_refresh_recovers_busy_job_and_displays_current_phase(isolated_jobs, tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(utils, "task_dir", lambda *_a, **_k: str(tmp_path))
    job = str(uuid4())
    now = time.time()
    isolated_jobs.update_task(job, generation_submitted_at=now-360, progress=40,
        generation_activity={"phase":"generating", "started_at":now-350,
            "confirmed_at":now, "remote_id":"paid-123", "provider":"muapi"})
    entry = Path(__file__).resolve().parents[2]/"webui"/"Main.py"
    # 两个独立 AppTest 实例模拟刷新后新建的 Streamlit 会话，共用后台任务。
    with patch.object(config, "try_save_config", return_value=True):
        for _ in range(2):
            app = AppTest.from_file(str(entry), default_timeout=60)
            app.query_params["generation_task"] = job
            app.run()
            assert not app.exception
            assert app.session_state["current_generation_task_id"] == job
            assert app.button(key="generate_video_button").disabled
            assert any("06:" in c.value for c in app.caption)
            assert any("paid-123" in c.value for c in app.caption)
        isolated_jobs.patch_task(job, generation_activity={"phase":"downloading", "downloaded_bytes":1048576})
        app.run()
        assert any("1.0 MB" in c.value for c in app.caption)
        isolated_jobs.update_task(job, state=const.TASK_STATE_FAILED, error="download failed",
            generation_activity={"phase":"downloading", "remote_id":"paid-123"})
        app.run()
        assert not app.button(key="generate_video_button").disabled
        assert any("paid-123" in c.value for c in app.warning)


def test_persisted_processing_job_can_be_untracked_after_service_restart(isolated_jobs, tmp_path, monkeypatch):
    """持久状态还在、当前服务已没有执行线程时，不能永远锁住生成按钮。"""
    from pathlib import Path

    monkeypatch.setattr(utils, "task_dir", lambda *_a, **_k: str(tmp_path))
    job = str(uuid4())
    isolated_jobs.update_task(job, generation_submitted_at=time.time()-600,
        generation_activity={"phase":"generating", "remote_id":"existing-paid-task"})
    assert not webui_task.is_generation_active(job)
    entry = Path(__file__).resolve().parents[2]/"webui"/"Main.py"
    with patch.object(config, "try_save_config", return_value=True):
        app = AppTest.from_file(str(entry), default_timeout=60)
        app.query_params["generation_task"] = job
        app.run()
        assert not app.exception
        assert app.button(key="generate_video_button").disabled
        app.button(key=f"stop_tracking_generation_{job}").click().run()
        assert not app.exception
        assert not app.button(key="generate_video_button").disabled
        assert not app.session_state["current_generation_task_id"]
        assert "generation_task" not in app.query_params
    assert isolated_jobs.get_task(job)["state"] == const.TASK_STATE_PROCESSING
    assert isolated_jobs.get_task(job)["generation_activity"]["remote_id"] == "existing-paid-task"
