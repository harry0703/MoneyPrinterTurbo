"""Safe, stateless helpers for discovering models through a local OpenCode CLI.

MoneyPrinterTurbo delegates authentication and provider configuration to OpenCode.
This module only invokes the documented V2 ``api`` command, validates the CLI
version, and parses the structured model catalog. It deliberately does not start
an agent session or expose tools, files, MCP, or provider credentials.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from loguru import logger
from packaging.version import InvalidVersion, Version


# The current experimental one-shot generation route is
# ``/api/experimental/generate``. OpenCode v2.0.4 is the first V2 release that
# exposes that route; v2.0.0-v2.0.3 used the earlier ``/api/generate`` path.
OPENCODE_MIN_VERSION: Final[Version] = Version("2.0.4")
OPENCODE_DEFAULT_TIMEOUT_SECONDS: Final[float] = 60.0

_OPENCODE_VERSION_RE = re.compile(
    r"(?<![0-9A-Za-z])v?(\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z.-]+)?)"
)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|authorization|secret|password)"
    r"\s*[:=]\s*[^\s,;]+"
)


class OpenCodeError(Exception):
    """Base class for errors raised by the local OpenCode integration."""


class OpenCodeNotFoundError(OpenCodeError):
    """The configured OpenCode executable could not be found."""


class OpenCodeVersionError(OpenCodeError):
    """The installed CLI did not report a supported OpenCode V2 version."""


class OpenCodeCommandError(OpenCodeError):
    """An OpenCode CLI command failed or returned an unusable result."""


class OpenCodeTimeoutError(OpenCodeCommandError):
    """An OpenCode CLI command exceeded its configured timeout."""


class OpenCodeProtocolError(OpenCodeCommandError):
    """OpenCode returned JSON that did not match the documented API shape."""


@dataclass(frozen=True, slots=True)
class OpenCodeCliInfo:
    """The resolved executable and validated version of an OpenCode CLI."""

    executable: str
    version: Version

    @property
    def version_string(self) -> str:
        return str(self.version)


@dataclass(frozen=True, slots=True)
class OpenCodeModelRef:
    """A provider/model/variant reference accepted by OpenCode's API."""

    provider_id: str
    model_id: str
    variant: str | None = None

    def __post_init__(self) -> None:
        provider_id = _validate_identifier(
            self.provider_id,
            field_name="provider_id",
            allow_slash=False,
        )
        model_id = _validate_identifier(
            self.model_id,
            field_name="model_id",
            allow_slash=True,
        )
        variant = self.variant
        if variant is not None:
            variant = _validate_identifier(
                variant,
                field_name="variant",
                allow_slash=True,
            )

        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "variant", variant)

    @classmethod
    def from_string(cls, value: str) -> OpenCodeModelRef:
        """Parse ``provider/model`` or ``provider/model#variant`` safely."""

        raw_value = str(value or "").strip()
        if not raw_value:
            raise ValueError("OpenCode model reference cannot be empty")

        model_part, separator, variant = raw_value.partition("#")
        if not separator:
            variant = ""
        provider_id, provider_separator, model_id = model_part.partition("/")
        if not provider_separator or not provider_id or not model_id:
            raise ValueError(
                "OpenCode model reference must use provider/model or "
                "provider/model#variant"
            )

        return cls(
            provider_id=provider_id,
            model_id=model_id,
            variant=variant or None,
        )

    def to_string(self) -> str:
        value = f"{self.provider_id}/{self.model_id}"
        if self.variant:
            value = f"{value}#{self.variant}"
        return value

    def to_api_dict(self) -> dict[str, str]:
        """Return the object shape accepted by OpenCode's generation API."""

        value = {"id": self.model_id, "providerID": self.provider_id}
        if self.variant:
            value["variant"] = self.variant
        return value

    def __str__(self) -> str:
        return self.to_string()


@dataclass(frozen=True, slots=True)
class OpenCodeModel:
    """A text-capable model returned by OpenCode's catalog."""

    ref: OpenCodeModelRef
    upstream_model_id: str
    name: str
    enabled: bool
    output_modalities: tuple[str, ...]
    variants: tuple[str, ...]
    status: str

    @property
    def supports_text(self) -> bool:
        return "text" in self.output_modalities

    @property
    def display_name(self) -> str:
        return f"{self.name} ({self.ref})"


def _validate_identifier(value: Any, *, field_name: str, allow_slash: bool) -> str:
    if not isinstance(value, str):
        raise ValueError(f"OpenCode {field_name} must be a string")

    normalized = value.strip()
    if not normalized:
        raise ValueError(f"OpenCode {field_name} cannot be empty")
    if "\x00" in normalized or "#" in normalized:
        raise ValueError(f"OpenCode {field_name} contains an invalid character")
    if not allow_slash and "/" in normalized:
        raise ValueError(f"OpenCode {field_name} cannot contain '/'")
    return normalized


def parse_opencode_version(output: str) -> Version:
    """Extract and parse a semantic version from ``opencode --version`` output."""

    text = str(output or "").strip()
    match = _OPENCODE_VERSION_RE.search(text)
    if not match:
        raise OpenCodeVersionError(
            "OpenCode CLI did not report a recognizable version; "
            f"output was {text[:120]!r}"
        )

    try:
        return Version(match.group(1))
    except InvalidVersion as exc:
        raise OpenCodeVersionError(
            f"OpenCode CLI reported an invalid version: {match.group(1)!r}"
        ) from exc


def ensure_supported_version(version: Version | str) -> Version:
    """Validate a parsed CLI version against the supported V2 API floor."""

    try:
        normalized = version if isinstance(version, Version) else Version(str(version))
    except InvalidVersion as exc:
        raise OpenCodeVersionError(
            f"OpenCode CLI reported an invalid version: {version!r}"
        ) from exc

    if normalized < OPENCODE_MIN_VERSION:
        raise OpenCodeVersionError(
            "OpenCode CLI "
            f"{normalized} is too old; install version {OPENCODE_MIN_VERSION} "
            "or newer for the MoneyPrinterTurbo integration"
        )
    return normalized


def resolve_opencode_executable(cli_path: str | None = None) -> str:
    """Resolve a configured command/path without invoking a shell."""

    configured = str(cli_path or "").strip()
    if configured:
        if len(configured) >= 2 and configured[0] == configured[-1] == '"':
            configured = configured[1:-1].strip()
        resolved = shutil.which(configured)
        if resolved:
            return resolved
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return str(candidate)
        raise OpenCodeNotFoundError(
            f"OpenCode CLI was not found at the configured path: {configured!r}"
        )

    resolved = shutil.which("opencode")
    if not resolved:
        raise OpenCodeNotFoundError(
            "OpenCode CLI was not found on PATH; install OpenCode or configure "
            "the CLI path"
        )
    return resolved


def _coerce_timeout(value: float | int | None) -> float:
    if value is None:
        return OPENCODE_DEFAULT_TIMEOUT_SECONDS
    if isinstance(value, bool):
        raise ValueError("OpenCode timeout must be a positive number of seconds")
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "OpenCode timeout must be a positive number of seconds"
        ) from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("OpenCode timeout must be a positive finite number")
    return timeout


def _sanitize_cli_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = str(value).strip()
    text = _SENSITIVE_ASSIGNMENT_RE.sub(r"\1=***", text)
    return text[:500]


def _run_opencode_command(
    executable: str,
    args: list[str],
    *,
    timeout: float,
    cwd: str | os.PathLike[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [executable, *args]
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
        "check": False,
        "stdin": subprocess.DEVNULL,
    }
    if cwd is not None:
        kwargs["cwd"] = cwd
    if os.name == "nt":
        # Avoid opening a console window for a WebUI child process on Windows.
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if creation_flags:
            kwargs["creationflags"] = creation_flags

    try:
        return subprocess.run(command, **kwargs)
    except FileNotFoundError as exc:
        raise OpenCodeNotFoundError(
            f"OpenCode executable could not be started: {executable!r}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise OpenCodeTimeoutError(
            f"OpenCode command timed out after {timeout:.0f}s"
        ) from exc
    except OSError as exc:
        raise OpenCodeCommandError(
            f"failed to start OpenCode command: {_sanitize_cli_output(str(exc))}"
        ) from exc


def _raise_for_command_failure(completed: subprocess.CompletedProcess[str]) -> None:
    if completed.returncode == 0:
        return
    detail = _sanitize_cli_output(completed.stderr or completed.stdout)
    suffix = f": {detail}" if detail else ""
    raise OpenCodeCommandError(
        f"OpenCode command exited with code {completed.returncode}{suffix}"
    )


def inspect_opencode_cli(
    cli_path: str | None = None,
    *,
    timeout: float | int | None = OPENCODE_DEFAULT_TIMEOUT_SECONDS,
    cwd: str | os.PathLike[str] | None = None,
) -> OpenCodeCliInfo:
    """Resolve and validate the local OpenCode CLI."""

    timeout_seconds = _coerce_timeout(timeout)
    executable = resolve_opencode_executable(cli_path)
    completed = _run_opencode_command(
        executable,
        ["--version"],
        timeout=timeout_seconds,
        cwd=cwd,
    )
    _raise_for_command_failure(completed)
    version = ensure_supported_version(parse_opencode_version(completed.stdout))
    return OpenCodeCliInfo(executable=executable, version=version)


def _parse_model(payload: Any) -> OpenCodeModel:
    if not isinstance(payload, Mapping):
        raise OpenCodeProtocolError("OpenCode model entry must be an object")

    model_id = payload.get("id")
    provider_id = payload.get("providerID")
    ref = OpenCodeModelRef(provider_id=provider_id, model_id=model_id)

    upstream_model_id = payload.get("modelID") or model_id
    upstream_model_id = _validate_identifier(
        upstream_model_id,
        field_name="modelID",
        allow_slash=True,
    )
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        name = model_id
    name = name.strip()

    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise OpenCodeProtocolError(f"OpenCode model {ref} has an invalid enabled flag")

    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, Mapping):
        raise OpenCodeProtocolError(f"OpenCode model {ref} has no capabilities object")
    output_modalities = capabilities.get("output")
    if not isinstance(output_modalities, (list, tuple)):
        raise OpenCodeProtocolError(
            f"OpenCode model {ref} has invalid output capabilities"
        )
    normalized_outputs = []
    for modality in output_modalities:
        if not isinstance(modality, str) or not modality.strip():
            raise OpenCodeProtocolError(
                f"OpenCode model {ref} has an invalid output modality"
            )
        normalized_outputs.append(modality.strip().lower())

    raw_variants = payload.get("variants", [])
    if raw_variants is None:
        raw_variants = []
    if not isinstance(raw_variants, (list, tuple)):
        raise OpenCodeProtocolError(f"OpenCode model {ref} has invalid variants")
    variants = []
    for raw_variant in raw_variants:
        if not isinstance(raw_variant, Mapping):
            raise OpenCodeProtocolError(
                f"OpenCode model {ref} has an invalid variant entry"
            )
        variant_id = raw_variant.get("id")
        variants.append(
            _validate_identifier(
                variant_id,
                field_name="variant id",
                allow_slash=True,
            )
        )

    status = payload.get("status") or "active"
    if not isinstance(status, str) or not status.strip():
        status = "active"

    return OpenCodeModel(
        ref=ref,
        upstream_model_id=upstream_model_id,
        name=name,
        enabled=enabled,
        output_modalities=tuple(dict.fromkeys(normalized_outputs)),
        variants=tuple(dict.fromkeys(variants)),
        status=status.strip(),
    )


def parse_model_catalog(payload: Any) -> tuple[OpenCodeModel, ...]:
    """Parse an OpenCode ``/api/model`` response and keep usable text models.

    Individual malformed entries are skipped so one unusual provider cannot
    make the entire catalog unusable. A malformed top-level response is still
    reported as a protocol error because it usually indicates an incompatible
    CLI or service.
    """

    if not isinstance(payload, Mapping):
        raise OpenCodeProtocolError("OpenCode model response must be an object")
    raw_models = payload.get("data")
    if not isinstance(raw_models, (list, tuple)):
        raise OpenCodeProtocolError("OpenCode model response has no data array")

    models = []
    for index, raw_model in enumerate(raw_models):
        try:
            model = _parse_model(raw_model)
        except (OpenCodeError, ValueError) as exc:
            logger.warning(
                "skip malformed OpenCode model entry: "
                f"index={index}, error_type={type(exc).__name__}"
            )
            continue
        if model.enabled and model.supports_text:
            models.append(model)

    return tuple(
        sorted(models, key=lambda model: (model.ref.provider_id, model.ref.model_id))
    )


def discover_opencode_models(
    cli_path: str | None = None,
    *,
    timeout: float | int | None = OPENCODE_DEFAULT_TIMEOUT_SECONDS,
    cwd: str | os.PathLike[str] | None = None,
) -> tuple[OpenCodeModel, ...]:
    """Discover enabled, text-capable models from the local OpenCode CLI."""

    timeout_seconds = _coerce_timeout(timeout)
    cli_info = inspect_opencode_cli(
        cli_path,
        timeout=timeout_seconds,
        cwd=cwd,
    )
    completed = _run_opencode_command(
        cli_info.executable,
        ["api", "get", "/api/model"],
        timeout=timeout_seconds,
        cwd=cwd,
    )
    _raise_for_command_failure(completed)

    try:
        payload = json.loads(completed.stdout or "")
    except (TypeError, json.JSONDecodeError) as exc:
        raise OpenCodeProtocolError(
            "OpenCode returned invalid JSON while discovering models"
        ) from exc
    return parse_model_catalog(payload)


__all__ = [
    "OPENCODE_DEFAULT_TIMEOUT_SECONDS",
    "OPENCODE_MIN_VERSION",
    "OpenCodeCliInfo",
    "OpenCodeCommandError",
    "OpenCodeError",
    "OpenCodeModel",
    "OpenCodeModelRef",
    "OpenCodeNotFoundError",
    "OpenCodeProtocolError",
    "OpenCodeTimeoutError",
    "OpenCodeVersionError",
    "discover_opencode_models",
    "ensure_supported_version",
    "inspect_opencode_cli",
    "parse_model_catalog",
    "parse_opencode_version",
    "resolve_opencode_executable",
]
