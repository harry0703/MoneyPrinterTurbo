import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from loguru import logger

DEFAULT_BINARY = "codex"
DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_EFFORT = "low"
DEFAULT_TIMEOUT = 300
LOGIN_TIMEOUT = 10
VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max")

_MAX_ERROR_LENGTH = 500
_STRIPPED_ENV_KEYS = frozenset(
    {
        "CODEX_ACCESS_TOKEN",
        "CODEX_API_KEY",
        "CODEX_CI",
        "CODEX_THREAD_ID",
        "OPENAI_API_KEY",
    }
)
_DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "multi_agent",
    "multi_agent_v2",
    "apps",
    "browser_use",
    "computer_use",
    "image_generation",
)


class CodexCliError(RuntimeError):
    pass


def _truncate(text: str) -> str:
    value = " ".join((text or "").split())
    if len(value) <= _MAX_ERROR_LENGTH:
        return value
    return f"{value[:_MAX_ERROR_LENGTH]}..."


def _child_env() -> dict[str, str]:
    return {
        key: value for key, value in os.environ.items() if key not in _STRIPPED_ENV_KEYS
    }


def _resolve_binary(binary: str) -> str:
    value = (binary or "").strip() or DEFAULT_BINARY
    executable = shutil.which(value)
    if not executable and os.path.isfile(value) and os.access(value, os.X_OK):
        executable = value
    if not executable:
        raise CodexCliError(
            f"codex cli '{value}' was not found or is not executable. Install Codex, "
            "log in with `codex login`, or set photo_library_codex_binary_path."
        )
    return executable


def _resolve_effort(effort: str | None) -> str:
    value = (effort or "").strip().lower() or DEFAULT_EFFORT
    if value not in VALID_EFFORTS:
        logger.warning(
            f"codex_cli: unsupported effort '{value}', "
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


def check_chatgpt_login(binary: str = "") -> None:
    executable = _resolve_binary(binary)
    try:
        completed = subprocess.run(
            [executable, "login", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=LOGIN_TIMEOUT,
            env=_child_env(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CodexCliError("codex login status timed out") from exc
    except OSError as exc:
        raise CodexCliError(f"failed to check codex login: {exc}") from exc

    output = f"{completed.stdout}\n{completed.stderr}".strip()
    if completed.returncode != 0:
        raise CodexCliError(
            f"codex login status exited with code {completed.returncode}: "
            f"{_truncate(output)}"
        )
    if "logged in using chatgpt" not in output.lower():
        raise CodexCliError(
            "codex cli is not authenticated with ChatGPT; run `codex login` "
            "before using the subscription provider"
        )


def build_command(
    binary: str,
    model: str,
    effort: str,
    image_path: Path,
    schema_path: Path,
    output_path: Path,
    work_dir: Path,
) -> list[str]:
    command = [
        binary,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--strict-config",
        "--sandbox",
        "read-only",
        "--cd",
        str(work_dir),
        "--model",
        model,
        "--image",
        str(image_path),
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output_path),
        "--config",
        f'model_reasoning_effort="{effort}"',
        "--config",
        'approval_policy="never"',
    ]
    for feature in _DISABLED_FEATURES:
        command.extend(("--disable", feature))
    command.append("-")
    return command


def generate_json(
    prompt: str,
    image_path: str | Path,
    schema: Mapping[str, Any],
    *,
    model: str = "",
    effort: str = "",
    binary: str = "",
    timeout: object = 0,
) -> dict[str, Any]:
    executable = _resolve_binary(binary)
    check_chatgpt_login(executable)
    resolved_model = (model or "").strip() or DEFAULT_MODEL
    resolved_effort = _resolve_effort(effort)
    timeout_seconds = _resolve_timeout(timeout)
    resolved_image = Path(image_path).expanduser().resolve()
    if not resolved_image.is_file():
        raise CodexCliError(f"image file does not exist: {resolved_image}")

    logger.info(
        f"codex_cli: model={resolved_model}, effort={resolved_effort}, "
        f"timeout={timeout_seconds}"
    )
    with tempfile.TemporaryDirectory(prefix="mpt-codex-") as directory:
        work_dir = Path(directory)
        schema_path = work_dir / "output.schema.json"
        output_path = work_dir / "response.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
        command = build_command(
            executable,
            resolved_model,
            resolved_effort,
            resolved_image,
            schema_path,
            output_path,
            work_dir,
        )
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
            raise CodexCliError(
                f"codex cli timed out after {timeout_seconds}s"
            ) from exc
        except OSError as exc:
            raise CodexCliError(f"failed to run codex cli: {exc}") from exc

        if completed.returncode != 0:
            raise CodexCliError(
                f"codex cli exited with code {completed.returncode}: "
                f"{_truncate(completed.stderr or completed.stdout)}"
            )
        try:
            raw_output = output_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CodexCliError("codex cli returned no output") from exc

    if not raw_output.strip():
        raise CodexCliError("codex cli returned an empty result")
    try:
        payload = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise CodexCliError(
            f"codex cli returned invalid json: {_truncate(raw_output)}"
        ) from exc
    if not isinstance(payload, dict):
        raise CodexCliError(
            f"codex cli returned a non-object json value: {_truncate(raw_output)}"
        )
    return payload
