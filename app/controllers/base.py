import secrets
from uuid import uuid4

from fastapi import Request

from app.config import config
from app.models.exception import HttpException


def get_task_id(request: Request):
    task_id = request.headers.get("x-task-id")
    if not task_id:
        task_id = uuid4()
    return str(task_id)


def get_api_key(request: Request):
    api_key = request.headers.get("x-api-key")
    return api_key


def verify_token(request: Request):
    # Fail closed: if no api_key is configured, reject all API requests rather
    # than silently allowing access. Set a non-empty api_key in config.toml
    # [app] section to enable the HTTP API.
    configured_key = config.app.get("api_key", "") or ""
    token = get_api_key(request) or ""
    request_id = get_task_id(request)

    if not configured_key:
        raise HttpException(
            task_id=request_id,
            status_code=401,
            message=(
                "API access is disabled: set a non-empty 'api_key' in the [app] "
                "section of config.toml and send it in the 'x-api-key' header."
            ),
        )

    # Constant-time comparison avoids leaking the key length/contents via timing.
    if not secrets.compare_digest(token, configured_key):
        request_url = request.url
        user_agent = request.headers.get("user-agent")
        raise HttpException(
            task_id=request_id,
            status_code=401,
            message=f"invalid token: {request_url}, {user_agent}",
        )
