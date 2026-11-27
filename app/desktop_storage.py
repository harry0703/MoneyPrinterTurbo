"""桌面端存储目录的选择与启动配置。"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from loguru import logger

from app import paths


def preference_file() -> Path:
    return paths.runtime_root() / "desktop-storage.txt"


def configured_directory() -> Path | None:
    try:
        value = preference_file().read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    path = Path(value)
    return path if path.is_absolute() else None


def writable_directory(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("storage directory must be absolute")
    try:
        path = path.resolve()
    except RuntimeError as error:
        # Python 3.11 将循环符号链接报告为 RuntimeError。
        raise ValueError("storage directory cannot be resolved") from error
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path, prefix=".mpt-write-"):
        pass
    return path


def configure_at_startup(default: str) -> None:
    configured = configured_directory()
    # 外置磁盘未连接或目录失效时优先启动应用，用户仍能在设置中修正路径。
    for candidate in (configured, default, paths.runtime_root() / "storage"):
        if not candidate:
            continue
        try:
            storage = writable_directory(candidate)
            temporary = writable_directory(storage / "temp")
        except (OSError, ValueError):
            logger.warning("桌面存储目录不可写，尝试下一个位置。")
            continue
        os.environ["MPT_DESKTOP_STORAGE_DIR"] = str(storage)
        tempfile.tempdir = str(temporary)
        return
    raise OSError("没有可写入的桌面存储目录")


def save_directory(value: str) -> Path:
    path = writable_directory(value.strip())
    writable_directory(path / "temp")
    destination = preference_file()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, prefix=".storage-", delete=False, mode="w", encoding="utf-8"
    ) as file:
        pending = Path(file.name)
        file.write(str(path))
    try:
        pending.replace(destination)
    finally:
        pending.unlink(missing_ok=True)
    return path


def open_directory(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)
    else:
        command = "/usr/bin/open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([command, str(path)])


def can_pick_directory() -> bool:
    return sys.platform in {"darwin", "win32"} or shutil.which("zenity") is not None


def pick_directory(current: Path) -> str:
    if sys.platform == "darwin":
        command = [
            "/usr/bin/osascript", "-e", "on run argv",
            "-e", 'return POSIX path of (choose folder with prompt "MoneyPrinterTurbo Storage" default location (POSIX file (item 1 of argv)))',
            "-e", "end run", str(current),
        ]
    elif sys.platform == "win32":
        script = """
        Add-Type -AssemblyName System.Windows.Forms
        [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
        $dialog = New-Object Windows.Forms.FolderBrowserDialog
        try {
            $dialog.Description = 'MoneyPrinterTurbo Storage'
            $dialog.SelectedPath = $env:MPT_FOLDER_PICKER_START
            if ($dialog.ShowDialog() -eq 'OK') { [Console]::WriteLine($dialog.SelectedPath) }
        } finally { $dialog.Dispose() }
        """
        command = ["powershell.exe", "-NoProfile", "-STA", "-Command", script]
    else:
        command = ["zenity", "--file-selection", "--directory", "--filename", str(current) + "/"]
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    result = subprocess.run(
        command, env={**os.environ, "MPT_FOLDER_PICKER_START": str(current)},
        capture_output=True, encoding="utf-8", **options,
    )
    return result.stdout.rstrip("\r\n") if result.returncode == 0 else ""
