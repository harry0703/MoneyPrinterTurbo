import os
import threading

from loguru import logger


PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
)
LOG_RECORD_FORMAT = (
    "<green>{time:%Y-%m-%d %H:%M:%S}</> | "
    "<level>{level}</> | "
    '"{file.path}:{line}":<blue> {function}</> '
    "- <level>{message}</>\n"
)
# Loguru 가 시작할 때 기본 터미널 handler 의 ID 는 0 이다. WebUI 가 다시 로드될 때는
# 이 기본 터미널 출력만 교체해야 하며, logger.remove() 로 전체 handler 를 비우면
# 실행 중인 작업이 WebUI 로그를 모으려고 쓰는 임시 sink 까지 함께 삭제된다.
_terminal_handler_id: int | None = 0
_terminal_handler_lock = threading.RLock()


def format_log_record(record):
    """
    터미널과 WebUI 로그 형식을 통일한다.

    Loguru 는 같은 레코드를 여러 sink 에 전달한다. 첫 번째 sink 가 이미 절대 경로를
    프로젝트 상대 경로로 바꿔 놨을 수 있으므로, 여기서는 절대 경로와 ``./`` 로 시작하는
    이미 변환된 경로를 모두 처리한다. WebUI sink 는 색상을 끄지만 시각, 레벨, 호출 위치,
    메시지 내용은 터미널과 동일하게 유지한다.
    """
    file_path = record["file"].path
    if os.path.isabs(file_path):
        relative_path = os.path.relpath(file_path, PROJECT_ROOT)
        record["file"].path = f"./{relative_path}"

    # 로그 메시지에는 작업 파일의 절대 경로가 섞이곤 한다. 프로젝트 상대 경로로 줄여 두면
    # 초기화 진입점이 달라도 WebUI 와 터미널이 서로 다른 내용을 보여 주지 않는다.
    record["message"] = record["message"].replace(PROJECT_ROOT, ".")
    return LOG_RECORD_FORMAT


def configure_terminal_logger(sink, level: str, colorize: bool = True) -> int:
    """
    프로세스 단위 터미널 로그 handler 를 안전하게 교체하면서 작업 전용 handler 는 남긴다.

    Streamlit 은 코드 핫 리로드나 캐시 무효화 때 로그 초기화를 다시 실행할 수 있다.
    여기서는 기록해 둔 handler ID 로 예전 터미널 출력만 정확히 제거하므로, 백그라운드
    작업이 쓰고 있는 WebUI 로그를 끊지 않는다. 락은 여러 브라우저 세션이 동시에
    초기화할 때의 ID 갱신을 보호한다.
    """
    global _terminal_handler_id

    with _terminal_handler_lock:
        if _terminal_handler_id is not None:
            try:
                logger.remove(_terminal_handler_id)
            except ValueError:
                # 테스트나 외부 진입점이 이미 이 handler 를 제거했을 수 있다. 새 터미널 출력은
                # 그대로 만들고, 아직 유효한 다른 로그 sink 에는 영향을 주지 않는다.
                pass

        _terminal_handler_id = logger.add(
            sink,
            level=level,
            format=format_log_record,
            colorize=colorize,
        )
        return _terminal_handler_id
