"""Text generation through the local Claude Code CLI (`claude -p`).

Lets the pipeline reuse an interactive Claude subscription instead of an API key.
The module owns every subprocess detail; app/services/llm.py only sees the same
``prompt -> text`` contract used by the HTTP providers.
"""

import json
import os
import shutil
import subprocess
import tempfile

from loguru import logger

DEFAULT_BINARY = "claude"
DEFAULT_MODEL = "opus"
DEFAULT_EFFORT = "medium"
DEFAULT_TIMEOUT = 300
VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max")

# The CLI ships a coding-agent system prompt. Replacing it keeps the model on
# copywriting instead of tool use, and cuts the per-call prompt overhead.
SYSTEM_PROMPT = (
    "You are a text generation engine inside an automated short-video pipeline. "
    "Follow the instructions in the user message exactly and return only the "
    "requested content: no preamble, no commentary, no markdown code fences and "
    "no follow-up questions."
)

_MAX_ERROR_LENGTH = 500
# Markers of the session that spawned us. Left in place they make the child
# behave like a nested agent; the OAuth token is the one value worth inheriting.
_INHERITED_ENV_KEYS = frozenset({"CLAUDE_CODE_OAUTH_TOKEN"})
_STRIPPED_ENV_PREFIXES = ("CLAUDECODE", "CLAUDE_CODE_", "CLAUDE_")


class ClaudeCliError(RuntimeError):
    """Raised when the CLI is missing, fails, times out or returns no text."""


def _truncate(text: str) -> str:
    value = " ".join((text or "").split())
    if len(value) <= _MAX_ERROR_LENGTH:
        return value
    return f"{value[:_MAX_ERROR_LENGTH]}..."


def _child_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key in _INHERITED_ENV_KEYS or not key.startswith(_STRIPPED_ENV_PREFIXES)
    }


def build_command(binary: str, model: str, effort: str) -> list[str]:
    return [
        binary,
        "-p",
        "--output-format",
        "json",
        "--model",
        model,
        "--effort",
        effort,
        "--system-prompt",
        SYSTEM_PROMPT,
        # No tools, no MCP servers, no skills: a single text turn.
        "--tools",
        "",
        "--strict-mcp-config",
        "--disable-slash-commands",
    ]


def _resolve_effort(effort: str | None) -> str:
    value = (effort or "").strip().lower() or DEFAULT_EFFORT
    if value not in VALID_EFFORTS:
        logger.warning(
            f"claude_code: unsupported effort '{value}', "
            f"falling back to '{DEFAULT_EFFORT}'"
        )
        return DEFAULT_EFFORT
    return value


def _resolve_timeout(timeout: object) -> int:
    try:
        value = int(timeout or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else DEFAULT_TIMEOUT


def _parse_output(stdout: str) -> str:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ClaudeCliError(
            f"claude cli returned invalid json: {_truncate(stdout)}"
        ) from exc

    if not isinstance(payload, dict):
        raise ClaudeCliError(f"claude cli returned invalid json: {_truncate(stdout)}")

    result = payload.get("result")
    if payload.get("is_error"):
        raise ClaudeCliError(
            f"claude cli reported an error: {_truncate(str(result or payload))}"
        )
    if not isinstance(result, str) or not result.strip():
        raise ClaudeCliError("claude cli returned an empty result")

    return result.strip()


def generate(
    prompt: str,
    *,
    model: str = "",
    effort: str = "",
    binary: str = "",
    timeout: object = 0,
) -> str:
    binary = (binary or "").strip() or DEFAULT_BINARY
    model = (model or "").strip() or DEFAULT_MODEL
    effort = _resolve_effort(effort)
    timeout_seconds = _resolve_timeout(timeout)

    executable = shutil.which(binary) or (binary if os.path.isfile(binary) else "")
    if not executable:
        raise ClaudeCliError(
            f"claude cli '{binary}' was not found. Install it from "
            "https://claude.ai/install.sh, log in with `claude`, or set "
            "claude_code_binary_path in config.toml."
        )

    command = build_command(executable, model, effort)
    logger.info(
        f"claude cli: model={model}, effort={effort}, timeout={timeout_seconds}"
    )

    # A neutral working directory keeps project CLAUDE.md, hooks and git state
    # out of a request that only has to return prose.
    with tempfile.TemporaryDirectory(prefix="mpt-claude-") as work_dir:
        try:
            completed = subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_seconds,
                cwd=work_dir,
                env=_child_env(),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ClaudeCliError(
                f"claude cli timed out after {timeout_seconds}s"
            ) from exc
        except OSError as exc:
            raise ClaudeCliError(f"failed to run claude cli: {exc}") from exc

    if completed.returncode != 0:
        raise ClaudeCliError(
            f"claude cli exited with code {completed.returncode}: "
            f"{_truncate(completed.stderr or completed.stdout)}"
        )

    return _parse_output(completed.stdout)
