from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import FileResponse, Response

router = APIRouter()
# @route.get("/videos/{rest_of_path:path}", response_class=Response, include_in_schema=False)
# async def static_files(
#     rest_of_path: str,
# ):
#     return FileResponse(f"/videos/{rest_of_path}")

@router.get("/videos/{task_id}", response_class=Response)
def get_task(request: Request, task_id: str):
    return task_id
