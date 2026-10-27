import json
from pathlib import Path
from string import Formatter
import time
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import codex_models, codex_oauth, llm

ROOT = Path(__file__).resolve().parents[2]
LOCALES = sorted(path.stem for path in (ROOT / "webui/i18n").glob("*.json"))


def translations(locale):
    return json.loads((ROOT / f"webui/i18n/{locale}.json").read_text(encoding="utf-8"))[
        "Translation"
    ]


@pytest.mark.parametrize("locale", LOCALES)
def test_all_codex_messages_are_translated_with_matching_placeholders(locale):
    english = translations("en")
    localized = translations(locale)
    keys = {key for key in english if key.startswith("codex.")}
    assert {"codex.oauth." + key for key in codex_oauth.ERROR_MESSAGES} <= keys
    for key in keys:
        assert localized[key].strip(), (locale, key)
        expected = {
            field for _, field, _, _ in Formatter().parse(english[key]) if field
        }
        actual = {
            field for _, field, _, _ in Formatter().parse(localized[key]) if field
        }
        assert expected == actual, (locale, key)
        if locale != "en":
            assert localized[key] != english[key], (locale, key)


@pytest.mark.parametrize("locale", LOCALES)
def test_browser_login_and_expiration_render_in_selected_language(locale):
    localized = translations(locale)
    catalog = codex_models.Catalog(
        (codex_models.Model("gpt-7-test", "Test model"),), time.time()
    )
    flow = {
        "id": "synthetic-flow",
        "authorize_url": "https://auth.openai.com/api/accounts/authorize?state=test",
    }
    details = {
        "connected": False,
        "authorized": False,
        "legacy": False,
        "profiles": [],
        "active": "",
        "email": "",
        "revision": 0,
    }
    script = f"""
import json
from pathlib import Path
from webui.codex_login import render_codex_login
from webui.codex_models import render_codex_model_selector
tr = json.loads(Path({str(ROOT / f"webui/i18n/{locale}.json")!r}).read_text(encoding='utf-8'))['Translation'].__getitem__
render_codex_model_selector('gpt-7-test', tr)
render_codex_login(tr)
"""
    with (
        patch.object(codex_models, "get_catalog", return_value=catalog),
        patch.object(codex_oauth, "account_status", return_value=False),
        patch.object(codex_oauth, "account_details", return_value=details),
        patch.object(codex_oauth, "begin_login", return_value=flow),
        patch.object(codex_oauth, "poll_login", return_value=False) as poll,
    ):
        app = AppTest.from_string(script, default_timeout=30).run()
        assert not app.exception
        assert app.button(key="codex_login").label == localized["codex.oauth.login"]
        app.button(key="codex_login").click().run()
        assert not app.exception
        assert localized["codex.oauth.pending"] in [item.value for item in app.caption]
        poll.side_effect = codex_oauth.CodexError("expired")
        app.run()
        assert not app.exception
        assert localized["codex.oauth.expired"] in [item.value for item in app.error]


def test_connection_error_is_localized_without_changing_provider_diagnostics():
    settings = dict(
        config.app, llm_provider="openai_codex", openai_codex_model_name="gpt-7-test"
    )
    catalog = codex_models.Catalog(
        (codex_models.Model("gpt-7-test", "Test"),), time.time()
    )
    error = str(codex_oauth.CodexError("codex.oauth.http_error", status=400))
    with (
        patch.object(config, "app", settings),
        patch.object(config, "ui", dict(config.ui, language="fr")),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(codex_oauth, "account_status", return_value=True),
        patch.object(
            codex_oauth,
            "account_details",
            return_value={
                "connected": True,
                "authorized": True,
                "legacy": False,
                "profiles": [("client", "Test")],
                "active": "client",
                "email": "test@example.invalid",
                "revision": 1,
            },
        ),
        patch.object(codex_models, "get_catalog", return_value=catalog),
        patch.object(llm, "test_connection", return_value=(False, error, 0.1)),
    ):
        app = AppTest.from_file(str(ROOT / "webui/Main.py"), default_timeout=60)
        app.session_state["settings_dialog_open"] = True
        app.run()
        app.button(key="test_llm_connection_button").click().run()
        assert not app.exception
        expected = translations("fr")["codex.oauth.http_error"].format(status=400)
        assert any(expected in item.value for item in app.error)
