"""Client for the authenticated host-side Codex OAuth bridge."""

import re
from typing import Any

import requests


DEFAULT_TIMEOUT_SECONDS = 300
MIN_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 900
MAX_OUTPUT_BYTES = 128 * 1024

_URL_USERINFO_RE = re.compile(r"((?:https?|wss?)://)([^/\s?#@]*:[^/\s?#@]*@)", re.IGNORECASE)


class CodexBridgeError(RuntimeError):
    """Raised when the local Codex bridge cannot provide valid output."""


def normalize_timeout(value: object) -> int:
    """Return a bridge-safe timeout, defaulting invalid values to five minutes."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_TIMEOUT_SECONDS
    if isinstance(value, float) and not value.is_integer():
        return DEFAULT_TIMEOUT_SECONDS
    return min(MAX_TIMEOUT_SECONDS, max(MIN_TIMEOUT_SECONDS, int(value)))


def _bridge_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _safe_message(message: object, bridge_token: str = "") -> str:
    safe_message = _URL_USERINFO_RE.sub(r"\1***:***@", str(message))
    if bridge_token:
        safe_message = safe_message.replace(bridge_token, "***")
    return safe_message


def _response_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except (ValueError, requests.JSONDecodeError):
        raise CodexBridgeError("Codex bridge returned an invalid response.") from None


def _remote_error(response: requests.Response, bridge_token: str) -> CodexBridgeError:
    payload = _response_json(response)
    error = payload.get("error") if isinstance(payload, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    if isinstance(message, str) and message.strip():
        return CodexBridgeError(_safe_message(message, bridge_token))
    return CodexBridgeError("Codex bridge returned an invalid response.")


def health(base_url: str, timeout_seconds: int = 10) -> dict:
    """Get the bridge health contract without sending credentials."""
    try:
        response = requests.get(
            _bridge_url(base_url, "/health"), timeout=(10, timeout_seconds)
        )
    except requests.Timeout:
        raise CodexBridgeError("Codex bridge request timed out.") from None
    except requests.RequestException:
        raise CodexBridgeError("Codex bridge request failed.") from None

    if not response.ok:
        raise _remote_error(response, "")
    payload = _response_json(response)
    if (
        not isinstance(payload, dict)
        or payload.get("status") != "ok"
        or not isinstance(payload.get("codex_available"), bool)
    ):
        raise CodexBridgeError("Codex bridge returned an invalid response.")
    return payload


def generate(
    base_url: str,
    bridge_token: str,
    instructions: str,
    input_text: str,
    model_name: str = "",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Generate narration through the OAuth-backed host bridge."""
    if not isinstance(bridge_token, str) or not bridge_token.strip():
        raise CodexBridgeError("Codex bridge token is required.")
    timeout = normalize_timeout(timeout_seconds)
    try:
        response = requests.post(
            _bridge_url(base_url, "/v1/generate"),
            headers={"Authorization": f"Bearer {bridge_token}"},
            json={
                "instructions": instructions,
                "input": input_text,
                "model": model_name,
                "timeout_seconds": timeout,
            },
            timeout=(10, timeout),
        )
    except requests.Timeout:
        raise CodexBridgeError("Codex bridge request timed out.") from None
    except requests.RequestException:
        raise CodexBridgeError("Codex bridge request failed.") from None

    if not response.ok:
        raise _remote_error(response, bridge_token)
    payload = _response_json(response)
    output_text = payload.get("output_text") if isinstance(payload, dict) else None
    if not isinstance(output_text, str) or not output_text.strip():
        raise CodexBridgeError("Codex bridge returned an invalid response.")
    try:
        output_size = len(output_text.encode("utf-8"))
    except UnicodeEncodeError:
        raise CodexBridgeError("Codex bridge returned an invalid response.") from None
    if output_size > MAX_OUTPUT_BYTES:
        raise CodexBridgeError("Codex bridge returned an invalid response.")
    return output_text
