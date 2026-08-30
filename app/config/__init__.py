"""加载运行期配置并初始化终端日志。

导入 ``app.config`` 时会读取 ``config.toml``，并把 loguru 接到标准输出。
"""

import sys

from app.config import config
from app.utils.logging_utils import configure_terminal_logger


def __init_logger():
    """按 config.toml 的日志级别初始化终端输出。"""
    # _log_file = utils.storage_dir("logs/server.log")
    _lvl = config.log_level

    configure_terminal_logger(
        sys.stdout,
        level=_lvl,
        colorize=True,
    )

    # logger.add(
    #     _log_file,
    #     level=_lvl,
    #     format=format_log_record,
    #     rotation="00:00",
    #     retention="3 days",
    #     backtrace=True,
    #     diagnose=True,
    #     enqueue=True,
    # )


__init_logger()
