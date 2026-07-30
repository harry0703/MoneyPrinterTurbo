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
    # api_key 未配置时必须拒绝所有请求：空配置与空请求头相等会让鉴权失效，
    # 让本应受保护的接口在默认配置下重新变成匿名可用。
    expected_token = config.app.get("api_key", "")
    token = get_api_key(request)
    if not expected_token or token != expected_token:
        request_id = get_task_id(request)
        request_url = request.url
        user_agent = request.headers.get("user-agent")
        raise HttpException(
            task_id=request_id,
            status_code=401,
            message=f"invalid token: {request_url}, {user_agent}",
        )
