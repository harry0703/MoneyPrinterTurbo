"""Safe, stateless helpers for discovering models through a local OpenCode CLI.

MoneyPrinterTurbo delegates authentication and provider configuration to OpenCode.
This module only invokes the documented V2 ``api`` command, validates the CLI
and shared server versions, explicitly scopes model discovery to the requested
working directory, and parses the structured model catalog. It deliberately does
not start an agent session or expose tools, files, MCP, or provider credentials.
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


# The provider's one-shot generation route is ``/api/experimental/generate``.
# OpenCode v2.0.4 is the first V2 release that exposes that route; v2.0.0-v2.0.3
# used the earlier ``/api/generate`` path. Keep this floor for the complete
# provider integration, including generation, rather than for model discovery
# alone.
OPENCODE_MIN_VERSION: Final[Version] = Version("2.0.4")
OPENCODE_DEFAULT_TIMEOUT_SECONDS: Final[float] = 60.0

_OPENCODE_VERSION_RE = re.compile(
    r"(?<![0-9A-Za-z.])v?(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)"
    r"(?!\.\d)(?=$|[\s,)]|\Z)"
)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|api\s+key|access[_-]?token|access\s+token|authorization|secret|password)"
    r"[\"']?\s*[:=]\s*[\"']?(?:bearer\s+)?)([^\s,;\"'}]+)"
)
_SENSITIVE_QUERY_RE = re.compile(
    r"(?i)([?&](?:api[_-]?key|access[_-]?token|token|key|secret|password)=)"
    r"[^&\s]+"
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


class OpenCodeNoModelsError(OpenCodeError):
    """OpenCode returned no enabled model that can accept a text prompt."""


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
        if separator and not variant:
            raise ValueError("OpenCode model variant cannot be empty")
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
    """A text-input/text-output model returned by OpenCode's catalog."""

    ref: OpenCodeModelRef
    upstream_model_id: str
    name: str
    enabled: bool
    input_modalities: tuple[str, ...]
    output_modalities: tuple[str, ...]
    variants: tuple[str, ...]
    status: str

    @property
    def supports_text(self) -> bool:
        """Whether the model accepts text prompts and returns text output."""

        return "text" in self.input_modalities and "text" in self.output_modalities

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
            f"output was {_sanitize_cli_output(text)[:120]!r}"
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


def _reject_unlaunchable_windows_shim(executable: str) -> str:
    if os.name == "nt" and Path(executable).suffix.lower() == ".ps1":
        raise OpenCodeNotFoundError(
            "OpenCode CLI path points to a PowerShell shim, which cannot be "
            "launched with shell=False; configure the .cmd shim or the OpenCode "
            "executable instead"
        )
    return executable


def resolve_opencode_executable(cli_path: str | None = None) -> str:
    """Resolve a configured command/path without invoking a shell."""

    configured = str(cli_path or "").strip()
    if configured:
        if len(configured) >= 2 and configured[0] == configured[-1] == '"':
            configured = configured[1:-1].strip()
        resolved = shutil.which(configured)
        if resolved:
            return _reject_unlaunchable_windows_shim(resolved)
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return _reject_unlaunchable_windows_shim(str(candidate.resolve()))
        raise OpenCodeNotFoundError(
            f"OpenCode CLI was not found at the configured path: {configured!r}"
        )

    resolved = shutil.which("opencode")
    if not resolved:
        raise OpenCodeNotFoundError(
            "OpenCode CLI was not found on PATH; install OpenCode or configure "
            "the CLI path"
        )
    return _reject_unlaunchable_windows_shim(resolved)


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


def coerce_opencode_timeout(
    value: float | int | str | None,
    *,
    config_key: str = "opencode_timeout",
) -> float:
    """Normalize a configured timeout and identify the invalid config key."""

    if value is None or (isinstance(value, str) and not value.strip()):
        return OPENCODE_DEFAULT_TIMEOUT_SECONDS
    try:
        return _coerce_timeout(value)
    except ValueError as exc:
        raise ValueError(f"{config_key}: {exc}") from exc


def _sanitize_cli_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = str(value).strip()
    text = _SENSITIVE_ASSIGNMENT_RE.sub(r"\1***", text)
    text = _SENSITIVE_QUERY_RE.sub(r"\1***", text)
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
    details = [
        _sanitize_cli_output(completed.stderr),
        _sanitize_cli_output(completed.stdout),
    ]
    detail = " | ".join(value for value in details if value)
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


def _normalized_directory(value: str | os.PathLike[str] | None) -> str:
    directory = Path(value or Path.cwd()).expanduser()
    if not directory.is_absolute():
        directory = Path.cwd() / directory
    return os.path.normcase(str(directory.resolve()))


def _response_directory(payload: Mapping[str, Any]) -> str:
    location = payload.get("location")
    if not isinstance(location, Mapping):
        raise OpenCodeProtocolError("OpenCode response has no location object")
    directory = location.get("directory")
    if not isinstance(directory, str) or not directory.strip():
        raise OpenCodeProtocolError("OpenCode response has no location directory")
    return _normalized_directory(directory)


def _decode_json_object(
    completed: subprocess.CompletedProcess[str], *, context: str
) -> Mapping[str, Any]:
    try:
        payload = json.loads(completed.stdout or "")
    except (TypeError, json.JSONDecodeError) as exc:
        raise OpenCodeProtocolError(
            f"OpenCode returned invalid JSON for {context}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise OpenCodeProtocolError(f"OpenCode returned a non-object for {context}")
    return payload


def inspect_opencode_server(
    cli_info: OpenCodeCliInfo,
    *,
    timeout: float | int | None = OPENCODE_DEFAULT_TIMEOUT_SECONDS,
    cwd: str | os.PathLike[str] | None = None,
) -> Version:
    """Validate the shared OpenCode service before using its credentials.

    The service is intentionally shared so the user's existing OpenCode accounts
    remain available. The generation request itself is stateless; no agent or
    session is created. Checking ``/api/info`` prevents silently using an older
    service left behind by another CLI installation.
    """

    timeout_seconds = _coerce_timeout(timeout)
    completed = _run_opencode_command(
        cli_info.executable,
        ["api", "get", "/api/info"],
        timeout=timeout_seconds,
        cwd=cwd,
    )
    _raise_for_command_failure(completed)
    payload = _decode_json_object(completed, context="server info")
    version = payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise OpenCodeProtocolError("OpenCode server info has no version")
    return ensure_supported_version(parse_opencode_version(version))


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

    def normalize_modalities(key: str) -> tuple[str, ...]:
        values = capabilities.get(key)
        if not isinstance(values, (list, tuple)):
            raise OpenCodeProtocolError(
                f"OpenCode model {ref} has invalid {key} capabilities"
            )
        normalized = []
        for modality in values:
            if not isinstance(modality, str) or not modality.strip():
                raise OpenCodeProtocolError(
                    f"OpenCode model {ref} has an invalid {key} modality"
                )
            normalized.append(modality.strip().lower())
        return tuple(dict.fromkeys(normalized))

    input_modalities = normalize_modalities("input")
    output_modalities = normalize_modalities("output")

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
        input_modalities=input_modalities,
        output_modalities=output_modalities,
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
    _response_directory(payload)
    raw_models = payload.get("data")
    if not isinstance(raw_models, (list, tuple)):
        raise OpenCodeProtocolError("OpenCode model response has no data array")

    models = []
    parsed_count = 0
    for index, raw_model in enumerate(raw_models):
        try:
            model = _parse_model(raw_model)
        except (OpenCodeError, ValueError) as exc:
            logger.warning(
                "skip malformed OpenCode model entry: "
                f"index={index}, error_type={type(exc).__name__}"
            )
            continue
        parsed_count += 1
        if model.enabled and model.supports_text:
            models.append(model)

    if raw_models and parsed_count == 0:
        raise OpenCodeProtocolError(
            "OpenCode returned no valid model entries; the CLI or server may "
            "be incompatible"
        )

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
    location = _normalized_directory(cwd)
    cli_info = inspect_opencode_cli(
        cli_path,
        timeout=timeout_seconds,
        cwd=location,
    )
    inspect_opencode_server(
        cli_info,
        timeout=timeout_seconds,
        cwd=location,
    )
    completed = _run_opencode_command(
        cli_info.executable,
        [
            "api",
            "model.list",
            "--param",
            f"location[directory]={location}",
        ],
        timeout=timeout_seconds,
        cwd=location,
    )
    _raise_for_command_failure(completed)
    payload = _decode_json_object(completed, context="model discovery")
    if _response_directory(payload) != location:
        raise OpenCodeProtocolError(
            "OpenCode returned models for a different location than requested"
        )
    models = parse_model_catalog(payload)
    if not models:
        raise OpenCodeNoModelsError(
            "OpenCode returned no enabled text-input/text-output models for "
            "the requested location; check the OpenCode provider configuration "
            "and try Refresh"
        )
    return models


def generate_opencode_text(
    prompt: str,
    model: OpenCodeModelRef | str,
    *,
    cli_path: str | None = None,
    timeout: float | int | None = OPENCODE_DEFAULT_TIMEOUT_SECONDS,
    cwd: str | os.PathLike[str] | None = None,
) -> str:
    """Generate text through OpenCode's stateless one-shot API route."""

    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("OpenCode prompt cannot be empty")
    if isinstance(model, OpenCodeModelRef):
        model_ref = model
    elif isinstance(model, str):
        model_ref = OpenCodeModelRef.from_string(model)
    else:
        raise ValueError("OpenCode model must be a model reference string")

    timeout_seconds = _coerce_timeout(timeout)
    location = _normalized_directory(cwd)
    cli_info = inspect_opencode_cli(
        cli_path,
        timeout=timeout_seconds,
        cwd=location,
    )
    inspect_opencode_server(
        cli_info,
        timeout=timeout_seconds,
        cwd=location,
    )
    request_body = json.dumps(
        {"prompt": prompt, "model": model_ref.to_api_dict()},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    completed = _run_opencode_command(
        cli_info.executable,
        [
            "api",
            "post",
            "/api/experimental/generate",
            "--data",
            request_body,
        ],
        timeout=timeout_seconds,
        cwd=location,
    )
    _raise_for_command_failure(completed)
    response = _decode_json_object(completed, context="text generation")
    data = response.get("data")
    if not isinstance(data, Mapping):
        raise OpenCodeProtocolError("OpenCode generation response has no data object")
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        raise OpenCodeProtocolError("OpenCode generation response has no text")
    return text


__all__ = [
    "OPENCODE_DEFAULT_TIMEOUT_SECONDS",
    "OPENCODE_MIN_VERSION",
    "OpenCodeCliInfo",
    "OpenCodeCommandError",
    "OpenCodeError",
    "OpenCodeModel",
    "OpenCodeModelRef",
    "OpenCodeNoModelsError",
    "OpenCodeNotFoundError",
    "OpenCodeProtocolError",
    "OpenCodeTimeoutError",
    "OpenCodeVersionError",
    "coerce_opencode_timeout",
    "discover_opencode_models",
    "ensure_supported_version",
    "generate_opencode_text",
    "inspect_opencode_cli",
    "inspect_opencode_server",
    "parse_model_catalog",
    "parse_opencode_version",
    "resolve_opencode_executable",
]
