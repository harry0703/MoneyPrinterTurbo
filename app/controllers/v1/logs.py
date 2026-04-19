from fastapi import Query, WebSocket, WebSocketDisconnect
from app.controllers.v1.base import new_router
from app.services.log_service import log_service
from app.utils import utils

router = new_router()


@router.get("/logs", summary="Get logs")
def get_logs(
    level: str = Query(None, description="Log level filter (INFO, WARNING, ERROR)"),
    task_id: str = Query(None, description="Task ID filter"),
    limit: int = Query(100, ge=1, le=1000, description="Number of logs to return"),
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
    
    # Add the connection to the log service
    log_service.add_websocket_connection(websocket)
    
    try:
        while True:
            # Wait for messages (we don't expect any from the client)
            await websocket.receive_text()
    except WebSocketDisconnect:
        # Remove the connection when disconnected
        log_service.remove_websocket_connection(websocket)
    except Exception as e:
        # Handle any other exceptions
        print(f"WebSocket error: {e}")
        log_service.remove_websocket_connection(websocket)
