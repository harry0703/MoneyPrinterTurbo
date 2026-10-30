import json
from pathlib import Path
import time
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.services import codex_models, codex_oauth
from app.config import config


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = f"""
import json
from pathlib import Path
from webui.codex_login import render_codex_login
from webui.codex_models import render_codex_model_selector
tr = json.loads(Path({str(ROOT / "webui/i18n/en.json")!r}).read_text(encoding='utf-8'))['Translation'].__getitem__
render_codex_model_selector('text-model', tr)
render_codex_model_selector('image-model', tr, prefix='codex_image')
render_codex_login(tr)
"""


def catalog():
    return codex_models.Catalog(
        (codex_models.Model("other-model", "Other"),), time.time()
    )


def test_independent_model_selections_share_an_existing_login():
    with (
        patch.object(codex_models, "get_catalog", return_value=catalog()),
        patch.object(codex_oauth, "account_status", return_value=True),
        patch.object(codex_oauth, "request_device_code") as request_code,
    ):
        app = AppTest.from_string(SCRIPT, default_timeout=30).run()
        assert not app.exception
        assert app.selectbox(key="openai_codex_model_name_select").value == "text-model"
        assert app.selectbox(key="codex_image_model_name_select").value == "image-model"
        app.selectbox(key="codex_image_model_name_select").select("other-model").run()
        assert not app.exception
        assert app.selectbox(key="openai_codex_model_name_select").value == "text-model"
        assert app.selectbox(key="codex_image_model_name_select").value == "other-model"
        assert len([b for b in app.button if b.key == "codex_disconnect"]) == 1
        request_code.assert_not_called()


def test_cancel_pending_login_does_not_disconnect_shared_account():
    with (
        patch.object(codex_models, "get_catalog", return_value=catalog()),
        patch.object(codex_oauth, "account_status", return_value=False),
        patch.object(codex_oauth, "disconnect") as disconnect,
        patch.object(codex_oauth, "poll_login") as poll,
    ):
        app = AppTest.from_string(SCRIPT, default_timeout=30)
        app.session_state["openai_codex_login_flow"] = {
            "generation": codex_oauth.authorization_generation(),
            "expires_at": time.time() + 900,
            "next_poll_at": time.time() + 900,
            "interval": 5,
            "user_code": "TEST-CODE",
        }
        app.run()
        app.button(key="codex_disconnect").click().run()
        assert not app.exception
        assert "openai_codex_login_flow" not in app.session_state
        disconnect.assert_not_called()
        poll.assert_not_called()


def test_shared_disconnect_removes_app_session_once():
    with (
        patch.object(codex_models, "get_catalog", return_value=catalog()),
        patch.object(
            codex_oauth, "account_status", return_value=True
        ) as account_status,
        patch.object(codex_oauth, "disconnect") as disconnect,
    ):
        app = AppTest.from_string(SCRIPT, default_timeout=30).run()
        disconnect.side_effect = lambda: setattr(account_status, "return_value", False)
        app.button(key="codex_disconnect").click().run()
        assert not app.exception
        disconnect.assert_called_once()


@pytest.mark.parametrize("provider", ["openai_codex", "openai"])
def test_settings_migrate_missing_image_timeout_and_keep_single_account_control(
    provider,
):
    settings = dict(
        config.app, llm_provider=provider, openai_codex_model_name="text-model"
    )
    settings.pop("codex_image_timeout", None)
    with (
        patch.object(config, "app", settings),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(codex_models, "get_catalog", return_value=catalog()),
        patch.object(codex_oauth, "account_status", return_value=True),
        patch.object(codex_oauth, "request_device_code") as request_code,
    ):
        app = AppTest.from_file(str(ROOT / "webui/Main.py"), default_timeout=60)
        app.session_state["settings_dialog_open"] = True
        app.session_state["settings_dialog_target_tab"] = "image"
        app.session_state["settings_material_providers"] = {"ai_image": "codex_image"}
        app.run()
        assert not app.exception
        assert app.text_input(key="codex_image_timeout_input").value == "300"
        assert settings["codex_image_timeout"] == "300"
        assert len([b for b in app.button if b.key == "codex_disconnect"]) == 1
        request_code.assert_not_called()


@pytest.mark.parametrize(
    "first_tab,second_tab", [("llm", "image"), ("image", "llm")]
)
def test_real_settings_reuse_pending_login_when_switching_tabs(first_tab, second_tab):
    settings = dict(
        config.app, llm_provider="openai_codex", openai_codex_model_name="text-model"
    )
    flow = {
        "device_auth_id": "test-device",
        "generation": codex_oauth.authorization_generation(),
        "expires_at": time.time() + 900,
        "interval": 900,
        "user_code": "SHARED-CODE",
    }
    with (
        patch.object(config, "app", settings),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(codex_models, "get_catalog", return_value=catalog()),
        patch.object(codex_oauth, "account_status", return_value=False),
        patch.object(
            codex_oauth, "request_device_code", return_value=flow
        ) as request_code,
        patch.object(codex_oauth, "poll_login") as poll,
    ):
        app = AppTest.from_file(str(ROOT / "webui/Main.py"), default_timeout=60)
        app.session_state["settings_dialog_open"] = True
        app.session_state["settings_dialog_target_tab"] = first_tab
        app.session_state["settings_material_providers"] = {"ai_image": "codex_image"}
        app.run()
        app.button(key="codex_login").click().run()
        assert not app.exception
        assert any(item.value == "SHARED-CODE" for item in app.code)
        app.session_state["settings_dialog_target_tab"] = second_tab
        app.run()
        assert not app.exception
        assert any(item.value == "SHARED-CODE" for item in app.code)
        assert len([b for b in app.button if b.key == "codex_disconnect"]) == 1
        request_code.assert_called_once()
        poll.assert_not_called()


@pytest.mark.parametrize(
    "error_key,error_params",
    [("codex.oauth.http_error", {"status": 403}), ("codex.image.uncertain", {})],
)
def test_failed_image_snapshot_renders_localized_error_and_parameters(
    error_key, error_params
):
    translations = json.loads(
        (ROOT / "webui/i18n/es.json").read_text(encoding="utf-8")
    )["Translation"]
    script = f"""
import ast
import json
from collections.abc import Mapping
from pathlib import Path
import streamlit as st
from app.models import const
tr = json.loads(Path({str(ROOT / "webui/i18n/es.json")!r}).read_text(encoding='utf-8'))['Translation'].__getitem__
_normalize_task_state = lambda value: value
_render_generation_logs = lambda task_id: None
entry = Path({str(ROOT / "webui/Main.py")!r})
nodes = [node for node in ast.parse(entry.read_text(encoding='utf-8')).body
         if isinstance(node, ast.FunctionDef) and node.name == '_render_generation_task_snapshot']
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(entry), 'exec'))
_render_generation_task_snapshot('image-task', {{
    'state': const.TASK_STATE_FAILED,
    'error': 'Original English diagnostic must stay out of the translated UI',
    'error_key': {error_key!r},
    'error_params': {error_params!r},
}})
"""
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception
    expected = translations[error_key].format(**error_params)
    assert [item.value for item in app.error] == [
        f"{translations['Video Generation Failed']}: {expected}"
    ]
