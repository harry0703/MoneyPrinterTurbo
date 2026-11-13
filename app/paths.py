"""统一源码版和安装版的资源、配置及运行数据目录。"""

import errno
import os
import shutil
import sys
import tempfile
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_ROOT = Path(__file__).resolve().parent / "_assets"


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


def _copy_missing_resource(source: Path, target: Path) -> None:
    """原子补齐内置资源；并发启动和升级都不覆盖用户已有的文件。"""
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".resource-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as destination, source.open("rb") as origin:
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
            # 资源补齐是启动必经路径，降级为独占占位 + 原子换入完成同样的发布。
            if exc.errno not in (errno.EPERM, errno.ENOTSUP):
                raise
            _publish_without_hard_links(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _publish_without_hard_links(temporary: Path, target: Path) -> None:
    """无硬链接文件系统上的降级发布：独占占位目标名，再原子换入内容。"""
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        # 并发进程已发布同名文件，保留胜者。
        return
    os.close(fd)
    try:
        os.replace(temporary, target)
    except OSError:
        # 换入失败时不能在目标名留下空占位文件。
        target.unlink(missing_ok=True)
        raise


def resource_directory(sub_dir: str = "") -> Path:
    root = runtime_root()
    target = root / "resource" / sub_dir
    if is_source_checkout() and root == SOURCE_ROOT:
        return target

    # 字体和音乐仍可由用户扩充。放在运行目录，避免 WebUI 上传或后续升级写入
    # site-packages；只补齐缺失文件，保留用户编辑过的资源。
    origin = (SOURCE_ROOT if is_source_checkout() else BUNDLED_ROOT) / "resource" / sub_dir
    if origin.is_dir():
        for source in origin.rglob("*"):
            if source.is_file() and not source.name.startswith("."):
                _copy_missing_resource(source, target / source.relative_to(origin))
    return target
