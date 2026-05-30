import os
import sys

from loguru import logger

from app.config import config
from app.utils import utils


def __init_logger():
    # _log_file = utils.storage_dir("logs/server.log")
    _lvl = config.log_level
    root_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    )

    def format_record(record):
        # 로그 레코드에서 파일의 전체 경로를 가져옵니다
        file_path = record["file"].path
        # 절대 경로를 프로젝트 루트 디렉터리 기준 상대 경로로 변환합니다
        relative_path = os.path.relpath(file_path, root_dir)
        # 레코드의 파일 경로를 갱신합니다
        record["file"].path = f"./{relative_path}"
        # 수정된 포맷 문자열을 반환합니다
        # 필요에 따라 여기 포맷을 조정할 수 있습니다
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

    # logger.add(
    #     _log_file,
    #     level=_lvl,
    #     format=format_record,
    #     rotation="00:00",
    #     retention="3 days",
    #     backtrace=True,
    #     diagnose=True,
    #     enqueue=True,
    # )


__init_logger()
