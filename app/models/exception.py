"""API 与文件访问相关的业务异常。"""

import traceback
from typing import Any

from loguru import logger


class HttpException(Exception):
    """带任务 ID 和 HTTP 状态码的接口异常，构造时同步写入日志。"""

    def __init__(
        self, task_id: str, status_code: int, message: str = "", data: Any = None
    ):
        self.message = message
        self.status_code = status_code
        self.data = data
        # 取出当前调用栈，便于在日志中定位抛出位置。
        tb_str = traceback.format_exc().strip()
        if not tb_str or tb_str == "NoneType: None":
            msg = f"HttpException: {status_code}, {task_id}, {message}"
        else:
            msg = f"HttpException: {status_code}, {task_id}, {message}\n{tb_str}"

        # 400/401 都是可预期的客户端输入问题。尤其鉴权开启后，公网扫描可能
        # 产生大量无效 Key；使用 WARNING 既保留定位信息，也避免污染 ERROR
        # 告警。服务端配置错误和其它异常仍保持 ERROR。
        if status_code in (400, 401):
            logger.warning(msg)
        else:
            logger.error(msg)


class FileNotFoundException(Exception):
    """请求的任务产物或资源文件不存在。"""
