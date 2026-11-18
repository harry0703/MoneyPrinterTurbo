"""Application implementation - ASGI."""

import math
import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
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
    """Handle API process startup recovery and shutdown logging in one place."""
    logger.info("startup event")

    configured_api_key = config.app.get("api_key", "")
    if configured_api_key in (None, ""):
        logger.warning(
            "API key authentication is disabled; keep the API on a trusted network"
        )
    elif isinstance(configured_api_key, str):
        # Only log the protected scope; never output the Key, its length or a digest, so credentials don't enter the logging system.
        logger.info("API key authentication is enabled for /api/v1 and /tasks")
    else:
        logger.error(
            "API key authentication is misconfigured: app.api_key must be a string"
        )

    # Cross-platform publishing runs in the current process's thread pool and isn't resumed after a service restart. On startup, converge
    # active states in Redis whose executing process is confirmed gone to failed, so tasks don't become permanently undeletable.
    from app.services import task as task_service

    task_service.recover_interrupted_cross_posts()

    # Redis queue entries persist across API restarts. No task_done callback
    # exists in the new process to dispatch them, so fill its worker slots now.
    from app.controllers.manager.redis_manager import RedisTaskManager
    from app.controllers.v1 import video as video_controller

    redis_task_manager = None
    if isinstance(video_controller.task_manager, RedisTaskManager):
        redis_task_manager = video_controller.task_manager
        redis_task_manager.resume_queued_tasks()
        redis_task_manager.start_queue_dispatcher()
    try:
        yield
    finally:
        if redis_task_manager is not None:
            redis_task_manager.stop_queue_dispatcher()
        logger.info("shutdown event")


def exception_handler(request: Request, e: HttpException):
    return JSONResponse(
        status_code=e.status_code,
        content=utils.get_response(e.status_code, e.data, e.message),
    )


def validation_exception_handler(request: Request, e: RequestValidationError):
    # Rejected inputs can contain NaN/Infinity, and custom validators attach
    # exception objects to ctx. Neither can be emitted by JSONResponse directly.
    errors = jsonable_encoder(
        e.errors(),
        custom_encoder={
            float: lambda value: value if math.isfinite(value) else str(value),
            Exception: str,
        },
    )
    # Describe the first rejected field instead of always claiming a missing
    # field: out-of-range values and malformed JSON are not "field required".
    message = "invalid request parameters"
    if errors and isinstance(errors[0], dict):
        location = ".".join(str(part) for part in errors[0].get("loc") or ())
        detail = errors[0].get("msg") or message
        message = f"{location}: {detail}" if location else str(detail)
    return JSONResponse(
        status_code=400,
        content=utils.get_response(status=400, data=errors, message=message),
    )


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _normalize_allowed_origin(raw_origin: str) -> str | None:
    """Fold a config entry into the Origin form the browser actually sends.

    RFC 6454 fixes the Origin request header as ``scheme://host[:port]``: no path, no trailing
    slash, scheme and host already normalized to lowercase, and the protocol's default port omitted. A
    ``https://frontend.example/`` copied from the browser address bar, or a
    ``https://frontend.example:443`` with the default port written explicitly, never equals character for character the
    ``https://frontend.example`` the browser actually sends, so the allowlist silently fails: the frontend only sees
    a CORS error, the server only leaves one blocked log line, and neither points to the config itself.

    Returning ``None`` means the entry can't possibly match any Origin (missing scheme, scheme not
    http/https, empty hostname or one containing whitespace, malformed IPv6 literal, invalid or out-of-range port), and the caller should
    drop it and warn. Parse failures must converge to ``None``: this function runs at module import time, and letting
    ``urlsplit()``'s ``ValueError`` escape would mean the whole API can't start.
    """

    if raw_origin == "*":
        return raw_origin

    try:
        parsed = urlsplit(raw_origin)
        scheme = parsed.scheme.lower()
        # The netloc is only validated when reading hostname / port: malformed IPv6 literals are raised by urlsplit(),
        # and non-numeric ports or ports outside 0-65535 are raised when reading port.
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None

    # Only http/https have browser Origin semantics, and both have an omittable default port.
    if scheme not in _DEFAULT_PORTS or not host:
        return None
    if any(character.isspace() for character in host):
        return None

    # Lowercase explicitly rather than relying on urlsplit's case handling across Python versions.
    host = host.lower()
    # Browsers keep the square brackets of IPv6 literals when serializing Origin; default-port forms like ``:443``, ``:0443`` and
    # ``:80`` must be folded to the portless form to match the real frontend.
    if ":" in host:
        host = f"[{host}]"
    if port is None or port == _DEFAULT_PORTS[scheme]:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def parse_cors_allowed_origins(raw_origins: str | None) -> list[str]:
    """Parse the browser cross-origin allowlist.

    CORS only constrains cross-origin JavaScript in browsers and doesn't affect curl, Postman, n8n
    or server-side SDKs. When unconfigured an empty list is returned, meaning cross-origin access is closed by default; users who really
    deploy a separate web frontend can enable it explicitly via ``CORS_ALLOWED_ORIGINS``.

    Each origin is first folded into the canonical form of the Origin request header, so ``https://a.example/``,
    ``HTTPS://A.Example`` and ``https://a.example:443`` with an explicit default port all give the same
    result, and entries that can't match any Origin are dropped with a warning. A malformed entry only drops itself
    and doesn't interrupt parsing here — this function is called at module import time, and a parse exception would stop the API from starting.
    """

    if not raw_origins:
        return []

    # Strip whitespace around comma-separated items and ignore empty ones, so the common environment variable format
    # ``https://a.example, https://b.example,`` doesn't produce origins that can never match.
    origins: list[str] = []
    for candidate in raw_origins.split(","):
        item = candidate.strip()
        if not item:
            continue
        origin = _normalize_allowed_origin(item)
        if origin is None:
            logger.warning(
                f"ignoring configured CORS origin that cannot match a browser "
                f"Origin header: {item!r}"
            )
            continue
        if origin not in origins:
            origins.append(origin)
    return origins


def configure_cors(instance: FastAPI, allowed_origins: list[str]) -> None:
    """Configure CORS from an explicit allowlist; an empty allowlist keeps the default same-origin policy."""

    if not allowed_origins:
        logger.info(
            "browser cross-origin API access is disabled; set "
            "CORS_ALLOWED_ORIGINS to enable trusted origins"
        )
        return

    allow_all_origins = "*" in allowed_origins
    configured_api_key = config.app.get("api_key", "")
    if allow_all_origins and configured_api_key in (None, ""):
        # ``*`` is a compatibility mode the user chose explicitly, so startup isn't refused; but without
        # authentication it lets any web page read and call the API, so a traceable security warning must be logged.
        logger.warning(
            "CORS allows every browser origin while API key authentication is "
            "disabled; configure app.api_key or restrict CORS_ALLOWED_ORIGINS"
        )

    instance.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        # Starlette reflects any Origin when ``*`` and credentials are both enabled.
        # Wildcard mode doesn't need Cookie auth, so credentials are turned off proactively; explicit origins
        # keep the old behavior, so existing separate web frontends using credentials requests aren't affected.
        allow_credentials=not allow_all_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        # When a remote HTTPS frontend accesses an API on the local machine or LAN, modern browsers additionally send
        # a Private Network Access preflight. Only exactly allowlisted origins can be granted it;
        # wildcard mode keeps refusing, so arbitrary websites can't probe the user's private network services.
        allow_private_network=not allow_all_origins,
    )


def is_browser_origin_allowed(
    request: Request, allowed_origins: list[str]
) -> bool:
    """Decide whether a browser request origin is same-origin or an explicitly allowlisted origin."""

    origin = request.headers.get("origin")
    if not origin:
        # curl, Postman, n8n and server-side SDKs usually don't send Origin. Keep allowing these requests,
        # so the security fix doesn't wrongly change the call contract of existing API clients.
        return True
    if "*" in allowed_origins or origin in allowed_origins:
        return True

    # Browsers may send Origin even for same-origin POSTs. Only scheme + authority are compared, ignoring
    # path and query parameters; reverse-proxy deployments that don't forward the public scheme/host correctly can declare the external origin
    # explicitly via CORS_ALLOWED_ORIGINS, avoiding reliance on untrusted forwarded headers.
    request_url = urlsplit(str(request.url))
    request_origin = f"{request_url.scheme}://{request_url.netloc}"
    return origin == request_origin


def configure_browser_access(instance: FastAPI, allowed_origins: list[str]) -> None:
    """Configure both server-side Origin protection and the browser CORS response policy."""

    @instance.middleware("http")
    async def reject_untrusted_browser_origin(request: Request, call_next):
        """Actively reject untrusted browser origins, covering simple requests that don't need a CORS preflight."""

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

    # The CORS middleware is registered last, so it sits outside the Origin protection: trusted preflights succeed directly,
    # untrusted preflights are rejected by CORS; actual requests that need no preflight still hit the 403 protection above.
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
    """Protect the task output static route, preventing downloads that bypass API auth.

    ``/tasks`` is mounted separately by StaticFiles and can't reuse APIRouter dependencies,
    so the same verify_token is called in the middleware. The auth function lets requests through when
    api_key isn't configured; OPTIONS preflight requests are also left to the CORS middleware.
    """

    request_path = request.url.path
    is_task_file = request_path == "/tasks" or request_path.startswith("/tasks/")
    if is_task_file and request.method != "OPTIONS":
        try:
            base.verify_token(request)
        except HttpException as exception:
            return exception_handler(request, exception)

    return await call_next(request)


# Follow the browser same-origin policy by default; cross-origin is only opened when the user explicitly configures trusted web origins.
cors_allowed_origins = parse_cors_allowed_origins(
    os.getenv("CORS_ALLOWED_ORIGINS", "")
)
configure_browser_access(app, cors_allowed_origins)

task_dir = utils.task_dir()
app.mount("/tasks", StaticFiles(directory=task_dir, html=True), name="")

public_dir = utils.public_dir()
app.mount("/", StaticFiles(directory=public_dir, html=True), name="")
