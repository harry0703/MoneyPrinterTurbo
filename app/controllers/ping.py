"""健康检查接口。"""

from fastapi import APIRouter, Request

router = APIRouter()


@router.get(
    "/ping",
    tags=["Health Check"],
    description="检查服务可用性",
    response_description="pong",
)
def ping(request: Request) -> str:
    """探测进程是否存活，成功时固定返回 ``pong``。"""
    return "pong"
