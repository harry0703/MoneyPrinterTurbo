import os
from unittest.mock import Mock, patch

import pytest
import requests

from app.config import aimlapi
from app.services import aimlapi_auth


def _response(status_code=200, data=None):
    response = Mock(status_code=status_code)
    response.json.return_value = data if data is not None else {}
    return response


def test_endpoint_resolver_uses_staging_defaults():
    with patch.dict(os.environ, {}, clear=True):
        endpoints = aimlapi.resolve_endpoints()

        assert endpoints.auth_base_url == "https://auth-staging.aimlapi.com"
        assert endpoints.app_base_url == "https://app-staging.aimlapi.com"
        assert endpoints.inference_base_url == "https://api-staging.aimlapi.com/v1"
        assert endpoints.pay_base_url == "https://staging-pay.aimlapi.com"
        assert endpoints.verification_base_url == "https://staging.aimlapi.com/app"
        assert aimlapi.resolve_partner_id() == "part_K7vQmX2pL9nR4tY8cWzB6hFd"
        assert aimlapi.resolve_partner_name() == "moneyprinterturbo"
        assert aimlapi.resolve_requested_usd_limit_minor() == 1000


def test_endpoint_resolver_accepts_environment_overrides():
    overrides = {
        "AIMLAPI_AUTH_URL": "https://auth.example.test/",
        "AIMLAPI_APP_URL": "https://app.example.test/",
        "AIMLAPI_INFERENCE_URL": "https://api.example.test/v1/",
        "AIMLAPI_PAY_URL": "https://pay.example.test/",
        "AIMLAPI_VERIFICATION_BASE_URL": "https://verify.example.test/app/",
        "AIMLAPI_PARTNER_ID": "part_override",
        "AIMLAPI_PARTNER_NAME": "override-name",
        "AIMLAPI_REQUESTED_USD_LIMIT_MINOR": "2500",
    }
    with patch.dict(os.environ, overrides, clear=True):
        endpoints = aimlapi.resolve_endpoints()

        assert endpoints.auth_base_url == "https://auth.example.test"
        assert endpoints.app_base_url == "https://app.example.test"
        assert endpoints.inference_base_url == "https://api.example.test/v1"
        assert endpoints.pay_base_url == "https://pay.example.test"
        assert endpoints.verification_base_url == "https://verify.example.test/app"
        assert aimlapi.resolve_partner_id() == "part_override"
        assert aimlapi.resolve_partner_name() == "override-name"
        assert aimlapi.resolve_requested_usd_limit_minor() == 2500
        assert aimlapi.attribution_headers() == {
            "X-AIMLAPI-Source": "agent",
            "X-AIMLAPI-Partner-ID": "part_override",
        }
        assert aimlapi.is_aimlapi_inference_url("https://api.example.test/v1")


@pytest.mark.parametrize("value", ["", "invalid", "0", "-1"])
def test_invalid_spend_limit_falls_back_to_ten_dollars(value):
    with patch.dict(
        os.environ,
        {"AIMLAPI_REQUESTED_USD_LIMIT_MINOR": value},
        clear=True,
    ):
        assert aimlapi.resolve_requested_usd_limit_minor() == 1000


def test_custom_inference_host_is_not_trusted_for_attribution():
    with patch.dict(os.environ, {}, clear=True):
        assert aimlapi.is_aimlapi_inference_url("https://api.aimlapi.com/v1")
        assert aimlapi.is_aimlapi_inference_url("https://api-staging.aimlapi.com/v1")
        assert not aimlapi.is_aimlapi_inference_url("https://proxy.example.com/v1")


def test_start_authorization_sends_rebate_metadata_and_rebuilds_staging_url():
    response = _response(
        201,
        {
            "requestId": "aar_request",
            "deviceCode": "aad_device_secret",
            "interval": 7,
            "expiresIn": 600,
            "verificationUriComplete": "https://aimlapi.com/agent/authorize?request=wrong",
        },
    )
    with (
        patch.object(aimlapi_auth.requests, "post", return_value=response) as post,
        patch.object(aimlapi_auth.time, "time", return_value=100.0),
        patch.dict(os.environ, {}, clear=True),
    ):
        authorization = aimlapi_auth.start_authorization()

    assert authorization == aimlapi_auth.AuthorizationRequest(
        request_id="aar_request",
        device_code="aad_device_secret",
        verification_uri=(
            "https://staging.aimlapi.com/app/agent/authorize?request=aar_request"
        ),
        interval=7,
        expires_at=700.0,
    )
    post.assert_called_once_with(
        "https://app-staging.aimlapi.com/v3/agent-auth/authorizations",
        json={
            "partnerId": "part_K7vQmX2pL9nR4tY8cWzB6hFd",
            "partnerName": "moneyprinterturbo",
            "agentName": "MoneyPrinterTurbo",
            "returnUrl": "https://staging.aimlapi.com/app",
            "requestedUsdLimitMinor": 1000,
        },
        headers={
            "X-AIMLAPI-Source": "agent",
            "X-AIMLAPI-Partner-ID": "part_K7vQmX2pL9nR4tY8cWzB6hFd",
        },
        timeout=15,
    )


@pytest.mark.parametrize(
    ("data", "expected_status", "expected_key"),
    [
        ({"status": "pending"}, "pending", ""),
        ({"status": "approved"}, "approved", ""),
        ({"status": "denied"}, "denied", ""),
        ({"status": "ready", "apiKey": "sk-generated"}, "ready", "sk-generated"),
        ({"access_token": "sk-token"}, "ready", "sk-token"),
    ],
)
def test_poll_authorization_handles_device_flow_states(
    data, expected_status, expected_key
):
    authorization = aimlapi_auth.AuthorizationRequest(
        request_id="aar_request",
        device_code="aad_device_secret",
        verification_uri="https://staging.aimlapi.com/agent/authorize?request=aar_request",
        interval=5,
        expires_at=1000.0,
    )
    with (
        patch.object(
            aimlapi_auth.requests,
            "post",
            return_value=_response(200, data),
        ) as post,
        patch.object(aimlapi_auth.time, "time", return_value=100.0),
        patch.dict(os.environ, {}, clear=True),
    ):
        result = aimlapi_auth.poll_authorization(authorization)

    assert result.status == expected_status
    assert result.api_key == expected_key
    post.assert_called_once_with(
        "https://app-staging.aimlapi.com/v3/agent-auth/token",
        json={
            "partnerId": "part_K7vQmX2pL9nR4tY8cWzB6hFd",
            "deviceCode": "aad_device_secret",
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
        headers={
            "X-AIMLAPI-Source": "agent",
            "X-AIMLAPI-Partner-ID": "part_K7vQmX2pL9nR4tY8cWzB6hFd",
        },
        timeout=15,
    )


def test_expired_authorization_does_not_call_token_endpoint():
    authorization = aimlapi_auth.AuthorizationRequest(
        request_id="aar_request",
        device_code="aad_device_secret",
        verification_uri="https://staging.aimlapi.com/agent/authorize?request=aar_request",
        interval=5,
        expires_at=99.0,
    )
    with (
        patch.object(aimlapi_auth.requests, "post") as post,
        patch.object(aimlapi_auth.time, "time", return_value=100.0),
    ):
        result = aimlapi_auth.poll_authorization(authorization)

    assert result == aimlapi_auth.AuthorizationPollResult(status="expired")
    post.assert_not_called()


@pytest.mark.parametrize("operation", ["start", "poll"])
def test_network_errors_are_wrapped_without_exposing_device_secrets(operation):
    with (
        patch.object(
            aimlapi_auth.requests,
            "post",
            side_effect=requests.Timeout("aad_device_secret"),
        ),
        patch.object(aimlapi_auth.time, "time", return_value=100.0),
        patch.dict(os.environ, {}, clear=True),
    ):
        with pytest.raises(aimlapi_auth.AimlapiAuthError) as error:
            if operation == "start":
                aimlapi_auth.start_authorization()
            else:
                aimlapi_auth.poll_authorization(
                    aimlapi_auth.AuthorizationRequest(
                        request_id="aar_request",
                        device_code="aad_device_secret",
                        verification_uri="https://verify.example.test",
                        interval=5,
                        expires_at=1000.0,
                    )
                )

    assert "aad_device_secret" not in str(error.value)


def test_malformed_authorization_response_is_rejected():
    response = _response(201, {})
    response.json.side_effect = ValueError("invalid JSON")
    with (
        patch.object(aimlapi_auth.requests, "post", return_value=response),
        patch.dict(os.environ, {}, clear=True),
    ):
        with pytest.raises(aimlapi_auth.AimlapiAuthError, match="invalid response"):
            aimlapi_auth.start_authorization()


def test_incomplete_poll_response_is_rejected():
    authorization = aimlapi_auth.AuthorizationRequest(
        request_id="aar_request",
        device_code="aad_device_secret",
        verification_uri="https://staging.aimlapi.com/agent/authorize?request=aar_request",
        interval=5,
        expires_at=1000.0,
    )
    with (
        patch.object(
            aimlapi_auth.requests,
            "post",
            return_value=_response(200, {}),
        ),
        patch.object(aimlapi_auth.time, "time", return_value=100.0),
        patch.dict(os.environ, {}, clear=True),
    ):
        with pytest.raises(aimlapi_auth.AimlapiAuthError, match="incomplete"):
            aimlapi_auth.poll_authorization(authorization)
