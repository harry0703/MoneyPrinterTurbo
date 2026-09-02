"""Parse the optional link back to the local Independent Media console."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import unquote, urlsplit


NavigationState = Literal["ENABLED", "DISABLED", "IGNORED"]


@dataclass(frozen=True)
class ConsoleNavigation:
    state: NavigationState
    url: str | None = None
    warning_code: str | None = None


def _ignored() -> ConsoleNavigation:
    return ConsoleNavigation(state="IGNORED", warning_code="INVALID_CONSOLE_URL")


def parse_console_navigation(raw: str | None) -> ConsoleNavigation:
    """Accept only explicit-port HTTP URLs pointing at the local loopback."""
    if raw is None or not raw.strip():
        return ConsoleNavigation(state="DISABLED")

    candidate = raw.strip()
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError:
        return _ignored()

    if (
        parsed.scheme.lower() != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port is None
        or not 1 <= port <= 65535
    ):
        return _ignored()

    hostname = parsed.hostname.lower()
    if hostname == "::1":
        closing_bracket = parsed.netloc.find("]")
        explicit_port = (
            parsed.netloc.startswith("[::1]")
            and closing_bracket >= 0
            and parsed.netloc[closing_bracket + 1 :].startswith(":")
        )
        authority = f"[::1]:{port}"
    else:
        explicit_port = parsed.netloc.rpartition(":")[2].isdigit()
        authority = f"{hostname}:{port}"

    decoded_path = unquote(parsed.path)
    if (
        not explicit_port
        or "\\" in parsed.path
        or "\\" in decoded_path
        or ".." in decoded_path.split("/")
    ):
        return _ignored()

    return ConsoleNavigation(
        state="ENABLED",
        url=f"http://{authority}{parsed.path}",
    )
