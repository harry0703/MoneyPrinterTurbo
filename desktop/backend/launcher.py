"""影创AI 桌面端后端启动器。

职责：
- 将配置与输出目录重定向到用户可写的数据目录（MPT_DATA_DIR）
- 首次运行完成配置/资源初始化
- 注入外部二进制（ffmpeg）路径
- 同时启动 Streamlit WebUI 与 FastAPI 后端
"""
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

APP_ID = "影创AI"
WEBUI_PORT = 8501
API_PORT = 8080


def user_data_dir() -> Path:
    """返回当前用户的应用数据目录（可写）。"""
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support" / APP_ID
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", home)) / APP_ID
    else:
        base = home / ".local" / "share" / APP_ID
    base.mkdir(parents=True, exist_ok=True)
    return base


def bundle_root() -> Path:
    """返回打包后的资源根目录（包含 app/webui/resource 等 data）。"""
    if getattr(sys, "frozen", False):
        # PyInstaller onedir：sys._MEIPASS 即数据所在目录
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def _legacy_data_dir() -> Path | None:
    """旧版数据目录（曾用 YingChuangAI 名），用于升级时迁移配置/资源。

    应用改名为“影创AI”后数据目录随之变化；若旧目录已有用户配置，
    把它迁移过来，避免 API Key 等配置像“丢失”一样需要重新填写。
    """
    if sys.platform != "darwin":
        return None
    legacy = Path.home() / "Library" / "Application Support" / "YingChuangAI"
    return legacy if legacy.is_dir() else None


def seed_data(data_dir: Path, bundle: Path) -> None:
    """首次运行：把可写配置模板与内置资源拷贝到数据目录、创建输出目录。

    若检测到旧数据目录（YingChuangAI）里已有用户配置，会优先迁移到当前目录，
    避免应用改名后 API Key 等配置“丢失”；资源目录缺项则按旧目录→包内顺序补齐。
    """
    legacy = _legacy_data_dir()

    target_config = data_dir / "config.toml"
    if not target_config.exists():
        # 优先迁移旧目录的用户配置，其次才使用打包内置模板。
        migrated = False
        if legacy is not None:
            legacy_config = legacy / "config.toml"
            if legacy_config.is_file():
                try:
                    shutil.copyfile(legacy_config, target_config)
                    migrated = True
                except OSError:
                    pass
        if not migrated:
            example = bundle / "config.example.toml"
            if example.is_file():
                try:
                    shutil.copyfile(example, target_config)
                except OSError:
                    pass

    (data_dir / "storage" / "tasks").mkdir(parents=True, exist_ok=True)

    # 把字体/音乐/静态资源复制到用户数据目录，避免运行时依赖包内只读路径。
    # 来源按“旧目录 → 包内”顺序，逐项复制且已存在即跳过，不覆盖用户资源。
    for sub in ("fonts", "songs", "public"):
        sources = []
        if legacy is not None:
            sources.append(legacy / "resource" / sub)
        sources.append(bundle / "resource" / sub)
        dst = data_dir / "resource" / sub
        for src in sources:
            if not src.is_dir():
                continue
            dst.mkdir(parents=True, exist_ok=True)
            for item in src.iterdir():
                target = dst / item.name
                if target.exists():
                    continue
                try:
                    if item.is_dir():
                        shutil.copytree(item, target)
                    else:
                        shutil.copyfile(item, target)
                except OSError:
                    pass


# 必须在导入 app 相关模块之前：设置数据目录并完成首次初始化，
# 否则 app.config 会在 config.toml 尚未生成时读取而抛异常。
os.environ["MPT_DATA_DIR"] = str(user_data_dir())
seed_data(user_data_dir(), bundle_root())

# 显式导入关键入口，帮助 PyInstaller 收集依赖图（打包期分析）
import app.asgi  # noqa: E402,F401
import streamlit  # noqa: E402,F401
import uvicorn  # noqa: E402,F401


def find_binary(bundle: Path, name: str) -> str:
    """优先使用捆绑的二进制，否则回退到系统 PATH。"""
    bundled = bundle / "bin" / name
    if bundled.is_file():
        return str(bundled)
    return shutil.which(name) or name


def start_streamlit(bundle: Path) -> None:
    from streamlit.web import cli as stcli

    # PyInstaller 冻结运行时 streamlit 的 __file__ 位于 _MEIPASS（不含
    # "site-packages"），其 global.developmentMode 会被误判为 True，进而
    # 与 --server.port 冲突报错。通过环境变量强制关闭，且端口/地址也走
    # 环境变量，避免 CLI 校验路径触发冲突。
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"
    os.environ["STREAMLIT_SERVER_ADDRESS"] = "127.0.0.1"
    os.environ["STREAMLIT_SERVER_PORT"] = str(WEBUI_PORT)
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

    main_py = bundle / "webui" / "Main.py"
    sys.argv = ["streamlit", "run", str(main_py)]
    stcli.main()


def start_api() -> None:
    uvicorn.run("app.asgi:app", host="127.0.0.1", port=API_PORT, log_level="warning")


def _port_in_use(port: int) -> bool:
    """探测 127.0.0.1 上指定端口是否已被监听。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.25)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def _listening_pids(port: int) -> list[int]:
    """列出监听指定端口(127.0.0.1)的进程 PID（平台相关）。"""
    pids: list[int] = []
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(
                ["/usr/sbin/lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except Exception:
            return pids
        for token in out.decode("utf-8", "replace").split():
            if token.strip().isdigit():
                pids.append(int(token.strip()))
    return pids


def _is_our_backend(pid: int) -> bool:
    """判断进程是否为本应用打包后端（命令行含特征标识）。"""
    try:
        out = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "command="],
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode("utf-8", "replace")
    except Exception:
        return False
    return "mpt-backend" in out or "backend-" in out


def _free_stale_backend() -> None:
    """若 8501/8080 被本应用残留后端占用，则终止它，确保本次干净启动。

    常见场景：上一次应用未完全退出（强制关闭/崩溃），其后端进程仍监听端口，
    导致本次 Streamlit/FastAPI 绑定失败，WebUI 页面出现 Internal Server Error。
    仅清理命令行带本应用后端特征的进程，避免误杀第三方服务。
    """
    for port in (WEBUI_PORT, API_PORT):
        for pid in _listening_pids(port):
            if pid != os.getpid() and _is_our_backend(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                    print(f"[launcher] terminated stale backend pid={pid} on port {port}")
                except OSError:
                    pass


def _monitor_api_ready(timeout: float = 25.0) -> bool:
    """轮询 FastAPI(8080) 是否已绑定监听，避免 WebUI 先于 API 就绪导致报错。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_in_use(API_PORT):
            return True
        time.sleep(0.4)
    return False


def main() -> None:
    bundle = bundle_root()

    # 启动即自愈：清理占端口的本应用残留后端，避免端口冲突导致半启动。
    _free_stale_backend()

    # 注入外部二进制
    os.environ["IMAGEIO_FFMPEG_EXE"] = find_binary(bundle, "ffmpeg")
    bin_dir = bundle / "bin"
    if bin_dir.is_dir():
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")

    # FastAPI 放后台线程，Streamlit 占用主线程。必须先等 FastAPI 就绪再起 WebUI，
    # 否则页面组件在 API 未就绪时调用 8080 而报 Internal Server Error。
    threading.Thread(target=start_api, daemon=True).start()
    if not _monitor_api_ready():
        print(
            "[launcher] ERROR: FastAPI failed to start on 127.0.0.1:"
            + str(API_PORT)
            + " . Aborting."
        )
        sys.exit(1)
    start_streamlit(bundle)


if __name__ == "__main__":
    main()
