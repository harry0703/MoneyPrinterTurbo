import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import time
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import pytest
import requests

from app.services import chatgpt_auth as auth


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "_credential_path", lambda: tmp_path / "auth.bin")
    yield
    for attempt in list(auth._attempts.values()):
        if attempt.status == "pending":
            attempt.status = "cancelled"
    auth._attempts.clear()


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def issuer(monkeypatch, signing_key):
    calls = []
    settings = {
        "scope": auth.SCOPES,
        "identity": {},
        "http_request": auth._request_json,
    }
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    jwk["kid"] = "test-signing-key"

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("openid-configuration"):
            return {
                "issuer": auth.ISSUER,
                "jwks_uri": auth.ISSUER + "/jwks",
                "revocation_endpoint": auth.ISSUER + "/revoke",
            }
        if url.endswith("/jwks"):
            return {"keys": [jwk]}
        assert url == auth.TOKEN_URL
        data = kwargs["data"]
        assert data["resource"] == auth.RESOURCE
        assert data["client_id"] != "dynamic_agent_client"
        if data["grant_type"] == "refresh_token":
            return {
                "access_token": "renewed-access",
                "refresh_token": "renewed-refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
            }
        attempt = next(
            a for a in auth._attempts.values() if a.redirect_uri == data["redirect_uri"]
        )
        assert data["code_verifier"] == attempt.verifier
        claims = {
            "iss": auth.ISSUER,
            "aud": data["client_id"],
            "sub": "user-one",
            "email": "test@example.invalid",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
            "nonce": attempt.nonce,
            **settings["identity"],
        }
        token = jwt.encode(
            claims,
            settings.get("signing_key", signing_key),
            algorithm="RS256",
            headers={"kid": "test-signing-key"},
        )
        return {
            "id_token": token,
            "access_token": "test-access",
            "refresh_token": "test-refresh",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": settings["scope"],
        }

    monkeypatch.setattr(auth, "_request_json", request)
    return settings, calls


def authorize(client="oaiapp_test", **options):
    flow = auth.begin_login(**options)
    attempt = auth._attempts[flow["id"]]
    auth._complete_login(
        attempt, {"state": attempt.state, "code": "synthetic-code", "client_id": client}
    )
    return flow


def test_real_loopback_callback_registers_and_saves_verified_identity(issuer):
    flow = auth.begin_login()
    attempt = auth._attempts[flow["id"]]
    params = parse_qs(urlsplit(flow["authorize_url"]).query)
    assert params["client_id"] == ["dynamic_agent_client"]
    assert params["agent_name_hint"] == ["MoneyPrinterTurbo"]
    assert params["ext_agent_host_id"][0].startswith("urn:uuid:")
    assert params["resource"] == [auth.RESOURCE]
    assert set(params["scope"][0].split()) == set(auth.SCOPES.split())
    assert params["code_challenge"] == [
        base64.urlsafe_b64encode(hashlib.sha256(attempt.verifier.encode()).digest())
        .decode()
        .rstrip("=")
    ]
    with requests.Session() as browser:
        browser.trust_env = False
        wrong = browser.get(attempt.redirect_uri, params={"state": "wrong"}, timeout=5)
        assert wrong.status_code == 400
        unicode_state = browser.get(
            attempt.redirect_uri, params={"state": "错误"}, timeout=5
        )
        assert unicode_state.status_code == 400
        assert attempt.status == "pending"
        response = browser.get(
            attempt.redirect_uri,
            params={
                "state": attempt.state,
                "code": "synthetic-code",
                "client_id": "oaiapp_test",
            },
            timeout=5,
        )
    assert response.status_code == 200
    assert "test-access" not in response.text
    assert auth.poll_login(flow)
    status = auth.account_details()
    assert status["authorized"] and status["email"] == "test@example.invalid"
    assert "access_token" not in status
    saved = auth._load()
    assert saved["profiles"]["oaiapp_test"]["subject"] == "user-one"
    assert auth.PLAN_SCOPE in saved["profiles"]["oaiapp_test"]["scopes"]
    if auth.os.name == "nt":
        assert b"test-refresh" not in auth._credential_path().read_bytes()


@pytest.mark.parametrize(
    "overrides",
    [
        {"nonce": "wrong"},
        {"aud": "other-app"},
        {"iss": "https://example.invalid"},
        {"exp": 1},
        {"sub": ""},
    ],
)
def test_invalid_identity_is_not_committed(issuer, overrides):
    issuer[0]["identity"] = overrides
    with pytest.raises(auth.ChatGPTError):
        authorize()
    assert not auth.account_status()
    assert auth._load()["profiles"]["oaiapp_test"] == {"client_id": "oaiapp_test"}


def test_invalid_signature_is_rejected(issuer):
    issuer[0]["signing_key"] = rsa.generate_private_key(
        public_exponent=65537, key_size=2048
    )
    with pytest.raises(auth.ChatGPTError):
        authorize()
    assert not auth.account_status()


def test_identity_only_sign_in_does_not_allow_inference(issuer):
    issuer[0]["scope"] = "openid profile email"
    authorize()
    assert auth.account_details()["connected"]
    assert not auth.account_status()
    with pytest.raises(auth.ChatGPTError, match="permission"):
        auth.credentials()
    retry = auth.begin_login(enable_plan=True)
    query = parse_qs(urlsplit(retry["authorize_url"]).query)
    assert query["client_id"] == ["oaiapp_test"]
    assert query["prompt"] == ["consent"]


@pytest.mark.parametrize(
    "kind", ["state", "denied", "cancelled", "expired", "missing_client"]
)
def test_invalid_callback_does_not_exchange_code(issuer, kind):
    flow = auth.begin_login()
    attempt = auth._attempts[flow["id"]]
    query = {"state": attempt.state, "code": "code", "client_id": "oaiapp_test"}
    if kind == "state":
        query["state"] = "wrong"
    elif kind == "denied":
        query["error"] = "access_denied"
    elif kind == "cancelled":
        auth.cancel_login(flow)
    elif kind == "expired":
        attempt.expires_at = 0
    else:
        query.pop("client_id")
    with pytest.raises(auth.ChatGPTError):
        auth._complete_login(attempt, query)
    assert issuer[1] == []


def test_returning_sign_in_reuses_registration_and_checks_subject(issuer):
    authorize()
    host_id = auth._load()["host_id"]
    flow = auth.begin_login()
    query = parse_qs(urlsplit(flow["authorize_url"]).query)
    assert query["client_id"] == ["oaiapp_test"]
    assert query["ext_agent_host_id"] == [host_id]
    assert "agent_name_hint" not in query
    issuer[0]["identity"] = {"sub": "other-user"}
    attempt = auth._attempts[flow["id"]]
    with pytest.raises(auth.ChatGPTError):
        auth._complete_login(attempt, {"state": attempt.state, "code": "code"})
    assert auth._load()["profiles"]["oaiapp_test"]["subject"] == "user-one"


def test_new_login_does_not_replace_current_account_before_completion(issuer):
    authorize()
    flow = auth.begin_login(new_account=True)
    assert auth.account_details()["active"] == "oaiapp_test"
    issuer[0]["identity"] = {"sub": "user-two"}
    attempt = auth._attempts[flow["id"]]
    auth._complete_login(
        attempt, {"state": attempt.state, "code": "code", "client_id": "oaiapp_two"}
    )
    assert len(auth.account_details()["profiles"]) == 2
    auth.select_account("oaiapp_test")
    assert auth.credentials()[0]["subject"] == "user-one"


def test_concurrent_refresh_uses_registered_client_and_rotates_once(issuer):
    authorize()
    data = auth._load()
    data["profiles"]["oaiapp_test"]["expires_at"] = 0
    auth._save(data)
    issuer[1].clear()
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(lambda _: auth.credentials(), range(4)))
    refreshes = [call for call in issuer[1] if call[1] == auth.TOKEN_URL]
    assert len(refreshes) == 1
    request = refreshes[0][2]["data"]
    assert request == {
        "grant_type": "refresh_token",
        "client_id": "oaiapp_test",
        "refresh_token": "test-refresh",
        "resource": auth.RESOURCE,
    }
    assert all(bundle["access_token"] == "renewed-access" for bundle, _ in results)
    assert auth._load()["profiles"]["oaiapp_test"]["refresh_token"] == "renewed-refresh"


def test_native_login_and_denial_preserve_device_credentials(monkeypatch):
    from app.services import codex_oauth

    legacy_path = auth._credential_path().with_name("openai_codex.bin")
    monkeypatch.setattr(codex_oauth, "_credential_path", lambda: legacy_path)
    codex_oauth._save(
        {
            "access_token": "legacy",
            "refresh_token": "old-refresh",
            "account_id": "old",
            "expires_at": time.time() + 3600,
        }
    )
    before = legacy_path.read_bytes()
    assert not auth.account_status()
    flow = auth.begin_login()
    attempt = auth._attempts[flow["id"]]
    with pytest.raises(auth.ChatGPTError):
        auth._complete_login(
            attempt, {"state": attempt.state, "error": "access_denied"}
        )
    assert legacy_path.read_bytes() == before
    assert codex_oauth.account_status()
    assert not auth.account_status()
    # An explicit preview import must not reinterpret old device credentials.
    auth._credential_path().unlink()
    with pytest.raises(auth.ChatGPTError, match="preview"):
        auth.import_preview_credentials()
    assert not auth._credential_path().exists()
    assert legacy_path.read_bytes() == before


def test_preview_import_preserves_registration_without_overwriting(issuer):
    authorize()
    expected = auth._load()
    source = auth._credential_path().with_name("openai_codex.bin")
    source.write_bytes(auth._credential_path().read_bytes())
    original_source = source.read_bytes()
    auth._credential_path().unlink()
    auth.import_preview_credentials()
    assert auth._load() == expected
    assert source.read_bytes() == original_source
    with pytest.raises(auth.ChatGPTError, match="destination"):
        auth.import_preview_credentials()
    assert auth._load() == expected


def test_disconnect_revokes_then_retains_registration_and_host(issuer, monkeypatch):
    authorize()
    before = auth._load()
    calls = []

    class Response:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    def revoke(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(auth.requests, "post", revoke)
    assert auth.disconnect()
    assert calls[0][1]["data"]["client_id"] == "oaiapp_test"
    assert calls[0][1]["data"]["token_type_hint"] == "refresh_token"
    after = auth._load()
    assert before["host_id"] == after["host_id"]
    assert after["active"] == "oaiapp_test"
    assert "access_token" not in after["profiles"]["oaiapp_test"]
    query = parse_qs(urlsplit(auth.begin_login()["authorize_url"]).query)
    assert query["client_id"] == ["oaiapp_test"]


def test_optional_request_diagnostics_redact_oauth_code_and_pkce():
    from app.utils.request_logging import sanitize_payload

    payload = {
        "data": {
            "code": "temporary-code-secret",
            "code_verifier": "pkce-secret",
            "nonce": "nonce-secret",
            "client_id": "oaiapp_test",
        }
    }
    sanitized = sanitize_payload(payload)
    assert sanitized["data"]["client_id"] == "oaiapp_test"
    assert all(
        value == "[REDACTED]"
        for key, value in sanitized["data"].items()
        if key != "client_id"
    )


@pytest.mark.parametrize("error_code", sorted(auth.TERMINAL_REFRESH_ERRORS))
def test_terminal_refresh_failure_allows_signing_in_again(
    issuer, monkeypatch, error_code
):
    authorize()
    before = auth._load()
    before["profiles"]["oaiapp_test"]["expires_at"] = 0
    auth._save(before)
    request = auth._request_json

    def expired_refresh(method, url, **kwargs):
        if url == auth.TOKEN_URL:
            return issuer[0]["http_request"](method, url, **kwargs)
        return request(method, url, **kwargs)

    response = MagicMock(status_code=400)
    response.__enter__.return_value = response
    response.json.return_value = {"error": error_code}
    monkeypatch.setattr(auth.requests, "request", lambda *a, **kw: response)
    monkeypatch.setattr(auth, "_request_json", expired_refresh)
    with pytest.raises(auth.ChatGPTError):
        auth.credentials()
    assert not auth.account_status()
    after = auth._load()
    assert after["host_id"] == before["host_id"]
    assert after["profiles"]["oaiapp_test"]["client_id"] == "oaiapp_test"
    assert "refresh_token" not in after["profiles"]["oaiapp_test"]
    query = parse_qs(urlsplit(auth.begin_login()["authorize_url"]).query)
    assert query["client_id"] == ["oaiapp_test"]


def test_jwks_outage_does_not_consume_a_rotating_refresh_token(issuer, monkeypatch):
    authorize()
    before = auth._load()
    before["profiles"]["oaiapp_test"]["expires_at"] = 0
    auth._save(before)
    request = auth._request_json
    refreshes = []

    def jwks_outage(method, url, **kwargs):
        if url.endswith("/jwks"):
            raise auth.ChatGPTError("network_error")
        if url == auth.TOKEN_URL:
            refreshes.append(kwargs)
            result = request(method, url, **kwargs)
            result["id_token"] = before["profiles"]["oaiapp_test"]["id_token"]
            return result
        return request(method, url, **kwargs)

    monkeypatch.setattr(auth, "_request_json", jwks_outage)
    with pytest.raises(auth.ChatGPTError):
        auth.credentials()
    assert refreshes == []
    assert auth._load() == before


def test_temporary_refresh_failure_preserves_the_session(issuer, monkeypatch):
    authorize()
    before = auth._load()
    before["profiles"]["oaiapp_test"]["expires_at"] = 0
    auth._save(before)
    request = auth._request_json

    def unavailable(method, url, **kwargs):
        if url == auth.TOKEN_URL:
            raise auth.ChatGPTError("network_error")
        return request(method, url, **kwargs)

    monkeypatch.setattr(auth, "_request_json", unavailable)
    with pytest.raises(auth.ChatGPTError):
        auth.credentials()
    assert auth._load() == before
