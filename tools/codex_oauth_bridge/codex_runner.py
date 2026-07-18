"""Run the host's logged-in Codex CLI without exposing its credentials."""

import json
import os
import subprocess
import tempfile
from pathlib import Path


class CodexRunError(RuntimeError):
    """A safe, classified error from an isolated Codex CLI invocation."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def build_codex_command(executable: str, cwd: Path, model: str = "") -> list[str]:
    """Build the fixed, read-only command used for an isolated Codex run."""
    del cwd
    command = [
        executable,
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
    ]
    if trimmed_model := model.strip():
        command.extend(["--model", trimmed_model])
    return [*command, "-"]


def parse_codex_jsonl(stdout: str) -> str:
    """Return the last completed agent message from Codex JSONL output."""
    last_message = ""
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise CodexRunError("invalid_output", "Codex returned invalid output.") from error
        if not isinstance(event, dict):
            raise CodexRunError("invalid_output", "Codex returned invalid output.")
        if event.get("type") == "turn.failed":
            raise CodexRunError("codex_failed", "Codex run failed.")
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict):
            text = item.get("text")
            if item.get("type") == "agent_message" and isinstance(text, str) and text:
                last_message = text
    if not last_message:
        raise CodexRunError("empty_output", "Codex returned no final agent message.")
    return last_message


def run_codex(
    instructions: str,
    input_text: str,
    model: str,
    timeout_seconds: int,
    executable: str = "codex",
) -> str:
    """Execute Codex in a fresh, read-only directory and return its final reply."""
    prompt = f"{instructions.strip()}\n\n<episode_input>\n{input_text}\n</episode_input>"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    with tempfile.TemporaryDirectory(prefix="mpt-codex-") as directory:
        try:
            result = subprocess.run(
                build_codex_command(executable, Path(directory), model),
                cwd=directory,
                input=prompt,
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
                creationflags=creationflags,
            )
        except FileNotFoundError as error:
            raise CodexRunError("codex_not_found", "Codex executable was not found.") from error
        except subprocess.TimeoutExpired as error:
            raise CodexRunError("timeout", "Codex run timed out.") from error

    if result.returncode != 0:
        raise CodexRunError("codex_failed", "Codex run failed.")
    return parse_codex_jsonl(result.stdout)
