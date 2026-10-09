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

# Kimi 会轮换 refresh token，同一个旧 token 只能成功续期一次。并发请求必须
# 串行续期，否则第二个线程会拿着已轮换的旧 token 得到 invalid_grant。
_refresh_lock = threading.Lock()


def _cfg(key, default=""):
    # 读路径必须合并排队中的非阻塞更新：视频任务持有配置锁期间，_set 的写入
    # 只进入队列，直接读 config.app 会看不到刚完成的登录或 refresh 结果，
    # 导致已授权被误判为未授权、或用已轮换的旧 refresh token 重复续期。
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
    # 真实身份（对齐 Kimi 第三方指引与 CLIProxyAPI 的生产实践）：platform 与
    # 版本都是 MoneyPrinterTurbo 自己的，不伪装成 kimi_code_cli。
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
    response = requests.post(
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
    response = requests.post(
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
    response = requests.post(
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


def store_token_bundle(region: str, payload: dict) -> None:
    """Persist a fresh token payload (from poll_token or refresh)."""
    expires_in = payload.get("expires_in") or 900
    _set(_K_REGION, region)
    _set(_K_ACCESS, payload["access_token"])
    if payload.get("refresh_token"):
        # Kimi rotates refresh tokens; only overwrite when a new one is issued.
        _set(_K_REFRESH, payload["refresh_token"])
    _set(_K_EXPIRES_AT, time.time() + float(expires_in))
    # 必须落盘：纯 API 调用路径没有后续 WebUI 保存，若 refresh token 已轮换而
    # 配置文件里仍是旧值，重启后将无法续期。非阻塞保存；长任务持锁时由后台
    # 线程在任务结束后写入。
    config.try_save_config()


def clear_credentials() -> None:
    for key in (_K_ACCESS, _K_REFRESH, _K_EXPIRES_AT, _K_USER_CODE):
        _set(key, "")
    config.try_save_config()


def is_authorized() -> bool:
    return bool(str(_cfg(_K_REFRESH, "")).strip() or str(_cfg(_K_ACCESS, "")).strip())


def authorized_region() -> str:
    return str(_cfg(_K_REGION, "") or "")


def get_valid_access_token() -> str:
    """
    Return an access token valid for at least the next minute, refreshing with
    the stored refresh token when needed. Raises ValueError when the user has
    not completed the device authorization.
    """
    access = str(_cfg(_K_ACCESS, "")).strip()
    expires_at = float(_cfg(_K_EXPIRES_AT, 0) or 0)
    if access and time.time() < expires_at - _EXPIRY_MARGIN_SECONDS:
        return access
    if not str(_cfg(_K_REFRESH, "")).strip():
        raise ValueError(
            "kimi_code: not authorized yet, please complete the Kimi sign-in "
            "in Settings first."
        )
    with _refresh_lock:
        # 拿到锁后重新检查：排队期间另一个线程可能已经完成续期并写回配置，
        # 直接用它的结果，不要再用同一个旧 refresh token 续第二次。
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
        logger.info("kimi_code: refreshing access token")
        payload = _refresh(region, refresh)
        if str(_cfg(_K_REFRESH, "")).strip() != refresh:
            # 等待响应期间用户断开了连接或重新登录：凭证已失效，丢弃这次
            # 在途 refresh 的结果，不能让它把授权状态“复活”。
            logger.info(
                "kimi_code: credentials changed while refreshing; "
                "discarding the in-flight refresh result"
            )
            raise ValueError(
                "kimi_code: credentials changed while refreshing; "
                "please sign in again if needed."
            )
        store_token_bundle(region, payload)
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
