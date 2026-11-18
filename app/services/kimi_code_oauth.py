"""
Kimi Code (Kimi subscription) OAuth device-flow support.

Kimi Code plan subscribers do not pay per token: they authenticate once in the
browser and third-party apps call the OpenAI-compatible coding endpoint with a
Bearer token. This module implements the device authorization grant used by
the Kimi Code CLI:

  1. POST {auth}/api/oauth/device_authorization  -> device_code + user_code
  2. user opens {site}/code/authorize_device?user_code=... and approves
  3. POST {auth}/api/oauth/token                 -> access_token (+ refresh_token)
  4. call {api}/usages, {api}/messages with the access token

Both regions are supported: China (auth.kimi.com / api.kimi.com) and Global
(auth.kimi.ai / api.kimi.ai). Token bundles are persisted in the app config so
a refresh survives restarts; access tokens expire after 15 minutes and are
renewed transparently with the stored refresh token.

Requests identify themselves genuinely as MoneyPrinterTurbo (X-Msh-* headers
and User-Agent), following Kimi's third-party guideline to keep the tool's
real client identity — the same shape CLIProxyAPI uses in production.
"""

import math
import threading
import time
import uuid

import requests
from loguru import logger

from app.utils.request_logging import trace_http_call

from app import __version__
from app.config import config

# Public OAuth client id shipped by the Kimi Code CLI. There is no third-party
# client registration today, so every integration with the device flow uses
# this id (CLIProxyAPI and many others do the same); what identifies the
# application is the genuine identity headers below, not the client id. A
# dedicated MoneyPrinterTurbo client id can be set later through the
# `kimi_code_client_id` config field once issued.
DEFAULT_CLIENT_ID = "17e5f671-d194-4dfb-9706-5516cb48c098"

DEFAULT_TIMEOUT_SECONDS = 300.0

_REGIONS = {
    "china": {
        "auth_base": "https://auth.kimi.com",
        "api_base": "https://api.kimi.com/coding/v1",
        "site_base": "https://www.kimi.com",
    },
    "global": {
        "auth_base": "https://auth.kimi.ai",
        "api_base": "https://api.kimi.ai/coding/v1",
        "site_base": "https://www.kimi.ai",
    },
}

# config.app keys used to persist the OAuth state
_K_REGION = "kimi_code_region"
_K_CLIENT_ID = "kimi_code_client_id"
_K_DEVICE_ID = "kimi_code_device_id"
_K_ACCESS = "kimi_code_access_token"
_K_REFRESH = "kimi_code_refresh_token"
_K_EXPIRES_AT = "kimi_code_token_expires_at"  # unix seconds (float)
_K_USER_CODE = "kimi_code_last_user_code"  # diagnostics only

# Refresh 60 seconds before actual expiry so a slow request never starts with
# a token that dies mid-flight.
_EXPIRY_MARGIN_SECONDS = 60.0

# Kimi rotates refresh tokens, and the same old token can only be used to renew once. Concurrent requests must
# renew serially, otherwise the second thread would get invalid_grant with an already rotated old token.
_refresh_lock = threading.Lock()
# Network requests don't hold the credential lock; verifying response ownership and writing back must happen in the same critical section.
_credentials_lock = threading.RLock()
_authorization_generation = 0


def authorization_generation() -> int:
    """Return the login/disconnect version, so in-flight authorization responses can check they still belong to the current account state."""
    with _credentials_lock:
        return _authorization_generation


def _cfg(key, default=""):
    # The read path must merge queued non-blocking updates: while a video task holds the config lock, writes from _set
    # only enter the queue, so reading config.app directly wouldn't see a just-completed login or refresh result,
    # making an authorized state look unauthorized, or renewing again with an already rotated old refresh token.
    snapshot = config.snapshot_config_with_pending(config.app)
    value = snapshot.get(key, default)
    return value if value is not None else default


def _set(key, value):
    # Queued non-blocking update; applied immediately when no video task holds
    # the config lock, otherwise applied when the running task releases it.
    config.update_config_nonblocking(config.app, key, value)


def client_id() -> str:
    return str(_cfg(_K_CLIENT_ID, "") or DEFAULT_CLIENT_ID)


def device_id() -> str:
    existing = str(_cfg(_K_DEVICE_ID, "")).strip()
    if existing:
        return existing
    new_id = str(uuid.uuid4())
    _set(_K_DEVICE_ID, new_id)
    return new_id


def region_ids() -> list[str]:
    return list(_REGIONS.keys())


def resolve_region(base_url: str | None = None) -> str:
    """Map an API base URL (or empty value) back to a region id."""
    url = (base_url or "").strip().lower()
    if "kimi.ai" in url:
        return "global"
    return "china"


def api_base_url(region: str) -> str:
    return _REGIONS[region]["api_base"]


def site_base_url(region: str) -> str:
    return _REGIONS[region]["site_base"]


def _identity_headers() -> dict:
    # Real identity (following Kimi's third-party guidance and CLIProxyAPI's production practice): platform and
    # version are MoneyPrinterTurbo's own, not disguised as kimi_code_cli.
    return {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": f"MoneyPrinterTurbo/{__version__}",
        "X-Msh-Platform": "MoneyPrinterTurbo",
        "X-Msh-Version": __version__,
        "X-Msh-Device-Name": "MoneyPrinterTurbo",
        "X-Msh-Device-Model": "MoneyPrinterTurbo",
        "X-Msh-Os-Version": "any",
        "X-Msh-Device-Id": device_id(),
    }


def api_headers() -> dict:
    """Identity headers for calls against the coding endpoint itself."""
    headers = _identity_headers()
    headers.pop("Content-Type", None)
    return headers


def request_device_code(region: str) -> dict:
    """Start a device authorization flow. Returns the raw provider payload."""
    if region not in _REGIONS:
        raise ValueError(f"kimi_code: unknown region '{region}'")
    url = f"{_REGIONS[region]['auth_base']}/api/oauth/device_authorization"
    response = trace_http_call(
        "POST", requests.post,
        url,
        headers=_identity_headers(),
        data={"client_id": client_id()},
        timeout=30,
    )
    if response.status_code != 200:
        raise ValueError(
            f"kimi_code: device code request failed "
            f"({response.status_code}): {response.text[:300]}"
        )
    data = _json_or_raise(response, "device authorization")
    for field in ("device_code", "user_code", "verification_uri_complete"):
        if not data.get(field):
            raise ValueError(f"kimi_code: device authorization missing '{field}'")
    _set(_K_USER_CODE, data["user_code"])
    return data


def _json_or_raise(response, what: str) -> dict:
    try:
        return response.json()
    except ValueError:
        raise ValueError(
            f"kimi_code: {what} returned a non-JSON response "
            f"(HTTP {response.status_code}): {response.text[:200]}"
        ) from None


def poll_token(region: str, device_code: str) -> dict:
    """
    One poll of the token endpoint. Returns:
      - {"pending": True}                     — user has not approved yet
      - {"pending": True, "slow_down": True}  — server asks to poll slower
      - {"expired": True}                     — device code expired; restart
      - {"denied": True}                      — user declined the request
      - the token payload                     — approved
    """
    url = f"{_REGIONS[region]['auth_base']}/api/oauth/token"
    response = trace_http_call(
        "POST", requests.post,
        url,
        headers=_identity_headers(),
        data={
            "client_id": client_id(),
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
        timeout=30,
    )
    data = _json_or_raise(response, "token endpoint")
    if data.get("access_token"):
        return data
    error = data.get("error", "")
    if error == "authorization_pending":
        return {"pending": True}
    if error == "slow_down":
        # RFC 8628 §3.5: keep polling, but increase the interval — this is a
        # rate hint, not a failure.
        return {"pending": True, "slow_down": True}
    if error == "expired_token":
        return {"expired": True}
    if error == "access_denied":
        return {"denied": True}
    raise ValueError(
        f"kimi_code: token request failed: "
        f"{data.get('error_description') or data.get('error') or data}"
    )


def _refresh(region: str, refresh_token: str) -> dict:
    url = f"{_REGIONS[region]['auth_base']}/api/oauth/token"
    response = trace_http_call(
        "POST", requests.post,
        url,
        headers=_identity_headers(),
        data={
            "client_id": client_id(),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    data = _json_or_raise(response, "token refresh")
    if not data.get("access_token"):
        raise ValueError(
            f"kimi_code: token refresh failed: "
            f"{data.get('error_description') or data.get('error') or data}"
        )
    return data


def store_token_bundle(
    region: str,
    payload: dict,
    *,
    expected_generation: int | None = None,
    expected_refresh_token: str | None = None,
) -> None:
    """Atomically check response ownership and save credentials, so an old response can't undo a disconnect or overwrite a new login."""
    global _authorization_generation
    access = payload["access_token"]
    expires_at = time.time() + float(payload.get("expires_in") or 900)
    with _credentials_lock:
        if (
            expected_generation is not None
            and expected_generation != _authorization_generation
        ) or (
            expected_refresh_token is not None
            and str(_cfg(_K_REFRESH, "")).strip() != expected_refresh_token
        ):
            raise ValueError(
                "kimi_code: credentials changed while authorizing or refreshing; "
                "please sign in again if needed."
            )
        _set(_K_REGION, region)
        _set(_K_ACCESS, access)
        if payload.get("refresh_token"):
            _set(_K_REFRESH, payload["refresh_token"])
        _set(_K_EXPIRES_AT, expires_at)
        if expected_refresh_token is None:
            _authorization_generation += 1
        # Saving doesn't wait for the video task's config lock, and queued credentials can still be read immediately.
        config.try_save_config()


def clear_credentials() -> None:
    global _authorization_generation
    with _credentials_lock:
        _authorization_generation += 1
        for key in (_K_ACCESS, _K_REFRESH, _K_EXPIRES_AT, _K_USER_CODE):
            _set(key, "")
        config.try_save_config()


def is_authorized() -> bool:
    with _credentials_lock:
        return bool(
            str(_cfg(_K_REFRESH, "")).strip() or str(_cfg(_K_ACCESS, "")).strip()
        )


def authorized_region() -> str:
    with _credentials_lock:
        return str(_cfg(_K_REGION, "") or "")


def get_valid_access_token() -> str:
    """Return a valid token; renew serially and reject old responses returned after a login/disconnect."""
    with _credentials_lock:
        access = str(_cfg(_K_ACCESS, "")).strip()
        expires_at = float(_cfg(_K_EXPIRES_AT, 0) or 0)
        if access and time.time() < expires_at - _EXPIRY_MARGIN_SECONDS:
            return access
    with _refresh_lock:
        # Another request may have renewed while queued, so re-read the full credential state.
        with _credentials_lock:
            access = str(_cfg(_K_ACCESS, "")).strip()
            expires_at = float(_cfg(_K_EXPIRES_AT, 0) or 0)
            if access and time.time() < expires_at - _EXPIRY_MARGIN_SECONDS:
                return access
            refresh = str(_cfg(_K_REFRESH, "")).strip()
            if not refresh:
                raise ValueError(
                    "kimi_code: not authorized yet, please complete the Kimi "
                    "sign-in in Settings first."
                )
            region = str(_cfg(_K_REGION, "") or "china")
            generation = _authorization_generation
        logger.info("kimi_code: refreshing access token")
        payload = _refresh(region, refresh)
        store_token_bundle(
            region,
            payload,
            expected_generation=generation,
            expected_refresh_token=refresh,
        )
        return payload["access_token"]


def coerce_timeout(value) -> float:
    if value in (None, ""):
        return DEFAULT_TIMEOUT_SECONDS
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"timeout must be a number, got '{value}'") from None
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"timeout must be a positive finite number, got '{value}'")
    return parsed
