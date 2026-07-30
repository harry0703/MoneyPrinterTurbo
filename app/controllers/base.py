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
    # api_key 가 설정되지 않았으면 모든 요청을 거부해야 한다. 빈 설정과 빈 요청 헤더가
    # 같다고 판정되면 인증이 무력화되어, 보호되어야 할 엔드포인트가 기본 설정에서
    # 다시 익명으로 열린다.
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
