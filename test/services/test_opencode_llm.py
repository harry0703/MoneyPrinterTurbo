from unittest.mock import patch

from app.models.llm_provider import get_llm_provider
from app.services import llm
from app.services.opencode import OpenCodeModelRef


def _opencode_config(**overrides):
    config = {
        "llm_provider": "opencode",
        "opencode_model_name": "opencode/gpt-5.5#high",
        "opencode_cli_path": "C:/tools/opencode.cmd",
        "opencode_timeout": "12",
    }
    config.update(overrides)
    return config


def test_opencode_provider_is_keyless_and_uses_cli_adapter():
    provider = get_llm_provider("opencode")

    assert provider is not None
    assert provider.adapter == "opencode_cli"
    assert provider.requires_api_key is False
    assert provider.requires_base_url is False
    assert provider.show_api_key is False
    assert provider.show_base_url is False
    assert provider.requires_model_name is True
    assert {field.config_suffix for field in provider.extra_fields} == {
        "cli_path",
        "timeout",
    }


def test_opencode_adapter_passes_model_cli_and_timeout_to_stateless_helper():
    app_config = _opencode_config()

    with patch.object(
        llm,
        "generate_opencode_text",
        return_value="<think>hidden</think>\nA short script.",
    ) as generate:
        result = llm._generate_response("Write a script.", app_config=app_config)

    assert result == "A short script."
    generate.assert_called_once()
    args, kwargs = generate.call_args
    assert args[0] == "Write a script."
    assert args[1] == OpenCodeModelRef.from_string("opencode/gpt-5.5#high")
    assert kwargs == {"cli_path": "C:/tools/opencode.cmd", "timeout": 12.0}


def test_opencode_adapter_reports_missing_model_and_invalid_timeout():
    missing_model = llm._generate_response(
        "Write a script.",
        app_config=_opencode_config(opencode_model_name=""),
    )
    assert missing_model.startswith("Error: opencode:")
    assert "model_name is not set" in missing_model

    invalid_timeout = llm._generate_response(
        "Write a script.",
        app_config=_opencode_config(opencode_timeout="not-a-number"),
    )
    assert invalid_timeout.startswith("Error: opencode_timeout:")
    assert "OpenCode timeout" in invalid_timeout


def test_opencode_adapter_surfaces_cli_errors():
    with patch.object(
        llm,
        "generate_opencode_text",
        side_effect=Exception("OpenCode request failed"),
    ):
        result = llm._generate_response(
            "Write a script.",
            app_config=_opencode_config(),
        )

    assert result == "Error: OpenCode request failed"
