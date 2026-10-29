import json
from pathlib import Path
import time
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.models.llm_provider import get_llm_provider
from app.services import chatgpt_models as models
from app.services import chatgpt_oauth, llm


@pytest.fixture(autouse=True)
def isolated_catalog(monkeypatch):
    monkeypatch.setattr(models, "_cached", None)
    monkeypatch.setattr(models, "_identity", None)


def payload(*ids):
    return {
        "models": [
            {"slug": model_id, "display_name": model_id, "visibility": "list"}
            for model_id in ids
        ]
    }


def details(client="client-one", revision=1):
    return {
        "active": client,
        "revision": revision,
        "authorized": True,
        "connected": True,
    }


def test_account_catalog_preserves_order_and_ids_without_name_heuristics():
    data = payload("custom-first", "gpt-5.5-pro", "gpt-5.6", "future-model")
    data["models"].append({"slug": "hidden", "visibility": "hide"})
    assert [m.id for m in models.parse_catalog(data)] == [
        "custom-first",
        "gpt-5.5-pro",
        "gpt-5.6",
        "future-model",
    ]
    assert get_llm_provider("openai_chatgpt").default_model == ""


def test_empty_catalog_is_not_replaced_by_public_models():
    assert models.parse_catalog({"models": []}) == ()
    with pytest.raises(models.CatalogError):
        models.parse_catalog({"openai": {"models": {}}})


def test_refresh_and_account_switch_never_reuse_another_accounts_models():
    with (
        patch.object(
            chatgpt_oauth, "account_details", return_value=details()
        ) as account,
        patch.object(
            chatgpt_oauth,
            "get_models",
            side_effect=[payload("one"), payload("one-new"), payload("two")],
        ) as fetch,
    ):
        assert models.get_catalog().models[0].id == "one"
        assert models.get_catalog().models[0].id == "one"
        assert fetch.call_count == 1
        assert models.get_catalog(force_refresh=True).models[0].id == "one-new"
        account.return_value = details("client-two", 2)
        assert models.get_catalog().models[0].id == "two"


def test_signed_in_without_plan_permission_does_not_fetch_models():
    with (
        patch.object(
            chatgpt_oauth,
            "account_details",
            return_value={**details(), "authorized": False},
        ),
        patch.object(chatgpt_oauth, "get_models") as fetch,
        pytest.raises(chatgpt_oauth.ChatGPTError),
    ):
        models.get_catalog()
    fetch.assert_not_called()


def test_llm_without_selected_model_does_not_choose_one():
    with patch.object(chatgpt_oauth, "generate_text") as generate:
        result = llm._generate_response(
            "test", app_config={"llm_provider": "openai_chatgpt"}
        )
    assert result.startswith("Error:") and "model_name" in result
    generate.assert_not_called()


def test_ui_keeps_saved_config_without_presenting_it_as_available():
    translations = Path("webui/i18n/en.json").read_text(encoding="utf-8")
    script = f"""
import json
import streamlit as st
from webui.chatgpt_models import render_chatgpt_model_selector
tr = json.loads({translations!r})['Translation'].__getitem__
st.session_state['result'] = render_chatgpt_model_selector('old-model', tr)
"""
    with (
        patch.object(chatgpt_oauth, "account_status", return_value=True),
        patch.object(
            models,
            "get_catalog",
            return_value=models.Catalog(
                (models.Model("allowed", "Allowed"),), time.time()
            ),
        ),
    ):
        app = AppTest.from_string(script, default_timeout=30).run()
        assert not app.exception
        assert app.session_state["result"] == "old-model"
        picker = app.selectbox(key="openai_chatgpt_model_name_select")
        assert picker.value is None
        assert picker.options == ["Allowed"]
        picker.select("allowed").run()
        assert app.session_state["result"] == "allowed"


def test_login_ui_uses_browser_link_without_device_code():
    tr = json.loads(Path("webui/i18n/en.json").read_text(encoding="utf-8"))[
        "Translation"
    ]
    script = f"""
from webui.chatgpt_login import render_chatgpt_login
render_chatgpt_login({tr!r}.__getitem__)
"""
    status = {
        **details(),
        "authorized": False,
        "connected": False,
        "legacy": False,
        "profiles": [],
        "email": "",
    }
    flow = {
        "id": "test-flow",
        "authorize_url": "https://auth.openai.com/api/accounts/authorize?state=test",
    }
    with (
        patch.object(chatgpt_oauth, "account_details", return_value=status),
        patch.object(chatgpt_oauth, "begin_login", return_value=flow) as begin,
        patch.object(chatgpt_oauth, "poll_login", return_value=False),
        patch.object(chatgpt_oauth, "cancel_login") as cancel,
    ):
        app = AppTest.from_string(script, default_timeout=30).run()
        app.button(key="chatgpt_login").click().run()
        assert not app.exception
        assert begin.called
        assert len(app.code) == 0
        assert any(
            item.proto.url == flow["authorize_url"] for item in app.get("link_button")
        )
        app.button(key="chatgpt_cancel").click().run()
        cancel.assert_called_once_with(flow)


@pytest.mark.parametrize("multiple", [False, True])
def test_connected_account_summary_never_shows_an_empty_account_choice(multiple):
    tr = json.loads(Path("webui/i18n/en.json").read_text(encoding="utf-8"))[
        "Translation"
    ]
    script = f"""
from webui.chatgpt_login import render_chatgpt_login
render_chatgpt_login({tr!r}.__getitem__)
"""
    profiles = [("active", "active@example.invalid")]
    if multiple:
        profiles.insert(0, ("other", "other@example.invalid"))
    status = {
        **details("active"),
        "legacy": False,
        "profiles": profiles,
        "email": "active@example.invalid",
    }
    with patch.object(chatgpt_oauth, "account_details", return_value=status):
        app = AppTest.from_string(script, default_timeout=30)
        app.session_state["chatgpt_account_picker"] = None
        app.run()
        assert not app.exception
        assert any(item.value == "active@example.invalid" for item in app.get("text"))
        if multiple:
            app.button(key="chatgpt_account_actions_toggle").click().run()
            assert app.selectbox(key="chatgpt_account_picker").value == "active"
        else:
            assert not app.selectbox


def test_model_selector_honors_restored_configuration():
    translations = json.loads(Path("webui/i18n/en.json").read_text(encoding="utf-8"))[
        "Translation"
    ]
    script = f"""
import streamlit as st
from webui.chatgpt_models import render_chatgpt_model_selector
st.session_state['saved_model'] = render_chatgpt_model_selector(st.session_state.get('saved_model', 'model-a'), {translations!r}.__getitem__)
"""
    with (
        patch.object(chatgpt_oauth, "account_status", return_value=True),
        patch.object(
            models,
            "get_catalog",
            return_value=models.Catalog(
                (models.Model("model-a", "A"), models.Model("model-b", "B")),
                time.time(),
            ),
        ),
    ):
        app = AppTest.from_string(script, default_timeout=30).run()
        assert app.selectbox(key="openai_chatgpt_model_name_select").value == "model-a"
        app.session_state["saved_model"] = "model-b"  # A restored settings backup.
        app.run()
        assert app.selectbox(key="openai_chatgpt_model_name_select").value == "model-b"
        assert app.session_state["saved_model"] == "model-b"
        app.selectbox(key="openai_chatgpt_model_name_select").select("model-a").run()
        assert app.session_state["saved_model"] == "model-a"


def test_disconnect_action_inside_settings_dialog_clears_connected_state():
    tr = json.loads(Path("webui/i18n/en.json").read_text(encoding="utf-8"))[
        "Translation"
    ]
    script = f"""
import streamlit as st
from webui.chatgpt_login import render_chatgpt_login
@st.dialog('Settings')
def settings():
    render_chatgpt_login({tr!r}.__getitem__)
settings()
"""
    status = {
        **details("active"),
        "legacy": False,
        "profiles": [("active", "Test")],
        "email": "test@example.invalid",
    }

    def disconnect():
        status.update(connected=False, authorized=False)
        return True

    with (
        patch.object(
            chatgpt_oauth, "account_details", side_effect=lambda: dict(status)
        ),
        patch.object(chatgpt_oauth, "disconnect", side_effect=disconnect) as logout,
    ):
        app = AppTest.from_string(script, default_timeout=30).run()
        app.button(key="chatgpt_account_actions_toggle").click().run()
        assert not app.exception
        app.button(key="chatgpt_disconnect").click().run()
        assert not app.exception
        logout.assert_called_once()
        assert app.button(key="chatgpt_login").label == tr["chatgpt.oauth.login"]
