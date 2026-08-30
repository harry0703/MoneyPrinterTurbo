"""v1 API 路由工厂：统一前缀、标签和鉴权依赖。"""

from fastapi import APIRouter


def new_router(dependencies=None):
    """创建 ``/api/v1`` 路由器；传入 ``dependencies`` 后会应用到该组全部接口。"""
    router = APIRouter()
    router.tags = ["V1"]
    router.prefix = "/api/v1"
    # 将认证依赖项应用于所有路由
    if dependencies:
        router.dependencies = dependencies
    return router
