import json
import subprocess
from unittest.mock import patch

import pytest
from packaging.version import Version

from app.services import opencode


def _completed(command, *, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        args=command,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _model_payload(
    *,
    model_id="vendor/model",
    upstream_model_id=None,
    provider_id="openrouter",
    enabled=True,
    inputs=("text",),
    outputs=("text",),
    variants=(),
):
    return {
        "id": model_id,
        "modelID": upstream_model_id or model_id,
        "providerID": provider_id,
        "name": "Test Model",
        "capabilities": {"input": list(inputs), "output": list(outputs)},
        "variants": [{"id": variant} for variant in variants],
        "status": "active",
        "enabled": enabled,
        "limit": {"context": 32000, "output": 4096},
    }


def _server_info(version="2.0.16"):
    return json.dumps({"version": version, "pid": 123, "urls": ["http://localhost"]})


def test_parse_opencode_version_accepts_cli_output_and_rejects_invalid_values():
    assert opencode.parse_opencode_version("opencode v2.0.16") == Version("2.0.16")
    assert opencode.parse_opencode_version("2.0.4\n") == Version("2.0.4")

    with pytest.raises(opencode.OpenCodeVersionError):
        opencode.parse_opencode_version("opencode")
    with pytest.raises(opencode.OpenCodeVersionError):
        opencode.parse_opencode_version("opencode v2.0.16.1")
    with pytest.raises(opencode.OpenCodeVersionError):
        opencode.ensure_supported_version("1.18.0")
    assert opencode.ensure_supported_version(Version("2.0.4")) == Version("2.0.4")


def test_model_ref_preserves_catalog_id_upstream_id_and_variants():
    ref = opencode.OpenCodeModelRef.from_string("openrouter/vendor/model#high")

    assert ref.provider_id == "openrouter"
    assert ref.model_id == "vendor/model"
    assert ref.variant == "high"
    assert str(ref) == "openrouter/vendor/model#high"
    assert ref.to_api_dict() == {
        "id": "vendor/model",
        "providerID": "openrouter",
        "variant": "high",
    }

    with pytest.raises(ValueError):
        opencode.OpenCodeModelRef.from_string("model-without-provider")
    with pytest.raises(ValueError):
        opencode.OpenCodeModelRef.from_string("openrouter/vendor/model#")
    with pytest.raises(ValueError):
        opencode.OpenCodeModelRef("bad/provider", "model")


def test_resolve_opencode_executable_supports_path_and_reports_missing_cli(tmp_path):
    executable = tmp_path / "opencode"
    executable.write_text("placeholder", encoding="utf-8")

    with patch.object(opencode.shutil, "which", return_value=None):
        assert opencode.resolve_opencode_executable(str(executable)) == str(
            executable.resolve()
        )

    with patch.object(opencode.shutil, "which", return_value="C:/tools/opencode"):
        assert opencode.resolve_opencode_executable() == "C:/tools/opencode"

    with patch.object(opencode.shutil, "which", return_value=None):
        with pytest.raises(opencode.OpenCodeNotFoundError):
            opencode.resolve_opencode_executable()

    if opencode.os.name == "nt":
        powershell_shim = tmp_path / "opencode.ps1"
        powershell_shim.write_text("placeholder", encoding="utf-8")
        with patch.object(opencode.shutil, "which", return_value=None):
            with pytest.raises(opencode.OpenCodeNotFoundError, match="PowerShell"):
                opencode.resolve_opencode_executable(str(powershell_shim))


def test_parse_model_catalog_keeps_only_enabled_text_prompt_models():
    good = _model_payload(
        upstream_model_id="upstream/model",
        variants=("low", "high"),
    )
    disabled = _model_payload(model_id="disabled", enabled=False)
    image_only = _model_payload(model_id="image", outputs=("image",))
    audio_only = _model_payload(model_id="audio", inputs=("audio",))
    malformed = {"id": "missing-provider"}

    models = opencode.parse_model_catalog(
        {
            "location": {"directory": "/tmp"},
            "data": [good, disabled, image_only, audio_only, malformed],
        }
    )

    assert len(models) == 1
    model = models[0]
    assert model.ref.to_string() == "openrouter/vendor/model"
    assert model.upstream_model_id == "upstream/model"
    assert model.name == "Test Model"
    assert model.input_modalities == ("text",)
    assert model.output_modalities == ("text",)
    assert model.variants == ("low", "high")
    assert model.supports_text is True

    with pytest.raises(opencode.OpenCodeProtocolError):
        opencode.parse_model_catalog({"data": "not-an-array"})
    with pytest.raises(opencode.OpenCodeProtocolError):
        opencode.parse_model_catalog({"data": []})
    with pytest.raises(opencode.OpenCodeProtocolError, match="no valid model"):
        opencode.parse_model_catalog(
            {"location": {"directory": "/tmp"}, "data": [malformed]}
        )
    assert (
        opencode.parse_model_catalog({"location": {"directory": "/tmp"}, "data": []})
        == ()
    )


def test_discover_opencode_models_uses_explicit_location_and_validates_server(tmp_path):
    location = opencode._normalized_directory(tmp_path)
    payload = {
        "location": {"directory": str(tmp_path)},
        "data": [_model_payload(variants=("fast",))],
    }
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1:] == ["--version"]:
            return _completed(command, stdout="opencode v2.0.16")
        if command[1:] == ["api", "get", "/api/info"]:
            return _completed(command, stdout=_server_info())
        if command[1:] == [
            "api",
            "model.list",
            "--param",
            f"location[directory]={location}",
        ]:
            return _completed(command, stdout=json.dumps(payload))
        raise AssertionError(f"unexpected command: {command}")

    with (
        patch.object(opencode.shutil, "which", return_value="opencode"),
        patch.object(opencode.subprocess, "run", side_effect=fake_run),
    ):
        models = opencode.discover_opencode_models(timeout=5, cwd=tmp_path)

    assert [model.ref.to_string() for model in models] == ["openrouter/vendor/model"]
    assert [command[1:] for command, _ in calls] == [
        ["--version"],
        ["api", "get", "/api/info"],
        ["api", "model.list", "--param", f"location[directory]={location}"],
    ]
    assert calls[0][1]["timeout"] == 5
    assert calls[0][1]["stdin"] is subprocess.DEVNULL
    assert calls[0][1]["cwd"] == location
    assert "shell" not in calls[0][1]


def test_discover_opencode_models_reports_cli_server_and_protocol_failures():
    def old_cli(command, **kwargs):
        return _completed(command, stdout="opencode v2.0.3")

    with (
        patch.object(opencode.shutil, "which", return_value="opencode"),
        patch.object(opencode.subprocess, "run", side_effect=old_cli),
    ):
        with pytest.raises(opencode.OpenCodeVersionError, match="2.0.4"):
            opencode.discover_opencode_models()

    def old_server(command, **kwargs):
        if command[1:] == ["--version"]:
            return _completed(command, stdout="opencode v2.0.16")
        if command[1:] == ["api", "get", "/api/info"]:
            return _completed(command, stdout=_server_info("2.0.3"))
        raise AssertionError(f"unexpected command: {command}")

    with (
        patch.object(opencode.shutil, "which", return_value="opencode"),
        patch.object(opencode.subprocess, "run", side_effect=old_server),
    ):
        with pytest.raises(opencode.OpenCodeVersionError, match="2.0.4"):
            opencode.discover_opencode_models()

    def invalid_json(command, **kwargs):
        if command[1:] == ["--version"]:
            return _completed(command, stdout="opencode v2.0.16")
        if command[1:] == ["api", "get", "/api/info"]:
            return _completed(command, stdout=_server_info())
        return _completed(command, stdout="not-json")

    with (
        patch.object(opencode.shutil, "which", return_value="opencode"),
        patch.object(opencode.subprocess, "run", side_effect=invalid_json),
    ):
        with pytest.raises(opencode.OpenCodeProtocolError, match="invalid JSON"):
            opencode.discover_opencode_models()


def test_discover_opencode_models_rejects_wrong_location_and_empty_catalog(tmp_path):
    def run_with_model_payload(payload):
        def fake_run(command, **kwargs):
            if command[1:] == ["--version"]:
                return _completed(command, stdout="opencode v2.0.16")
            if command[1:] == ["api", "get", "/api/info"]:
                return _completed(command, stdout=_server_info())
            return _completed(command, stdout=json.dumps(payload))

        with (
            patch.object(opencode.shutil, "which", return_value="opencode"),
            patch.object(opencode.subprocess, "run", side_effect=fake_run),
        ):
            return opencode.discover_opencode_models(cwd=tmp_path)

    with pytest.raises(opencode.OpenCodeProtocolError, match="different location"):
        run_with_model_payload(
            {
                "location": {"directory": str(tmp_path.parent)},
                "data": [_model_payload()],
            }
        )

    with pytest.raises(opencode.OpenCodeNoModelsError, match="no enabled"):
        run_with_model_payload({"location": {"directory": str(tmp_path)}, "data": []})


def test_discover_opencode_models_reports_command_timeout():
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    with (
        patch.object(opencode.shutil, "which", return_value="opencode"),
        patch.object(opencode.subprocess, "run", side_effect=timeout),
    ):
        with pytest.raises(opencode.OpenCodeTimeoutError, match="timed out"):
            opencode.discover_opencode_models(timeout=0.1)


def test_generate_opencode_text_uses_stateless_route_and_model_reference(tmp_path):
    location = opencode._normalized_directory(tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1:] == ["--version"]:
            return _completed(command, stdout="opencode v2.0.16")
        if command[1:] == ["api", "get", "/api/info"]:
            return _completed(command, stdout=_server_info())
        if command[1:5] == ["api", "post", "/api/experimental/generate", "--data"]:
            request = json.loads(command[5])
            assert request == {
                "prompt": "Write a short line.",
                "model": {
                    "id": "vendor/model",
                    "providerID": "openrouter",
                    "variant": "high",
                },
            }
            return _completed(command, stdout=json.dumps({"data": {"text": "Done"}}))
        raise AssertionError(f"unexpected command: {command}")

    with (
        patch.object(opencode.shutil, "which", return_value="opencode"),
        patch.object(opencode.subprocess, "run", side_effect=fake_run),
    ):
        result = opencode.generate_opencode_text(
            "Write a short line.",
            "openrouter/vendor/model#high",
            timeout=5,
            cwd=tmp_path,
        )

    assert result == "Done"
    assert calls[-1][0][1:5] == [
        "api",
        "post",
        "/api/experimental/generate",
        "--data",
    ]
    assert calls[-1][1]["cwd"] == location
    assert "shell" not in calls[-1][1]


def test_run_opencode_command_adds_windows_creation_flag():
    completed = _completed(["opencode", "--version"], stdout="opencode v2.0.16")
    with (
        patch.object(opencode.os, "name", "nt"),
        patch.object(opencode.subprocess, "run", return_value=completed) as run,
    ):
        opencode._run_opencode_command(
            "opencode",
            ["--version"],
            timeout=5,
        )

    kwargs = run.call_args.kwargs
    if getattr(subprocess, "CREATE_NO_WINDOW", 0):
        assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert "shell" not in kwargs


def test_cli_error_sanitizer_redacts_common_secret_forms():
    sanitized = opencode._sanitize_cli_output(
        '{"apiKey":"secret"} API key: other Authorization: Bearer token '
        "https://example.test/?api_key=query-secret"
    )

    assert "secret" not in sanitized
    assert "other" not in sanitized
    assert "token" not in sanitized
    assert "query-secret" not in sanitized
    assert "apiKey" in sanitized
    assert "Authorization" in sanitized


def test_coerce_opencode_timeout_handles_blank_and_invalid_values():
    assert (
        opencode.coerce_opencode_timeout("")
        == opencode.OPENCODE_DEFAULT_TIMEOUT_SECONDS
    )
    assert opencode.coerce_opencode_timeout("12.5") == 12.5
    with pytest.raises(ValueError, match="opencode_timeout"):
        opencode.coerce_opencode_timeout("nan", config_key="opencode_timeout")
