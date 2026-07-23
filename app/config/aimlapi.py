import os
from dataclasses import dataclass
from urllib.parse import urlparse


DEFAULT_AIMLAPI_PARTNER_ID = "part_K7vQmX2pL9nR4tY8cWzB6hFd"
DEFAULT_AIMLAPI_PARTNER_NAME = "moneyprinterturbo"
DEFAULT_AIMLAPI_REQUESTED_USD_LIMIT_MINOR = 1000


@dataclass(frozen=True, slots=True)
class AimlapiEndpoints:
    auth_base_url: str
    app_base_url: str
    inference_base_url: str
    pay_base_url: str
    verification_base_url: str


def _env_or_default(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


def resolve_endpoints() -> AimlapiEndpoints:
    """Resolve AIMLAPI service endpoints, using production defaults."""
    return AimlapiEndpoints(
        auth_base_url=_env_or_default(
            "AIMLAPI_AUTH_URL", "https://auth.aimlapi.com"
        ).rstrip("/"),
        app_base_url=_env_or_default(
            "AIMLAPI_APP_URL", "https://app.aimlapi.com"
        ).rstrip("/"),
        inference_base_url=_env_or_default(
            "AIMLAPI_INFERENCE_URL", "https://api.aimlapi.com/v1"
        ).rstrip("/"),
        pay_base_url=_env_or_default(
            "AIMLAPI_PAY_URL", "https://pay.aimlapi.com"
        ).rstrip("/"),
        verification_base_url=_env_or_default(
            "AIMLAPI_VERIFICATION_BASE_URL", "https://aimlapi.com/app"
        ).rstrip("/"),
    )


def resolve_partner_id() -> str:
    return _env_or_default("AIMLAPI_PARTNER_ID", DEFAULT_AIMLAPI_PARTNER_ID)


def resolve_partner_name() -> str:
    return _env_or_default("AIMLAPI_PARTNER_NAME", DEFAULT_AIMLAPI_PARTNER_NAME)


def resolve_requested_usd_limit_minor() -> int:
    raw_value = os.environ.get(
        "AIMLAPI_REQUESTED_USD_LIMIT_MINOR",
        str(DEFAULT_AIMLAPI_REQUESTED_USD_LIMIT_MINOR),
    )
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_AIMLAPI_REQUESTED_USD_LIMIT_MINOR
    return value if value > 0 else DEFAULT_AIMLAPI_REQUESTED_USD_LIMIT_MINOR


def attribution_headers() -> dict[str, str]:
    return {
        "X-AIMLAPI-Source": "agent",
        "X-AIMLAPI-Partner-ID": resolve_partner_id(),
    }


def is_aimlapi_inference_url(base_url: str) -> bool:
    """Return whether attribution headers may be sent to this endpoint."""
    hostname = (urlparse(base_url).hostname or "").lower()
    resolved_hostname = (
        urlparse(resolve_endpoints().inference_base_url).hostname or ""
    ).lower()
    return bool(
        hostname
        and hostname
        in {
            "api.aimlapi.com",
            "api-staging.aimlapi.com",
            resolved_hostname,
        }
    )
