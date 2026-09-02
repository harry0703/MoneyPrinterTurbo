"""Application implementation - ASGI."""

import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.config import config
from app.controllers import base
from app.models.exception import HttpException
from app.router import root_api_router
from app.utils import utils


@asynccontextmanager
async def application_lifespan(_: FastAPI):
    """集中处理 API 进程启动恢复和关闭日志。"""
    logger.info("startup event")

    configured_api_key = config.app.get("api_key", "")
    if configured_api_key in (None, ""):
        logger.warning(
            "API key authentication is disabled; keep the API on a trusted network"
        )
    elif isinstance(configured_api_key, str):
        # 只记录保护范围，不得输出 Key、长度或摘要，避免凭据进入日志系统。
        logger.info("API key authentication is enabled for /api/v1 and /tasks")
    else:
        logger.error(
            "API key authentication is misconfigured: app.api_key must be a string"
        )

    # 跨平台发布由当前进程线程池执行，不会在服务重启后恢复。启动时把 Redis
    # 中确认已失去执行进程的活动状态收敛为失败，避免任务永久无法删除。
    from app.services import task as task_service

    task_service.recover_interrupted_cross_posts()
    try:
        yield
    finally:
        logger.info("shutdown event")


def exception_handler(request: Request, e: HttpException):
    return JSONResponse(
        status_code=e.status_code,
        content=utils.get_response(e.status_code, e.data, e.message),
    )


def validation_exception_handler(request: Request, e: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content=utils.get_response(
            status=400, data=e.errors(), message="field required"
        ),
    )


def parse_cors_allowed_origins(raw_origins: str | None) -> list[str]:
    """解析浏览器跨域来源白名单。

    CORS 只约束浏览器中的跨域 JavaScript，不影响 curl、Postman、n8n
    或服务端 SDK。未配置时返回空列表，表示默认不开放跨域访问；用户确实
    部署了独立网页前端时，再通过 ``CORS_ALLOWED_ORIGINS`` 显式开启。
    """

    if not raw_origins:
        return []

    # 去除逗号分隔项两侧的空白，并忽略空项，避免常见的环境变量格式
    # ``https://a.example, https://b.example,`` 产生永远无法匹配的来源。
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


def configure_cors(instance: FastAPI, allowed_origins: list[str]) -> None:
    """按显式白名单配置 CORS；空白名单保持默认同源策略。"""

    if not allowed_origins:
        logger.info(
            "browser cross-origin API access is disabled; set "
            "CORS_ALLOWED_ORIGINS to enable trusted origins"
        )
        return

    allow_all_origins = "*" in allowed_origins
    configured_api_key = config.app.get("api_key", "")
    if allow_all_origins and configured_api_key in (None, ""):
        # ``*`` 是用户显式选择的兼容模式，因此不强制拒绝启动；但在免认证
        # 状态下它会允许任意网页读取和调用 API，必须留下可定位的安全告警。
        logger.warning(
            "CORS allows every browser origin while API key authentication is "
            "disabled; configure app.api_key or restrict CORS_ALLOWED_ORIGINS"
        )

    instance.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        # Starlette 在 ``*`` 与 credentials 同时启用时会反射任意 Origin。
        # 通配符模式不需要 Cookie 认证，因此主动关闭 credentials；显式来源
        # 仍保留旧行为，避免影响已有独立网页前端的 credentials 请求模式。
        allow_credentials=not allow_all_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        # 远程 HTTPS 前端访问本机或局域网 API 时，现代浏览器会额外发送
        # Private Network Access 预检。只有精确白名单来源可以获得许可；
        # 通配符模式继续拒绝，避免任意网站探测用户的私有网络服务。
        allow_private_network=not allow_all_origins,
    )


def is_browser_origin_allowed(
    request: Request, allowed_origins: list[str]
) -> bool:
    """判断浏览器请求来源是否为同源或显式白名单来源。"""

    origin = request.headers.get("origin")
    if not origin:
        # curl、Postman、n8n 和服务端 SDK 通常不发送 Origin。保留这类请求，
        # 避免安全修复错误地改变现有 API 客户端的调用契约。
        return True
    if "*" in allowed_origins or origin in allowed_origins:
        return True

    # 浏览器对同源 POST 也可能发送 Origin。仅比较 scheme + authority，忽略
    # 路径和查询参数；反向代理部署若未正确转发公网 scheme/host，可通过显式
    # CORS_ALLOWED_ORIGINS 声明外部来源，避免依赖不可信的转发 Header。
    request_url = urlsplit(str(request.url))
    request_origin = f"{request_url.scheme}://{request_url.netloc}"
    return origin == request_origin


def configure_browser_access(instance: FastAPI, allowed_origins: list[str]) -> None:
    """同时配置服务端 Origin 防护与浏览器 CORS 响应策略。"""

    @instance.middleware("http")
    async def reject_untrusted_browser_origin(request: Request, call_next):
        """主动拒绝不可信浏览器来源，覆盖无需 CORS 预检的简单请求。"""

        if not is_browser_origin_allowed(request, allowed_origins):
            origin = request.headers.get("origin", "")
            logger.warning(
                f"blocked untrusted browser origin: method={request.method}, "
                f"path={request.url.path}, origin={origin}"
            )
            return JSONResponse(
                status_code=403,
                content=utils.get_response(
                    status=403,
                    message="cross-origin browser request is not allowed",
                ),
            )

        return await call_next(request)

    # CORS 中间件最后注册后位于 Origin 防护外层：可信预检可直接成功，
    # 非可信预检由 CORS 拒绝；无需预检的实际请求仍会进入上面的 403 防护。
    configure_cors(instance, allowed_origins)


def get_application() -> FastAPI:
    """Initialize FastAPI application.

    Returns:
       FastAPI: Application object instance.

    """
    instance = FastAPI(
        title=config.project_name,
        description=config.project_description,
        version=config.project_version,
        debug=False,
        lifespan=application_lifespan,
    )
    instance.include_router(root_api_router)
    instance.add_exception_handler(HttpException, exception_handler)
    instance.add_exception_handler(RequestValidationError, validation_exception_handler)
    return instance


app = get_application()


@app.middleware("http")
async def protect_generated_task_files(request: Request, call_next):
    """保护任务产物静态路由，防止绕过 API 鉴权直接下载。

    ``/tasks`` 由 StaticFiles 独立挂载，无法复用 APIRouter 的依赖，
    因此在中间件中调用同一个 verify_token。鉴权函数会在未配置
    api_key 时放行；OPTIONS 预检请求也保留给 CORS 中间件处理。
    """

    request_path = request.url.path
    is_task_file = request_path == "/tasks" or request_path.startswith("/tasks/")
    if is_task_file and request.method != "OPTIONS":
        try:
            base.verify_token(request)
        except HttpException as exception:
            return exception_handler(request, exception)

    return await call_next(request)


# 默认遵循浏览器同源策略；仅在用户显式配置可信网页来源时开放跨域。
cors_allowed_origins = parse_cors_allowed_origins(
    os.getenv("CORS_ALLOWED_ORIGINS", "")
)
configure_browser_access(app, cors_allowed_origins)

task_dir = utils.task_dir()
app.mount("/tasks", StaticFiles(directory=task_dir, html=True), name="")

public_dir = utils.public_dir()
app.mount("/", StaticFiles(directory=public_dir, html=True), name="")
