"""Application implementation - ASGI."""

import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.config import config
from app.models.exception import HttpException
from app.router import root_api_router
from app.utils import utils


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
    )
    instance.include_router(root_api_router)
    instance.add_exception_handler(HttpException, exception_handler)
    instance.add_exception_handler(RequestValidationError, validation_exception_handler)
    return instance


app = get_application()

# Configures the CORS middleware for the FastAPI app.
# Never pair a wildcard origin with allow_credentials=True. By default we only
# trust same-host browser origins; widen via the CORS_ALLOWED_ORIGINS env var
# (comma-separated list of full origins, e.g. "https://app.example.com").
cors_allowed_origins_str = os.getenv("CORS_ALLOWED_ORIGINS", "")
if cors_allowed_origins_str:
    origins = [o.strip() for o in cors_allowed_origins_str.split(",") if o.strip()]
else:
    origins = [
        "http://localhost:8501",
        "http://127.0.0.1:8501",
        f"http://localhost:{config.listen_port}",
        f"http://127.0.0.1:{config.listen_port}",
    ]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

task_dir = utils.task_dir()
# follow_symlink is intentionally disabled: a symlink placed inside the task
# directory must not be able to expose files elsewhere on the host.
app.mount(
    "/tasks", StaticFiles(directory=task_dir, html=True), name=""
)

public_dir = utils.public_dir()
app.mount("/", StaticFiles(directory=public_dir, html=True), name="")


@app.on_event("shutdown")
def shutdown_event():
    logger.info("shutdown event")


@app.on_event("startup")
def startup_event():
    logger.info("startup event")
