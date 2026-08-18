"""Fail-closed filesystem layout for external health-trend data."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path


class PathSafetyError(ValueError):
    """Raised when a configured path is not safe to access."""


def _has_parent_traversal(path: Path) -> bool:
    return any(part == ".." for part in path.parts)


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

    if not path.is_absolute() or _has_parent_traversal(path):
        raise PathSafetyError("path must be absolute and traversal-free")
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
        if not configured.is_absolute() or _has_parent_traversal(configured):
            raise PathSafetyError("root must be an absolute traversal-free path")
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
        if (self.raw, self.curated, self.approved) != expected:
            raise PathSafetyError("layout paths do not match the configured root")
        assert_safe_path_chain(self.root)
        for layer in expected:
            assert_safe_path_chain(layer)
        if initialized:
            assert_safe_directory(self.root)
            for layer in expected:
                assert_safe_directory(layer)

    def initialize(self) -> None:
        self.validate()
        if self.root.exists() and not self.root.is_dir():
            raise PathSafetyError("root is not a directory")
        self.root.mkdir(parents=True, exist_ok=True)
        assert_safe_directory(self.root)
        for layer in (self.raw, self.curated, self.approved):
            layer.mkdir(exist_ok=True)
            assert_safe_directory(layer)
