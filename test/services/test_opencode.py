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
    provider_id="openrouter",
    enabled=True,
    outputs=("text",),
    variants=(),
):
    return {
        "id": model_id,
        "modelID": model_id,
        "providerID": provider_id,
        "name": "Test Model",
        "capabilities": {"output": list(outputs)},
        "variants": [{"id": variant} for variant in variants],
        "status": "active",
        "enabled": enabled,
        "limit": {"context": 32000, "output": 4096},
    }


def test_parse_opencode_version_accepts_cli_output_and_rejects_invalid_values():
    assert opencode.parse_opencode_version("opencode v2.0.16") == Version("2.0.16")
    assert opencode.parse_opencode_version("2.0.4\n") == Version("2.0.4")

    with pytest.raises(opencode.OpenCodeVersionError):
        opencode.parse_opencode_version("opencode")
    with pytest.raises(opencode.OpenCodeVersionError):
        opencode.ensure_supported_version("1.18.0")
    assert opencode.ensure_supported_version(Version("2.0.4")) == Version("2.0.4")


def test_model_ref_preserves_nested_model_ids_and_variants():
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
        opencode.OpenCodeModelRef("bad/provider", "model")


def test_resolve_opencode_executable_supports_path_and_reports_missing_cli(tmp_path):
    executable = tmp_path / "opencode"
    executable.write_text("placeholder", encoding="utf-8")

    with patch.object(opencode.shutil, "which", return_value=None):
        assert opencode.resolve_opencode_executable(str(executable)) == str(executable)

    with patch.object(opencode.shutil, "which", return_value="C:/tools/opencode"):
        assert opencode.resolve_opencode_executable() == "C:/tools/opencode"

    with patch.object(opencode.shutil, "which", return_value=None):
        with pytest.raises(opencode.OpenCodeNotFoundError):
            opencode.resolve_opencode_executable()


def test_parse_model_catalog_keeps_only_enabled_text_models_and_skips_bad_entries():
    good = _model_payload(variants=("low", "high"))
    disabled = _model_payload(model_id="disabled", enabled=False)
    image_only = _model_payload(model_id="image", outputs=("image",))
    malformed = {"id": "missing-provider"}

    models = opencode.parse_model_catalog(
        {
            "location": {"directory": "/tmp"},
            "data": [good, disabled, image_only, malformed],
        }
    )

    assert len(models) == 1
    model = models[0]
    assert model.ref.to_string() == "openrouter/vendor/model"
    assert model.upstream_model_id == "vendor/model"
    assert model.name == "Test Model"
    assert model.variants == ("low", "high")
    assert model.supports_text is True

    with pytest.raises(opencode.OpenCodeProtocolError):
        opencode.parse_model_catalog({"data": "not-an-array"})


def test_discover_opencode_models_uses_version_and_structured_api_only(tmp_path):
    payload = {
        "location": {"directory": str(tmp_path)},
        "data": [_model_payload(variants=("fast",))],
    }
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1:] == ["--version"]:
            return _completed(command, stdout="opencode v2.0.16")
        if command[1:] == ["api", "get", "/api/model"]:
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
        ["api", "get", "/api/model"],
    ]
    assert calls[0][1]["timeout"] == 5
    assert calls[0][1]["stdin"] is subprocess.DEVNULL
    assert calls[0][1]["cwd"] == tmp_path
    assert "shell" not in calls[0][1]


def test_discover_opencode_models_reports_version_and_protocol_failures():
    def version_failure(command, **kwargs):
        return _completed(
            command,
            stdout="opencode v2.0.3",
        )

    with (
        patch.object(opencode.shutil, "which", return_value="opencode"),
        patch.object(opencode.subprocess, "run", side_effect=version_failure),
    ):
        with pytest.raises(opencode.OpenCodeVersionError, match="2.0.4"):
            opencode.discover_opencode_models()

    def invalid_json(command, **kwargs):
        if command[1:] == ["--version"]:
            return _completed(command, stdout="opencode v2.0.16")
        return _completed(command, stdout="not-json")

    with (
        patch.object(opencode.shutil, "which", return_value="opencode"),
        patch.object(opencode.subprocess, "run", side_effect=invalid_json),
    ):
        with pytest.raises(opencode.OpenCodeProtocolError, match="invalid JSON"):
            opencode.discover_opencode_models()


def test_discover_opencode_models_reports_command_timeout():
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    with (
        patch.object(opencode.shutil, "which", return_value="opencode"),
        patch.object(opencode.subprocess, "run", side_effect=timeout),
    ):
        with pytest.raises(opencode.OpenCodeTimeoutError, match="timed out"):
            opencode.discover_opencode_models(timeout=0.1)
