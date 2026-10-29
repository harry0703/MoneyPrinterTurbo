"""Device authorization and shared Codex Responses transport.

The protocol is also used by Jarvys. This is an independent Python implementation;
credentials belong to this application and never touch the user's Codex login.
"""

import base64
import ctypes
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import math
import os
import re
from pathlib import Path
import tempfile
import threading
import time
from uuid import uuid4

from filelock import FileLock, Timeout as FileLockTimeout
import requests

from app import paths

ISSUER = "https://auth.openai.com"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
VERIFY_URL = ISSUER + "/codex/device"
TOKEN_URL = ISSUER + "/oauth/token"
RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
_lock = threading.RLock()
_generation = 0
_file_locks = {}
_image_diagnostics = ContextVar("codex_image_diagnostics", default=None)
ERROR_MESSAGES = {
    "storage_error": "Could not read Codex credentials. Disconnect and sign in again on this computer.",
    "network_error": "Could not connect to OpenAI. Check the network and try again.",
    "invalid_response": "OpenAI returned an invalid response.",
    "login_failed": "OpenAI sign-in failed. Check that device-code sign-in is enabled for your account.",
    "expired": "The authorization code expired. Start sign-in again.",
    "changed": "The account changed or sign-in was cancelled. Start again.",
    "not_connected": "Connect your ChatGPT account in the OpenAI - Codex settings first.",
    "reconnect": "Your Codex session is no longer valid. Disconnect and sign in again.",
    "incomplete": "OpenAI did not finish the response. No partial text was accepted.",
    "timeout": "The OpenAI - Codex request timed out.",
    "empty": "OpenAI returned no text.",
    "rate_limit": "Your Codex usage limit was reached. Wait before trying again.",
    "http_error": "OpenAI - Codex returned HTTP {status}. Check the selected model and your account access.",
}


class CodexError(ValueError):
    """Sanitized error suitable for UI and logs (never a raw HTTP body)."""

    def __init__(self, key, **params):
        self.key = key
        self.params = params
        super().__init__(
            ERROR_MESSAGES.get(key.removeprefix("codex.oauth."), key).format(**params)
        )


def _credential_path():
    return paths.runtime_root() / "storage" / "auth" / "openai_codex.bin"


@dataclass(frozen=True)
class CodexSessionBinding:
    """Identity of one authorization, never a token or a displayable account."""

    account_id: str = field(repr=False)
    revision: str = field(repr=False)


@contextmanager
def _store_guard():
    # Use the same reentrant lock instance for nested credential operations.
    # A file lock coordinates different API/WebUI processes sharing MPT_HOME.
    with _lock:
        path = _credential_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        name = str(path) + ".lock"
        lock = _file_locks.setdefault(name, FileLock(name, timeout=30))
        try:
            lock.acquire()
        except FileLockTimeout:
            raise CodexError("codex.oauth.timeout") from None
        try:
            yield
        finally:
            lock.release()


@contextmanager
def capture_image_diagnostics():
    """Opt-in acceptance evidence; only explicitly selected metadata is kept."""
    records = []
    token = _image_diagnostics.set(records)
    try:
        yield records
    finally:
        _image_diagnostics.reset(token)


def _record_image_diagnostic(**fields):
    records = _image_diagnostics.get()
    if records is None:
        return
    allowed = {
        "kind",
        "event",
        "attempt",
        "status",
        "request_id",
        "requested_model",
        "response_id",
        "response_model",
        "tool_id",
        "result_bytes",
        "error_type",
        "error_code",
        "error_param",
        "reason",
    }
    record = {}
    for key, value in fields.items():
        if key not in allowed:
            continue
        if isinstance(value, int) and not isinstance(value, bool):
            record[key] = value
        elif (
            isinstance(value, str)
            and not value.startswith(("sk-", "eyJ"))
            and re.fullmatch(r"[\w./:-]{1,160}", value, re.ASCII)
        ):
            record[key] = value
    if record:
        records.append(record)


def _image_response_diagnostic(response, payload, attempt, deadline):
    headers = response.headers
    _record_image_diagnostic(
        kind="http",
        attempt=attempt + 1,
        status=response.status_code,
        requested_model=payload.get("model"),
        request_id=headers.get("x-request-id") or headers.get("openai-request-id"),
    )
    if response.status_code == 200 or _image_diagnostics.get() is None:
        return
    # Never retain the provider's free-text body. A fixed classification records
    # the specific compatibility failure reported by the maintainer.
    try:
        body = bytearray()
        for chunk in response.iter_content(chunk_size=4096):
            if time.monotonic() >= deadline or len(body) + len(chunk) > 64 * 1024:
                return
            body.extend(chunk)
        error = json.loads(body).get("error", {})
        if not isinstance(error, dict):
            return
        values = {
            "error_type": {
                "invalid_request_error",
                "server_error",
                "insufficient_quota",
            },
            "error_code": {
                "model_not_found",
                "rate_limit_exceeded",
                "insufficient_quota",
                "invalid_request_error",
                "content_policy_violation",
            },
            "error_param": {"tool_choice", "tools", "model", "input"},
        }
        fields = {
            key: error.get(key.removeprefix("error_"))
            if error.get(key.removeprefix("error_")) in allowed
            else "other"
            for key, allowed in values.items()
        }
        fields["reason"] = (
            "tool_choice_missing_image_tool"
            if error.get("message")
            == "Tool choice 'image_generation' must be specified with 'tools' parameter."
            else "provider_rejection"
        )
        _record_image_diagnostic(kind="provider_error", **fields)
    except (ValueError, AttributeError, TypeError, requests.RequestException):
        pass


def _protect(data, decrypt=False):
    if os.name != "nt":
        return data
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    operation.restype = wintypes.BOOL
    if not operation(
        ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)
    ):
        raise CodexError("codex.oauth.storage_error")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


def _load():
    try:
        raw = _credential_path().read_bytes()
    except FileNotFoundError:
        return None
    try:
        result = json.loads(_protect(raw, decrypt=True))
        if not isinstance(result, dict) or not all(
            isinstance(result.get(k), str) and result[k]
            for k in ("access_token", "refresh_token", "account_id")
        ):
            raise ValueError()
        if not math.isfinite(float(result["expires_at"])):
            raise ValueError()
        revision = result.get("session_revision")
        if revision is not None and (
            not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{32}", revision)
        ):
            raise ValueError()
        return result
    except (ValueError, KeyError, TypeError):
        raise CodexError("codex.oauth.storage_error") from None


def _save(bundle):
    destination = _credential_path()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    bundle = dict(bundle)
    bundle.setdefault("session_revision", uuid4().hex)
    data = _protect(json.dumps(bundle).encode("utf-8"))
    fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".codex-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _bound_current(binding=None):
    current = _load()
    if not current:
        raise CodexError(
            "codex.oauth.changed"
            if binding is not None
            else "codex.oauth.not_connected"
        )
    if "session_revision" not in current:
        # One-time migration is serialized and atomic, without a new login.
        _save(current)
        current = _load()
    if binding is not None and (
        current["account_id"] != binding.account_id
        or current["session_revision"] != binding.revision
    ):
        raise CodexError("codex.oauth.changed")
    return current


def capture_session_binding():
    with _store_guard():
        current = _bound_current()
        return CodexSessionBinding(current["account_id"], current["session_revision"])


def assert_session_binding(binding):
    if not isinstance(binding, CodexSessionBinding):
        raise CodexError("codex.oauth.changed")
    with _store_guard():
        _bound_current(binding)


def authorization_generation():
    with _lock:
        return _generation


def account_status():
    with _store_guard():
        return bool(_load())


def disconnect():
    global _generation
    with _store_guard():
        _generation += 1
        _credential_path().unlink(missing_ok=True)


def _post(url, *, timeout=30, **kwargs):
    try:
        return requests.post(url, timeout=timeout, allow_redirects=False, **kwargs)
    except requests.RequestException:
        raise CodexError("codex.oauth.network_error") from None


def _json(response):
    try:
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError()
        return payload
    except ValueError:
        raise CodexError("codex.oauth.invalid_response") from None


def request_device_code():
    generation = authorization_generation()
    with _store_guard():
        current = _load()
        revision = current.get("session_revision") if current else None
        if current and revision is None:
            current = _bound_current()
            revision = current["session_revision"]
    with _post(
        ISSUER + "/api/accounts/deviceauth/usercode", json={"client_id": CLIENT_ID}
    ) as response:
        if response.status_code != 200:
            raise CodexError("codex.oauth.login_failed")
        payload = _json(response)
    device_id = payload.get("device_auth_id")
    user_code = payload.get("user_code") or payload.get("usercode")
    try:
        interval = float(payload.get("interval", 5))
        if not math.isfinite(interval) or interval < 0 or interval > 900:
            raise ValueError()
    except (TypeError, ValueError):
        raise CodexError("codex.oauth.invalid_response") from None
    if (
        not isinstance(device_id, str)
        or not device_id
        or not isinstance(user_code, str)
        or not user_code
    ):
        raise CodexError("codex.oauth.invalid_response")
    return dict(
        device_auth_id=device_id,
        user_code=user_code,
        interval=max(interval + 3, 5),
        expires_at=time.time() + 900,
        generation=generation,
        session_revision=revision,
    )


def _claims(token):
    if not isinstance(token, str):
        return {}
    try:
        encoded = token.split(".")[1]
        claims = json.loads(
            base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        )
        return claims if isinstance(claims, dict) else {}
    except (ValueError, IndexError, TypeError):
        return {}


def _bundle(payload, previous=None):
    previous = previous or {}
    access = payload.get("access_token")
    refresh = payload.get("refresh_token") or previous.get("refresh_token")
    account_id = ""
    for token in (payload.get("id_token", ""), access):
        auth = _claims(token).get("https://api.openai.com/auth", {})
        if isinstance(auth, dict):
            account_id = auth.get("chatgpt_account_id", "") or account_id
    account_id = account_id or previous.get("account_id")
    try:
        duration = float(payload.get("expires_in", 3600))
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise CodexError("codex.oauth.invalid_response") from None
    if not all(
        isinstance(value, str) and value for value in (access, refresh, account_id)
    ):
        raise CodexError("codex.oauth.invalid_response")
    return dict(
        access_token=access,
        refresh_token=refresh,
        account_id=account_id,
        expires_at=time.time() + duration,
        session_revision=previous.get("session_revision") or uuid4().hex,
    )


def poll_login(flow):
    """One bounded poll; pending is False, committed authorization is True."""
    if time.time() >= flow["expires_at"]:
        raise CodexError("codex.oauth.expired")
    with _post(
        ISSUER + "/api/accounts/deviceauth/token",
        json={
            "device_auth_id": flow["device_auth_id"],
            "user_code": flow["user_code"],
        },
    ) as response:
        if response.status_code in (403, 404):
            return False
        if response.status_code in (400, 410):
            raise CodexError("codex.oauth.expired")
        if response.status_code != 200:
            raise CodexError("codex.oauth.login_failed")
        payload = _json(response)
    code, verifier = payload.get("authorization_code"), payload.get("code_verifier")
    if not all(isinstance(v, str) and v for v in (code, verifier)):
        raise CodexError("codex.oauth.invalid_response")
    with _store_guard():
        current = _load()
        if "session_revision" not in flow or flow["session_revision"] != (
            current.get("session_revision") if current else None
        ):
            raise CodexError("codex.oauth.changed")
        if flow["generation"] != _generation:
            raise CodexError("codex.oauth.changed")
        with _post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": ISSUER + "/deviceauth/callback",
            },
        ) as response:
            if response.status_code != 200:
                raise CodexError("codex.oauth.login_failed")
            bundle = _bundle(_json(response))
        if time.time() >= flow["expires_at"]:
            raise CodexError("codex.oauth.expired")
        _save(bundle)
        # Invalidate other outstanding device flows when this account wins.
        _advance_generation()
    return True


def _advance_generation():
    global _generation
    _generation += 1


def _credentials(force=False, expected=None, generation=None, session=None):
    with _store_guard():
        if generation is not None and generation != _generation:
            raise CodexError("codex.oauth.changed")
        current = _bound_current(session)
        # A concurrent refresh already replaced the rejected access token.
        if force and expected and current["access_token"] != expected:
            return current
        if not force and current["expires_at"] > time.time() + 60:
            return current
        with _post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": current["refresh_token"],
            },
        ) as response:
            if response.status_code != 200:
                raise CodexError("codex.oauth.reconnect")
            renewed = _bundle(_json(response), current)
        if renewed["account_id"] != current["account_id"]:
            raise CodexError("codex.oauth.changed")
        _save(renewed)
        return renewed


def request_image(payload, *, generation, session, timeout, read_result):
    """Send an image request with the application's existing credentials.

    Only an explicit 401 permits another POST. The caller owns image parsing;
    credentials and the serialized refresh stay inside this service.
    """
    if not isinstance(session, CodexSessionBinding):
        raise CodexError("codex.oauth.changed")
    deadline = time.monotonic() + timeout
    credentials = _credentials(generation=generation, session=session)
    for attempt in range(2):
        if generation != authorization_generation():
            raise CodexError("codex.oauth.changed")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CodexError("codex.oauth.timeout")
        try:
            # Keep account mutation serialized until the authenticated POST has
            # been sent. Release before consuming SSE so another process can
            # disconnect, and the post-result binding check can reject it.
            with _store_guard():
                if generation != authorization_generation():
                    raise CodexError("codex.oauth.changed")
                _bound_current(session)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CodexError("codex.oauth.timeout")
                if (
                    credentials.get("account_id") != session.account_id
                    or credentials.get("session_revision") != session.revision
                ):
                    raise CodexError("codex.oauth.changed")
                response = _post(
                    RESPONSES_URL,
                    timeout=(min(15, remaining), remaining),
                    stream=True,
                    headers={
                        "Authorization": "Bearer " + credentials["access_token"],
                        "chatgpt-account-id": credentials["account_id"],
                        "Accept": "text/event-stream",
                        "OpenAI-Beta": "responses=experimental",
                        "originator": "moneyprinterturbo",
                        "User-Agent": "MoneyPrinterTurbo/1.3.9",
                    },
                    json=payload,
                )
            with response:
                _image_response_diagnostic(response, payload, attempt, deadline)
                if response.status_code == 401 and attempt == 0:
                    credentials = _credentials(
                        force=True,
                        expected=credentials["access_token"],
                        generation=generation,
                        session=session,
                    )
                    continue
                if response.status_code == 429:
                    raise CodexError("codex.oauth.rate_limit")
                if response.status_code != 200:
                    raise CodexError(
                        "codex.oauth.http_error", status=response.status_code
                    )
                result = read_result(response, deadline)
                assert_session_binding(session)
                if generation != authorization_generation():
                    raise CodexError("codex.oauth.changed")
                return result
        except requests.RequestException:
            raise CodexError("codex.oauth.network_error") from None
    raise CodexError("codex.oauth.reconnect")


def _final_text(payload):
    if payload.get("status") != "completed":
        raise CodexError("codex.oauth.incomplete")
    pieces = []
    for item in payload.get("output", []):
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text" and isinstance(
                    part.get("text"), str
                ):
                    pieces.append(part["text"])
    result = "\n".join(pieces).strip()
    if not result:
        raise CodexError("codex.oauth.empty")
    return result


def _read_stream(response, deadline):
    data = []
    size = 0
    for line in response.iter_lines(decode_unicode=True):
        if time.monotonic() >= deadline:
            raise CodexError("codex.oauth.timeout")
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        size += len(line)
        if size > 8 * 1024 * 1024:
            raise CodexError("codex.oauth.invalid_response")
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line and data:
            result = _stream_event("\n".join(data))
            data = []
            if result is not None:
                return result
    if data:
        result = _stream_event("\n".join(data))
        if result is not None:
            return result
    raise CodexError("codex.oauth.incomplete")


def _stream_event(data):
    if data == "[DONE]":
        return None
    try:
        event = json.loads(data)
        if not isinstance(event, dict):
            raise ValueError()
        kind = event.get("type")
        if kind in ("error", "response.failed", "response.incomplete"):
            raise CodexError("codex.oauth.incomplete")
        if kind == "response.completed":
            return _final_text(event.get("response", {}))
    except CodexError:
        raise
    except (ValueError, TypeError, AttributeError):
        raise CodexError("codex.oauth.invalid_response") from None
    return None


def generate_text(prompt, model, timeout=300):
    deadline = time.monotonic() + timeout
    generation = authorization_generation()
    credentials = _credentials(generation=generation)
    for attempt in range(2):
        if generation != authorization_generation():
            raise CodexError("codex.oauth.changed")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CodexError("codex.oauth.timeout")
        try:
            with _post(
                RESPONSES_URL,
                timeout=(min(15, remaining), remaining),
                stream=True,
                headers={
                    "Authorization": "Bearer " + credentials["access_token"],
                    "chatgpt-account-id": credentials["account_id"],
                    "Accept": "text/event-stream",
                    "OpenAI-Beta": "responses=experimental",
                    "originator": "moneyprinterturbo",
                    "User-Agent": "MoneyPrinterTurbo/1.3.9",
                },
                json={
                    "model": model,
                    "store": False,
                    "stream": True,
                    "instructions": "Follow the requested language and output format exactly. Return only the requested text.",
                    "input": [
                        {
                            "role": "user",
                            "content": [{"type": "input_text", "text": prompt}],
                        }
                    ],
                },
            ) as response:
                if response.status_code == 401 and attempt == 0:
                    credentials = _credentials(
                        force=True,
                        expected=credentials["access_token"],
                        generation=generation,
                    )
                    continue
                if response.status_code == 429:
                    raise CodexError("codex.oauth.rate_limit")
                if response.status_code in (401, 403):
                    raise CodexError("codex.oauth.reconnect")
                if response.status_code != 200:
                    raise CodexError(
                        "codex.oauth.http_error", status=response.status_code
                    )
                response.encoding = "utf-8"
                text = _read_stream(response, deadline)
                if generation != authorization_generation():
                    raise CodexError("codex.oauth.changed")
                return text
        except requests.RequestException:
            raise CodexError("codex.oauth.network_error") from None
    raise CodexError("codex.oauth.reconnect")
