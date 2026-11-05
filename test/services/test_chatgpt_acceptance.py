import json
import time
from unittest.mock import MagicMock

import pytest

from app.config import config
from app.services import (
    chatgpt_auth as auth,
    chatgpt_models,
    chatgpt_oauth,
    codex_oauth,
    llm,
)
from scripts import accept_chatgpt_oauth as acceptance


@pytest.fixture
def synthetic_live_route(tmp_path, monkeypatch):
    monkeypatch.setattr(
        auth, "_credential_path", lambda: tmp_path / "openai_chatgpt.bin"
    )
    monkeypatch.setattr(
        acceptance, "_revision", lambda: {"commit": "synthetic", "dirty": False}
    )
    monkeypatch.setattr(acceptance, "sign_in", lambda: None)
    monkeypatch.setattr(chatgpt_models, "_cached", None)
    monkeypatch.setattr(chatgpt_models, "_identity", None)
    auth._save(
        {
            "version": 2,
            "host_id": "urn:uuid:synthetic",
            "active": "client",
            "revision": 1,
            "profiles": {
                "client": {
                    "client_id": "client",
                    "subject": "synthetic-user",
                    "email": "private@example.invalid",
                    "issuer": auth.ISSUER,
                    "id_token": "SENSITIVE_ID_TOKEN",
                    "access_token": "SENSITIVE_ACCESS_TOKEN",
                    "refresh_token": "SENSITIVE_REFRESH_TOKEN",
                    "scopes": auth.SCOPES.split(),
                    "expires_at": time.time() + 3600,
                }
            },
        }
    )
    calls = []
    texts = iter(
        [
            "A short walk outdoors is a simple daily activity.",
            '["walking outdoors", "park path", "walking shoes"]',
            "OAuth refresh OK",
        ]
    )

    def request(method, url, **kwargs):
        calls.append((method, url))
        response = MagicMock(status_code=200)
        response.__enter__.return_value = response
        response.headers = {
            "x-request-id": "req_synthetic",
            "Set-Cookie": "SENSITIVE_COOKIE",
        }
        if url.endswith("openid-configuration"):
            payload = {
                "issuer": auth.ISSUER,
                "jwks_uri": auth.ISSUER + "/jwks",
                "revocation_endpoint": auth.ISSUER + "/revoke",
            }
        elif url.endswith("/jwks"):
            payload = {"keys": []}
        elif url == auth.TOKEN_URL:
            payload = {
                "access_token": "SENSITIVE_NEW_ACCESS",
                "refresh_token": "SENSITIVE_NEW_REFRESH",
                "expires_in": 3600,
                "token_type": "Bearer",
            }
        elif url == chatgpt_oauth.MODELS_URL:
            payload = {
                "models": [
                    {
                        "slug": "synthetic-model",
                        "display_name": "Synthetic",
                        "visibility": "list",
                    }
                ]
            }
        elif url == chatgpt_oauth.RESPONSES_URL:
            payload = {
                "type": "response.completed",
                "response": {
                    "id": "resp_synthetic",
                    "model": "synthetic-model",
                    "status": "completed",
                    "id_token": "SENSITIVE_RESPONSE_FIELD",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": next(texts)}],
                        }
                    ],
                },
            }
            response.iter_lines.return_value = iter(
                ["data: " + json.dumps(payload), ""]
            )
        else:
            assert url == auth.ISSUER + "/revoke"
            payload = {}
        response.json.return_value = payload
        return response

    monkeypatch.setattr(auth.requests, "request", request)
    monkeypatch.setattr(
        auth.requests, "post", lambda url, **kw: request("POST", url, **kw)
    )
    return calls


def test_acceptance_runs_real_entrypoints_and_exports_only_allowed_fields(
    synthetic_live_route,
):
    before_config = dict(config.app)
    report = acceptance.run_acceptance(login=True, disconnect=True)
    assert report["status"] == "passed", report
    assert report["selected_model"] == "synthetic-model"
    for stage in ("script", "keywords", "after_refresh"):
        assert report["stages"][stage]["response_completed"]
        assert report["stages"][stage]["trace"][0]["request_id"] == "req_synthetic"
        assert report["stages"][stage]["trace"][1]["response_id"] == "resp_synthetic"
    assert report["stages"]["refresh"]["refresh_token_rotated"]
    assert report["stages"]["disconnect"]["local_tokens_cleared"]
    assert report["stages"]["disconnect"]["inference_requests_after_signout"] == 0
    assert dict(config.app) == before_config
    serialized = json.dumps(report)
    assert "SENSITIVE" not in serialized
    assert "private@example.invalid" not in serialized
    assert not any("backend-api" in url for _, url in synthetic_live_route)


def test_existing_session_does_not_claim_fresh_browser_authorization(
    synthetic_live_route,
):
    report = acceptance.run_acceptance(disconnect=True)
    assert report["status"] == "partial"
    assert report["stages"]["authorization"]["browser_flow_performed_this_run"] is False


def test_no_connection_report_is_actionable_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "_credential_path", lambda: tmp_path / "absent.bin")
    monkeypatch.setattr(
        auth.requests, "request", lambda *a, **kw: pytest.fail("Unexpected request")
    )
    report = acceptance.run_acceptance()
    assert report["status"] == "failed"
    assert "eligible" in report["error"]["message"]


def test_provider_selection_never_changes_billing_implicitly(monkeypatch):
    legacy = MagicMock(return_value="device-code output")
    native = MagicMock(side_effect=auth.ChatGPTError("ineligible"))
    monkeypatch.setattr(codex_oauth, "generate_text", legacy)
    monkeypatch.setattr(chatgpt_oauth, "generate_text", native)
    settings = {
        "llm_provider": "openai_codex",
        "openai_codex_model_name": "device-model",
        "openai_chatgpt_model_name": "native-model",
    }
    assert llm._generate_response("test", app_config=settings) == "device-code output"
    native.assert_not_called()
    settings["llm_provider"] = "openai_chatgpt"
    assert llm._generate_response("test", app_config=settings).startswith("Error:")
    assert legacy.call_count == 1
    assert settings["llm_provider"] == "openai_chatgpt"


def test_structured_account_ineligibility_remains_distinct(
    synthetic_live_route, monkeypatch
):
    response = MagicMock(status_code=403)
    response.__enter__.return_value = response
    response.headers = {"x-request-id": "req_denied"}
    response.json.return_value = {
        "error": {"code": "subscription_sharing_user_not_eligible"}
    }
    monkeypatch.setattr(auth.requests, "request", lambda *a, **kw: response)
    with pytest.raises(auth.ChatGPTError) as error:
        chatgpt_oauth.generate_text("test", "synthetic-model")
    assert error.value.key == "chatgpt.oauth.ineligible"
    assert auth.account_status()


def test_failed_acceptance_retains_request_id_without_exporting_error_body(
    synthetic_live_route, monkeypatch
):
    response = MagicMock(status_code=403)
    response.__enter__.return_value = response
    response.headers = {
        "x-request-id": "req_denied",
        "Authorization": "SENSITIVE_HEADER",
    }
    response.json.return_value = {
        "error": {
            "code": "subscription_sharing_user_not_eligible",
            "message": "SENSITIVE_BODY",
        }
    }
    monkeypatch.setattr(auth.requests, "request", lambda *a, **kw: response)
    report = acceptance.run_acceptance()
    assert report["status"] == "failed"
    assert report["stages"]["models"]["trace"][0]["request_id"] == "req_denied"
    assert "SENSITIVE" not in json.dumps(report)
