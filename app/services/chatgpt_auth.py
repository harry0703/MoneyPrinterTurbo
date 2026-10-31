"""Official Sign in with ChatGPT for a local MoneyPrinterTurbo installation.

The application owns its dynamic registration; Codex CLI credentials and the
legacy device-flow grant are never imported into this flow.
"""

import base64
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass, field
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

from filelock import FileLock, Timeout as FileLockTimeout
import jwt
import requests

from app import paths
from app.utils.request_logging import trace_http_call

ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = ISSUER + "/api/accounts/authorize"
TOKEN_URL = ISSUER + "/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = "openid profile email offline_access resource.invoke " + PLAN_SCOPE
USAGE_URL = "https://chatgpt.com/settings/usage"
_lock = threading.RLock()
_attempts_lock = threading.RLock()
_attempts = {}
UI_LOCK_TIMEOUT = 0.5
AUTH_TIMEOUT = 90
TERMINAL_REFRESH_ERRORS = frozenset(
    {
        "invalid_grant",
        "invalid_refresh_token",
        "token_expired",
        "refresh_token_expired",
        "refresh_token_invalidated",
        "refresh_token_reused",
    }
)

ERROR_MESSAGES = {
    "storage_error": "Could not read ChatGPT credentials on this computer.",
    "network_error": "Could not connect to OpenAI. Check the network and try again.",
    "invalid_response": "OpenAI returned an invalid response.",
    "login_failed": "Could not complete ChatGPT sign-in. Start sign-in again.",
    "expired": "The sign-in request expired. Start sign-in again.",
    "changed": "The account changed or sign-in was cancelled. Start again.",
    "not_connected": "Connect your ChatGPT account in the OpenAI - ChatGPT (Native OAuth) settings first.",
    "reconnect": "Your ChatGPT session is no longer valid. Sign in again.",
    "incomplete": "OpenAI did not finish the response. No partial text was accepted.",
    "timeout": "The OpenAI - ChatGPT (Native OAuth) request timed out.",
    "empty": "OpenAI returned no text.",
    "rate_limit": "ChatGPT plan usage is limited. Review your usage settings.",
    "http_error": "OpenAI - ChatGPT (Native OAuth) returned HTTP {status}. Check the selected model and your account access.",
    "plan_required": "Sign-in succeeded, but permission to use your ChatGPT plan is not enabled.",
    "busy": "Another process is updating the ChatGPT session. Please retry shortly.",
    "ineligible": "ChatGPT plan usage is unavailable for this account or workspace. Choose another provider explicitly.",
    "preview_import": "No native OAuth preview credentials can be imported, or the destination already exists.",
}


class ChatGPTError(ValueError):
    """Public, credential-free diagnostics shared by the existing provider UI."""

    def __init__(self, key, **params):
        self.key = key if key.startswith("chatgpt.oauth.") else "chatgpt.oauth." + key
        self.params = params
        super().__init__(
            ERROR_MESSAGES[self.key.removeprefix("chatgpt.oauth.")].format(**params)
        )


def _credential_path():
    return paths.runtime_root() / "storage" / "auth" / "openai_chatgpt.bin"


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
        raise ChatGPTError("storage_error")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ChatGPTError("timeout")
    return remaining


@contextmanager
def _store_lock(*, timeout=UI_LOCK_TIMEOUT, deadline=None):
    # WebUI and API may be separate processes sharing the same runtime root.
    destination = _credential_path()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    wait_until = time.monotonic() + timeout
    if deadline is not None:
        wait_until = min(wait_until, deadline)
    if not _lock.acquire(timeout=max(0, wait_until - time.monotonic())):
        raise ChatGPTError("busy")
    try:
        file_lock = FileLock(str(destination) + ".lock")
        try:
            file_lock.acquire(timeout=max(0, wait_until - time.monotonic()))
        except FileLockTimeout:
            raise ChatGPTError("busy") from None
        try:
            yield
        finally:
            file_lock.release()
    finally:
        _lock.release()


def _validate_store(data):
    if (
        not isinstance(data, dict)
        or data.get("version") != 2
        or not isinstance(data.get("profiles"), dict)
        or not isinstance(data.get("revision"), int)
        or not isinstance(data.get("active"), str)
        or not isinstance(data.get("host_id"), str)
        or any(not isinstance(profile, dict) for profile in data["profiles"].values())
    ):
        raise ChatGPTError("storage_error")
    return data


def _load():
    try:
        return _validate_store(
            json.loads(_protect(_credential_path().read_bytes(), decrypt=True))
        )
    except FileNotFoundError:
        return {
            "version": 2,
            "host_id": "",
            "profiles": {},
            "active": "",
            "revision": 0,
        }
    except (OSError, ValueError, TypeError):
        raise ChatGPTError("storage_error") from None


def _save(data):
    target = _credential_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".chatgpt-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_protect(json.dumps(data).encode("utf-8")))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def import_preview_credentials():
    """Explicitly copy this PR's old v2 store; never modify device-flow data.

    The preview source is retained. Users can disconnect it in the Codex UI
    after import; original device-flow credentials cannot be converted to OAuth.
    """
    with _store_lock():
        if _credential_path().exists():
            raise ChatGPTError("preview_import")
        source = _credential_path().with_name("openai_codex.bin")
        try:
            data = _validate_store(
                json.loads(_protect(source.read_bytes(), decrypt=True))
            )
        except (OSError, ValueError, TypeError):
            raise ChatGPTError("preview_import") from None
        _save(data)


def _request_json(method, url, *, deadline=None, **kwargs):
    remaining = _remaining(deadline) if deadline is not None else 30
    try:
        # The opt-in request tracer covers the OpenAI sign-in exchange as well.
        # The token, its verifier and the refresh token live in the payload and
        # are redacted by the tracer; the request headers stay untraced.
        with trace_http_call(
            "REQUEST",
            requests.request,
            method,
            url,
            timeout=(min(10, remaining), min(30, remaining)),
            allow_redirects=False,
            **kwargs,
        ) as response:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError()
            if response.status_code != 200:
                if response.status_code >= 500:
                    raise ChatGPTError("network_error")
                error_code = payload.get("error")
                if isinstance(error_code, dict):
                    error_code = error_code.get("code")
                if (
                    isinstance(error_code, str)
                    and error_code in TERMINAL_REFRESH_ERRORS
                ):
                    error = ChatGPTError("reconnect")
                    error.oauth_error = error_code
                    raise error
                raise ChatGPTError("login_failed")
            return payload
    except requests.Timeout:
        raise ChatGPTError("timeout") from None
    except requests.RequestException:
        raise ChatGPTError("network_error") from None
    except (ValueError, TypeError) as exc:
        if isinstance(exc, ChatGPTError):
            raise
        raise ChatGPTError("invalid_response") from None


def _metadata(*, deadline=None):
    data = _request_json(
        "GET", ISSUER + "/.well-known/openid-configuration", deadline=deadline
    )
    if data.get("issuer") != ISSUER:
        raise ChatGPTError("invalid_response")
    return data


def _issuer_endpoint(url):
    parsed = urlsplit(url or "")
    if parsed.scheme != "https" or parsed.netloc != "auth.openai.com":
        raise ChatGPTError("invalid_response")
    return url


def _identity_keys(*, deadline=None):
    metadata = _metadata(deadline=deadline)
    return _request_json(
        "GET", _issuer_endpoint(metadata.get("jwks_uri")), deadline=deadline
    )


def _verify_identity(token, client_id, nonce=None, expected_subject=None, keys=None):
    try:
        if keys is None:
            keys = _identity_keys()
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256":
            raise ValueError()
        key = next(
            item for item in keys["keys"] if item.get("kid") == header.get("kid")
        )
        identity = jwt.decode(
            token,
            jwt.PyJWK.from_dict(key, algorithm="RS256").key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=30,
        )
        if not isinstance(identity.get("sub"), str) or not identity["sub"]:
            raise ValueError()
        if nonce is not None and not secrets.compare_digest(
            str(identity.get("nonce", "")), nonce
        ):
            raise ValueError()
        if expected_subject and identity["sub"] != expected_subject:
            raise ValueError()
        return identity
    except (jwt.PyJWTError, ValueError, KeyError, TypeError, StopIteration) as exc:
        if isinstance(exc, ChatGPTError):
            raise
        raise ChatGPTError("login_failed") from None


def _token_bundle(payload, client_id, identity, previous=None):
    previous = previous or {}
    try:
        access = payload.get("access_token", "")
        duration = float(payload.get("expires_in", 3600))
        scope = payload.get("scope")
        scopes = scope.split() if isinstance(scope, str) else previous.get("scopes", [])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError()
        if access and (
            not isinstance(access, str)
            or payload.get("token_type", "").lower() != "bearer"
        ):
            raise ValueError()
        refresh = payload.get("refresh_token", previous.get("refresh_token", ""))
        if not isinstance(refresh, str):
            raise ValueError()
        return {
            "client_id": client_id,
            "issuer": ISSUER,
            "subject": identity["sub"],
            "email": identity.get("email", ""),
            "id_token": payload.get("id_token", previous.get("id_token", "")),
            "access_token": access,
            "refresh_token": refresh,
            "scopes": scopes,
            "expires_at": time.time() + duration if access else 0,
        }
    except (ValueError, TypeError, KeyError):
        raise ChatGPTError("invalid_response") from None


def account_details():
    with _store_lock():
        data = _load()
        profile = data["profiles"].get(data["active"], {})
        return {
            "connected": bool(profile.get("subject") and profile.get("id_token")),
            "authorized": bool(
                profile.get("access_token") and PLAN_SCOPE in profile.get("scopes", [])
            ),
            "active": data["active"],
            "email": profile.get("email", ""),
            "revision": data["revision"],
            "profiles": [
                (key, (value.get("email") or "ChatGPT") + " · " + key[-8:])
                for key, value in data["profiles"].items()
            ],
        }


def account_status():
    return account_details()["authorized"]


def select_account(client_id):
    with _store_lock():
        data = _load()
        if client_id not in data["profiles"]:
            raise ChatGPTError("not_connected")
        if data["active"] != client_id:
            data["active"] = client_id
            data["revision"] += 1
            _save(data)


@dataclass
class _LoginAttempt:
    id: str
    client_id: str
    revision: int
    host_id: str
    subject: str = ""
    state: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    nonce: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    verifier: str = field(default_factory=lambda: secrets.token_urlsafe(48), repr=False)
    expires_at: float = field(default_factory=lambda: time.time() + 600)
    redirect_uri: str = ""
    status: str = "pending"
    error: ChatGPTError | None = None
    server: HTTPServer | None = field(default=None, repr=False)


def _complete_login(attempt, query):
    deadline = time.monotonic() + AUTH_TIMEOUT
    if not secrets.compare_digest(
        query.get("state", "").encode("utf-8"), attempt.state.encode("utf-8")
    ):
        raise ChatGPTError("login_failed")
    if attempt.status != "pending":
        raise ChatGPTError("changed")
    if time.time() >= attempt.expires_at:
        raise ChatGPTError("expired")
    if query.get("error"):
        raise ChatGPTError("login_failed")
    client_id = query.get("client_id", attempt.client_id)
    if not client_id or client_id == "dynamic_agent_client" or not query.get("code"):
        raise ChatGPTError("login_failed")
    if attempt.client_id != "dynamic_agent_client" and client_id != attempt.client_id:
        raise ChatGPTError("login_failed")
    with _store_lock():
        data = _load()
        if data["revision"] != attempt.revision:
            raise ChatGPTError("changed")
        # Retain the issued registration even if the code exchange needs retrying.
        data["profiles"].setdefault(client_id, {"client_id": client_id})
        data["last_registration"] = client_id
        _save(data)
    verification_keys = _identity_keys(deadline=deadline)
    payload = _request_json(
        "POST",
        TOKEN_URL,
        deadline=deadline,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": query["code"],
            "code_verifier": attempt.verifier,
            "redirect_uri": attempt.redirect_uri,
            "resource": RESOURCE,
        },
    )
    identity = _verify_identity(
        payload.get("id_token", ""),
        client_id,
        attempt.nonce,
        attempt.subject,
        keys=verification_keys,
    )
    profile = _token_bundle(payload, client_id, identity)
    with _store_lock(timeout=AUTH_TIMEOUT):
        data = _load()
        if data["revision"] != attempt.revision or attempt.status != "pending":
            raise ChatGPTError("changed")
        if time.time() >= attempt.expires_at:
            raise ChatGPTError("expired")
        data["profiles"][client_id] = profile
        data["active"] = client_id
        data["revision"] += 1
        _save(data)
        attempt.status = "complete"


class _CallbackHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_):
        pass  # Callback URLs contain authorization codes; never log them.

    def do_GET(self):
        attempt = self.server.attempt
        parsed = urlsplit(self.path)
        if parsed.path != "/auth/callback":
            self.send_error(404)
            return
        try:
            query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=20)
        except ValueError:
            self.send_error(400, "Invalid authorization callback")
            return
        valid_state = len(query.get("state", [])) == 1 and secrets.compare_digest(
            query["state"][0].encode("utf-8"), attempt.state.encode("utf-8")
        )
        if not valid_state:
            self.send_error(400, "Invalid authorization state")
            return
        try:
            if any(len(values) != 1 for values in query.values()):
                raise ChatGPTError("login_failed")
            _complete_login(attempt, {key: values[0] for key, values in query.items()})
            message = "ChatGPT sign-in completed. Return to MoneyPrinterTurbo."
            status = 200
        except ChatGPTError as exc:
            attempt.error = exc
            attempt.status = "failed"
            message, status = (
                "Sign-in was not completed. Return to MoneyPrinterTurbo.",
                400,
            )
        except Exception:
            attempt.error = ChatGPTError("login_failed")
            attempt.status = "failed"
            message, status = (
                "Sign-in was not completed. Return to MoneyPrinterTurbo.",
                400,
            )
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _listen(attempt):
    try:
        while attempt.status == "pending" and time.time() < attempt.expires_at:
            attempt.server.handle_request()
        if attempt.status == "pending":
            attempt.error = ChatGPTError("expired")
            attempt.status = "failed"
    finally:
        attempt.server.server_close()


def begin_login(*, new_account=False, enable_plan=False):
    with _store_lock():
        data = _load()
        data["host_id"] = data.get("host_id") or "urn:uuid:" + str(uuid4())
        profile_id = (
            "" if new_account else data["active"] or data.get("last_registration", "")
        )
        profile = data["profiles"].get(profile_id, {})
        _save(data)
        attempt = _LoginAttempt(
            str(uuid4()),
            profile_id or "dynamic_agent_client",
            data["revision"],
            data["host_id"],
            profile.get("subject", ""),
        )
    try:
        server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    except OSError:
        raise ChatGPTError("login_failed") from None
    server.timeout = 0.5
    server.attempt = attempt
    attempt.server = server
    attempt.redirect_uri = f"http://127.0.0.1:{server.server_port}/auth/callback"
    params = {
        "client_id": attempt.client_id,
        "ext_agent_host_id": attempt.host_id,
        "response_type": "code",
        "redirect_uri": attempt.redirect_uri,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": attempt.state,
        "nonce": attempt.nonce,
        "code_challenge_method": "S256",
        "code_challenge": base64.urlsafe_b64encode(
            hashlib.sha256(attempt.verifier.encode()).digest()
        )
        .decode()
        .rstrip("="),
    }
    if attempt.client_id == "dynamic_agent_client":
        params["agent_name_hint"] = "MoneyPrinterTurbo"
    elif profile.get("email"):
        params["login_hint"] = profile["email"]
    if enable_plan:
        params["prompt"] = "consent"
    with _attempts_lock:
        # Finished attempts have no credentials and need not outlive the UI poll.
        for key in list(_attempts):
            if _attempts[key].status != "pending":
                _attempts.pop(key)
        _attempts[attempt.id] = attempt
    threading.Thread(target=_listen, args=(attempt,), daemon=True).start()
    return {
        "id": attempt.id,
        "authorize_url": AUTHORIZE_URL + "?" + urlencode(params),
        "expires_at": attempt.expires_at,
    }


def poll_login(flow):
    with _attempts_lock:
        attempt = _attempts.get(flow["id"])
        if not attempt:
            raise ChatGPTError("expired")
        if attempt.error:
            raise attempt.error
        return attempt.status == "complete"


def cancel_login(flow):
    with _attempts_lock:
        attempt = _attempts.get(flow["id"])
        if attempt and attempt.status == "pending":
            attempt.status = "cancelled"
            attempt.error = ChatGPTError("changed")


def _clear_tokens(data, profile):
    for name in ("access_token", "refresh_token", "id_token"):
        profile.pop(name, None)
    data["revision"] += 1
    _save(data)


def _selected_credentials(data, session=None):
    selected = (data["active"], data["revision"])
    if session is not None and session != selected:
        raise ChatGPTError("changed")
    profile = data["profiles"].get(data["active"], {})
    if not profile.get("id_token"):
        raise ChatGPTError("not_connected")
    if PLAN_SCOPE not in profile.get("scopes", []):
        raise ChatGPTError("plan_required")
    if not profile.get("access_token"):
        raise ChatGPTError("reconnect")
    return profile, selected


def credentials(*, force=False, expected=None, session=None, deadline=None):
    deadline = deadline if deadline is not None else time.monotonic() + AUTH_TIMEOUT
    with _store_lock(timeout=_remaining(deadline), deadline=deadline):
        data = _load()
        profile, selected = _selected_credentials(data, session)
        if force and expected and profile["access_token"] != expected:
            return dict(profile), selected
        if not force and profile["expires_at"] > time.time() + 60:
            return dict(profile), selected
        if not profile.get("refresh_token"):
            _clear_tokens(data, profile)
            raise ChatGPTError("reconnect")
        previous_access = profile["access_token"]

    # Discovery and JWKS do not mutate credentials. Fetch them without blocking
    # account controls, before consuming a rotating refresh token.
    verification_keys = _identity_keys(deadline=deadline)
    with _store_lock(timeout=_remaining(deadline), deadline=deadline):
        data = _load()
        profile, selected = _selected_credentials(data, selected)
        # Another process may have refreshed while we fetched keys or waited.
        if profile["access_token"] != previous_access or (
            not force and profile["expires_at"] > time.time() + 60
        ):
            return dict(profile), selected
        if not profile.get("refresh_token"):
            _clear_tokens(data, profile)
            raise ChatGPTError("reconnect")
        try:
            payload = _request_json(
                "POST",
                TOKEN_URL,
                deadline=deadline,
                data={
                    "grant_type": "refresh_token",
                    "client_id": profile["client_id"],
                    "refresh_token": profile["refresh_token"],
                    "resource": RESOURCE,
                },
            )
        except ChatGPTError as error:
            if getattr(error, "oauth_error", None) in TERMINAL_REFRESH_ERRORS:
                _clear_tokens(data, profile)
            raise
        try:
            identity = {"sub": profile["subject"], "email": profile.get("email", "")}
            if payload.get("id_token"):
                identity = _verify_identity(
                    payload["id_token"],
                    profile["client_id"],
                    expected_subject=profile["subject"],
                    keys=verification_keys,
                )
            renewed = _token_bundle(payload, profile["client_id"], identity, profile)
        except ChatGPTError:
            _clear_tokens(data, profile)
            raise
        # Persist the rotated token even if the caller's inference budget has
        # just expired; discarding it here would lose the renewable session.
        data["profiles"][data["active"]] = renewed
        _save(data)
        if PLAN_SCOPE not in renewed["scopes"]:
            raise ChatGPTError("plan_required")
        if not renewed["access_token"]:
            raise ChatGPTError("reconnect")
        return dict(renewed), selected


def assert_session(session, *, deadline=None):
    wait = _remaining(deadline) if deadline is not None else UI_LOCK_TIMEOUT
    with _store_lock(timeout=wait, deadline=deadline):
        data = _load()
        if (data["active"], data["revision"]) != session:
            raise ChatGPTError("changed")


def disconnect():
    """Revoke the active session; keep its registration and the host identity."""
    deadline = time.monotonic() + AUTH_TIMEOUT
    with _store_lock():
        data = _load()
        profile = data["profiles"].get(data["active"], {})
        confirmed = True
        if profile.get("refresh_token"):
            try:
                endpoint = _issuer_endpoint(
                    _metadata(deadline=deadline).get("revocation_endpoint")
                )
                with trace_http_call(
                    "POST",
                    requests.post,
                    endpoint,
                    data={
                        "token": profile["refresh_token"],
                        "token_type_hint": "refresh_token",
                        "client_id": profile["client_id"],
                    },
                    timeout=min(30, _remaining(deadline)),
                    allow_redirects=False,
                ) as response:
                    confirmed = response.status_code == 200
            except (ChatGPTError, requests.RequestException):
                confirmed = False
        for name in ("access_token", "refresh_token", "id_token"):
            profile.pop(name, None)
        data["revision"] += 1
        _save(data)
        return confirmed
