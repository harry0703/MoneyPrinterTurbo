from fastapi import APIRouter, Request

router = APIRouter()


@router.get(
    "/ping",
    tags=["Health Check"],
    description="서비스 가용성 확인",
    response_description="pong",
)
def ping(request: Request) -> str:
    return "pong"
