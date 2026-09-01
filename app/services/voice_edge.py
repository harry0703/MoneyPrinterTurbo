"""Edge TTS provider (``azure_tts_v1`` in the dispatcher's naming)."""

import asyncio
import inspect
import os
import queue
import threading
import time
from typing import Union

import edge_tts
from loguru import logger

from app.config import config
from app.services.voice_common import (
    convert_rate_to_percent,
    ensure_file_path_exists,
    parse_voice_name,
)

_DEFAULT_EDGE_TTS_TIMEOUT_SECONDS = 30.0


def create_edge_tts_communicate(
    text: str, voice_name: str, rate_str: str
) -> edge_tts.Communicate:
    """
    按当前已安装的 edge_tts 版本构造 Communicate 对象。

    背景：
    1. 主线代码已经升级到 edge_tts 7.x，并使用 `boundary` 参数拿到更细的边界事件；
    2. 但 Windows 便携包如果更新失败，现场环境可能仍然停留在旧版 edge_tts；
    3. 旧版 `Communicate.__init__()` 不接受 `boundary`，会直接抛出
       `unexpected keyword argument 'boundary'`，导致整个 TTS 链路失败。

    因此这里先根据构造函数签名探测当前版本支持的参数，再决定是否传入
    `boundary`，让同一份代码同时兼容旧版和新版依赖。
    """
    communicate_kwargs = {"rate": rate_str}
    communicate_signature = inspect.signature(edge_tts.Communicate)

    if "boundary" in communicate_signature.parameters:
        communicate_kwargs["boundary"] = "WordBoundary"

    return edge_tts.Communicate(text, voice_name, **communicate_kwargs)


def get_edge_tts_timeout_seconds() -> Union[float, None]:
    """
    获取 Azure TTS V1 单次流式请求的超时时间。

    背景：
    Edge consumer TTS 在网络不通、服务端限流、voice 与文本语言不匹配等场景下，
    可能长时间卡在 `stream_sync()` 内部，日志只停留在 `start`。这里提供一个
    默认超时，避免 WebUI 任务长期无反馈。

    使用方式：
    - 默认 30 秒，覆盖常见短视频脚本的首包等待时间；
    - 如用户处于慢网络或代理环境，可在 `config.toml` 里设置
      `edge_tts_timeout = 60`；
    - 设置为 0 或负数表示显式禁用超时，保留完全向后兼容。
    """
    raw_timeout = config.app.get(
        "edge_tts_timeout", _DEFAULT_EDGE_TTS_TIMEOUT_SECONDS
    )
    try:
        timeout_seconds = float(raw_timeout)
    except (TypeError, ValueError):
        logger.warning(
            "invalid edge_tts_timeout: "
            f"{raw_timeout}, fallback to {_DEFAULT_EDGE_TTS_TIMEOUT_SECONDS}s"
        )
        timeout_seconds = _DEFAULT_EDGE_TTS_TIMEOUT_SECONDS

    if timeout_seconds <= 0:
        return None

    return timeout_seconds


def _stream_edge_tts_sync_with_timeout(
    communicate, on_chunk, timeout_seconds: float
) -> None:
    """
    带总超时地消费 edge_tts 7.x 的同步流。

    实现原因：
    `stream_sync()` 本身是阻塞迭代器，网络层卡住时主线程无法及时恢复。
    这里把阻塞迭代放到 daemon 线程中，主线程通过 Queue 获取 chunk，
    到达超时时间后直接抛出 TimeoutError，让外层重试和错误日志继续工作。

    注意：
    daemon 线程只作为兜底保护使用，最多随 Azure TTS V1 的 3 次重试产生
    少量残留线程；进程退出时会自动回收。相比 WebUI 任务永久卡住，这是
    更可控的失败模式。
    """
    stream_queue = queue.Queue()
    done_marker = object()

    def _produce_chunks():
        try:
            for chunk in communicate.stream_sync():
                stream_queue.put(("chunk", chunk))
            stream_queue.put(("done", done_marker))
        except Exception as e:
            stream_queue.put(("error", e))

    thread = threading.Thread(target=_produce_chunks, daemon=True)
    thread.start()

    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            raise TimeoutError(
                f"edge_tts stream timed out after {timeout_seconds:g}s"
            )

        try:
            item_type, payload = stream_queue.get(
                timeout=min(0.5, remaining_seconds)
            )
        except queue.Empty:
            continue

        if item_type == "chunk":
            on_chunk(payload)
        elif item_type == "error":
            raise payload
        elif item_type == "done":
            return


def stream_edge_tts_chunks(
    communicate, on_chunk, timeout_seconds: Union[float, None] = None
) -> None:
    """
    统一消费 edge_tts 的同步流和旧版异步流。

    edge_tts 7.x 提供 `stream_sync()`，可以在同步函数里直接迭代；
    更早的版本通常只有异步 `stream()`。为了让 `azure_tts_v1()` 在
    旧依赖残留场景下仍能继续工作，这里统一做一层流式兼容。

    Args:
        communicate: edge_tts.Communicate 实例
        on_chunk: 每拿到一个事件块时执行的回调
        timeout_seconds: 单次流式请求总超时；为 None 时不启用超时。
    """
    if hasattr(communicate, "stream_sync"):
        if timeout_seconds:
            _stream_edge_tts_sync_with_timeout(
                communicate, on_chunk, timeout_seconds
            )
            return

        for chunk in communicate.stream_sync():
            on_chunk(chunk)
        return

    if not hasattr(communicate, "stream"):
        raise AttributeError("edge_tts communicate object has no stream method")

    async def _consume_async_stream():
        async for chunk in communicate.stream():
            on_chunk(chunk)

    # 这里显式创建独立事件循环，而不是复用外部上下文，目的是避免
    # 在同步调用栈里遇到“当前线程没有事件循环”或跨线程复用循环的问题。
    loop = asyncio.new_event_loop()
    try:
        if timeout_seconds:
            loop.run_until_complete(
                asyncio.wait_for(_consume_async_stream(), timeout=timeout_seconds)
            )
        else:
            loop.run_until_complete(_consume_async_stream())
    finally:
        loop.close()


def azure_tts_v1(
    text: str, voice_name: str, voice_rate: float, voice_file: str
) -> Union[edge_tts.SubMaker, None]:
    voice_name = parse_voice_name(voice_name)
    text = text.strip()
    rate_str = convert_rate_to_percent(voice_rate)
    for i in range(3):
        try:
            logger.info(f"start, voice name: {voice_name}, try: {i + 1}")

            # 这里同时兼容 edge_tts 7.x 和旧版便携包里可能残留的老依赖：
            # 1. 新版支持 `boundary` + `stream_sync()`
            # 2. 旧版不支持 `boundary`，且通常只暴露异步 `stream()`
            ensure_file_path_exists(voice_file)
            communicate = create_edge_tts_communicate(text, voice_name, rate_str)
            sub_maker = edge_tts.SubMaker()
            timeout_seconds = get_edge_tts_timeout_seconds()

            with open(voice_file, "wb") as file:
                def _handle_chunk(chunk):
                    chunk_type = chunk["type"]
                    if chunk_type == "audio":
                        file.write(chunk["data"])
                    elif chunk_type in ["WordBoundary", "SentenceBoundary"]:
                        # 无论来自 7.x 的同步流，还是旧版异步流，只要事件结构
                        # 里仍有边界信息，就统一喂给 SubMaker，保证后续字幕链路
                        # 仍然走项目现有逻辑。
                        sub_maker.feed(chunk)

                stream_edge_tts_chunks(
                    communicate, _handle_chunk, timeout_seconds=timeout_seconds
                )

            if not sub_maker.get_srt():
                logger.warning("failed, sub_maker.get_srt() is empty")
                continue

            logger.info(f"completed, output file: {voice_file}")
            return sub_maker
        except Exception as e:
            logger.error(f"failed, error: {str(e)}")
            # TTS 流式写入如果在首包前超时或网络异常，会留下 0 字节音频文件。
            # 这种文件既不可播放，也可能误导后续排查，因此失败后只清理空文件；
            # 如果已经写入了部分数据，则保留现场文件，便于分析服务端返回内容。
            if os.path.exists(voice_file) and os.path.getsize(voice_file) == 0:
                try:
                    os.remove(voice_file)
                except Exception as remove_error:
                    logger.warning(
                        "failed to remove empty tts file: "
                        f"{voice_file}, error: {str(remove_error)}"
                    )
    return None
