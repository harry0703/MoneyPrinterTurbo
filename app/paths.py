"""统一源码版和安装版的资源、配置及运行数据目录。"""

import errno
import os
import shutil
import sys
import tempfile
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows 没有 fcntl；占位锁与清扫在这类环境保守跳过。
    fcntl = None


SOURCE_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_ROOT = Path(__file__).resolve().parent / "_assets"

# 补齐内置资源时的隐藏占位命名前缀，随机后缀由 mkstemp 生成：占位永远
# 不占用最终资源名，且可被启动清扫按同一模式识别。
RESERVATION_PREFIX = ".resource-"


def is_source_checkout() -> bool:
    return (SOURCE_ROOT / "pyproject.toml").is_file() and (
        SOURCE_ROOT / "cli.py"
    ).is_file()


def runtime_root() -> Path:
    """源码沿用项目目录；安装版使用用户目录，也允许显式指定 MPT_HOME。"""
    override = os.environ.get("MPT_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if is_source_checkout():
        return SOURCE_ROOT
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MoneyPrinterTurbo"
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        if not base.is_absolute():
            base = Path.home() / ".local" / "share"
    return base / "MoneyPrinterTurbo"


def config_template() -> Path:
    base = SOURCE_ROOT if is_source_checkout() else BUNDLED_ROOT
    return base / "config.example.toml"


def _hold_reservation(fd: int) -> None:
    """独占锁定占位文件，标记写入者存活；进程崩溃后锁由内核释放。"""
    if fcntl is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # 个别文件系统不支持文件锁：清扫会因同样拿不到锁而保守跳过。
        pass


def _sweep_stale_reservations(directory: Path) -> None:
    """清扫崩溃写入者留下的占位文件；无法确认失效的占位一律保留。"""
    if fcntl is None:
        return
    for stale in directory.glob(f"{RESERVATION_PREFIX}*"):
        fd = None
        try:
            fd = os.open(stale, os.O_RDONLY)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.unlink(stale)
        except OSError:
            # 拿不到锁说明写入者仍然存活（或文件系统不支持锁），保留占位。
            continue
        finally:
            if fd is not None:
                os.close(fd)


def _copy_missing_resource(source: Path, target: Path) -> None:
    """原子补齐内置资源；并发启动和升级都不覆盖用户已有的文件。"""
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=RESERVATION_PREFIX, dir=target.parent)
    destination = None
    try:
        _hold_reservation(fd)
        # 占位句柄保持打开到发布结束：锁标记写入者存活，避免并发清扫误删。
        destination = os.fdopen(fd, "wb")
        with source.open("rb") as origin:
            shutil.copyfileobj(origin, destination)
        try:
            # Windows rename 拒绝覆盖；POSIX 使用硬链接实现同样的独占发布。
            if os.name == "nt":
                os.rename(temporary, target)
            else:
                os.link(temporary, target)
        except FileExistsError:
            pass
        except OSError as exc:
            # exFAT/FAT 及部分网络挂载不支持硬链接，link(2) 返回 EPERM/ENOTSUP；
            # 资源补齐是启动必经路径，降级为临时名占位 + 原子换入完成同样的发布。
            if exc.errno not in (errno.EPERM, errno.ENOTSUP):
                raise
            _publish_without_hard_links(temporary, target)
    finally:
        if destination is not None:
            destination.close()
        Path(temporary).unlink(missing_ok=True)


def _publish_without_hard_links(temporary: Path, target: Path) -> None:
    """无硬链接文件系统上的降级发布：占位只留在临时名，最后原子换入最终名。

    空占位绝不占用最终资源名，读者看到的 target 要么不存在（缺失路径随后
    会重新补齐），要么已经包含完整内容；换入前的检查同时保留并发胜者与
    用户已有的文件。
    """
    if target.exists():
        # 复制期间另一进程已发布同名文件，或用户此刻放入了自己的文件：保留胜者。
        return
    os.replace(temporary, target)


def resource_directory(sub_dir: str = "") -> Path:
    root = runtime_root()
    target = root / "resource" / sub_dir
    if is_source_checkout() and root == SOURCE_ROOT:
        return target

    # 字体和音乐仍可由用户扩充。放在运行目录，避免 WebUI 上传或后续升级写入
    # site-packages；只补齐缺失文件，保留用户编辑过的资源。
    origin = (SOURCE_ROOT if is_source_checkout() else BUNDLED_ROOT) / "resource" / sub_dir
    if origin.is_dir():
        _sweep_stale_reservations(target)
        for source in origin.rglob("*"):
            if source.is_file() and not source.name.startswith("."):
                _copy_missing_resource(source, target / source.relative_to(origin))
    return target
