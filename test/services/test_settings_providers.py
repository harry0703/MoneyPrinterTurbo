"""General lists only locally configured providers; no network probes are needed."""

import pytest

from app.models.llm_provider import LLM_PROVIDER_REGISTRY
from webui import settings_providers

GROUPS = {
    "ai_video": (
        "metaso_minimax",
        "ofox",
        "loomloom",
        "volcengine_seedance",
        "infistar",
        "jalapeno",
        "wavespeed",
        "muapi",
    ),
    "ai_image": ("openai_image", "codex_image"),
    "stock_video": ("pexels", "pixabay", "coverr"),
}
OAUTH = {"openai_codex": False, "openai_chatgpt": False, "kimi_code": False}


@pytest.mark.parametrize("invalid", [1, True, {"key": "invalid"}, [1, None, False]])
def test_malformed_key_lists_do_not_break_general(invalid):
    providers = ("pexels", "pixabay", "coverr", "wavespeed")
    settings = {f"{provider}_api_keys": invalid for provider in providers}
    configured = settings_providers.configured_material_providers(settings, GROUPS)
    assert not set(providers) & {
        provider for options in configured.values() for provider in options
    }


@pytest.fixture(autouse=True)
def isolated_readiness(monkeypatch):
    monkeypatch.setattr(settings_providers.shutil, "which", lambda _: None)
    monkeypatch.delenv("INFISTAR_VIDEO_API_KEY", raising=False)
    monkeypatch.delenv("JALAPENO_VIDEO_API_KEY", raising=False)

    def unexpected_network(*args, **kwargs):
        pytest.fail("Local configuration checks must not contact remote services")

    monkeypatch.setattr("requests.sessions.Session.request", unexpected_network)


@pytest.mark.parametrize("provider", LLM_PROVIDER_REGISTRY, ids=lambda p: p.provider_id)
def test_registry_defaults_alone_do_not_count_as_configured(provider):
    defaults = {
        provider.config_key("model_name"): provider.default_model,
        provider.config_key("base_url"): provider.effective_default_base_url,
    }
    for field in provider.extra_fields:
        defaults[provider.config_key(field.config_suffix)] = field.default_value
    assert provider.provider_id not in settings_providers.configured_llm_providers(
        defaults, OAUTH
    )


@pytest.mark.parametrize("provider", LLM_PROVIDER_REGISTRY, ids=lambda p: p.provider_id)
def test_each_registered_llm_can_be_locally_configured(provider, monkeypatch):
    values = {
        provider.config_key("api_key"): "synthetic-key",
        provider.config_key("model_name"): "explicit-model",
        provider.config_key("base_url"): "https://configured.example/v1",
    }
    for field in provider.extra_fields:
        if field.required:
            values[provider.config_key(field.config_suffix)] = "required-value"
    if provider.provider_id == "claude_code":
        values["claude_code_cli_path"] = "C:/synthetic/claude.cmd"
        monkeypatch.setattr(
            settings_providers.shutil, "which", lambda _: "synthetic-claude"
        )
    oauth = {**OAUTH, provider.provider_id: True}
    assert provider.provider_id in settings_providers.configured_llm_providers(
        values, oauth
    )


def test_claude_default_cli_on_path_is_configured(monkeypatch):
    monkeypatch.setattr(
        settings_providers.shutil,
        "which",
        lambda command: "synthetic-claude" if command == "claude" else None,
    )
    assert "claude_code" in settings_providers.configured_llm_providers({}, OAUTH)


def test_claude_custom_cli_file_is_configured(tmp_path):
    executable = tmp_path / "custom-claude"
    executable.write_text("synthetic executable", encoding="utf-8")
    assert "claude_code" in settings_providers.configured_llm_providers(
        {"claude_code_cli_path": str(executable)}, OAUTH
    )


def test_claude_missing_explicit_cli_is_not_configured(tmp_path):
    assert "claude_code" not in settings_providers.configured_llm_providers(
        {"claude_code_cli_path": str(tmp_path / "missing-claude")}, OAUTH
    )


@pytest.mark.parametrize("provider_id", OAUTH)
def test_subscription_readiness_requires_cached_local_authorization(provider_id):
    values = {f"{provider_id}_model_name": "chosen-model"}
    assert provider_id not in settings_providers.configured_llm_providers(values, OAUTH)
    assert provider_id in settings_providers.configured_llm_providers(
        values, {**OAUTH, provider_id: True}
    )


@pytest.mark.parametrize(
    "provider_id,values,expected",
    [
        ("ollama", {"ollama_model_name": "local-model"}, True),
        ("ollama", {"ollama_base_url": "http://localhost:11434/v1"}, False),
        ("litellm", {"litellm_model_name": "custom-model"}, True),
        ("litellm", {"litellm_base_url": "http://localhost:4000/v1"}, True),
    ],
)
def test_keyless_requires_explicit_evidence_and_effective_required_fields(
    provider_id, values, expected
):
    assert (
        provider_id in settings_providers.configured_llm_providers(values, OAUTH)
    ) is expected


MATERIAL_VALUES = {
    "pexels": {"pexels_api_keys": ["synthetic-key"]},
    "pixabay": {"pixabay_api_keys": ["synthetic-key"]},
    "coverr": {"coverr_api_keys": ["synthetic-key"]},
    "metaso_minimax": {"metaso_minimax_api_key": "synthetic-key"},
    "ofox": {"ofox_api_key": "synthetic-key"},
    "loomloom": {"loomloom_api_token": "synthetic-key"},
    "volcengine_seedance": {"volcengine_seedance_api_key": "synthetic-key"},
    "infistar": {"infistar_video_api_key": "synthetic-key"},
    "jalapeno": {"jalapeno_video_api_key": "synthetic-key"},
    "wavespeed": {"wavespeed_api_keys": ["synthetic-key"]},
    "muapi": {"muapi_api_key": "synthetic-key"},
    "openai_image": {
        "openai_image_api_keys": ["synthetic-key"],
        "openai_image_base_url": "https://images.example/v1",
        "openai_image_model": "chosen-image-model",
    },
    "codex_image": {"codex_image_model_name": "image-model"},
}


@pytest.mark.parametrize("provider_id", MATERIAL_VALUES)
def test_every_material_provider_requires_local_configuration(provider_id):
    group = next(
        group for group, providers in GROUPS.items() if provider_id in providers
    )
    assert (
        provider_id
        not in settings_providers.configured_material_providers({}, GROUPS)[group]
    )
    result = settings_providers.configured_material_providers(
        MATERIAL_VALUES[provider_id],
        GROUPS,
        codex_connected=provider_id == "codex_image",
    )
    assert provider_id in result[group]
    assert sum(len(providers) for providers in result.values()) == 1


@pytest.mark.parametrize("provider_id", ["jalapeno"])
def test_video_readiness_accepts_existing_shared_llm_credentials(provider_id):
    result = settings_providers.configured_material_providers(
        {f"{provider_id}_api_key": "shared-synthetic-key"}, GROUPS
    )
    assert provider_id in result["ai_video"]


def test_shengsuan_readiness_uses_existing_credential_source():
    shared = {
        "llm_provider": "shengsuanyun",
        "shengsuanyun_api_key": "shared-synthetic-key",
    }
    assert (
        "loomloom"
        in settings_providers.configured_material_providers(shared, GROUPS)["ai_video"]
    )
    shared["shengsuanyun_api_key"] = " "
    assert (
        "loomloom"
        not in settings_providers.configured_material_providers(shared, GROUPS)[
            "ai_video"
        ]
    )


def test_configured_provider_lists_keep_registry_and_group_order(monkeypatch):
    monkeypatch.setattr(
        settings_providers.shutil, "which", lambda _: "synthetic-claude"
    )
    values = {
        key: value
        for settings in MATERIAL_VALUES.values()
        for key, value in settings.items()
    }
    assert (
        settings_providers.configured_material_providers(
            values, GROUPS, codex_connected=True
        )
        == GROUPS
    )
    llm_values = {
        key: value
        for provider in LLM_PROVIDER_REGISTRY
        for key, value in (
            (provider.config_key("api_key"), "synthetic-key"),
            (provider.config_key("base_url"), "https://configured.example/v1"),
            (provider.config_key("model_name"), "configured-model"),
        )
    }
    llm_values["claude_code_cli_path"] = "synthetic-claude"
    for provider in LLM_PROVIDER_REGISTRY:
        for field in provider.extra_fields:
            if field.required:
                llm_values[provider.config_key(field.config_suffix)] = "required-value"
    assert settings_providers.configured_llm_providers(
        llm_values, {key: True for key in OAUTH}
    ) == tuple(provider.provider_id for provider in LLM_PROVIDER_REGISTRY)


@pytest.mark.parametrize("missing", ["openai_image_base_url", "openai_image_model"])
def test_keyless_image_gateway_needs_explicit_endpoint_and_model(missing):
    values = {
        "openai_image_base_url": "http://localhost:8188/v1",
        "openai_image_model": "local-image",
    }
    assert (
        "openai_image"
        in settings_providers.configured_material_providers(values, GROUPS)["ai_image"]
    )
    del values[missing]
    assert (
        "openai_image"
        not in settings_providers.configured_material_providers(values, GROUPS)[
            "ai_image"
        ]
    )


def test_codex_image_needs_saved_model_and_same_local_llm_session():
    assert (
        "codex_image"
        not in settings_providers.configured_material_providers(
            {}, GROUPS, codex_connected=True
        )["ai_image"]
    )
    assert (
        "codex_image"
        not in settings_providers.configured_material_providers(
            {"codex_image_model_name": "image-model"}, GROUPS
        )["ai_image"]
    )
    assert (
        "codex_image"
        in settings_providers.configured_material_providers(
            {"codex_image_model_name": "image-model"}, GROUPS, codex_connected=True
        )["ai_image"]
    )


def test_infistar_video_does_not_accept_separate_llm_key():
    result = settings_providers.configured_material_providers(
        {"infistar_api_key": "llm-only-key"}, GROUPS
    )
    assert "infistar" not in result["ai_video"]
