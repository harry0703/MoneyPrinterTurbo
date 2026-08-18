from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


ALLOWED_GIT_SUBCOMMANDS = {
    "cat-file",
    "check-attr",
    "diff",
    "ls-files",
    "ls-remote",
    "ls-tree",
    "merge-base",
    "rev-parse",
    "status",
    "symbolic-ref",
}


class GitInspectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class StatusEntry:
    index_status: str
    worktree_status: str
    path: str
    original_path: str | None = None


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    object_type: str
    oid: str
    size: int | None
    path: str


@dataclass(frozen=True)
class RepoSnapshot:
    head_sha: str
    branch: str
    index_path: str
    index_sha256: str
    index_size: int
    index_mtime_ns: int
    status_sha256: str


def _decode_path(raw: bytes) -> str:
    return raw.decode("utf-8", errors="surrogateescape")


def parse_porcelain_v1_z(raw: bytes) -> tuple[StatusEntry, ...]:
    fields = raw.split(b"\0")
    result: list[StatusEntry] = []
    index = 0
    while index < len(fields) and fields[index]:
        field = fields[index]
        if len(field) < 4 or field[2:3] != b" ":
            raise GitInspectionError("invalid porcelain v1 -z record")
        xy = field[:2].decode("ascii")
        path = _decode_path(field[3:])
        original = None
        if "R" in xy or "C" in xy:
            index += 1
            if index >= len(fields) or not fields[index]:
                raise GitInspectionError("rename record is missing original path")
            original = _decode_path(fields[index])
        result.append(StatusEntry(xy[0], xy[1], path, original))
        index += 1
    return tuple(result)


def parse_ls_tree_z(raw: bytes) -> tuple[TreeEntry, ...]:
    result: list[TreeEntry] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, path_raw = record.split(b"\t", 1)
        mode, object_type, oid, size_raw = metadata.decode("ascii").split(" ", 3)
        size = None if size_raw == "-" else int(size_raw)
        result.append(TreeEntry(mode, object_type, oid, size, _decode_path(path_raw)))
    return tuple(result)


class GitInspector:
    def __init__(self, repo: Path) -> None:
        self.repo = repo.resolve(strict=True)
        if not (self.repo / ".git").exists():
            probe = subprocess.run(
                self._command("rev-parse", "--is-inside-work-tree"),
                cwd=self.repo,
                env=self._environment(),
                capture_output=True,
                text=True,
                check=False,
            )
            if probe.returncode != 0 or probe.stdout.strip() != "true":
                raise GitInspectionError(f"not a git worktree: {self.repo}")

    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env["GIT_OPTIONAL_LOCKS"] = "0"
        return env

    def _command(self, *args: str) -> list[str]:
        return ["git", "-c", f"safe.directory={self.repo}", *args]

    def _run(self, args: Sequence[str], *, allowed_exit_codes: tuple[int, ...] = (0,)) -> bytes:
        if not args or args[0] not in ALLOWED_GIT_SUBCOMMANDS:
            raise GitInspectionError(f"git subcommand not allowed: {args[0] if args else '<empty>'}")
        completed = subprocess.run(
            self._command(*args),
            cwd=self.repo,
            env=self._environment(),
            capture_output=True,
            check=False,
        )
        if completed.returncode not in allowed_exit_codes:
            message = completed.stderr.decode("utf-8", errors="replace").strip()
            raise GitInspectionError(f"git {' '.join(args)} failed: {message}")
        return completed.stdout

    def status(self) -> tuple[StatusEntry, ...]:
        return parse_porcelain_v1_z(self._run(("status", "--porcelain=v1", "-z", "--untracked-files=all")))

    def tree(self, revision: str, pathspec: str) -> tuple[TreeEntry, ...]:
        return parse_ls_tree_z(self._run(("ls-tree", "-r", "-z", "-l", revision, "--", pathspec)))

    def blob(self, oid: str) -> bytes:
        return self._run(("cat-file", "blob", oid))

    def remote_head(self, remote: str, ref: str) -> str:
        raw = self._run(("ls-remote", "--exit-code", remote, ref))
        lines = raw.decode("ascii").splitlines()
        if len(lines) != 1:
            raise GitInspectionError(f"remote ref is ambiguous: {remote} {ref}")
        return lines[0].split("\t", 1)[0]

    def snapshot(self) -> RepoSnapshot:
        head = self._run(("rev-parse", "HEAD")).decode("ascii").strip()
        branch_raw = self._run(("symbolic-ref", "--quiet", "--short", "HEAD"), allowed_exit_codes=(0, 1))
        branch = branch_raw.decode("utf-8").strip() or "DETACHED"
        Path(
            self._run(("rev-parse", "--absolute-git-dir")).decode("utf-8").strip()
        ).resolve(strict=True)
        index_path = Path(self._run(("rev-parse", "--git-path", "index")).decode("utf-8").strip())
        if not index_path.is_absolute():
            index_path = self.repo / index_path
        stat = index_path.stat()
        index_bytes = index_path.read_bytes()
        status_raw = self._run(("status", "--porcelain=v1", "-z", "--untracked-files=all"))
        return RepoSnapshot(
            head_sha=head,
            branch=branch,
            index_path=str(index_path.resolve()),
            index_sha256=hashlib.sha256(index_bytes).hexdigest(),
            index_size=stat.st_size,
            index_mtime_ns=stat.st_mtime_ns,
            status_sha256=hashlib.sha256(status_raw).hexdigest(),
        )
