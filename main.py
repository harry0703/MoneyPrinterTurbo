import uvicorn
from loguru import logger
from clipp_auth import ClippAuthMiddleware   # ✅ Line 3 — correct
from clipp_health import register_health 

from app.config import config

if __name__ == "__main__":
    logger.info(
        "start server, docs: http://127.0.0.1:" + str(config.listen_port) + "/docs"
    )

    # ✅ This line must be OUTSIDE and BEFORE uvicorn.run()
    # You need to import the actual app object first
    from app.asgi import app
    register_health(app)
    app.add_middleware(ClippAuthMiddleware)

    uvicorn.run(
        app=app,                        # ← pass the app object, not the string
        host=config.listen_host,
        port=config.listen_port,
        reload=config.reload_debug,
        log_level="warning",
    )
