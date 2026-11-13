import io
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import requests
from loguru import logger

from app.config import config
from app.services import webui_task
from app.models.schema import VideoParams
from app.utils import logging_utils as logs
from app.utils import request_logging as trace


@pytest.fixture(autouse=True)
def restore_logging_options():
    previous = logs.get_logging_options()
    yield
    logs.set_logging_options(*previous)


@pytest.fixture
def output():
    sink = io.StringIO()
    handler = logger.add(
        sink, level=0, filter=logs.runtime_log_filter, format="{message}"
    )
    try:
        yield sink
    finally:
        logger.remove(handler)


def test_runtime_level_changes_apply_to_existing_handlers(output):
    logs.set_logging_options("ERROR")
    logger.debug("hidden-debug")
    logger.error("visible-error")
    logs.set_logging_options("DEBUG")
    logger.debug("visible-debug")
    assert "hidden-debug" not in output.getvalue()
    assert "visible-error" in output.getvalue()
    assert "visible-debug" in output.getvalue()


@pytest.mark.parametrize("level,enabled", [("invalid", False), ("INFO", "false")])
def test_invalid_settings_do_not_replace_current_snapshot(level, enabled):
    logs.set_logging_options("WARNING", True)
    with pytest.raises(ValueError):
        logs.set_logging_options(level, enabled)
    assert logs.get_logging_options() == ("WARNING", True)


def test_disabled_tracing_never_serializes_or_inspects_response(output):
    logs.set_logging_options("DEBUG", False)
    response = object()
    send = Mock(return_value=response)
    payload = {"api_key": "hidden"}
    with patch.object(trace, "sanitize_payload", side_effect=AssertionError):
        assert (
            trace.trace_http_call("POST", send, "https://example.test", json=payload)
            is response
        )
    send.assert_called_once_with("https://example.test", json=payload)
    assert output.getvalue() == ""


def test_request_parameters_redacted_without_modifying_original(output):
    logs.set_logging_options("ERROR", True)
    response = SimpleNamespace(status_code=201)
    send = Mock(return_value=response)
    payload = {
        "model": "test-model",
        "messages": [{"content": "visible prompt"}],
        "nested": {"API-Key": "private-api-key", "refresh_token": "private-refresh"},
        "audio": "private-media",
        "files": {"voice": b"private-file"},
        "url": "https://user:private-password@example.test/file?custom_signature=private-signature",
    }
    headers = {"Authorization": "Bearer private-auth", "Cookie": "private-cookie"}
    result = trace.trace_http_call(
        "POST",
        send,
        "https://user:private-password@example.test/v1?secret=private-url-key",
        json=payload,
        headers=headers,
        timeout=5,
        allow_redirects=False,
    )
    assert result is response
    assert send.call_args.kwargs["json"] is payload
    assert send.call_args.kwargs["headers"] is headers
    assert payload["nested"]["API-Key"] == "private-api-key"
    records = [
        json.loads(line.removeprefix("request_trace "))
        for line in output.getvalue().splitlines()
    ]
    assert [r["event"] for r in records] == ["request", "response"]
    assert records[0]["id"] == records[1]["id"]
    assert records[1]["status"] == 201
    assert "visible prompt" in output.getvalue()
    assert "test-model" in output.getvalue()
    assert "private-" not in output.getvalue()


def test_failure_does_not_retry_or_replace_exception(output):
    logs.set_logging_options("DEBUG", True)
    error = requests.Timeout("private-token-in-error")
    send = Mock(side_effect=error)
    with pytest.raises(requests.Timeout) as caught:
        trace.trace_http_call(
            "POST", send, "https://example.test", json={"prompt": "hello"}
        )
    assert caught.value is error
    send.assert_called_once()
    assert '"error_type": "Timeout"' in output.getvalue()
    assert "private-token-in-error" not in output.getvalue()


def test_diagnostics_failure_never_prevents_request_or_changes_result():
    logs.set_logging_options("DEBUG", True)
    response = object()
    send = Mock(return_value=response)
    with patch.object(trace, "sanitize_payload", side_effect=RuntimeError):
        assert trace.trace_http_call("POST", send, "https://example.test") is response
    send.assert_called_once()


def test_streaming_response_is_not_consumed(output):
    logs.set_logging_options("INFO", True)

    class Stream:
        status_code = 200

        @property
        def content(self):
            raise AssertionError("stream must not be read")

        text = content

        def json(self):
            raise AssertionError("stream must not be read")

    response = Stream()
    send = Mock(return_value=response)
    assert (
        trace.trace_http_call("GET", send, "https://example.test/audio", stream=True)
        is response
    )
    send.assert_called_once_with("https://example.test/audio", stream=True)


def test_session_request_keeps_original_method_and_arguments(output):
    logs.set_logging_options("INFO", True)
    send = Mock(return_value=SimpleNamespace(status_code=200))
    trace.trace_http_call(
        "REQUEST", send, "POST", "https://example.test", json={"model": "test"}
    )
    send.assert_called_once_with("POST", "https://example.test", json={"model": "test"})


def test_sdk_parameters_log_without_consuming_stream(output):
    logs.set_logging_options("DEBUG", True)
    stream = iter([1, 2])
    send = Mock(return_value=stream)
    assert (
        trace.trace_sdk_call(
            "qwen",
            "https://example.test",
            send,
            api_key="private-key",
            messages=[{"content": "hello"}],
        )
        is stream
    )
    assert next(stream) == 1
    assert "private-key" not in output.getvalue()
    assert "hello" in output.getvalue()


def test_payload_limits_cycles_media_and_embedded_tokens():
    payload = {
        "prompt": "token sk-testtoken123456 and " + "text " * 5000,
        "media": "data:audio/wav;base64,private-media",
        "unknown": object(),
    }
    payload["cycle"] = payload
    text = json.dumps(trace.sanitize_payload(payload))
    assert len(text) < 12000
    assert "sk-testtoken123456" not in text
    assert "private-media" not in text
    assert "[truncated]" in text


def test_trace_can_be_disabled_on_existing_logger(output):
    send = Mock(return_value=SimpleNamespace(status_code=200))
    logs.set_logging_options("INFO", True)
    trace.trace_http_call("GET", send, "https://example.test")
    before = output.getvalue()
    logs.set_logging_options("INFO", False)
    trace.trace_http_call("GET", send, "https://example.test")
    assert output.getvalue() == before


def test_active_webui_task_obeys_runtime_level_without_losing_its_sink():
    task_id = "runtime-diagnostic-test"

    def run(**kwargs):
        logger.debug("visible-before-change")
        logger.error("always-visible")

        def update():
            # 模拟用户在另一线程调试持有配置锁的运行任务。
            logs.set_logging_options("ERROR", True)

        thread = threading.Thread(target=update)
        thread.start()
        thread.join(timeout=1)
        assert not thread.is_alive()
        logger.debug("hidden-after-change")
        trace.trace_http_call(
            "POST",
            lambda *a, **kw: SimpleNamespace(status_code=200),
            "https://example.test",
            json={"prompt": "task-trace"},
        )
        return {"ok": True}

    logs.set_logging_options("DEBUG", False)
    with patch.object(webui_task.tm, "start", side_effect=run):
        assert webui_task._run_generation(
            task_id, VideoParams(video_subject="test"), True
        ) == {"ok": True}
    text = "\n".join(webui_task.get_task_logs(task_id))
    assert "visible-before-change" in text
    assert "always-visible" in text
    assert "hidden-after-change" not in text
    assert "task-trace" in text


def test_diagnostics_settings_persist_without_changing_legacy_level(tmp_path):
    with (
        patch.object(config, "config_file", str(tmp_path / "config.toml")),
        patch.object(config, "root_dir", str(tmp_path)),
        patch.object(config, "_cfg", dict(config._cfg)),
        patch.object(
            config, "diagnostics", {"log_level": "ERROR", "log_requests": True}
        ),
    ):
        config.save_config()
        import toml

        saved = toml.load(tmp_path / "config.toml")
        assert saved["diagnostics"] == {"log_level": "ERROR", "log_requests": True}


def test_sdk_config_model_is_serialized_and_redacted():
    from pydantic import BaseModel

    class SDKConfig(BaseModel):
        temperature: float = 0.5
        api_key: str = "private-key"

    payload = trace.sanitize_payload({"config": SDKConfig()})
    assert payload["config"]["temperature"] == 0.5
    assert payload["config"]["api_key"] == "[REDACTED]"


@pytest.mark.parametrize(
    "params",
    [
        {"api_key": "opaque-query-secret", "custom_auth": "opaque-query-secret"},
        [("api_key", "opaque-query-secret"), ("custom_auth", "opaque-query-secret")],
        "custom_auth=opaque-query-secret",
    ],
)
def test_every_query_parameter_value_is_redacted(params, output):
    logs.set_logging_options("ERROR", True)
    send = Mock(return_value=SimpleNamespace(status_code=200))
    trace.trace_http_call("GET", send, "https://example.test", params=params)
    assert send.call_args.kwargs["params"] is params
    assert "opaque-query-secret" not in output.getvalue()


def test_invalid_trace_config_preserves_valid_error_level(tmp_path):
    import os
    import subprocess
    import sys

    (tmp_path / "config.toml").write_text(
        'log_level="ERROR"\n[diagnostics]\nlog_requests="false"\n'
    )
    run = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.config import config; from app.utils.logging_utils import get_logging_options; import json; print(json.dumps(get_logging_options()))",
        ],
        env=dict(os.environ, MPT_HOME=str(tmp_path)),
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert json.loads(run.stdout) == ["ERROR", False]


def test_concurrent_logging_updates_keep_runtime_and_saved_options_together(tmp_path):
    """两个会话在任务持锁时同时应用，保存与运行状态必须采用同一组值。"""
    import toml

    acquired = threading.Event()
    release_task = threading.Event()
    a_entered = threading.Event()
    release_a = threading.Event()
    b_entered = threading.Event()
    errors = []
    original_update = config.update_config_values_nonblocking

    def task():
        with config.runtime_config_lock():
            acquired.set()
            release_task.wait(5)

    def delay_a(section, changes):
        if threading.current_thread().name == "logging-A":
            a_entered.set()
            assert release_a.wait(5)
        return original_update(section, changes)

    def apply(level, enabled):
        try:
            if threading.current_thread().name == "logging-B":
                b_entered.set()
            config.update_logging_options(level, enabled)
        except Exception as exc:
            errors.append(exc)

    with (
        patch.object(config, "config_file", str(tmp_path / "config.toml")),
        patch.object(config, "root_dir", str(tmp_path)),
        patch.object(config, "_cfg", dict(config._cfg)),
        patch.object(config, "diagnostics", {}),
        patch.object(config, "update_config_values_nonblocking", side_effect=delay_a),
    ):
        threads = [
            threading.Thread(target=task),
            threading.Thread(target=apply, args=("INFO", True), name="logging-A"),
            threading.Thread(target=apply, args=("ERROR", False), name="logging-B"),
        ]
        try:
            threads[0].start()
            assert acquired.wait(5)
            threads[1].start()
            assert a_entered.wait(5)
            threads[2].start()
            assert b_entered.wait(5)
            release_a.set()
            threads[1].join(5)
            threads[2].join(5)
            assert not threads[1].is_alive() and not threads[2].is_alive()
            assert logs.get_logging_options() == ("ERROR", False)
        finally:
            release_a.set()
            release_task.set()
            for thread in threads:
                if thread.ident is not None:
                    thread.join(5)
        assert not errors
        # 后台刷新退出后再恢复被 patch 的配置，避免写入用户配置。
        config.try_save_config()
        import time

        deadline = time.monotonic() + 5
        while config._pending_config_flush_scheduled and time.monotonic() < deadline:
            time.sleep(0.005)
        assert not config._pending_config_flush_scheduled
        saved = toml.load(tmp_path / "config.toml")["diagnostics"]
        assert (saved["log_level"], saved["log_requests"]) == logs.get_logging_options()
