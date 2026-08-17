import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services import codex_cli

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["caption"],
    "properties": {"caption": {"type": "string"}},
}
PAYLOAD = {"caption": "Городская улица."}


def _completed(
    stdout: str = "", stderr: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["codex"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _successful_run(
    captured: dict[str, Any],
) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ["login", "status"]:
            return _completed(stdout="Logged in using ChatGPT")
        output_path = Path(command[command.index("--output-last-message") + 1])
        schema_path = Path(command[command.index("--output-schema") + 1])
        captured["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
        output_path.write_text(json.dumps(PAYLOAD), encoding="utf-8")
        return _completed(stderr="codex progress")

    return run


def test_safe_invocation_forwards_image_schema_prompt_and_environment(
    tmp_path: Path,
) -> None:
    image = tmp_path / "asset with spaces.png"
    image.write_bytes(b"image")
    captured: dict[str, Any] = {}
    environment = {
        "PATH": "/usr/bin",
        "CODEX_HOME": "/auth/home",
        "CODEX_THREAD_ID": "nested",
        "CODEX_CI": "1",
        "CODEX_ACCESS_TOKEN": "token",
        "CODEX_API_KEY": "codex-key",
        "OPENAI_API_KEY": "openai-key",
    }
    with (
        patch.dict(os.environ, environment, clear=True),
        patch.object(codex_cli.shutil, "which", return_value="/usr/bin/codex"),
        patch.object(
            codex_cli.subprocess,
            "run",
            side_effect=_successful_run(captured),
        ) as run,
    ):
        result = codex_cli.generate_json(
            "describe this image",
            image,
            SCHEMA,
            model="gpt-test",
            effort="low",
            timeout=123,
        )

    assert result == PAYLOAD
    assert run.call_count == 2
    login_call, exec_call = run.call_args_list
    assert login_call.args[0] == ["/usr/bin/codex", "login", "status"]
    command = exec_call.args[0]
    assert command[:2] == ["/usr/bin/codex", "exec"]
    assert command[-1] == "-"
    assert exec_call.kwargs["input"] == "describe this image"
    assert exec_call.kwargs["cwd"] == Path(command[command.index("--cd") + 1])
    assert exec_call.kwargs["timeout"] == 123
    assert command[command.index("--image") + 1] == str(image.resolve())
    assert command[command.index("--model") + 1] == "gpt-test"
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert "--skip-git-repo-check" in command
    assert "--strict-config" in command
    assert 'model_reasoning_effort="low"' in command
    assert 'approval_policy="never"' in command
    disabled = {
        command[index + 1]
        for index, value in enumerate(command)
        if value == "--disable"
    }
    assert disabled == set(codex_cli._DISABLED_FEATURES)
    assert captured["schema"] == SCHEMA
    child_env = exec_call.kwargs["env"]
    assert child_env["CODEX_HOME"] == "/auth/home"
    assert child_env["PATH"] == "/usr/bin"
    for key in (
        "CODEX_THREAD_ID",
        "CODEX_CI",
        "CODEX_ACCESS_TOKEN",
        "CODEX_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert key not in child_env
    assert "shell" not in exec_call.kwargs


def test_empty_options_use_documented_defaults(tmp_path: Path) -> None:
    image = tmp_path / "asset.png"
    image.write_bytes(b"image")
    with (
        patch.object(codex_cli.shutil, "which", return_value="/usr/bin/codex"),
        patch.object(
            codex_cli.subprocess, "run", side_effect=_successful_run({})
        ) as run,
    ):
        codex_cli.generate_json(
            "prompt", image, SCHEMA, model="", effort="", binary="", timeout=""
        )

    exec_call = run.call_args_list[1]
    command = exec_call.args[0]
    assert command[command.index("--model") + 1] == codex_cli.DEFAULT_MODEL
    assert f'model_reasoning_effort="{codex_cli.DEFAULT_EFFORT}"' in command
    assert exec_call.kwargs["timeout"] == codex_cli.DEFAULT_TIMEOUT


def test_missing_or_non_executable_binary_is_rejected(tmp_path: Path) -> None:
    image = tmp_path / "asset.png"
    image.write_bytes(b"image")
    with (
        patch.object(codex_cli.shutil, "which", return_value=None),
        patch.object(codex_cli.os.path, "isfile", return_value=True),
        patch.object(codex_cli.os, "access", return_value=False),
        pytest.raises(codex_cli.CodexCliError, match="not found or is not executable"),
    ):
        codex_cli.generate_json("prompt", image, SCHEMA, binary="/bad/codex")


def test_api_login_is_rejected_before_inference() -> None:
    with (
        patch.object(codex_cli.shutil, "which", return_value="/usr/bin/codex"),
        patch.object(
            codex_cli.subprocess,
            "run",
            return_value=_completed(stdout="Logged in using an API key"),
        ) as run,
        pytest.raises(codex_cli.CodexCliError, match="authenticated with ChatGPT"),
    ):
        codex_cli.check_chatgpt_login()
    assert run.call_count == 1


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (subprocess.TimeoutExpired(cmd="codex", timeout=300), "timed out"),
        (OSError("spawn failed"), "failed to run codex cli"),
    ],
)
def test_inference_process_errors_are_typed(
    tmp_path: Path, failure: BaseException, message: str
) -> None:
    image = tmp_path / "asset.png"
    image.write_bytes(b"image")
    run = MagicMock(side_effect=[_completed(stdout="Logged in using ChatGPT"), failure])
    with (
        patch.object(codex_cli.shutil, "which", return_value="/usr/bin/codex"),
        patch.object(codex_cli.subprocess, "run", run),
        pytest.raises(codex_cli.CodexCliError, match=message),
    ):
        codex_cli.generate_json("prompt", image, SCHEMA)


def test_nonzero_exit_has_bounded_diagnostics(tmp_path: Path) -> None:
    image = tmp_path / "asset.png"
    image.write_bytes(b"image")
    run = MagicMock(
        side_effect=[
            _completed(stdout="Logged in using ChatGPT"),
            _completed(stderr="secret " * 200, returncode=1),
        ]
    )
    with (
        patch.object(codex_cli.shutil, "which", return_value="/usr/bin/codex"),
        patch.object(codex_cli.subprocess, "run", run),
        pytest.raises(codex_cli.CodexCliError) as error,
    ):
        codex_cli.generate_json("prompt", image, SCHEMA)
    assert "exited with code 1" in str(error.value)
    assert len(str(error.value)) < 600


@pytest.mark.parametrize("raw_output", ["", "not json", "[]"])
def test_empty_invalid_or_non_object_output_is_rejected(
    tmp_path: Path, raw_output: str
) -> None:
    image = tmp_path / "asset.png"
    image.write_bytes(b"image")

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ["login", "status"]:
            return _completed(stdout="Logged in using ChatGPT")
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(raw_output, encoding="utf-8")
        return _completed()

    with (
        patch.object(codex_cli.shutil, "which", return_value="/usr/bin/codex"),
        patch.object(codex_cli.subprocess, "run", side_effect=run),
        pytest.raises(codex_cli.CodexCliError),
    ):
        codex_cli.generate_json("prompt", image, SCHEMA)
