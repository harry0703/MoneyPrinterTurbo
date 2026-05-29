"""
Clipp Engine — Health Check Endpoint
Adds GET /api/v1/health to the FastAPI app.
Railway's healthcheck hits this route to confirm the app is running.
Import this in main.py AFTER the app is created.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

@router.get("/api/v1/health")
async def health_check():
    return JSONResponse(
        status_code=200,
        content={"status": "ok", "service": "clipp-engine"}
    )


def register_health(app):
    """Call this with your FastAPI app instance to register the health route."""
    app.include_router(router)
