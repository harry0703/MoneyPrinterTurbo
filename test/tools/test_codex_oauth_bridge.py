import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.codex_oauth_bridge.codex_runner import (
    CodexRunError,
    build_codex_command,
    parse_codex_jsonl,
    run_codex,
)


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
