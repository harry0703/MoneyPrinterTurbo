from fastapi import APIRouter
from typing import Any


def new_router(dependencies: list[Any] | None = None) -> APIRouter:
    router = APIRouter()
    router.tags = ["V1"]
    router.prefix = "/api/v1"
    # 将认证依赖项应用于所有路由
    if dependencies:
        router.dependencies = dependencies
    return router
