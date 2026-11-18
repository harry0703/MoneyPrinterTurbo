import secrets
from typing import Annotated
from uuid import uuid4

from fastapi import Header, Request

from app.config import config
from app.models.exception import HttpException

MAX_TASK_ID_LENGTH = 128


def normalize_task_id(value: object) -> str:
    """Return a log-safe request ID, replacing invalid client input with a UUID."""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_TASK_ID_LENGTH
        or not value.isprintable()
    ):
        return str(uuid4())
    return value


def get_task_id(request: Request) -> str:
    return normalize_task_id(request.headers.get("x-task-id"))


def get_api_key(request: Request):
    api_key = request.headers.get("x-api-key")
    return api_key


def get_api_key_values(request: Request) -> list[str]:
    """Return all API Key headers in the request, keeping duplicate values for security validation."""

    # Starlette Headers provides getlist(), which can detect duplicate headers sent by proxies or clients.
    # The lightweight Request doubles in unit tests only use a plain dict, so a compatible fallback is kept.
    get_list = getattr(request.headers, "getlist", None)
    if callable(get_list):
        return [value for value in get_list("x-api-key") if isinstance(value, str)]

    api_key = get_api_key(request)
    return [api_key] if isinstance(api_key, str) else []


def verify_token(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="x-api-key")] = None,
):
    """Decide whether to validate the API Key based on config.

    An empty Key keeps the existing local no-auth mode; once an administrator explicitly configures a non-empty Key, API
    routes and task output downloads require clients to provide the same
    value via the ``x-api-key`` request header. The parameter declaration also makes Swagger show this header, easing debugging in protected environments.
    """

    configured_key = config.app.get("api_key", "")
    if configured_key in (None, ""):
        return None

    # The config item must be a string. Wrong types such as lists or numbers are rejected here, so implicit string
    # conversion doesn't produce hard-to-spot auth behavior; the error message doesn't include the actual Key either.
    if not isinstance(configured_key, str):
        raise HttpException(
            task_id=get_task_id(request),
            status_code=500,
            message="API authentication is misconfigured",
        )

    # The FastAPI parameter declares x-api-key in OpenAPI; actual validation always reads the Request,
    # so duplicate same-named headers can be detected. Ordinary clients and reverse proxies may order duplicate header
    # values differently, so they must be rejected rather than implicitly taking the first or last value.
    token_values = get_api_key_values(request)
    if not token_values and isinstance(x_api_key, str):
        token_values = [x_api_key]

    if len(token_values) != 1:
        raise HttpException(
            task_id=get_task_id(request),
            status_code=401,
            message="invalid API key",
        )

    # compare_digest only supports ASCII for str. Request headers are untrusted input, and an attacker
    # could send Latin-1 characters to trigger a TypeError. Encoding uniformly to UTF-8 bytes keeps
    # the constant-time comparison while supporting valid Unicode Keys in TOML.
    token = token_values[0]
    if not secrets.compare_digest(
        token.encode("utf-8"), configured_key.encode("utf-8")
    ):
        raise HttpException(
            task_id=get_task_id(request),
            status_code=401,
            message="invalid API key",
        )

    return None
