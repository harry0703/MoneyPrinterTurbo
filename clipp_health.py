"""
Clipp Engine — Health Check Endpoint
=====================================
GET /api/v1/health returns 200 always while the process is alive.

KEY DESIGN: We return 200 even when a task is processing.
Railway should NOT restart the container just because it's busy.
The health check only fails if the process is truly dead.

We also expose a /api/v1/status endpoint so the worker can
distinguish between "idle" and "busy" without triggering restarts.
"""

import os
import time
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

# Track active task count in-process
# MPT updates this via the task manager — we just expose it
_start_time = time.time()


@router.get("/api/v1/health")
async def health_check():
    """
    Always returns 200 while the process is alive.
    Railway uses this ONLY to detect dead containers, not busy ones.
    """
    return JSONResponse(
        status_code=200,
        content={
            "status":   "ok",
            "service":  "clipp-engine",
            "uptime_s": int(time.time() - _start_time),
        }
    )


@router.get("/api/v1/status")
async def engine_status():
    """
    Lightweight status endpoint for the worker to check
    if the engine is idle before submitting a new job.
    """
    tasks_dir = os.environ.get("TASKS_DIR", "./storage/tasks")
    try:
        task_dirs = [
            d for d in os.listdir(tasks_dir)
            if os.path.isdir(os.path.join(tasks_dir, d))
        ] if os.path.exists(tasks_dir) else []
    except Exception:
        task_dirs = []

    return JSONResponse(
        status_code=200,
        content={
            "status":      "ok",
            "task_count":  len(task_dirs),
            "uptime_s":    int(time.time() - _start_time),
        }
    )


def register_health(app):
    """Call this with your FastAPI app instance to register health routes."""
    app.include_router(router)
