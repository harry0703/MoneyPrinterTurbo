"""Application configuration - root APIRouter.

Defines all FastAPI application endpoints.

Resources:
    1. https://fastapi.tiangolo.com/tutorial/bigger-applications

"""

from fastapi import APIRouter

from app.controllers import ping
from app.controllers.v1 import llm, video

root_api_router = APIRouter()
# 健康检查（无 /api/v1 前缀，挂载在根级 /ping，供启动脚本和监控探活）
root_api_router.include_router(ping.router)
# v1
root_api_router.include_router(video.router)
root_api_router.include_router(llm.router)
