"""桌面窗口专用的本地 Streamlit 入口。"""

import os
import signal
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn
from imageio_ffmpeg import get_ffmpeg_exe
from streamlit import App, config

from app import desktop_storage, paths


def _watch_desktop(server: uvicorn.Server, ready_file: Path) -> None:
    if sys.platform == "win32":
        # 阻塞读取 Windows 标准输入会卡住 NumPy 的 DLL 加载（numpy/numpy#24290）。
        shutdown_file = ready_file.with_name("shutdown")
        while not shutdown_file.exists():
            time.sleep(0.1)
        server.should_exit = True
        return
    sys.stdin.buffer.read(1)
    # 关闭同一进程组里的 Python 和 FFmpeg。
    pid = os.getpid()
    if os.getpgrp() == pid:
        os.killpg(pid, signal.SIGTERM)
    else:
        os.kill(pid, signal.SIGTERM)


def run(ready_file: Path) -> None:
    os.environ["MPT_DESKTOP"] = "1"
    desktop_storage.configure_at_startup(os.environ.get("MPT_DESKTOP_STORAGE_DEFAULT", ""))
    media_tools = Path(__file__).resolve().with_name("tools")
    ffmpeg = media_tools / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if ffmpeg.is_file():
        # MoviePy 使用绝对路径，pydub 等调用方则通过 PATH 查找 ffprobe。
        os.environ["PATH"] = str(media_tools) + os.pathsep + os.environ.get("PATH", "")
        os.environ.setdefault("IMAGEIO_FFMPEG_EXE", str(ffmpeg))
    else:
        os.environ.setdefault("IMAGEIO_FFMPEG_EXE", get_ffmpeg_exe())
    for key, value in {
        "server.address": "127.0.0.1",
        "server.allowedHosts": ["127.0.0.1"],
        "server.enableCORS": True,
        "server.enableXsrfProtection": True,
        "server.fileWatcherType": "none",
        "server.headless": True,
        "browser.gatherUsageStats": False,
        "client.toolbarMode": "minimal",
    }.items():
        config.set_option(key, value)

    # 先占住系统分配的端口，再把同一个 socket 交给 Uvicorn，避免选端口时发生竞争。
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        config.set_option("server.port", port)
        app = App(paths.SOURCE_ROOT / "webui" / "Main.py")
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False)
        )
        temporary = ready_file.with_suffix(".tmp")
        temporary.write_text(str(port), encoding="ascii")
        temporary.replace(ready_file)
        threading.Thread(
            target=_watch_desktop, args=(server, ready_file), daemon=True
        ).start()
        server.run(sockets=[listener])


if __name__ == "__main__":
    run(Path(sys.argv[1]))
