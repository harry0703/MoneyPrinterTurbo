import json
import time
from unittest.mock import MagicMock, patch

import pytest
import requests
from streamlit.testing.v1 import AppTest

from app.config import config
from app.models.llm_provider import get_llm_provider
from app.services import codex_models as models
from app.services import llm


@pytest.fixture(autouse=True)
def isolated_catalog(tmp_path):
    with (
        patch.object(models, "_cache_path", return_value=tmp_path / "catalog.json"),
        patch.object(models, "_cached", None),
        patch.object(models, "_retry_after", 0),
    ):
        yield


def payload(*ids):
    return {
        "openai": {
            "models": {
                model_id: {
                    "id": model_id,
                    "name": model_id,
                    "modalities": {"output": ["text"]},
                }
                for model_id in ids
            }
        }
    }


def test_discovery_includes_future_models_and_excludes_incompatible_entries():
    data = payload(
        "gpt-5.4",
        "gpt-7-new",
        "gpt-4o",
        "gpt-5.5-pro",
        "gpt-5.6",
        "gpt-7-pro",
        "gpt-7-image",
    )
    data["openai"]["models"]["gpt-7-pro"]["options"] = {"reasoningMode": "pro"}
    data["openai"]["models"]["gpt-7-image"]["modalities"] = {"output": ["image"]}
    assert {m.id for m in models.parse_catalog(data)} == {"gpt-5.4", "gpt-7-new"}
    assert get_llm_provider("openai_codex").default_model == ""


def test_malformed_model_metadata_does_not_break_other_models():
    data = payload("gpt-7-valid", "gpt-7-invalid")
    data["openai"]["models"]["gpt-7-invalid"]["modalities"]["output"] = None
    assert [model.id for model in models.parse_catalog(data)] == ["gpt-7-valid"]


def test_fetch_is_public_bounded_and_cached_across_restart():
    response = MagicMock(status_code=200)
    response.__enter__.return_value = response
    response.iter_content.return_value = iter(
        [json.dumps(payload("gpt-7-new")).encode()]
    )
    with patch.object(models.requests, "get", return_value=response) as get:
        first = models.get_catalog()
        assert models.get_catalog() == first
        # Simulate a new application process loading the on-disk cache.
        models._cached = None
        assert models.get_catalog() == first
    assert get.call_count == 1
    assert "Authorization" not in get.call_args.kwargs["headers"]
    assert get.call_args.kwargs["allow_redirects"] is False


def test_refresh_bypasses_cache_and_replaces_list():
    with patch.object(
        models,
        "_download",
        side_effect=[
            models.parse_catalog(payload("gpt-7-old")),
            models.parse_catalog(payload("gpt-7-new")),
        ],
    ) as download:
        assert models.get_catalog().models[0].id == "gpt-7-old"
        assert models.get_catalog(force_refresh=True).models[0].id == "gpt-7-new"
    assert download.call_count == 2


def test_expired_cache_survives_outage_and_throttles_retries():
    old = models.Catalog(
        models.parse_catalog(payload("gpt-7-old")), time.time() - models.CACHE_TTL - 10
    )
    models._write_cache(old)
    with patch.object(
        models, "_download", side_effect=models.CatalogError("codex.models.failed")
    ) as download:
        result = models.get_catalog()
        assert result.stale and result.models == old.models
        assert models.get_catalog().stale
        assert download.call_count == 1
        assert models.get_catalog(force_refresh=True).stale
        assert download.call_count == 2


def test_invalid_response_does_not_poison_last_valid_catalog():
    good = models.Catalog(models.parse_catalog(payload("gpt-7-good")), time.time())
    models._write_cache(good)
    response = MagicMock(status_code=200)
    response.__enter__.return_value = response
    response.iter_content.return_value = iter([b'{"openai":{"models":{}}}'])
    with patch.object(models.requests, "get", return_value=response):
        result = models.get_catalog(force_refresh=True)
    assert result.stale and result.models == good.models
    assert models._read_cache() == good


def test_network_failure_without_cache_is_actionable_and_does_not_retry_on_rerun():
    with patch.object(
        models.requests, "get", side_effect=requests.ConnectionError("internal detail")
    ) as get:
        for _ in range(2):
            with pytest.raises(models.CatalogError, match="codex.models.failed"):
                models.get_catalog()
    assert get.call_count == 1


def test_llm_without_selected_model_does_not_silently_choose_one():
    with patch("app.services.codex_oauth.generate_text") as generate:
        result = llm._generate_response(
            "test", app_config={"llm_provider": "openai_codex"}
        )
    assert result.startswith("Error:")
    assert "model_name" in result
    generate.assert_not_called()


def test_real_settings_select_and_refresh_preserve_saved_model():
    settings = dict(
        config.app,
        llm_provider="openai_codex",
        openai_codex_model_name="gpt-7-original",
    )
    original = models.Catalog(
        models.parse_catalog(payload("gpt-7-original", "gpt-7-choice")), time.time()
    )
    updated = models.Catalog(models.parse_catalog(payload("gpt-7-future")), time.time())
    with (
        patch.object(config, "app", settings),
        patch.object(config, "ui", dict(config.ui, language="es")),
        patch.object(config, "try_save_config", return_value=True),
        patch("app.services.codex_oauth.account_status", return_value=True),
        patch.object(models, "get_catalog", return_value=original) as catalog,
    ):
        app = AppTest.from_file("webui/Main.py", default_timeout=60)
        app.session_state["settings_dialog_open"] = True
        app.run()
        assert not app.exception
        assert (
            app.selectbox(key="openai_codex_model_name_select").value
            == "gpt-7-original"
        )
        app.selectbox(key="openai_codex_model_name_select").select("gpt-7-choice").run()
        assert settings["openai_codex_model_name"] == "gpt-7-choice"
        catalog.return_value = updated
        app.button(key="codex_models_refresh").click().run()
        assert not app.exception
        catalog.assert_any_call(force_refresh=True)
        assert (
            app.selectbox(key="openai_codex_model_name_select").value == "gpt-7-choice"
        )
        assert settings["openai_codex_model_name"] == "gpt-7-choice"
        assert any("conserva" in item.value for item in app.caption)


def test_ui_outage_preserves_manual_model_then_recovers():
    settings = dict(
        config.app, llm_provider="openai_codex", openai_codex_model_name="gpt-7-manual"
    )
    with (
        patch.object(config, "app", settings),
        patch.object(config, "ui", dict(config.ui, language="es")),
        patch.object(config, "try_save_config", return_value=True),
        patch("app.services.codex_oauth.account_status", return_value=True),
        patch.object(
            models,
            "get_catalog",
            side_effect=models.CatalogError("codex.models.failed"),
        ) as catalog,
    ):
        app = AppTest.from_file("webui/Main.py", default_timeout=60)
        app.session_state["settings_dialog_open"] = True
        app.run()
        assert not app.exception
        assert (
            app.text_input(key="openai_codex_model_name_input").value == "gpt-7-manual"
        )
        assert settings["openai_codex_model_name"] == "gpt-7-manual"
        catalog.side_effect = None
        catalog.return_value = models.Catalog(
            models.parse_catalog(payload("gpt-7-manual")), time.time()
        )
        app.button(key="codex_models_refresh").click().run()
        assert not app.exception
        assert (
            app.selectbox(key="openai_codex_model_name_select").value == "gpt-7-manual"
        )
