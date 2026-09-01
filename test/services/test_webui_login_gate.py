from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import auth_store
from app.utils import utils

ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
TEST_EMAIL = "gate-test@example.com"


@pytest.fixture
def login_app(tmp_path, monkeypatch):
    storage_dir = tmp_path / "storage"
    monkeypatch.setattr(utils, "storage_dir", lambda *a, **k: str(storage_dir))
    db_path = str(storage_dir / "auth.db")
    storage_dir.mkdir(parents=True, exist_ok=True)
    password = auth_store.ensure_account(TEST_EMAIL, db_path)

    original_login_email = config.app.get("login_email", "")
    config.app["login_email"] = TEST_EMAIL
    try:
        with patch.object(config, "try_save_config", return_value=True):
            app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
            app.run()
            yield app, password
    finally:
        config.app["login_email"] = original_login_email


def test_unauthenticated_session_only_shows_login_form(login_app):
    app, _password = login_app

    assert not app.exception
    assert "authenticated" not in app.session_state or not app.session_state["authenticated"]
    assert any("Email" in text_input.label for text_input in app.text_input)
    # Painel principal de geração não deve existir sem login.
    assert not any(
        button.key and str(button.key).startswith("start_generation")
        for button in app.button
    )


def test_wrong_password_keeps_gate_closed(login_app):
    app, _password = login_app

    email_input, password_input = app.text_input[0], app.text_input[1]
    email_input.input(TEST_EMAIL)
    password_input.input("wrong-password")
    app.button(key="FormSubmitter:login_form-Entrar").click()
    app.run()

    assert not app.exception
    assert "authenticated" not in app.session_state or not app.session_state["authenticated"]
    assert len(app.error) == 1


def test_correct_password_unlocks_application(login_app):
    app, password = login_app

    email_input, password_input = app.text_input[0], app.text_input[1]
    email_input.input(TEST_EMAIL)
    password_input.input(password)
    app.button(key="FormSubmitter:login_form-Entrar").click()
    app.run()

    assert not app.exception
    assert app.session_state["authenticated"] is True
    assert any(button.key == "logout_button" for button in app.button)
