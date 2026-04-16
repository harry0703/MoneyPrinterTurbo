from fastapi import APIRouter, Request
from app.config import config

router = APIRouter()


@router.get(
    "/ping",
    tags=["Health Check"],
    description="检查服务可用性",
    response_description="pong",
)
def ping(request: Request) -> str:
    return "pong"


@router.get(
    "/version",
    tags=["Health Check"],
    description="获取服务版本信息",
    response_description="版本信息",
)
def version(request: Request) -> dict:
    return {
        "name": config.project_name,
        "version": config.project_version
    }
