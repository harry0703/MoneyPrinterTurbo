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
    """Require ``x-api-key`` only when an API key is configured."""
    expected_token = str(config.app.get("api_key", "") or "").strip()
    if not expected_token:
        return

    token = get_api_key(request)
    if not isinstance(token, str) or not secrets.compare_digest(
        token, expected_token
    ):
        request_id = get_task_id(request)
        raise HttpException(
            task_id=request_id,
            status_code=401,
            message="invalid or missing API key",
        )
