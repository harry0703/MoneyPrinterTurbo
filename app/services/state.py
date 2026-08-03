import ast
import copy
import threading
from abc import ABC, abstractmethod

from app.config import config
from app.models import const


_BEGIN_TASK_IF_IDLE_SCRIPT = """
if redis.call("HGET", KEYS[1], "state") == ARGV[1] then
    return 0
end

-- 지난 실행이 남긴 영상 목록, 오류, 업로드 상태를 함께 지운다. HSET 만 하면 이번
-- 실행과 상관없는 필드가 그대로 붙어 있어, 기록이 실제 결과와 어긋난다.
redis.call("DEL", KEYS[1])

for index = 2, #ARGV, 2 do
    redis.call("HSET", KEYS[1], ARGV[index], ARGV[index + 1])
end

return 1
"""


_PATCH_EXISTING_TASK_SCRIPT = """
if redis.call("EXISTS", KEYS[1]) == 0 then
    return 0
end

for index = 1, #ARGV, 2 do
    redis.call("HSET", KEYS[1], ARGV[index], ARGV[index + 1])
end

return 1
"""


# Base class for state management
class BaseState(ABC):
    @abstractmethod
    def update_task(self, task_id: str, state: int, progress: int = 0, **kwargs):
        pass

    @abstractmethod
    def get_task(self, task_id: str):
        pass

    @abstractmethod
    def get_all_tasks(self, page: int, page_size: int):
        pass

    @abstractmethod
    def patch_task(self, task_id: str, **kwargs) -> bool:
        """이미 존재하는 작업의 지정 필드만 갱신한다. 작업이 없으면 False 를 반환한다."""
        pass

    @abstractmethod
    def begin_task_if_idle(self, task_id: str, **kwargs) -> bool:
        """
        진행 중이 아닐 때만 작업을 '진행 중' 으로 바꾸고 ``True`` 를 반환한다.

        확인과 기록이 나뉘어 있으면 두 요청이 동시에 '진행 중이 아니다' 를 보고
        둘 다 시작한다. 그러면 같은 출력 파일에 두 개가 쓴다. 판정과 기록을 한
        연산으로 묶어야 한 쪽만 통과한다.
        """
        pass


# Memory state management
class MemoryState(BaseState):
    def __init__(self):
        self._tasks = {}
        self._lock = threading.RLock()

    def get_all_tasks(self, page: int, page_size: int):
        start = (page - 1) * page_size
        end = start + page_size
        with self._lock:
            tasks = [copy.deepcopy(task) for task in self._tasks.values()]
            total = len(tasks)
        return tasks[start:end], total

    def update_task(
        self,
        task_id: str,
        state: int = const.TASK_STATE_PROCESSING,
        progress: int = 0,
        **kwargs,
    ):
        progress = int(progress)
        if progress > 100:
            progress = 100

        with self._lock:
            self._tasks[task_id] = {
                "task_id": task_id,
                "state": state,
                "progress": progress,
                **kwargs,
            }

    def get_task(self, task_id: str):
        with self._lock:
            task = self._tasks.get(task_id, None)
            return copy.deepcopy(task) if task is not None else None

    def patch_task(self, task_id: str, **kwargs) -> bool:
        # 비동기 업로드는 업로드 상태만 덧붙여야 하며, 이미 저장된 영상·자막 결과를
        # 덮어써서는 안 된다. 존재 확인과 필드 병합을 같은 락 안에서 끝내면 작업이
        # 삭제된 뒤 백그라운드 스레드가 다시 만들어 내는 것도 막을 수 있다.
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.update(copy.deepcopy(kwargs))
            return True

    def begin_task_if_idle(self, task_id: str, **kwargs) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None and task.get("state") == const.TASK_STATE_PROCESSING:
                return False
            self._tasks[task_id] = {
                "task_id": task_id,
                "state": const.TASK_STATE_PROCESSING,
                "progress": 0,
                **kwargs,
            }
            return True

    def delete_task(self, task_id: str):
        with self._lock:
            self._tasks.pop(task_id, None)


# Redis state management
class RedisState(BaseState):
    """
    Redis-backed task state.

    Trust boundary: Redis is expected to be private to this application. Task
    values are written by shipcast and converted back from strings for
    compatibility with existing state records. Do not expose this Redis database
    to untrusted writers without replacing deserialization with a stricter
    schema-based format.
    """

    def __init__(self, host="localhost", port=6379, db=0, password=None):
        import redis

        self._redis = redis.StrictRedis(host=host, port=port, db=db, password=password)

    def get_all_tasks(self, page: int, page_size: int):
        start = (page - 1) * page_size
        end = start + page_size
        tasks = []
        cursor = 0
        total = 0
        while True:
            # Redis 데이터베이스에는 작업 Hash 말고도 RedisTaskManager 가 쓰는 List 대기열이
            # 있을 수 있다. Hash 만 스캔하면 대기열에 HGETALL 을 실행해 WRONGTYPE 이 나는 것을
            # 피하면서, total 이 실제 작업 레코드만 세도록 보장할 수 있다.
            cursor, keys = self._redis.scan(
                cursor,
                count=page_size,
                _type="HASH",
            )
            batch_start = total
            batch_size = len(keys)
            total += batch_size

            # Redis SCAN 은 key 를 배치 단위로 반환한다. 페이지 슬라이스는 반드시 '현재 배치의
            # 시작 인덱스' 를 기준으로 계산해야 하며, 누적된 total 로 역산하면 첫 페이지가 빈
            # 배열이 되고 두 번째 페이지도 일부 데이터만 반환될 수 있다.
            if batch_start < end and total > start:
                slice_start = max(0, start - batch_start)
                slice_end = min(batch_size, end - batch_start)
                for key in keys[slice_start:slice_end]:
                    task_data = self._redis.hgetall(key)
                    task = {
                        k.decode("utf-8"): self._convert_to_original_type(v)
                        for k, v in task_data.items()
                    }
                    tasks.append(task)

            # 현재 페이지가 다 찼더라도 cursor=0 이 될 때까지 SCAN 을 계속해야 한다.
            # 호출자가 페이지 정보를 그리려면 정확한 total 이 필요하기 때문이다.
            if cursor == 0:
                break
        return tasks, total

    def update_task(
        self,
        task_id: str,
        state: int = const.TASK_STATE_PROCESSING,
        progress: int = 0,
        **kwargs,
    ):
        progress = int(progress)
        if progress > 100:
            progress = 100

        fields = {
            "task_id": task_id,
            "state": state,
            "progress": progress,
            **kwargs,
        }

        for field, value in fields.items():
            self._redis.hset(task_id, field, str(value))

    def get_task(self, task_id: str):
        task_data = self._redis.hgetall(task_id)
        if not task_data:
            return None

        task = {
            key.decode("utf-8"): self._convert_to_original_type(value)
            for key, value in task_data.items()
        }
        return task

    def patch_task(self, task_id: str, **kwargs) -> bool:
        if not kwargs:
            return False

        arguments = []
        for field, value in kwargs.items():
            arguments.extend((field, str(value)))

        # EXISTS 와 HSET 을 두 명령으로 나누면, 백그라운드 업로드 스레드와 삭제 요청이
        # 동시에 들어올 때 HSET 이 삭제 뒤에 불완전한 작업을 다시 만들 수 있다. Lua 스크립트는
        # Redis 가 원자적으로 실행하므로, 작업이 없으면 쓰지 않고 기존 필드 외의 데이터도
        # 바꾸지 않는다.
        updated = self._redis.eval(
            _PATCH_EXISTING_TASK_SCRIPT,
            1,
            task_id,
            *arguments,
        )
        return bool(updated)

    def begin_task_if_idle(self, task_id: str, **kwargs) -> bool:
        fields = {
            "task_id": task_id,
            "state": const.TASK_STATE_PROCESSING,
            "progress": 0,
            **kwargs,
        }
        arguments = [str(const.TASK_STATE_PROCESSING)]
        for field, value in fields.items():
            arguments.extend([field, str(value)])

        # 판정과 기록을 서버 쪽 스크립트 한 번으로 끝낸다. 두 요청이 동시에 들어와도
        # 한 쪽만 1 을 받는다.
        return bool(
            self._redis.eval(_BEGIN_TASK_IF_IDLE_SCRIPT, 1, task_id, *arguments)
        )

    def delete_task(self, task_id: str):
        self._redis.delete(task_id)

    @staticmethod
    def _convert_to_original_type(value):
        """
        Convert values written by this application back to common Python types.

        This compatibility parser assumes Redis is inside the application's
        trust boundary. If Redis can be written by untrusted clients, task state
        should move to a strict JSON/schema parser instead of open-ended literal
        conversion.
        """
        value_str = value.decode("utf-8")

        try:
            # try to convert byte string array to list
            return ast.literal_eval(value_str)
        except (ValueError, SyntaxError):
            pass

        if value_str.isdigit():
            return int(value_str)
        # Add more conversions here if needed
        return value_str


# Global state
_enable_redis = config.app.get("enable_redis", False)
_redis_host = config.app.get("redis_host", "localhost")
_redis_port = config.app.get("redis_port", 6379)
_redis_db = config.app.get("redis_db", 0)
_redis_password = config.app.get("redis_password", None)

state = (
    RedisState(
        host=_redis_host, port=_redis_port, db=_redis_db, password=_redis_password
    )
    if _enable_redis
    else MemoryState()
)
