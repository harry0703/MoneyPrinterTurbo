"""根 APIRouter：汇总健康检查与 v1 业务接口。

新增 HTTP 端点时应在对应控制器中声明，再于此处挂载，避免路由分散。
"""

from fastapi import APIRouter

from app.controllers import ping
from app.controllers.v1 import llm, video

root_api_router = APIRouter()
root_api_router.include_router(ping.router)

# v1
root_api_router.include_router(video.router)
root_api_router.include_router(llm.router)
