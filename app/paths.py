"""Unify the resource, config and runtime data directories of the source and installed versions."""

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
    """The source version keeps using the project directory; the installed version uses the user directory, and MPT_HOME can also be set explicitly."""
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
    """Atomically fill in built-in resources; concurrent starts and upgrades never overwrite files the user already has."""
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".resource-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as destination, source.open("rb") as origin:
            shutil.copyfileobj(origin, destination)
        try:
            # Windows rename refuses to overwrite; POSIX uses a hard link to achieve the same exclusive publish.
            if os.name == "nt":
                os.rename(temporary, target)
            else:
                os.link(temporary, target)
        except FileExistsError:
            pass
    finally:
        Path(temporary).unlink(missing_ok=True)


def resource_directory(sub_dir: str = "") -> Path:
    root = runtime_root()
    target = root / "resource" / sub_dir
    if is_source_checkout() and root == SOURCE_ROOT:
        return target

    # Users can still add fonts and music. They live in the runtime directory, so WebUI uploads or later upgrades don't write into
    # site-packages; only missing files are filled in, keeping resources the user edited.
    origin = (SOURCE_ROOT if is_source_checkout() else BUNDLED_ROOT) / "resource" / sub_dir
    if origin.is_dir():
        for source in origin.rglob("*"):
            if source.is_file() and not source.name.startswith("."):
                _copy_missing_resource(source, target / source.relative_to(origin))
    return target
