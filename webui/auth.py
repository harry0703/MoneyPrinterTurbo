import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path


AUTH_QUERY_PARAM = "mpt_auth_token"
_DEFAULT_SESSION_FILE = (
    Path(__file__).resolve().parent.parent / "storage" / "webui-auth-sessions.json"
)
_SESSION_LOCK = threading.RLock()


def _get_env(name: str) -> str:
    return (os.getenv(name, "") or "").strip()


def _matches_password(candidate: str, expected: str) -> bool:
    if not candidate or not expected:
        return False
    if expected.startswith("sha256:"):
        digest = expected.split(":", 1)[1]
        return hashlib.sha256(candidate.encode("utf-8")).hexdigest() == digest
    return secrets.compare_digest(candidate, expected)


def is_auth_enabled() -> bool:
    username = _get_env("MPT_WEBUI_USERNAME")
    password = _get_env("MPT_WEBUI_PASSWORD")
    return bool(username and password)


def authenticate(username: str, password: str) -> bool:
    if not is_auth_enabled():
        return False

    configured_username = _get_env("MPT_WEBUI_USERNAME")
    configured_password = _get_env("MPT_WEBUI_PASSWORD")

    return secrets.compare_digest(username or "", configured_username) and _matches_password(
        password or "", configured_password
    )


def _session_file() -> Path:
    configured_path = _get_env("MPT_WEBUI_SESSION_FILE")
    return Path(configured_path).expanduser() if configured_path else _DEFAULT_SESSION_FILE


def _credential_fingerprint() -> str:
    """Bind persistent tokens to the current configured credentials."""
    value = f"{_get_env('MPT_WEBUI_USERNAME')}\0{_get_env('MPT_WEBUI_PASSWORD')}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_sessions() -> dict:
    path = _session_file()
    try:
        with path.open("r", encoding="utf-8") as session_file:
            payload = json.load(session_file)
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def _write_sessions(sessions: dict) -> None:
    path = _session_file()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Replace the file atomically so a process restart or simultaneous login
    # cannot leave a partially-written token database behind.
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            json.dump(sessions, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)

        try:
            os.chmod(temporary_path, 0o600)
        except OSError:
            # Windows and some mounted filesystems may not support Unix modes.
            pass
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def create_persistent_session(username: str) -> str:
    """Create a non-expiring bearer token for a successfully authenticated user.

    Streamlit's built-in session state is tied to one browser websocket and is
    lost after a refresh. The WebUI stores only a hash of this random token on
    disk; the raw token is kept by the browser in the auth query parameter. It
    has no expiry, and changing either configured credential invalidates all
    existing tokens through the credential fingerprint.
    """
    if not is_auth_enabled() or not secrets.compare_digest(
        username or "", _get_env("MPT_WEBUI_USERNAME")
    ):
        raise ValueError("cannot create a persistent session for unauthenticated user")

    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    record = {
        "username": username,
        "credential_fingerprint": _credential_fingerprint(),
        "created_at": time.time(),
    }

    with _SESSION_LOCK:
        sessions = _read_sessions()
        sessions[token_hash] = record
        _write_sessions(sessions)

    return raw_token


def validate_persistent_session(token: str) -> bool:
    """Validate a persistent token without imposing an inactivity timeout."""
    if not is_auth_enabled() or not token:
        return False

    token_hash = hashlib.sha256(str(token).encode("utf-8")).hexdigest()
    with _SESSION_LOCK:
        record = _read_sessions().get(token_hash)

    if not isinstance(record, dict):
        return False
    if record.get("credential_fingerprint") != _credential_fingerprint():
        return False

    configured_username = _get_env("MPT_WEBUI_USERNAME")
    return secrets.compare_digest(
        str(record.get("username", "")), configured_username
    )
