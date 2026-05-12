import asyncio
from fastapi import Query, WebSocket, WebSocketDisconnect
from app.controllers.v1.base import new_router
from app.services.log_service import log_service
from app.utils import utils

router = new_router()


@router.get("/logs", summary="Get logs")
def get_logs(
    level: str = Query(None, description="Log level filter (INFO, WARNING, ERROR)"),
    task_id: str = Query(None, description="Task ID filter"),
    limit: int = Query(100, ge=1, le=3000, description="Number of logs to return"),
    offset: int = Query(0, ge=0, description="Pagination offset")
):
    result = log_service.get_logs(level, task_id, limit, offset)
    return utils.get_response(200, result)


@router.delete("/logs", summary="Clear logs")
def clear_logs():
    log_service.clear_logs()
    return utils.get_response(200, {"message": "Logs cleared successfully"})


@router.websocket("/logs/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time log updates."""
    await websocket.accept()
    
    log_service._event_loop = asyncio.get_event_loop()
    log_service.add_websocket_connection(websocket)
    
    try:
        while True:
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        log_service.remove_websocket_connection(websocket)
