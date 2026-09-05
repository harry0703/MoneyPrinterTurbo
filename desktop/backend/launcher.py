"""影创AI 桌面端后端启动器。

职责：
- 将配置与输出目录重定向到用户可写的数据目录（MPT_DATA_DIR）
- 首次运行完成配置/资源初始化
- 注入外部二进制（ffmpeg）路径
- 同时启动 Streamlit WebUI 与 FastAPI 后端
"""
import os
import shutil
import sys
import threading
from pathlib import Path

APP_ID = "YingChuangAI"
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


def seed_data(data_dir: Path, bundle: Path) -> None:
    """首次运行：把可写配置模板与内置资源拷贝到数据目录、创建输出目录。"""
    example = bundle / "config.example.toml"
    if example.is_file():
        target = data_dir / "config.toml"
        if not target.exists():
            try:
                shutil.copyfile(example, target)
            except OSError:
                pass
    (data_dir / "storage" / "tasks").mkdir(parents=True, exist_ok=True)

    # 把打包内置的字体/音乐/静态资源复制到用户数据目录，避免运行时依赖包内
    # 只读路径。逐项复制且已存在即跳过，不覆盖用户后续放入的同名资源。
    for sub in ("fonts", "songs", "public"):
        src = bundle / "resource" / sub
        dst = data_dir / "resource" / sub
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


def main() -> None:
    bundle = bundle_root()

    # 注入外部二进制
    os.environ["IMAGEIO_FFMPEG_EXE"] = find_binary(bundle, "ffmpeg")
    bin_dir = bundle / "bin"
    if bin_dir.is_dir():
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")

    # FastAPI 放后台线程，Streamlit 占用主线程
    threading.Thread(target=start_api, daemon=True).start()
    start_streamlit(bundle)


if __name__ == "__main__":
    main()
