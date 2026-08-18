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

_ORDINARY_STATUSES = frozenset({
    " A", " M", " D", " R", " C",
    "M ", "MM", "MT", "MD",
    "T ", "TM", "TT", "TD",
    "A ", "AM", "AT", "AD",
    "D ",
    "R ", "RM", "RT", "RD",
    "C ", "CM", "CT", "CD",
})
_UNMERGED_STATUSES = frozenset({"DD", "AU", "UD", "UA", "DU", "AA", "UU"})
_SPECIAL_STATUSES = frozenset({"??", "!!"})
_VALID_PORCELAIN_STATUSES = _ORDINARY_STATUSES | _UNMERGED_STATUSES | _SPECIAL_STATUSES
_BLOB_MODES = frozenset({"100644", "100755", "120000"})


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


def _null_records(raw: bytes, record_type: str) -> tuple[bytes, ...]:
    if not raw:
        return ()
    if not raw.endswith(b"\0"):
        raise GitInspectionError(f"unterminated {record_type} -z output")
    records = tuple(raw[:-1].split(b"\0"))
    if any(not record for record in records):
        raise GitInspectionError(f"invalid empty {record_type} -z record")
    return records


def _is_object_id(value: str) -> bool:
    return len(value) in {40, 64} and all(character in "0123456789abcdefABCDEF" for character in value)


def _is_valid_porcelain_status(status: str) -> bool:
    return status in _VALID_PORCELAIN_STATUSES


def parse_porcelain_v1_z(raw: bytes) -> tuple[StatusEntry, ...]:
    fields = _null_records(raw, "porcelain v1")
    result: list[StatusEntry] = []
    index = 0
    while index < len(fields):
        field = fields[index]
        if len(field) < 4 or field[2:3] != b" ":
            raise GitInspectionError("invalid porcelain v1 -z record")
        try:
            xy = field[:2].decode("ascii")
        except UnicodeDecodeError as error:
            raise GitInspectionError("invalid porcelain v1 -z status") from error
        if not _is_valid_porcelain_status(xy):
            raise GitInspectionError("invalid porcelain v1 -z status")
        path = _decode_path(field[3:])
        if not path:
            raise GitInspectionError("porcelain v1 record is missing a path")
        original = None
        if "R" in xy or "C" in xy:
            index += 1
            if index >= len(fields):
                raise GitInspectionError("rename record is missing original path")
            original = _decode_path(fields[index])
            if not original:
                raise GitInspectionError("rename record is missing original path")
        result.append(StatusEntry(xy[0], xy[1], path, original))
        index += 1
    return tuple(result)


def parse_ls_tree_z(raw: bytes) -> tuple[TreeEntry, ...]:
    result: list[TreeEntry] = []
    for record in _null_records(raw, "ls-tree"):
        try:
            metadata, path_raw = record.split(b"\t", 1)
            mode, object_type, oid, size_raw = metadata.decode("ascii").split(" ", 3)
            if not path_raw or not mode.isdecimal() or object_type not in {"blob", "tree", "commit"}:
                raise ValueError
            if not _is_object_id(oid):
                raise ValueError
            size_value = size_raw.strip()
            if mode == "040000" and object_type == "tree":
                if size_value != "-":
                    raise ValueError
                size = None
            elif mode == "160000" and object_type == "commit":
                if size_value != "-":
                    raise ValueError
                size = None
            elif mode in _BLOB_MODES and object_type == "blob":
                if not size_value.isdecimal():
                    raise ValueError
                size = int(size_value)
            else:
                raise ValueError
        except (UnicodeDecodeError, ValueError) as error:
            raise GitInspectionError("invalid ls-tree -z record") from error
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
        if not remote or remote.startswith("-"):
            raise GitInspectionError(f"invalid remote name: {remote!r}")
        if not ref or any(character in ref for character in "\0\r\n"):
            raise GitInspectionError(f"invalid remote ref: {ref!r}")
        try:
            expected_ref = ref.encode("utf-8")
        except UnicodeEncodeError as error:
            raise GitInspectionError(f"invalid remote ref: {ref!r}") from error
        raw = self._run(("ls-remote", "--exit-code", "--", remote, ref))
        suffix = b"\t" + expected_ref + b"\n"
        if not raw.endswith(suffix):
            raise GitInspectionError(f"remote ref is ambiguous or mismatched: {remote} {ref}")
        oid_raw = raw[: -len(suffix)]
        try:
            oid = oid_raw.decode("ascii")
        except UnicodeDecodeError as error:
            raise GitInspectionError(f"invalid remote object id: {remote} {ref}") from error
        if not _is_object_id(oid):
            raise GitInspectionError(f"invalid remote object id: {remote} {ref}")
        return oid

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
