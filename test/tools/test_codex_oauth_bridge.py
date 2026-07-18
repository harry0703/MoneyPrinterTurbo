import json
import subprocess
import threading
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from tools.codex_oauth_bridge import server
from tools.codex_oauth_bridge.codex_runner import (
    CodexRunError,
    build_codex_command,
    parse_codex_jsonl,
    run_codex,
)


@pytest.fixture
def bridge_http_url() -> str:
    bridge = server.create_server("127.0.0.1", 0, "test-token", "codex-test")
    thread = threading.Thread(target=bridge.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{bridge.server_port}"
    finally:
        bridge.shutdown()
        bridge.server_close()
        thread.join(timeout=2)


def bridge_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def bridge_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "instructions": "plain text",
        "input": "episode",
        "model": "",
        "timeout_seconds": 120,
    }
    payload.update(overrides)
    return payload


def event(event_type: str, **values: object) -> str:
    return json.dumps({"type": event_type, **values})


def test_builds_exact_ephemeral_read_only_command() -> None:
    assert build_codex_command("C:/bin/codex.exe", Path("unused"), " gpt-5 ") == [
        "C:/bin/codex.exe",
        "exec",
        "--ephemeral",
        "--json",
        "--sandbox",
        "read-only",
        "--ask-for-approval",
        "never",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--model",
        "gpt-5",
        "-",
    ]


def test_parse_returns_last_completed_agent_message() -> None:
    stdout = "\n".join(
        [
            event("item.completed", item={"type": "agent_message", "text": "first"}),
            event("item.completed", item={"type": "agent_message", "text": "last"}),
        ]
    )

    assert parse_codex_jsonl(stdout) == "last"


def test_parse_classifies_failed_turn() -> None:
    with pytest.raises(CodexRunError, match="Codex run failed") as error:
        parse_codex_jsonl(event("turn.failed"))

    assert error.value.code == "codex_failed"


def test_run_uses_empty_temp_cwd_prompt_and_timeout() -> None:
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=event("item.completed", item={"type": "agent_message", "text": "done"}),
        stderr="private stderr",
    )

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        cwd = Path(str(kwargs["cwd"]))
        assert cwd.name.startswith("mpt-codex-")
        assert list(cwd.iterdir()) == []
        return completed

    with patch("tools.codex_oauth_bridge.codex_runner.subprocess.run", side_effect=fake_run) as run:
        result = run_codex("  Follow policy.  ", "episode body", "", 37)

    assert result == "done"
    kwargs = run.call_args.kwargs
    assert kwargs["timeout"] == 37
    assert kwargs["input"] == "Follow policy.\n\n<episode_input>\nepisode body\n</episode_input>"
    assert kwargs["text"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["capture_output"] is True


def test_run_removes_api_key_environment_variables_but_preserves_oauth_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=event("item.completed", item={"type": "agent_message", "text": "done"}),
        stderr="",
    )
    monkeypatch.setenv("CODEX_API_KEY", "must-not-reach-codex")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-codex")
    monkeypatch.setenv("PATH_MARKER", "preserve-oauth-context")

    with patch("tools.codex_oauth_bridge.codex_runner.subprocess.run", return_value=completed) as run:
        assert run_codex("instruction", "input", "", 30) == "done"

    environment = run.call_args.kwargs["env"]
    assert "CODEX_API_KEY" not in environment
    assert "OPENAI_API_KEY" not in environment
    assert environment["PATH_MARKER"] == "preserve-oauth-context"


def test_run_maps_missing_executable_without_stderr() -> None:
    with patch(
        "tools.codex_oauth_bridge.codex_runner.subprocess.run",
        side_effect=FileNotFoundError("private executable path"),
    ):
        with pytest.raises(CodexRunError) as error:
            run_codex("instruction", "input", "", 10)

    assert error.value.code == "codex_not_found"
    assert "private" not in str(error.value)


def test_run_maps_timeout_without_stderr() -> None:
    timeout = subprocess.TimeoutExpired("codex", 10, stderr="private stderr")
    with patch("tools.codex_oauth_bridge.codex_runner.subprocess.run", side_effect=timeout):
        with pytest.raises(CodexRunError) as error:
            run_codex("instruction", "input", "", 10)

    assert error.value.code == "timeout"
    assert "private" not in str(error.value)


def test_run_maps_nonzero_exit_without_stderr() -> None:
    completed = subprocess.CompletedProcess([], 1, "", "private stderr")
    with patch("tools.codex_oauth_bridge.codex_runner.subprocess.run", return_value=completed):
        with pytest.raises(CodexRunError) as error:
            run_codex("instruction", "input", "", 10)

    assert error.value.code == "codex_failed"
    assert "private" not in str(error.value)


def test_run_maps_malformed_jsonl() -> None:
    completed = subprocess.CompletedProcess([], 0, "not json", "private stderr")
    with patch("tools.codex_oauth_bridge.codex_runner.subprocess.run", return_value=completed):
        with pytest.raises(CodexRunError) as error:
            run_codex("instruction", "input", "", 10)

    assert error.value.code == "invalid_output"
    assert "private" not in str(error.value)


def test_run_maps_empty_output() -> None:
    completed = subprocess.CompletedProcess([], 0, event("turn.completed"), "private stderr")
    with patch("tools.codex_oauth_bridge.codex_runner.subprocess.run", return_value=completed):
        with pytest.raises(CodexRunError) as error:
            run_codex("instruction", "input", "", 10)

    assert error.value.code == "empty_output"
    assert "private" not in str(error.value)


def test_bridge_http_generate_requires_bearer_token(bridge_http_url: str) -> None:
    response = requests.post(f"{bridge_http_url}/v1/generate", json=bridge_payload())

    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "unauthorized", "message": "Invalid bridge token"}
    }


def test_bridge_http_rejects_non_ascii_bearer_token(bridge_http_url: str) -> None:
    response = requests.post(
        f"{bridge_http_url}/v1/generate",
        headers={"Authorization": "Bearer t\u00e9st-token"},
        json=bridge_payload(),
    )

    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "unauthorized", "message": "Invalid bridge token"}
    }


def test_bridge_http_generate_returns_runner_output(
    bridge_http_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run_codex(**kwargs: object) -> str:
        calls.append(kwargs)
        return "narration"

    monkeypatch.setattr(server, "run_codex", fake_run_codex)

    response = requests.post(
        f"{bridge_http_url}/v1/generate",
        headers=bridge_headers(),
        json=bridge_payload(),
    )

    assert response.status_code == 200
    assert response.json() == {"output_text": "narration"}
    assert calls == [
        {
            "instructions": "plain text",
            "input_text": "episode",
            "model": "",
            "timeout_seconds": 120,
            "executable": "codex-test",
        }
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"instructions": "x", "input": "y", "unknown": True},
        bridge_payload(instructions="   "),
        bridge_payload(input="\t"),
        bridge_payload(timeout_seconds=29),
        bridge_payload(timeout_seconds=901),
        bridge_payload(timeout_seconds=True),
    ],
)
def test_bridge_http_rejects_invalid_json_requests(
    bridge_http_url: str, payload: dict[str, object]
) -> None:
    response = requests.post(
        f"{bridge_http_url}/v1/generate", headers=bridge_headers(), json=payload
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {"code": "invalid_request", "message": "Request body is invalid"}
    }


def test_bridge_http_rejects_non_json_body(bridge_http_url: str) -> None:
    response = requests.post(
        f"{bridge_http_url}/v1/generate",
        headers=bridge_headers(),
        data=b"not json",
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {"code": "invalid_request", "message": "Request body is invalid"}
    }


def test_bridge_http_rejects_missing_or_invalid_content_length(bridge_http_url: str) -> None:
    host, port = bridge_http_url.removeprefix("http://").split(":")
    connection = HTTPConnection(host, int(port), timeout=2)
    connection.putrequest("POST", "/v1/generate", skip_accept_encoding=True)
    connection.putheader("Authorization", "Bearer test-token")
    connection.endheaders(b"{}")
    missing_length = connection.getresponse()

    assert missing_length.status == 400
    assert json.loads(missing_length.read()) == {
        "error": {"code": "invalid_request", "message": "Request body is invalid"}
    }

    connection.close()
    connection = HTTPConnection(host, int(port), timeout=2)
    connection.putrequest("POST", "/v1/generate", skip_accept_encoding=True)
    connection.putheader("Authorization", "Bearer test-token")
    connection.putheader("Content-Length", "not-a-number")
    connection.endheaders(b"{}")
    invalid_length = connection.getresponse()

    assert invalid_length.status == 400
    assert json.loads(invalid_length.read()) == {
        "error": {"code": "invalid_request", "message": "Request body is invalid"}
    }
    connection.close()


def test_bridge_http_rejects_oversized_body_before_reading(bridge_http_url: str) -> None:
    host, port = bridge_http_url.removeprefix("http://").split(":")
    connection = HTTPConnection(host, int(port), timeout=2)
    connection.putrequest("POST", "/v1/generate", skip_accept_encoding=True)
    connection.putheader("Authorization", "Bearer test-token")
    connection.putheader("Content-Length", "262145")
    connection.endheaders()
    response = connection.getresponse()

    assert response.status == 413
    assert json.loads(response.read()) == {
        "error": {"code": "invalid_request", "message": "Request body is invalid"}
    }
    connection.close()


def test_bridge_http_uses_bounded_default_timeout(
    bridge_http_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(server, "run_codex", lambda **kwargs: calls.append(kwargs) or "ok")

    response = requests.post(
        f"{bridge_http_url}/v1/generate",
        headers=bridge_headers(),
        json={"instructions": "plain text", "input": "episode"},
    )

    assert response.status_code == 200
    assert calls[0]["timeout_seconds"] == 300


def test_bridge_http_maps_runner_errors(
    bridge_http_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        server,
        "run_codex",
        lambda **kwargs: (_ for _ in ()).throw(CodexRunError("timeout", "Codex run timed out.")),
    )
    timeout_response = requests.post(
        f"{bridge_http_url}/v1/generate", headers=bridge_headers(), json=bridge_payload()
    )

    assert timeout_response.status_code == 504
    assert timeout_response.json() == {
        "error": {"code": "timeout", "message": "Codex run timed out."}
    }

    monkeypatch.setattr(
        server,
        "run_codex",
        lambda **kwargs: (_ for _ in ()).throw(
            CodexRunError("codex_not_found", "Codex executable was not found.")
        ),
    )
    unavailable_response = requests.post(
        f"{bridge_http_url}/v1/generate", headers=bridge_headers(), json=bridge_payload()
    )

    assert unavailable_response.status_code == 502
    assert unavailable_response.json() == {
        "error": {"code": "codex_not_found", "message": "Codex executable was not found."}
    }


def test_bridge_http_rejects_oversized_runner_output(
    bridge_http_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "run_codex", lambda **kwargs: "x" * 131073)

    response = requests.post(
        f"{bridge_http_url}/v1/generate", headers=bridge_headers(), json=bridge_payload()
    )

    assert response.status_code == 502
    assert response.json() == {
        "error": {"code": "invalid_output", "message": "Codex output exceeded maximum size."}
    }


def test_bridge_http_rejects_concurrent_generation(
    bridge_http_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = threading.Event()
    release = threading.Event()
    first_response: list[requests.Response] = []

    def blocking_run_codex(**kwargs: object) -> str:
        started.set()
        assert release.wait(timeout=2)
        return "first"

    monkeypatch.setattr(server, "run_codex", blocking_run_codex)
    first = threading.Thread(
        target=lambda: first_response.append(
            requests.post(
                f"{bridge_http_url}/v1/generate",
                headers=bridge_headers(),
                json=bridge_payload(),
                timeout=3,
            )
        )
    )
    first.start()
    assert started.wait(timeout=2)

    busy_response = requests.post(
        f"{bridge_http_url}/v1/generate",
        headers=bridge_headers(),
        json=bridge_payload(),
        timeout=3,
    )
    release.set()
    first.join(timeout=3)

    assert busy_response.status_code == 429
    assert busy_response.json() == {
        "error": {
            "code": "busy",
            "message": "Codex bridge is processing another request",
        }
    }
    assert first_response[0].status_code == 200


def test_bridge_http_health_reports_executable_availability(
    bridge_http_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server.shutil, "which", lambda executable: executable == "codex-test")

    response = requests.get(f"{bridge_http_url}/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "codex_available": True}


def test_bridge_http_uses_stable_error_for_unsupported_methods(bridge_http_url: str) -> None:
    response = requests.delete(f"{bridge_http_url}/v1/generate")

    assert response.status_code == 400
    assert response.json() == {
        "error": {"code": "invalid_request", "message": "Request body is invalid"}
    }
