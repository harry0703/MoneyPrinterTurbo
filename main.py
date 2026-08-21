import uvicorn
from loguru import logger

from app.config import config
from app.utils import utils

if __name__ == "__main__":
    logger.info(
        "start server, docs: http://127.0.0.1:" + str(config.listen_port) + "/docs"
    )
    # 提前探测 FFmpeg 是否可用，避免用户在真正生成视频时才第一次看到
    # 不知所以的报错；探测失败只记录警告，不阻止服务启动。
    utils.check_ffmpeg_ready()
    uvicorn.run(
        app="app.asgi:app",
        host=config.listen_host,
        port=config.listen_port,
        reload=config.reload_debug,
        log_level="warning",
    )
