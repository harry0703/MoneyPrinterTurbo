import hashlib
import os
import secrets


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
