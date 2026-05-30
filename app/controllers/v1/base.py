from fastapi import APIRouter


def new_router(dependencies=None):
    router = APIRouter()
    router.tags = ["V1"]
    router.prefix = "/api/v1"
    # 인증 의존성을 모든 라우트에 적용합니다
    if dependencies:
        router.dependencies = dependencies
    return router
