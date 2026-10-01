import functools
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
# Loguru 启动时默认终端 handler 的 ID 为 0。WebUI 重新加载时只能替换这个
# 基础终端输出，不能调用 logger.remove() 清空全部 handler，否则正在运行任务
# 用于收集 WebUI 日志的临时 sink 也会被删除。
_terminal_handler_id: int | None = 0
_terminal_handler_lock = threading.RLock()
# WebUI 按任务工作线程的 ID 过滤日志。任务为并行下载、片段编码和心跳启动的
# 辅助线程有各自的线程 ID，它们写出的日志会被整条丢弃，结果耗时最长的阶段
# 在 WebUI 里反而没有任何输出。这里记录“辅助线程 -> 发起它的线程”的映射，
# 让日志过滤器可以把辅助线程的记录归回所属任务。
_log_scope_roots: dict[int, int] = {}
_log_scope_lock = threading.Lock()


def log_scope_thread_id(thread_id: int | None = None) -> int:
    """返回线程所属日志作用域的根线程 ID；未绑定的线程就是它自己。"""
    if thread_id is None:
        thread_id = threading.get_ident()
    with _log_scope_lock:
        return _log_scope_roots.get(thread_id, thread_id)


def bind_log_scope(func):
    """
    包装一个将在其它线程执行的函数，使其日志归属调用本函数的线程。

    必须在提交任务的线程里调用：作用域在包装时确定，辅助线程再启动的线程
    也会归到最初的任务线程。执行结束后解除绑定，因为线程 ID 会被系统复用，
    残留映射会把之后无关线程的日志算进已经结束的任务。
    """
    root_thread_id = log_scope_thread_id()

    @functools.wraps(func)
    def run_in_log_scope(*args, **kwargs):
        thread_id = threading.get_ident()
        if thread_id == root_thread_id:
            return func(*args, **kwargs)

        with _log_scope_lock:
            previous_root = _log_scope_roots.get(thread_id)
            _log_scope_roots[thread_id] = root_thread_id
        try:
            return func(*args, **kwargs)
        finally:
            with _log_scope_lock:
                # 线程池会复用线程：恢复进入前的归属，而不是一律删除，避免
                # 嵌套包装提前清掉外层仍在使用的绑定。
                if previous_root is None:
                    _log_scope_roots.pop(thread_id, None)
                else:
                    _log_scope_roots[thread_id] = previous_root

    return run_in_log_scope


def _project_relative_path(file_path):
    """
    把绝对路径缩短为 ``./`` 开头、始终使用正斜杠的项目相对路径。

    Windows 上项目可能通过映射网络盘或 ``subst`` 盘启动。此时调用栈里的路径
    仍是 ``X:\\MoneyPrinterTurbo\\...``，而 ``PROJECT_ROOT`` 经 ``realpath``
    解析后落在 ``C:\\...``，``os.path.relpath`` 会直接抛出 ``ValueError``。
    格式化函数抛错会被 loguru 捕获并丢弃整条记录，终端和 WebUI 日志面板会
    同时变空，因此这里必须兜底返回原始路径。项目目录之外的文件同理：把
    ``./`` 拼到 ``..`` 回溯路径上只会得到更难读的结果。
    """
    try:
        relative_path = os.path.relpath(file_path, PROJECT_ROOT)
    except ValueError:
        return file_path
    if relative_path == os.pardir or relative_path.startswith(os.pardir + os.sep):
        return file_path
    # Windows 的 relpath 返回反斜杠分隔的路径，直接拼接会得到 ``./app\\utils``
    # 这种混合分隔符的输出，与其它平台的日志不一致。
    return f"./{relative_path.replace(os.sep, '/')}"


def format_log_record(record):
    """
    统一格式化终端与 WebUI 日志。

    Loguru 会把同一条记录交给多个 sink。第一个 sink 可能已经将绝对路径转换
    为项目相对路径，因此这里同时兼容绝对路径和 ``./`` 开头的已格式化路径。
    WebUI sink 会关闭颜色，但时间、级别、调用位置和消息内容与终端保持一致。
    """
    file_path = record["file"].path
    if os.path.isabs(file_path):
        record["file"].path = _project_relative_path(file_path)

    # 日志消息有时会包含任务文件的绝对路径。统一缩短为项目相对路径，可以
    # 避免 WebUI 和终端因初始化入口不同而展示两套内容。
    record["message"] = record["message"].replace(PROJECT_ROOT, ".")
    return LOG_RECORD_FORMAT


def configure_terminal_logger(sink, level: str, colorize: bool = True) -> int:
    """
    安全替换进程级终端日志 handler，并保留任务专用 handler。

    Streamlit 在代码热重载或缓存失效时可能重新执行日志初始化。这里只按已记录
    的 handler ID 精确移除旧终端输出，因此不会中断后台任务正在写入的 WebUI
    日志。锁用于保护多个浏览器会话同时初始化时的 ID 更新。
    """
    global _terminal_handler_id

    with _terminal_handler_lock:
        if _terminal_handler_id is not None:
            try:
                logger.remove(_terminal_handler_id)
            except ValueError:
                # 测试或外部入口可能已经移除该 handler。继续创建新的终端输出，
                # 不需要影响其它仍有效的日志 sink。
                pass

        _terminal_handler_id = logger.add(
            sink,
            level=level,
            format=format_log_record,
            colorize=colorize,
        )
        return _terminal_handler_id
