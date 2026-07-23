import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse, urlunparse

import requests

from app.config.aimlapi import (
    attribution_headers,
    resolve_endpoints,
    resolve_partner_id,
    resolve_partner_name,
    resolve_requested_usd_limit_minor,
)


DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
HTTP_TIMEOUT_SECONDS = 15
TERMINAL_FAILURE_STATUSES = {
    "cancelled",
    "canceled",
    "denied",
    "error",
    "expired",
    "failed",
    "rejected",
}


class AimlapiAuthError(RuntimeError):
    """A safe, user-presentable failure of the AIMLAPI authorization flow."""


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    request_id: str
    device_code: str
    verification_uri: str
    interval: int
    expires_at: float


@dataclass(frozen=True, slots=True)
class AuthorizationPollResult:
    status: str
    api_key: str = ""


def _positive_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _response_json(response: requests.Response) -> dict:
    try:
        data = response.json()
    except ValueError as exc:
        raise AimlapiAuthError("AIMLAPI returned an invalid response") from exc
    if not isinstance(data, dict):
        raise AimlapiAuthError("AIMLAPI returned an invalid response")
    return data


def _verification_uri(request_id: str) -> str:
    endpoint = resolve_endpoints().verification_base_url
    parsed = urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise AimlapiAuthError("AIMLAPI verification URL is invalid")
    verification_path = f"{parsed.path.rstrip('/')}/agent/authorize"
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            verification_path,
            "",
            urlencode({"request": request_id}),
            "",
        )
    )


def start_authorization() -> AuthorizationRequest:
    endpoints = resolve_endpoints()
    payload = {
        "partnerId": resolve_partner_id(),
        "partnerName": resolve_partner_name(),
        "agentName": "MoneyPrinterTurbo",
        "returnUrl": endpoints.verification_base_url,
        "requestedUsdLimitMinor": resolve_requested_usd_limit_minor(),
    }
    try:
        response = requests.post(
            f"{endpoints.app_base_url}/v3/agent-auth/authorizations",
            json=payload,
            headers=attribution_headers(),
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise AimlapiAuthError("Unable to start AIMLAPI authorization") from exc

    if response.status_code not in {200, 201}:
        raise AimlapiAuthError(
            f"AIMLAPI authorization failed with HTTP {response.status_code}"
        )

    data = _response_json(response)
    request_id = str(data.get("requestId") or "").strip()
    device_code = str(data.get("deviceCode") or "").strip()
    if not request_id or not device_code:
        raise AimlapiAuthError("AIMLAPI authorization response is incomplete")

    interval = _positive_int(data.get("interval"), 5)
    expires_in = _positive_int(data.get("expiresIn"), 900)
    return AuthorizationRequest(
        request_id=request_id,
        device_code=device_code,
        verification_uri=_verification_uri(request_id),
        interval=interval,
        expires_at=time.time() + expires_in,
    )


def poll_authorization(
    authorization: AuthorizationRequest,
) -> AuthorizationPollResult:
    if time.time() >= authorization.expires_at:
        return AuthorizationPollResult(status="expired")

    endpoints = resolve_endpoints()
    payload = {
        "partnerId": resolve_partner_id(),
        "deviceCode": authorization.device_code,
        "grant_type": DEVICE_CODE_GRANT,
    }
    try:
        response = requests.post(
            f"{endpoints.app_base_url}/v3/agent-auth/token",
            json=payload,
            headers=attribution_headers(),
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise AimlapiAuthError("Unable to check AIMLAPI authorization") from exc

    if response.status_code not in {200, 201}:
        raise AimlapiAuthError(
            f"AIMLAPI authorization check failed with HTTP {response.status_code}"
        )

    data = _response_json(response)
    status = str(data.get("status") or "").strip().lower()
    api_key = str(
        data.get("apiKey")
        or data.get("api_key")
        or data.get("access_token")
        or data.get("key")
        or ""
    ).strip()
    if api_key:
        return AuthorizationPollResult(status="ready", api_key=api_key)
    if not status:
        raise AimlapiAuthError("AIMLAPI authorization response is incomplete")
    if status in TERMINAL_FAILURE_STATUSES:
        return AuthorizationPollResult(status=status)
    return AuthorizationPollResult(status=status)
