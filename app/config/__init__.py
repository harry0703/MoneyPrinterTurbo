import sys

from app.config import config
from app.utils.logging_utils import (
    LOG_LEVELS,
    configure_terminal_logger,
    set_logging_options,
)


def __init_logger():
    # _log_file = utils.storage_dir("logs/server.log")
    _lvl = str(config.diagnostics.get("log_level", config.log_level)).strip().upper()
    if _lvl not in LOG_LEVELS:
        _lvl = str(config.log_level).strip().upper()
        if _lvl not in LOG_LEVELS:
            _lvl = "DEBUG"
    # 分别校验两个选项：非法追踪值不能降低用户已有的日志等级。
    _trace = config.diagnostics.get("log_requests", False)
    set_logging_options(_lvl, _trace if isinstance(_trace, bool) else False)

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
