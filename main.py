import logging
import uvicorn
from loguru import logger

class ConnectionResetErrorFilter(logging.Filter):
    def filter(self, record):
        if record.name == "asyncio" and "ConnectionResetError" in record.getMessage():
            if "10054" in record.getMessage() or "远程主机强迫关闭" in record.getMessage():
                return False
        return True

logging.getLogger("asyncio").addFilter(ConnectionResetErrorFilter())

# Import log_service first to register the logger handler
from app.services import log_service  # noqa: F401

from app.config import config

if __name__ == "__main__":
    logger.info(
        "start server, docs: http://127.0.0.1:" + str(config.listen_port) + "/docs"
    )
    uvicorn.run(
        app="app.asgi:app",
        host=config.listen_host,
        port=config.listen_port,
        reload=config.reload_debug,
        log_level="warning",
    )
