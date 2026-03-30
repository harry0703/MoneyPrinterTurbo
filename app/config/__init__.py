import os
import sys

from loguru import logger
import pytz

from app.utils import utils

# Try to get timezone from host system
def get_host_timezone():
    # Try to read from /etc/timezone (Linux/Mac)
    try:
        with open('/etc/timezone', 'r') as f:
            return f.read().strip()
    except Exception:
        pass
    
    # Try to get from environment variable
    tz_name = os.environ.get('TZ')
    if tz_name:
        return tz_name
    
    # Default to local timezone
    return 'Asia/Shanghai'

# Get timezone
tz_name = get_host_timezone()
try:
    local_tz = pytz.timezone(tz_name)
except pytz.exceptions.UnknownTimeZoneError:
    local_tz = pytz.timezone('Asia/Shanghai')

def __init_logger():
    # _log_file = utils.storage_dir("logs/server.log")
    # Use default log level for now to avoid circular import
    _lvl = "INFO"
    root_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    )

    def format_record(record):
        # 获取日志记录中的文件全路径
        file_path = record["file"].path
        # 将绝对路径转换为相对于项目根目录的路径
        relative_path = os.path.relpath(file_path, root_dir)
        # 更新记录中的文件路径
        record["file"].path = f"./{relative_path}"
        # Get local time
        local_time = record['time'].astimezone(local_tz)
        # Update record with local time
        record['time'] = local_time
        # 返回修改后的格式字符串
        # 您可以根据需要调整这里的格式
        _format = (
            "<green>{time:%Y-%m-%d %H:%M:%S}</> | "
            + "<level>{level}</> | "
            + '"{file.path}:{line}":<blue> {function}</> '
            + "- <level>{message}</>"
            + "\n"
        )
        return _format

    logger.remove()
    logger.add(
        sys.stdout,
        level=_lvl,
        format=format_record,
        colorize=True,
    )


__init_logger()

# Import config after logger initialization to avoid circular import
from app.config import config