import threading
from collections import deque

from loguru import logger

from app.config import config
from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.models import const
from app.models.schema import VideoParams
from app.services import state as sm
from app.services import task as tm
from app.utils.logging_utils import format_log_record


# WebUI 설정은 프로세스 단위 전역 딕셔너리에 보관된다. 기존 동기 구현은 생성이 끝날
# 때까지 runtime_config_lock 을 쥐고 있어서, 서로 다른 브라우저 세션도 사실상 직렬로
# 실행됐다. 여기서 동시 실행 수를 1 로 고정하면 기존 설정 일관성을 그대로 잇는 동시에,
# 여러 스레드가 설정 락 밖에서 의미 없이 대기하는 것도 피할 수 있다.
_task_manager = InMemoryTaskManager(
    max_concurrent_tasks=1,
    max_queued_tasks=max(1, int(config.app.get("max_queued_tasks", 100))),
)
_task_logs: dict[str, deque[str]] = {}
_task_logs_lock = threading.RLock()
_MAX_LOG_TASKS = 20
_MAX_LOG_RECORDS_PER_TASK = 1000
# Streamlit 은 백그라운드 스레드에서 위젯 갱신을 직접 밀어 넣을 수 없고 Fragment 폴링만
# 가능하다. 0.5 초면 WebUI 로그가 터미널 실시간 출력에 가깝게 따라오면서, 고빈도 갱신처럼
# 브라우저 자원을 계속 잡아먹지도 않는다.
TASK_LOG_REFRESH_INTERVAL_SECONDS = 0.5


def _append_task_log(task_id: str, message: str) -> None:
    """작업별로 제한된 양의 로그를 보관해, Streamlit Fragment 가 안전하게 폴링하도록 한다."""
    with _task_logs_lock:
        records = _task_logs.get(task_id)
        if records is None:
            # 최근 작업의 로그만 남겨, WebUI 서비스가 오래 돌아도 메모리를 계속 점유하지 않게 한다.
            # dict 는 삽입 순서를 유지한다. 작업 로그는 화면 진단용일 뿐이므로 가장 오래된
            # 기록을 밀어내도 작업에는 영향이 없다.
            if len(_task_logs) >= _MAX_LOG_TASKS:
                oldest_task_id = next(iter(_task_logs))
                _task_logs.pop(oldest_task_id, None)
            records = deque(maxlen=_MAX_LOG_RECORDS_PER_TASK)
            _task_logs[task_id] = records
        records.append(message.rstrip())


def get_task_logs(task_id: str) -> list[str]:
    """로그 스냅샷을 반환한다. 페이지를 그리는 동안 백그라운드 스레드가 쓰는 락을 쥐지 않기 위해서다."""
    with _task_logs_lock:
        return list(_task_logs.get(task_id, ()))


def _run_generation(
    task_id: str,
    params: VideoParams,
    capture_logs: bool,
    voice_preview: dict | None = None,
) -> dict:
    """
    기존 영상 파이프라인을 백그라운드 스레드에서 실행한다.

    Loguru 의 sink 는 프로세스 단위 자원이므로 현재 작업 스레드 기준으로 걸러야 한다.
    그러지 않으면 동시에 도는 API 작업이나 다른 페이지의 로그가 현재 작업에 섞인다.
    페이지는 평범한 리스트 스냅샷만 읽고 백그라운드 스레드에서 Streamlit session_state 에
    접근하지 않으므로, 새로고침 시 delta 경로가 꼬이는 문제를 근본적으로 피한다.
    """
    log_handler_id = None
    worker_thread_id = threading.get_ident()
    try:
        if capture_logs:
            log_handler_id = logger.add(
                lambda message: _append_task_log(task_id, str(message)),
                level="DEBUG",
                format=format_log_record,
                colorize=False,
                filter=lambda record: record["thread"].id == worker_thread_id,
            )

        # 전체 작업은 기존 설정 락을 그대로 쓴다. 다른 WebUI 세션이 생성 도중 Provider 나
        # 키 같은 프로세스 단위 설정을 바꿔, 같은 영상의 앞뒤가 서로 다른 설정으로
        # 만들어지는 것을 막기 위해서다.
        with config.runtime_config_lock():
            return tm.start(
                task_id=task_id,
                params=params,
                voice_preview=voice_preview,
            )
    except Exception as exc:
        # tm.start 가 파이프라인 예외를 실패 상태로 바꾸는 일은 이미 담당한다. 여기서는
        # 로그 sink, 설정 락 같은 WebUI 래퍼 계층을 추가로 보호한다. 백그라운드 스레드의
        # 어떤 예외든 반드시 최종 상태를 남겨야 하며, 작업 스레드가 끝난 뒤에도 작업
        # 관리자가 영원히 '생성 중' 을 표시하게 두어서는 안 된다.
        error = f"{type(exc).__name__}: {exc}"
        failure = {
            "task_id": task_id,
            "state": const.TASK_STATE_FAILED,
            "progress": 0,
            "failed_stage": "webui_worker",
            "error": error,
        }
        sm.state.update_task(
            task_id,
            state=failure["state"],
            progress=failure["progress"],
            failed_stage=failure["failed_stage"],
            error=failure["error"],
        )
        logger.exception(
            f"unexpected WebUI generation worker failure, "
            f"task_id={task_id}, error={exc}"
        )
        return failure
    finally:
        if log_handler_id is not None:
            try:
                logger.remove(log_handler_id)
            except ValueError:
                logger.debug(
                    f"WebUI task log handler already removed: task_id={task_id}"
                )


def submit_generation(
    task_id: str,
    params: VideoParams,
    capture_logs: bool = True,
    voice_preview: dict | None = None,
) -> None:
    """
    WebUI 영상 생성 작업을 등록·제출하고 즉시 반환한다.

    작업 상태는 반드시 스레드를 시작하기 전에 기록해야 한다. 그래야 이번 페이지 스크립트
    실행이 끝나는 시점에 작업을 조회할 수 있고, 브라우저 새로고침이나 WebSocket 재연결도
    예전 페이지 메모리의 자리표시자에 의존하지 않는다.

    이미 돌고 있는 작업이면 아무것도 하지 않는다. 두 번째 제출은 첫 번째를 빠르게
    만들지 않고, 같은 파일을 함께 덮어써 결과를 망칠 뿐이다. 자리 잡기와 판정은
    상태 계층의 한 연산으로 끝낸다. 나눠 하면 두 요청이 동시에 '비어 있다' 를 보고
    둘 다 시작한다.
    """
    task_params = params.model_copy(deep=True)
    # 미리보기 페이로드에는 변경되지 않는 오디오 경로, 파라미터 스냅샷, 읽기 전용 자막
    # 타임라인만 들어 있다. 최상위 딕셔너리를 복사해, 이후 페이지 rerun 이 캐시 필드를
    # 교체할 때 이미 백그라운드 큐에 제출된 작업에 영향을 주지 않게 한다.
    voice_preview_snapshot = dict(voice_preview) if voice_preview else None
    reserved = sm.state.begin_task_if_idle(
        task_id,
        video_subject=task_params.video_subject or task_params.video_script or task_id,
    )
    if not reserved:
        logger.warning(f"ignored a duplicate generation submit: task_id={task_id}")
        return

    try:
        _task_manager.add_task(
            _run_generation,
            task_id=task_id,
            params=task_params,
            capture_logs=capture_logs,
            voice_preview=voice_preview_snapshot,
        )
    except Exception as exc:
        # 스케줄 실패도 파이프라인 실패와 마찬가지로 조회 가능한 상태가 되어야 한다.
        # 작업 관리자가 영원히 '생성 중' 을 표시하지 않게 하기 위해서다. 예외 종류를 남겨
        # 두면 Docker 나 로컬 로그에서 큐 문제를 빠르게 짚을 수 있다.
        error = f"{type(exc).__name__}: {exc}"
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_FAILED,
            progress=0,
            failed_stage="scheduling",
            error=error,
        )
        logger.exception(
            f"failed to submit WebUI generation task, task_id={task_id}, error={exc}"
        )
        raise
