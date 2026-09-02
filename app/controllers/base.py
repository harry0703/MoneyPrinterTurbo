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
    """返回请求中全部 API Key Header，保留重复值用于安全校验。"""

    # Starlette Headers 提供 getlist()，可以区分代理或客户端发送的重复 Header。
    # 单元测试中的轻量 Request 替身只使用普通 dict，因此保留兼容回退。
    get_list = getattr(request.headers, "getlist", None)
    if callable(get_list):
        return [value for value in get_list("x-api-key") if isinstance(value, str)]

    api_key = get_api_key(request)
    return [api_key] if isinstance(api_key, str) else []


def verify_token(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="x-api-key")] = None,
):
    """按配置决定是否校验 API Key。

    空 Key 保留现有的本地免认证模式；管理员显式配置非空 Key 后，API
    路由和任务产物下载都会要求客户端通过 ``x-api-key`` 请求头提供同一
    个值。参数声明同时让 Swagger 展示该请求头，便于受保护环境调试。
    """

    configured_key = config.app.get("api_key", "")
    if configured_key in (None, ""):
        return None

    # 配置项必须是字符串。这里拒绝列表、数字等错误类型，避免字符串隐式
    # 转换产生难以发现的认证行为；错误信息也不包含实际 Key。
    if not isinstance(configured_key, str):
        raise HttpException(
            task_id=get_task_id(request),
            status_code=500,
            message="API authentication is misconfigured",
        )

    # FastAPI 参数用于在 OpenAPI 中声明 x-api-key；实际校验始终读取 Request，
    # 才能识别同名 Header 被重复发送的情况。普通客户端和反向代理对重复 Header
    # 的取值顺序可能不同，因此必须拒绝，而不能隐式采用第一个或最后一个值。
    token_values = get_api_key_values(request)
    if not token_values and isinstance(x_api_key, str):
        token_values = [x_api_key]

    if len(token_values) != 1:
        raise HttpException(
            task_id=get_task_id(request),
            status_code=401,
            message="invalid API key",
        )

    # compare_digest 对 str 只支持 ASCII。请求 Header 属于不可信输入，攻击者
    # 可以发送 Latin-1 字符触发 TypeError。统一编码为 UTF-8 bytes 后既保留
    # 恒定时间比较，也支持 TOML 中合法的 Unicode Key。
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
