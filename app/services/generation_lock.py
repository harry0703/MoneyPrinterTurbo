"""
进程间视频生成互斥锁。

WebUI 自身已经把并发数限制为 1，但 CLI、API 和 WebUI 属于不同进程，
各自的队列互不可见。同一台机器上同时跑两条完整流水线会争抢 CPU、内存
和 FFmpeg 临时目录，在低配机器上还会让两个任务一起变慢甚至失败。

这里用文件锁把"同一时刻只允许一条生成流水线"提升为主机级约束：
1. 锁由操作系统持有，进程崩溃或被 kill 时自动释放，不会留下死锁；
2. 锁文件里记录持有者信息，失败信息可以直接告诉用户是谁在跑。
"""

import os
import socket
import time
from contextlib import contextmanager

from loguru import logger

from app.utils import utils

_LOCK_FILENAME = ".generation.lock"


class GenerationBusyError(RuntimeError):
    """另一条生成流水线正在运行时抛出。"""


def lock_path() -> str:
    return os.path.join(utils.storage_dir(create=True), _LOCK_FILENAME)


def _describe_self() -> str:
    return (
        f"host={socket.gethostname()} pid={os.getpid()} "
        f"since={time.strftime('%Y-%m-%d %H:%M:%S')}"
    )


def _read_owner(path: str) -> str:
    """尽力读取当前持有者信息；读不到不影响加锁结果。"""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _try_acquire(handle) -> bool:
    """非阻塞加锁。成功返回 True，已被占用返回 False。"""
    if os.name == "nt":
        import msvcrt

        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _release(handle) -> None:
    if os.name == "nt":
        import msvcrt

        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError as exc:
            logger.warning(f"failed to release generation lock: {exc}")
        return

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        logger.warning(f"failed to release generation lock: {exc}")


@contextmanager
def acquire():
    """
    获取主机级生成锁，失败时抛出 ``GenerationBusyError``。

    刻意使用非阻塞加锁：让第二个请求立刻得到明确的"正在生成"提示，
    比让它静默排队更容易理解，也不会让 WebUI 线程长时间挂起。
    """
    path = lock_path()
    handle = open(path, "a+", encoding="utf-8")
    try:
        if not _try_acquire(handle):
            owner = _read_owner(path)
            detail = f" ({owner})" if owner else ""
            raise GenerationBusyError(
                "another video generation is already running on this machine"
                f"{detail}; wait for it to finish before starting a new one"
            )

        try:
            handle.seek(0)
            handle.truncate()
            handle.write(_describe_self())
            handle.flush()
        except OSError as exc:
            # 记录持有者信息只是为了排障，写失败不应阻止真正的生成任务。
            logger.warning(f"failed to write generation lock owner: {exc}")

        logger.info("acquired generation lock")
        try:
            yield
        finally:
            _release(handle)
            logger.info("released generation lock")
    finally:
        handle.close()
