import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
from unittest.mock import MagicMock, patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import codex_oauth as codex
from app.services import codex_models
from app.services import llm


def reply(status=200, payload=None, lines=None):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload or {}
    response.iter_lines.return_value = iter(lines or [])
    response.__enter__.return_value = response
    return response


def token_payload(access="access-one", refresh="refresh-one"):
    claims = {"https://api.openai.com/auth": {"chatgpt_account_id": "account-one"}}
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return {
        "access_token": access,
        "refresh_token": refresh,
        "id_token": "header." + encoded + ".sig",
        "expires_in": 3600,
    }


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path):
    with patch.object(codex, "_credential_path", return_value=tmp_path / "auth.bin"):
        codex.disconnect()
        yield
        codex.disconnect()


def flow():
    return {
        "device_auth_id": "device",
        "user_code": "CODE-ONE",
        "generation": codex.authorization_generation(),
        "session_revision": None,
        "expires_at": time.time() + 900,
    }


def test_device_login_pending_commit_and_encrypted_persistence():
    responses = [
        reply(404),
        reply(payload={"authorization_code": "code", "code_verifier": "verifier"}),
        reply(payload=token_payload()),
    ]
    pending = flow()
    with patch.object(codex.requests, "post", side_effect=responses) as post:
        assert codex.poll_login(pending) is False
        assert codex.poll_login(pending) is True
    assert codex.account_status()
    assert codex._load()["account_id"] == "account-one"
    assert post.call_args.kwargs["data"]["grant_type"] == "authorization_code"
    assert post.call_args.kwargs["allow_redirects"] is False
    if codex.os.name == "nt":
        assert b"refresh-one" not in codex._credential_path().read_bytes()
    codex.disconnect()
    assert not codex.account_status()


def test_cancelled_flow_cannot_reconnect():
    pending = flow()
    codex.disconnect()
    with patch.object(
        codex,
        "_post",
        return_value=reply(
            payload={"authorization_code": "code", "code_verifier": "verifier"}
        ),
    ) as post:
        with pytest.raises(codex.CodexError) as error:
            codex.poll_login(pending)
    assert error.value.key == "codex.oauth.changed"
    assert post.call_count == 1  # Never exchanges the stale code.
    assert not codex.account_status()


def test_expired_code_makes_no_request():
    pending = dict(flow(), expires_at=0)
    with patch.object(codex, "_post") as post, pytest.raises(codex.CodexError):
        codex.poll_login(pending)
    post.assert_not_called()


@pytest.mark.parametrize("interval", [-1, "nan", "inf", {}, 1000])
def test_rejects_invalid_poll_interval(interval):
    with (
        patch.object(
            codex,
            "_post",
            return_value=reply(
                payload={
                    "device_auth_id": "id",
                    "user_code": "CODE",
                    "interval": interval,
                }
            ),
        ),
        pytest.raises(codex.CodexError),
    ):
        codex.request_device_code()


def test_concurrent_requests_refresh_rotating_token_once():
    old = codex._bundle(token_payload())
    old["expires_at"] = 0
    codex._save(old)
    with patch.object(
        codex,
        "_post",
        return_value=reply(payload=token_payload("access-two", "refresh-two")),
    ) as post:
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(lambda _: codex._credentials(), range(4)))
    assert post.call_count == 1
    assert all(item["access_token"] == "access-two" for item in results)
    assert codex._load()["refresh_token"] == "refresh-two"


def completed_event(text="Narraci\u00f3n de las pir\u00e1mides"):
    return {
        "type": "response.completed",
        "response": {
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": text}]}
            ],
        },
    }


def test_stream_accepts_only_final_output_and_preserves_spanish():
    lines = [
        'data: {"type":"response.output_text.delta","delta":"discard"}',
        "",
        "data: " + json.dumps(completed_event()),
        "",
    ]
    codex._save(codex._bundle(token_payload()))
    with patch.object(codex.requests, "post", return_value=reply(lines=lines)) as post:
        result = codex.generate_text("Historia\n\nEscenas", "test-model")
    assert result == "Narraci\u00f3n de las pir\u00e1mides"
    request = post.call_args.kwargs
    assert request["json"]["store"] is False
    assert "tools" not in request["json"]
    assert request["json"]["input"][0]["content"][0]["text"] == "Historia\n\nEscenas"
    assert request["headers"]["chatgpt-account-id"] == "account-one"


@pytest.mark.parametrize(
    "lines",
    [
        ['data: {"type":"response.output_text.delta","delta":"partial"}', ""],
        ['data: {"type":"response.failed","error":{"message":"secret"}}', ""],
        ['data: {"type":"response.completed","response":{"status":"incomplete"}}', ""],
        ["data: not-json", ""],
    ],
)
def test_stream_failure_never_returns_partial_text_or_raw_errors(lines):
    with pytest.raises(codex.CodexError) as error:
        codex._read_stream(reply(lines=lines), time.monotonic() + 30)
    assert "secret" not in str(error.value)


def test_unauthorized_refresh_retries_once():
    codex._save(codex._bundle(token_payload()))
    responses = [
        reply(401),
        reply(payload=token_payload("new-access", "new-refresh")),
        reply(lines=["data: " + json.dumps(completed_event("OK")), ""]),
    ]
    with patch.object(codex, "_post", side_effect=responses) as post:
        assert codex.generate_text("hola", "test-model") == "OK"
    assert post.call_count == 3
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer new-access"


def test_llm_dispatch_uses_subscription_and_bounds_connection_timeout():
    settings = {
        "llm_provider": "openai_codex",
        "openai_codex_timeout": "300",
        "openai_codex_model_name": "selected-live-model",
    }
    with (
        patch.object(codex, "generate_text", return_value="OK") as generate,
        patch.object(llm, "OpenAI") as api,
    ):
        assert (
            llm._generate_response("hola", app_config=settings, request_timeout=30)
            == "OK"
        )
    api.assert_not_called()
    assert generate.call_args.args == (
        "hola",
        "selected-live-model",
        30,
    )


def test_webui_device_code_flow_in_spanish():
    settings = dict(config.app, llm_provider="openai_codex")
    with (
        patch.object(config, "app", settings),
        patch.object(config, "ui", dict(config.ui, language="es")),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(
            codex, "request_device_code", return_value=dict(flow(), interval=5)
        ) as start,
        patch.object(codex, "poll_login", return_value=False),
        patch.object(
            codex_models,
            "get_catalog",
            return_value=codex_models.Catalog(
                (codex_models.Model("gpt-7-test", "Test model"),), time.time()
            ),
        ),
    ):
        app = AppTest.from_file(Path(__file__).resolve().parents[2] / "webui/Main.py", default_timeout=60)
        app.session_state["settings_dialog_open"] = True
        app.session_state["settings_dialog_target_tab"] = "llm"
        app.run()
        assert not app.exception
        assert not start.called
        app.button(key="codex_login").click().run()
        assert not app.exception
        assert any("CODE-ONE" in item.value for item in app.code)
        assert not any(
            "openai_codex_api_key_input" in str(item.key) for item in app.text_input
        )
        app.button(key="codex_disconnect").click().run()
        assert not app.exception
        assert "openai_codex_login_flow" not in app.session_state
