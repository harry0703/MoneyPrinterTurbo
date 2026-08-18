"""Fail-closed filesystem layout for external health-trend data."""

from __future__ import annotations

import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath


class PathSafetyError(ValueError):
    """Raised when a configured path is not safe to access."""


_WINDOWS_DEVICE = re.compile(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9]|conin\$|conout\$)\Z")


def _normalized_windows_component(component: str) -> str:
    normalized = unicodedata.normalize("NFKC", component)
    if (
        not component
        or component in {".", ".."}
        or normalized in {".", ".."}
        or component != component.rstrip(". ")
        or normalized != normalized.rstrip(". ")
        or any(separator in normalized for separator in ("/", "\\", ":"))
    ):
        raise PathSafetyError("unsafe Windows path component")
    device_stem = normalized.split(".", 1)[0].casefold()
    if _WINDOWS_DEVICE.fullmatch(device_stem):
        raise PathSafetyError("Windows device path components are forbidden")
    return normalized


def validate_windows_basename(name: str) -> None:
    """Require one portable Windows filename with no drive, ADS, or device alias."""

    if not isinstance(name, str):
        raise PathSafetyError("filename must be text")
    windows_name = PureWindowsPath(name)
    if windows_name.drive or windows_name.root or len(windows_name.parts) != 1:
        raise PathSafetyError("filename must be one relative component")
    _normalized_windows_component(name)


def validate_windows_absolute_path(path: str | os.PathLike[str]) -> None:
    """Reject Windows lexical aliases before resolution or filesystem access."""

    raw = os.fspath(path)
    if not isinstance(raw, str):
        raise PathSafetyError("path must be text")
    windows_path = PureWindowsPath(raw)
    if (
        not windows_path.is_absolute()
        or not re.fullmatch(r"[A-Za-z]:", windows_path.drive)
        or windows_path.root != "\\"
        or raw.startswith(("\\\\", "//"))
    ):
        raise PathSafetyError("path must be a local absolute drive path")
    drive_and_tail = raw[2:].replace("/", "\\")
    lexical_parts = drive_and_tail.split("\\")
    if any(part in {".", ".."} for part in lexical_parts):
        raise PathSafetyError("path traversal is forbidden")
    for component in windows_path.parts[1:]:
        _normalized_windows_component(component)


def _is_reparse(status: os.stat_result) -> bool:
    attributes = getattr(status, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(status.st_mode) or bool(attributes & reparse_flag)


def _path_chain(path: Path) -> tuple[Path, ...]:
    anchor = Path(path.anchor)
    current = anchor
    chain = [anchor]
    for part in path.parts[1:]:
        current = current / part
        chain.append(current)
    return tuple(chain)


def assert_safe_path_chain(path: Path) -> None:
    """Reject lexical traversal and every existing reparse component."""

    validate_windows_absolute_path(path)
    for component in _path_chain(path):
        try:
            status = component.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise PathSafetyError("path chain cannot be inspected safely") from error
        if _is_reparse(status):
            raise PathSafetyError("reparse paths are forbidden")


def assert_safe_directory(path: Path) -> None:
    assert_safe_path_chain(path)
    try:
        status = path.lstat()
    except OSError as error:
        raise PathSafetyError("required directory is unavailable") from error
    if _is_reparse(status) or not stat.S_ISDIR(status.st_mode):
        raise PathSafetyError("required path is not a safe directory")


def assert_safe_regular_file(path: Path) -> None:
    assert_safe_path_chain(path)
    try:
        status = path.lstat()
    except OSError as error:
        raise PathSafetyError("required file is unavailable") from error
    if _is_reparse(status) or not stat.S_ISREG(status.st_mode):
        raise PathSafetyError("required path is not a safe regular file")


@dataclass(frozen=True, slots=True)
class DataLayout:
    """The only three persistent data layers exposed by this integration."""

    root: Path
    raw: Path
    curated: Path
    approved: Path

    @classmethod
    def from_root(cls, root: Path) -> DataLayout:
        configured = Path(root)
        validate_windows_absolute_path(configured)
        normalized = Path(os.path.abspath(os.fspath(configured)))
        assert_safe_path_chain(normalized)
        return cls(
            root=normalized,
            raw=normalized / "raw",
            curated=normalized / "curated",
            approved=normalized / "approved",
        )

    def validate(self, *, initialized: bool = False) -> None:
        expected = (self.root / "raw", self.root / "curated", self.root / "approved")
        registry = self.raw / ".registry"
        if (self.raw, self.curated, self.approved) != expected:
            raise PathSafetyError("layout paths do not match the configured root")
        assert_safe_path_chain(self.root)
        for layer in expected:
            assert_safe_path_chain(layer)
        assert_safe_path_chain(registry)
        if initialized:
            assert_safe_directory(self.root)
            for layer in expected:
                assert_safe_directory(layer)
            assert_safe_directory(registry)

    def initialize(self) -> None:
        self.validate()
        if self.root.exists() and not self.root.is_dir():
            raise PathSafetyError("root is not a directory")
        self.root.mkdir(parents=True, exist_ok=True)
        assert_safe_directory(self.root)
        for layer in (self.raw, self.curated, self.approved):
            layer.mkdir(exist_ok=True)
            assert_safe_directory(layer)
        registry = self.raw / ".registry"
        registry.mkdir(exist_ok=True)
        assert_safe_directory(registry)
