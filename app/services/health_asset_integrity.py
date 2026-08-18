from __future__ import annotations

import csv
import ctypes
import hashlib
import io
import json
import os
import re
import subprocess
from ctypes import wintypes
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Sequence


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

_ORDINARY_STATUSES = frozenset(
    {
        " A",
        " M",
        " T",
        " D",
        " R",
        " C",
        "M ",
        "MM",
        "MT",
        "MD",
        "T ",
        "TM",
        "TT",
        "TD",
        "A ",
        "AM",
        "AT",
        "AD",
        "D ",
        "R ",
        "RM",
        "RT",
        "RD",
        "C ",
        "CM",
        "CT",
        "CD",
    }
)
_UNMERGED_STATUSES = frozenset({"DD", "AU", "UD", "UA", "DU", "AA", "UU"})
_SPECIAL_STATUSES = frozenset({"??", "!!"})
_VALID_PORCELAIN_STATUSES = _ORDINARY_STATUSES | _UNMERGED_STATUSES | _SPECIAL_STATUSES
_BLOB_MODES = frozenset({"100644", "100755", "120000"})

MANUAL_PACK_RE = re.compile(
    r"^09_泛健康日更/work/(HC20260810-\d{3})/production/v01/04_grok_batch/manual_pack/(.+)$"
)
LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1\n"
LARGE_BLOB_THRESHOLD = 50 * 1024 * 1024
_CONTROL_FILES = frozenset(
    {
        "MANIFEST.csv",
        "MANUAL-GENERATION-GUIDE.md",
        "MANUAL-PACK-QA.md",
    }
)
_AUDIT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_BUNDLE_PAYLOAD_NAMES = (
    "audit.json",
    "deleted-assets.csv",
    "audit-summary.md",
)
_BUNDLE_NAMES = (*_BUNDLE_PAYLOAD_NAMES, "bundle-manifest.json")
_WINDOWS_RESERVED_AUDIT_IDS = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)

_DELETE = 0x00010000
_SYNCHRONIZE = 0x00100000
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_LIST_DIRECTORY = 0x00000001
_FILE_TRAVERSE = 0x00000020
_FILE_READ_ATTRIBUTES = 0x00000080
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_FILE_SHARE_ALL = _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_OPEN_EXISTING = 3
_FILE_OPEN = 1
_FILE_CREATE = 2
_FILE_DIRECTORY_FILE = 0x00000001
_FILE_WRITE_THROUGH = 0x00000002
_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_FILE_NON_DIRECTORY_FILE = 0x00000040
_OBJ_CASE_INSENSITIVE = 0x00000040
_FILE_BEGIN = 0
_FILE_STANDARD_INFO_CLASS = 1
_FILE_RENAME_INFORMATION_CLASS = 10
_FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
_FILE_ID_BOTH_DIRECTORY_INFO_CLASS = 10
_FILE_ID_BOTH_DIRECTORY_RESTART_INFO_CLASS = 11
_FILE_ID_INFO_CLASS = 18
_ERROR_NO_MORE_FILES = 18
_MAX_BUNDLE_FILE_BYTES = 128 * 1024 * 1024


class _FILE_ID_128(ctypes.Structure):
    _fields_ = [("Identifier", ctypes.c_ubyte * 16)]


class _FILE_ID_INFO(ctypes.Structure):
    _fields_ = [
        ("VolumeSerialNumber", ctypes.c_ulonglong),
        ("FileId", _FILE_ID_128),
    ]


class _FILE_ATTRIBUTE_TAG_INFO(ctypes.Structure):
    _fields_ = [
        ("FileAttributes", wintypes.DWORD),
        ("ReparseTag", wintypes.DWORD),
    ]


class _FILE_STANDARD_INFO(ctypes.Structure):
    _fields_ = [
        ("AllocationSize", ctypes.c_longlong),
        ("EndOfFile", ctypes.c_longlong),
        ("NumberOfLinks", wintypes.DWORD),
        ("DeletePending", wintypes.BOOLEAN),
        ("Directory", wintypes.BOOLEAN),
    ]


class _FILE_ID_BOTH_DIR_INFO(ctypes.Structure):
    _fields_ = [
        ("NextEntryOffset", wintypes.DWORD),
        ("FileIndex", wintypes.DWORD),
        ("CreationTime", ctypes.c_longlong),
        ("LastAccessTime", ctypes.c_longlong),
        ("LastWriteTime", ctypes.c_longlong),
        ("ChangeTime", ctypes.c_longlong),
        ("EndOfFile", ctypes.c_longlong),
        ("AllocationSize", ctypes.c_longlong),
        ("FileAttributes", wintypes.DWORD),
        ("FileNameLength", wintypes.DWORD),
        ("EaSize", wintypes.DWORD),
        ("ShortNameLength", ctypes.c_byte),
        ("ShortName", ctypes.c_wchar * 12),
        ("FileId", ctypes.c_longlong),
        ("FileName", ctypes.c_wchar * 1),
    ]


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", wintypes.LPWSTR),
    ]


class _OBJECT_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.ULONG),
        ("RootDirectory", wintypes.HANDLE),
        ("ObjectName", ctypes.POINTER(_UNICODE_STRING)),
        ("Attributes", wintypes.ULONG),
        ("SecurityDescriptor", wintypes.LPVOID),
        ("SecurityQualityOfService", wintypes.LPVOID),
    ]


class _IO_STATUS_BLOCK(ctypes.Structure):
    _fields_ = [
        ("Status", wintypes.LPVOID),
        ("Information", ctypes.c_size_t),
    ]


@dataclass
class _WindowsFileTarget:
    directory_handle: int
    name: str
    handle: int | None = None
    identity: tuple[int, bytes] | None = None


@dataclass
class _WindowsStaging:
    parent_handle: int
    directory_handle: int
    directory_identity: tuple[int, bytes]
    files: dict[str, _WindowsFileTarget]


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


@dataclass(frozen=True)
class DeletedAsset:
    content_id: str
    path: str
    asset_kind: str
    head_oid: str
    head_size: int
    head_blob_sha256: str
    head_blob_recoverable: bool
    source_path: str | None
    source_exists: bool
    source_sha256: str | None
    source_matches_head: bool | None
    lfs_pointer: bool


@dataclass(frozen=True)
class LargeBlob:
    path: str
    oid: str
    size: int
    lfs_pointer: bool


@dataclass(frozen=True)
class AuditReport:
    schema: str
    repo_root: str
    branch: str
    head_sha: str
    remote: dict[str, Any]
    summary: dict[str, Any]
    episodes: tuple[dict[str, Any], ...]
    deleted_assets: tuple[DeletedAsset, ...]
    large_blobs: tuple[LargeBlob, ...]
    lfs: dict[str, Any]
    mutation_guard: dict[str, Any]
    decision_options: tuple[dict[str, str], ...]


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
    return len(value) in {40, 64} and all(
        character in "0123456789abcdefABCDEF" for character in value
    )


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
            if (
                not path_raw
                or not mode.isdecimal()
                or object_type not in {"blob", "tree", "commit"}
            ):
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

    def _run(
        self, args: Sequence[str], *, allowed_exit_codes: tuple[int, ...] = (0,)
    ) -> bytes:
        if not args or args[0] not in ALLOWED_GIT_SUBCOMMANDS:
            raise GitInspectionError(
                f"git subcommand not allowed: {args[0] if args else '<empty>'}"
            )
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
        return parse_porcelain_v1_z(
            self._run(("status", "--porcelain=v1", "-z", "--untracked-files=all"))
        )

    def tree(self, revision: str, pathspec: str) -> tuple[TreeEntry, ...]:
        return parse_ls_tree_z(
            self._run(("ls-tree", "-r", "-z", "-l", revision, "--", pathspec))
        )

    def blob(self, oid: str) -> bytes:
        return self._run(("cat-file", "blob", oid))

    def has_object(self, oid: str) -> bool:
        try:
            self._run(("cat-file", "-e", oid))
        except GitInspectionError:
            return False
        return True

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
            raise GitInspectionError(
                f"remote ref is ambiguous or mismatched: {remote} {ref}"
            )
        oid_raw = raw[: -len(suffix)]
        try:
            oid = oid_raw.decode("ascii")
        except UnicodeDecodeError as error:
            raise GitInspectionError(
                f"invalid remote object id: {remote} {ref}"
            ) from error
        if not _is_object_id(oid):
            raise GitInspectionError(f"invalid remote object id: {remote} {ref}")
        return oid

    def snapshot(self) -> RepoSnapshot:
        head = self._run(("rev-parse", "HEAD")).decode("ascii").strip()
        branch_raw = self._run(
            ("symbolic-ref", "--quiet", "--short", "HEAD"), allowed_exit_codes=(0, 1)
        )
        branch = branch_raw.decode("utf-8").strip() or "DETACHED"
        Path(
            self._run(("rev-parse", "--absolute-git-dir")).decode("utf-8").strip()
        ).resolve(strict=True)
        index_path = Path(
            self._run(("rev-parse", "--git-path", "index")).decode("utf-8").strip()
        )
        if not index_path.is_absolute():
            index_path = self.repo / index_path
        stat = index_path.stat()
        index_bytes = index_path.read_bytes()
        status_raw = self._run(
            ("status", "--porcelain=v1", "-z", "--untracked-files=all")
        )
        return RepoSnapshot(
            head_sha=head,
            branch=branch,
            index_path=str(index_path.resolve()),
            index_sha256=hashlib.sha256(index_bytes).hexdigest(),
            index_size=stat.st_size,
            index_mtime_ns=stat.st_mtime_ns,
            status_sha256=hashlib.sha256(status_raw).hexdigest(),
        )


def is_lfs_pointer(payload: bytes) -> bool:
    return (
        payload.startswith(LFS_PREFIX)
        and b"\noid sha256:" in payload
        and b"\nsize " in payload
    )


def _run_lfs_readonly(inspector: GitInspector, args: Sequence[str]) -> bytes:
    allowed = {
        ("version",),
        ("ls-files", "--all", "-n"),
    }
    normalized = tuple(args)
    if normalized not in allowed:
        raise GitInspectionError(
            f"git lfs command not allowed: {' '.join(normalized) or '<empty>'}"
        )
    if normalized == ("ls-files", "--all", "-n"):
        format_probe = subprocess.run(
            inspector._command(
                "config", "--local", "--get", "lfs.repositoryformatversion"
            ),
            cwd=inspector.repo,
            env=inspector._environment(),
            capture_output=True,
            check=False,
        )
        if format_probe.returncode != 0 or format_probe.stdout not in {
            b"0\n",
            b"0\r\n",
        }:
            raise GitInspectionError(
                "Git LFS repository format is not initialized; refusing a probe "
                "that may mutate repository config"
            )
    completed = subprocess.run(
        inspector._command("lfs", *normalized),
        cwd=inspector.repo,
        env=inspector._environment(),
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise GitInspectionError(f"git lfs {' '.join(normalized)} failed: {message}")
    return completed.stdout


def _asset_kind(content_id: str, relative: str) -> str | None:
    shot = r"S(?:0[1-9]|10)"
    if re.fullmatch(
        rf"01_first_frames/{re.escape(content_id)}-v01-{shot}-firstframe\.png",
        relative,
    ):
        return "first_frame"
    if re.fullmatch(
        rf"02_prompts/{re.escape(content_id)}-v01-{shot}-prompt-zh-en\.txt",
        relative,
    ):
        return "prompt"
    if relative in _CONTROL_FILES or relative == (
        f"{content_id}-v01-Grok-Automation-10条提示词.txt"
    ):
        return "control"
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect_lfs(inspector: GitInspector) -> tuple[dict[str, Any], bool]:
    try:
        version_output = _run_lfs_readonly(inspector, ("version",)).decode("utf-8")
        if version_output.endswith("\r\n"):
            version_line = version_output[:-2]
        elif version_output.endswith("\n"):
            version_line = version_output[:-1]
        else:
            version_line = version_output
        has_control = any(
            ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F
            for character in version_line
        )
        if (
            has_control
            or re.fullmatch(
                r"git-lfs/\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?"
                r"(?: \([^\r\n]+\))?",
                version_line,
            )
            is None
        ):
            raise GitInspectionError("unrecognized Git LFS version output")
        version = version_line
        paths_raw = _run_lfs_readonly(inspector, ("ls-files", "--all", "-n"))
        tracked_paths = [
            line.decode("utf-8", errors="strict")
            for line in paths_raw.splitlines()
            if line
        ]
    except (GitInspectionError, UnicodeDecodeError) as error:
        return {
            "complete": False,
            "version": None,
            "tracked_paths": None,
            "error": str(error),
        }, False
    return {
        "complete": True,
        "version": version,
        "tracked_paths": tracked_paths,
        "error": None,
    }, True


def _inspect_remote(
    inspector: GitInspector,
    remote: str | None,
    remote_ref: str | None,
    head_tree: tuple[TreeEntry, ...],
) -> tuple[dict[str, Any], bool]:
    requested = remote is not None or remote_ref is not None
    result: dict[str, Any] = {
        "requested": requested,
        "name": remote,
        "ref": remote_ref,
        "oid": None,
        "object_available_locally": None,
        "tree_comparison": "not_requested",
        "error": None,
    }
    if not requested:
        return result, True
    if not remote or not remote_ref:
        result["tree_comparison"] = "unavailable"
        result["error"] = "remote and remote_ref must be provided together"
        return result, False
    try:
        oid = inspector.remote_head(remote, remote_ref)
    except GitInspectionError as error:
        result["tree_comparison"] = "unavailable"
        result["error"] = str(error)
        return result, False
    result["oid"] = oid
    if not inspector.has_object(oid):
        result["object_available_locally"] = False
        result["tree_comparison"] = "unavailable_without_fetch"
        return result, False
    result["object_available_locally"] = True
    try:
        remote_tree = inspector.tree(oid, "09_泛健康日更")
    except GitInspectionError as error:
        result["tree_comparison"] = "unavailable"
        result["error"] = str(error)
        return result, False
    local_scoped_tree = tuple(
        entry for entry in head_tree if entry.path.startswith("09_泛健康日更/")
    )
    result["tree_comparison"] = (
        "identical" if remote_tree == local_scoped_tree else "different"
    )
    return result, True


def audit_health_assets(
    inspector: GitInspector,
    remote: str | None,
    remote_ref: str | None,
) -> AuditReport:
    before = inspector.snapshot()
    status = inspector.status()
    head_tree = inspector.tree(before.head_sha, ".")
    head_by_path = {
        entry.path: entry for entry in head_tree if entry.object_type == "blob"
    }
    evidence_complete = True
    deleted_assets: list[DeletedAsset] = []

    for status_entry in status:
        if status_entry.worktree_status != "D" and status_entry.index_status != "D":
            continue
        match = MANUAL_PACK_RE.fullmatch(status_entry.path)
        if match is None:
            continue
        content_id, relative = match.groups()
        asset_kind = _asset_kind(content_id, relative)
        if asset_kind is None:
            raise GitInspectionError(
                f"unrecognized manual-pack deletion: {status_entry.path}"
            )
        tree_entry = head_by_path.get(status_entry.path)
        if tree_entry is None or tree_entry.size is None:
            evidence_complete = False
            continue
        try:
            head_payload = inspector.blob(tree_entry.oid)
        except GitInspectionError:
            evidence_complete = False
            continue
        head_sha256 = hashlib.sha256(head_payload).hexdigest()
        source_path = None
        source_exists = False
        source_sha256 = None
        source_matches_head = None
        if asset_kind == "first_frame":
            source_path = status_entry.path.replace(
                "/04_grok_batch/manual_pack/01_first_frames/",
                "/03_first_frames/",
                1,
            )
            source = inspector.repo.joinpath(*source_path.split("/"))
            source_exists = source.is_file()
            if source_exists:
                source_sha256 = _sha256_file(source)
                source_matches_head = source_sha256 == head_sha256
        deleted_assets.append(
            DeletedAsset(
                content_id=content_id,
                path=status_entry.path,
                asset_kind=asset_kind,
                head_oid=tree_entry.oid,
                head_size=tree_entry.size,
                head_blob_sha256=head_sha256,
                head_blob_recoverable=True,
                source_path=source_path,
                source_exists=source_exists,
                source_sha256=source_sha256,
                source_matches_head=source_matches_head,
                lfs_pointer=is_lfs_pointer(head_payload),
            )
        )

    large_blobs: list[LargeBlob] = []
    for entry in head_tree:
        if (
            entry.object_type != "blob"
            or entry.size is None
            or entry.size <= LARGE_BLOB_THRESHOLD
        ):
            continue
        try:
            payload = inspector.blob(entry.oid)
        except GitInspectionError:
            evidence_complete = False
            continue
        large_blobs.append(
            LargeBlob(
                path=entry.path,
                oid=entry.oid,
                size=entry.size,
                lfs_pointer=is_lfs_pointer(payload),
            )
        )

    lfs, lfs_complete = _inspect_lfs(inspector)
    remote_result, remote_complete = _inspect_remote(
        inspector, remote, remote_ref, head_tree
    )
    after = inspector.snapshot()
    if after != before:
        raise GitInspectionError("repository changed during audit")

    deleted_assets.sort(key=lambda item: item.path)
    large_blobs.sort(key=lambda item: item.path)
    episode_rows: list[dict[str, Any]] = []
    for content_id in sorted({item.content_id for item in deleted_assets}):
        assets = [item for item in deleted_assets if item.content_id == content_id]
        episode_rows.append(
            {
                "content_id": content_id,
                "deleted_count": len(assets),
                "first_frames": sum(
                    item.asset_kind == "first_frame" for item in assets
                ),
                "prompts": sum(item.asset_kind == "prompt" for item in assets),
                "control_files": sum(item.asset_kind == "control" for item in assets),
            }
        )
    summary = {
        "audit_complete": evidence_complete and lfs_complete and remote_complete,
        "deleted_manual_pack_files": len(deleted_assets),
        "episodes": len(episode_rows),
        "first_frames": sum(
            item.asset_kind == "first_frame" for item in deleted_assets
        ),
        "prompts": sum(item.asset_kind == "prompt" for item in deleted_assets),
        "control_files": sum(item.asset_kind == "control" for item in deleted_assets),
        "large_blobs": len(large_blobs),
    }
    return AuditReport(
        schema="health_asset_integrity.v1",
        repo_root=str(inspector.repo),
        branch=before.branch,
        head_sha=before.head_sha,
        remote=remote_result,
        summary=summary,
        episodes=tuple(episode_rows),
        deleted_assets=tuple(deleted_assets),
        large_blobs=tuple(large_blobs),
        lfs=lfs,
        mutation_guard={
            "unchanged": True,
            "before": asdict(before),
            "after": asdict(after),
        },
        decision_options=(
            {
                "id": "restore_exact_from_head",
                "meaning": "按 HEAD blob 精确恢复，需用户另行授权",
            },
            {
                "id": "regenerate_outside_repo_and_compare",
                "meaning": "在外部临时目录重生，逐字节比对后再决策",
            },
            {"id": "keep_deletions", "meaning": "确认删除意图并另行更新下游清单"},
        ),
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


def report_to_dict(report: AuditReport) -> dict[str, Any]:
    return _json_safe(asdict(report))


def _absolute_path(path: Path) -> Path:
    try:
        return Path(os.path.abspath(os.fspath(path)))
    except (OSError, ValueError) as error:
        raise GitInspectionError(f"invalid output path: {path!s}") from error


def _path_chain(path: Path) -> tuple[Path, ...]:
    anchor = Path(path.anchor)
    current = anchor
    chain = [current]
    for part in path.parts[1:]:
        current /= part
        chain.append(current)
    return tuple(chain)


def _is_reparse_point(path: Path) -> bool:
    metadata = path.lstat()
    attributes = getattr(metadata, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def _assert_plain_directory_chain(path: Path) -> None:
    for component in _path_chain(path):
        if not os.path.lexists(component):
            break
        try:
            if _is_reparse_point(component):
                raise GitInspectionError(
                    f"output path contains a symlink or reparse point: {component}"
                )
            if not component.is_dir():
                raise GitInspectionError(
                    f"output path component is not a directory: {component}"
                )
        except OSError as error:
            raise GitInspectionError(
                f"cannot safely inspect output path component: {component}"
            ) from error


def ensure_external_output(repo: Path, output_parent: Path) -> Path:
    try:
        repo_root = repo.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise GitInspectionError(
            f"cannot resolve audited repository: {repo}"
        ) from error
    output_path = _absolute_path(output_parent)
    _assert_plain_directory_chain(output_path)
    try:
        resolved_output = output_path.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise GitInspectionError(
            f"cannot resolve output path: {output_parent}"
        ) from error
    if resolved_output == repo_root or repo_root in resolved_output.parents:
        raise GitInspectionError("audit output must be outside audited repository")
    return resolved_output


def _prepare_output_parent(output_parent: Path) -> Path:
    output_path = _absolute_path(output_parent)
    _assert_plain_directory_chain(output_path)
    for component in _path_chain(output_path):
        if os.path.lexists(component):
            continue
        try:
            component.mkdir()
        except FileExistsError:
            pass
        except OSError as error:
            raise GitInspectionError(
                f"cannot create output directory: {component}"
            ) from error
        try:
            if _is_reparse_point(component) or not component.is_dir():
                raise GitInspectionError(
                    f"output path contains a symlink or reparse point: {component}"
                )
        except OSError as error:
            raise GitInspectionError(
                f"cannot safely inspect output path component: {component}"
            ) from error
    _assert_plain_directory_chain(output_path)
    try:
        return output_path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise GitInspectionError(
            f"cannot resolve output path: {output_parent}"
        ) from error


def _validate_audit_id(audit_id: str) -> None:
    if (
        _AUDIT_ID_RE.fullmatch(audit_id) is None
        or audit_id.upper() in _WINDOWS_RESERVED_AUDIT_IDS
    ):
        raise GitInspectionError(f"invalid audit id: {audit_id!r}")


def render_deleted_assets_csv(report: AuditReport) -> bytes:
    columns = tuple(field.name for field in fields(DeletedAsset))
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for asset in sorted(report.deleted_assets, key=lambda item: item.path):
        writer.writerow(asdict(asset))
    return output.getvalue().encode("utf-8")


def _markdown_cell(value: Any) -> str:
    if value is None:
        return "—"
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", "")
        .replace("\n", "<br>")
    )


def render_audit_summary(report: AuditReport) -> bytes:
    summary = report.summary
    remote = report.remote
    lfs = report.lfs
    mutation = report.mutation_guard
    lines = [
        "# Health asset integrity audit summary",
        "",
        f"- Schema: `{_markdown_cell(report.schema)}`",
        f"- Repository: `{_markdown_cell(report.repo_root)}`",
        f"- Branch / HEAD: `{_markdown_cell(report.branch)}` / `{_markdown_cell(report.head_sha)}`",
        f"- Audit complete: `{str(bool(summary['audit_complete'])).lower()}`",
        "",
        "## Counts",
        "",
        "| Deleted manual-pack files | Episodes | First frames | Prompts | Control files | Large blobs |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        "| {deleted_manual_pack_files} | {episodes} | {first_frames} | {prompts} | "
        "{control_files} | {large_blobs} |".format(**summary),
        "",
        "## Per-episode evidence",
        "",
        "| Content ID | Deleted | First frames | Prompts | Control files |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for episode in sorted(report.episodes, key=lambda item: str(item["content_id"])):
        lines.append(
            "| {content_id} | {deleted_count} | {first_frames} | {prompts} | "
            "{control_files} |".format(
                **{key: _markdown_cell(value) for key, value in episode.items()}
            )
        )
    lines.extend(
        [
            "",
            "## Remote evidence",
            "",
            f"- Requested: `{str(bool(remote['requested'])).lower()}`",
            f"- Remote / ref: `{_markdown_cell(remote['name'])}` / `{_markdown_cell(remote['ref'])}`",
            f"- OID: `{_markdown_cell(remote['oid'])}`",
            f"- Object available locally: `{_markdown_cell(remote['object_available_locally'])}`",
            f"- Tree comparison: `{_markdown_cell(remote['tree_comparison'])}`",
            f"- Error: `{_markdown_cell(remote['error'])}`",
            "",
            "## LFS evidence",
            "",
            f"- Complete: `{str(bool(lfs['complete'])).lower()}`",
            f"- Version: `{_markdown_cell(lfs['version'])}`",
            f"- Tracked path count: `{_markdown_cell(None if lfs['tracked_paths'] is None else len(lfs['tracked_paths']))}`",
            f"- Error: `{_markdown_cell(lfs['error'])}`",
            "",
            "## Large-blob evidence",
            "",
            "| Path | OID | Bytes | LFS pointer |",
            "| --- | --- | ---: | --- |",
        ]
    )
    for blob in sorted(report.large_blobs, key=lambda item: item.path):
        lines.append(
            f"| {_markdown_cell(blob.path)} | `{_markdown_cell(blob.oid)}` | "
            f"{blob.size} | `{str(blob.lfs_pointer).lower()}` |"
        )
    if not report.large_blobs:
        lines.append("| _None_ | — | — | — |")
    lines.extend(
        [
            "",
            "## Mutation guard",
            "",
            f"- Unchanged: `{str(bool(mutation['unchanged'])).lower()}`",
            f"- Before status SHA-256: `{_markdown_cell(mutation['before']['status_sha256'])}`",
            f"- After status SHA-256: `{_markdown_cell(mutation['after']['status_sha256'])}`",
            f"- Before index SHA-256: `{_markdown_cell(mutation['before']['index_sha256'])}`",
            f"- After index SHA-256: `{_markdown_cell(mutation['after']['index_sha256'])}`",
            "",
            "## User decision options",
            "",
            "No option is preferred. Only the user may choose a disposition after reading the evidence.",
            "",
        ]
    )
    for option in report.decision_options:
        lines.append(
            f"- `{_markdown_cell(option['id'])}` — {_markdown_cell(option['meaning'])}"
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


_WINDOWS_API: tuple[Any, Any] | None = None


def _windows_api() -> tuple[Any, Any]:
    global _WINDOWS_API
    if os.name != "nt":
        raise GitInspectionError(
            "secure bundle publication requires Windows handle semantics"
        )
    if _WINDOWS_API is not None:
        return _WINDOWS_API
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    kernel32.FlushFileBuffers.restype = wintypes.BOOL
    kernel32.SetFilePointerEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_longlong,
        ctypes.POINTER(ctypes.c_longlong),
        wintypes.DWORD,
    ]
    kernel32.SetFilePointerEx.restype = wintypes.BOOL
    ntdll.NtCreateFile.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(_OBJECT_ATTRIBUTES),
        ctypes.POINTER(_IO_STATUS_BLOCK),
        ctypes.POINTER(ctypes.c_longlong),
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.LPVOID,
        wintypes.ULONG,
    ]
    ntdll.NtCreateFile.restype = ctypes.c_long
    ntdll.NtSetInformationFile.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_IO_STATUS_BLOCK),
        wintypes.LPVOID,
        wintypes.ULONG,
        ctypes.c_int,
    ]
    ntdll.NtSetInformationFile.restype = ctypes.c_long
    ntdll.RtlNtStatusToDosError.argtypes = [ctypes.c_long]
    ntdll.RtlNtStatusToDosError.restype = wintypes.ULONG
    _WINDOWS_API = kernel32, ntdll
    return _WINDOWS_API


def _raise_windows_error(action: str) -> None:
    code = ctypes.get_last_error()
    raise OSError(code, f"{action}: {ctypes.FormatError(code).strip()}")


def _raise_nt_error(action: str, status: int) -> None:
    _kernel32, ntdll = _windows_api()
    code = int(ntdll.RtlNtStatusToDosError(status))
    raise OSError(code, f"{action}: {ctypes.FormatError(code).strip()}")


def _win_close(handle: int | None) -> None:
    if handle is None:
        return
    kernel32, _ntdll = _windows_api()
    kernel32.CloseHandle(wintypes.HANDLE(handle))


def _win_open_directory_path(path: Path, *, lock_name: bool) -> int:
    kernel32, _ntdll = _windows_api()
    share = _FILE_SHARE_READ | _FILE_SHARE_WRITE
    if not lock_name:
        share |= _FILE_SHARE_DELETE
    handle = kernel32.CreateFileW(
        str(path),
        _GENERIC_READ,
        share,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        _raise_windows_error(f"open directory handle {path}")
    return int(handle)


def _win_nt_relative_handle(
    parent_handle: int,
    name: str,
    *,
    directory: bool,
    create: bool,
) -> int:
    _kernel32, ntdll = _windows_api()
    name_buffer = ctypes.create_unicode_buffer(name)
    name_bytes = name.encode("utf-16-le")
    unicode_name = _UNICODE_STRING(
        Length=len(name_bytes),
        MaximumLength=len(name_bytes),
        Buffer=ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    attributes = _OBJECT_ATTRIBUTES(
        Length=ctypes.sizeof(_OBJECT_ATTRIBUTES),
        RootDirectory=wintypes.HANDLE(parent_handle),
        ObjectName=ctypes.pointer(unicode_name),
        Attributes=_OBJ_CASE_INSENSITIVE,
        SecurityDescriptor=None,
        SecurityQualityOfService=None,
    )
    io_status = _IO_STATUS_BLOCK()
    result_handle = wintypes.HANDLE()
    if directory:
        desired_access = (
            _FILE_LIST_DIRECTORY
            | _FILE_TRAVERSE
            | _FILE_READ_ATTRIBUTES
            | _DELETE
            | _SYNCHRONIZE
        )
        file_attributes = _FILE_ATTRIBUTE_DIRECTORY
        share_access = _FILE_SHARE_ALL
        create_options = _FILE_DIRECTORY_FILE | _FILE_SYNCHRONOUS_IO_NONALERT
    else:
        desired_access = _GENERIC_READ | _GENERIC_WRITE | _DELETE | _SYNCHRONIZE
        file_attributes = _FILE_ATTRIBUTE_NORMAL
        share_access = _FILE_SHARE_READ | _FILE_SHARE_DELETE
        create_options = (
            _FILE_NON_DIRECTORY_FILE
            | _FILE_SYNCHRONOUS_IO_NONALERT
            | _FILE_WRITE_THROUGH
        )
        if not create:
            desired_access = _GENERIC_READ | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE
            share_access = _FILE_SHARE_ALL
            create_options |= _FILE_FLAG_OPEN_REPARSE_POINT
    status = int(
        ntdll.NtCreateFile(
            ctypes.byref(result_handle),
            desired_access,
            ctypes.byref(attributes),
            ctypes.byref(io_status),
            None,
            file_attributes,
            share_access,
            _FILE_CREATE if create else _FILE_OPEN,
            create_options,
            None,
            0,
        )
    )
    if status < 0:
        _raise_nt_error(f"{'create' if create else 'open'} bundle entry {name}", status)
    if result_handle.value is None:
        raise OSError(f"Windows returned an empty handle for bundle entry {name}")
    return int(result_handle.value)


def _win_handle_identity(handle: int) -> tuple[int, bytes]:
    kernel32, _ntdll = _windows_api()
    identity = _FILE_ID_INFO()
    if not kernel32.GetFileInformationByHandleEx(
        wintypes.HANDLE(handle),
        _FILE_ID_INFO_CLASS,
        ctypes.byref(identity),
        ctypes.sizeof(identity),
    ):
        _raise_windows_error("read handle identity")
    return int(identity.VolumeSerialNumber), bytes(identity.FileId.Identifier)


def _win_handle_attributes(handle: int) -> int:
    kernel32, _ntdll = _windows_api()
    attributes = _FILE_ATTRIBUTE_TAG_INFO()
    if not kernel32.GetFileInformationByHandleEx(
        wintypes.HANDLE(handle),
        _FILE_ATTRIBUTE_TAG_INFO_CLASS,
        ctypes.byref(attributes),
        ctypes.sizeof(attributes),
    ):
        _raise_windows_error("read handle attributes")
    return int(attributes.FileAttributes)


def _win_handle_standard_info(handle: int) -> _FILE_STANDARD_INFO:
    kernel32, _ntdll = _windows_api()
    standard = _FILE_STANDARD_INFO()
    if not kernel32.GetFileInformationByHandleEx(
        wintypes.HANDLE(handle),
        _FILE_STANDARD_INFO_CLASS,
        ctypes.byref(standard),
        ctypes.sizeof(standard),
    ):
        _raise_windows_error("read handle standard information")
    return standard


def _win_assert_plain_directory(handle: int, context: str) -> None:
    attributes = _win_handle_attributes(handle)
    if not attributes & _FILE_ATTRIBUTE_DIRECTORY:
        raise GitInspectionError(f"{context} is not a directory")
    if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise GitInspectionError(f"{context} is a reparse point")
    if not _win_handle_standard_info(handle).Directory:
        raise GitInspectionError(f"{context} is not a directory")


def _win_assert_regular_file(handle: int, name: str) -> None:
    attributes = _win_handle_attributes(handle)
    standard = _win_handle_standard_info(handle)
    if (
        attributes & (_FILE_ATTRIBUTE_DIRECTORY | _FILE_ATTRIBUTE_REPARSE_POINT)
        or standard.Directory
    ):
        raise GitInspectionError(f"bundle entry is not a regular file: {name}")


def _win_write_all(handle: int, payload: bytes) -> None:
    kernel32, _ntdll = _windows_api()
    offset = 0
    buffer = ctypes.create_string_buffer(payload)
    while offset < len(payload):
        written = wintypes.DWORD()
        if not kernel32.WriteFile(
            wintypes.HANDLE(handle),
            ctypes.byref(buffer, offset),
            len(payload) - offset,
            ctypes.byref(written),
            None,
        ):
            _raise_windows_error("write bundle entry")
        if written.value == 0:
            raise OSError("short Windows bundle write")
        offset += int(written.value)
    if not kernel32.FlushFileBuffers(wintypes.HANDLE(handle)):
        _raise_windows_error("flush bundle entry")


def _win_read_all(handle: int) -> bytes:
    kernel32, _ntdll = _windows_api()
    standard = _win_handle_standard_info(handle)
    size = int(standard.EndOfFile)
    if size < 0 or size > _MAX_BUNDLE_FILE_BYTES:
        raise GitInspectionError(f"invalid bundle entry size: {size}")
    if not kernel32.SetFilePointerEx(
        wintypes.HANDLE(handle), ctypes.c_longlong(0), None, _FILE_BEGIN
    ):
        _raise_windows_error("rewind bundle entry")
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk_size = min(remaining, 1024 * 1024)
        buffer = ctypes.create_string_buffer(chunk_size)
        read = wintypes.DWORD()
        if not kernel32.ReadFile(
            wintypes.HANDLE(handle),
            buffer,
            chunk_size,
            ctypes.byref(read),
            None,
        ):
            _raise_windows_error("read bundle entry")
        if read.value == 0:
            raise GitInspectionError("short bundle entry read")
        chunks.append(buffer.raw[: read.value])
        remaining -= int(read.value)
    return b"".join(chunks)


def _win_directory_entries(handle: int) -> dict[str, int]:
    kernel32, _ntdll = _windows_api()
    entries: dict[str, int] = {}
    information_class = _FILE_ID_BOTH_DIRECTORY_RESTART_INFO_CLASS
    while True:
        buffer = ctypes.create_string_buffer(64 * 1024)
        if not kernel32.GetFileInformationByHandleEx(
            wintypes.HANDLE(handle), information_class, buffer, len(buffer)
        ):
            error = ctypes.get_last_error()
            if error == _ERROR_NO_MORE_FILES:
                break
            _raise_windows_error("enumerate staging directory")
        information_class = _FILE_ID_BOTH_DIRECTORY_INFO_CLASS
        address = ctypes.addressof(buffer)
        offset = 0
        while True:
            entry = _FILE_ID_BOTH_DIR_INFO.from_address(address + offset)
            name = ctypes.wstring_at(
                address + offset + _FILE_ID_BOTH_DIR_INFO.FileName.offset,
                entry.FileNameLength // ctypes.sizeof(ctypes.c_wchar),
            )
            if name not in {".", ".."}:
                if name in entries:
                    raise GitInspectionError(
                        f"duplicate bundle directory entry: {name}"
                    )
                entries[name] = int(entry.FileAttributes)
            if entry.NextEntryOffset == 0:
                break
            offset += int(entry.NextEntryOffset)
    return entries


def _win_assert_staging_path_identity(
    staging: Path, expected: tuple[int, bytes]
) -> None:
    current_handle = None
    try:
        current_handle = _win_open_directory_path(staging, lock_name=False)
        attributes = _win_handle_attributes(current_handle)
        if (
            attributes & _FILE_ATTRIBUTE_REPARSE_POINT
            or not attributes & _FILE_ATTRIBUTE_DIRECTORY
            or _win_handle_identity(current_handle) != expected
        ):
            raise GitInspectionError("staging directory changed during bundle write")
    except OSError as error:
        raise GitInspectionError(
            "staging directory changed during bundle write"
        ) from error
    finally:
        _win_close(current_handle)


def _win_rename_handle_exclusive(
    directory_handle: int, parent_handle: int, audit_id: str
) -> None:
    _kernel32, ntdll = _windows_api()
    name_bytes = audit_id.encode("utf-16-le")

    class _FILE_RENAME_INFO_BUFFER(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", ctypes.c_wchar * 1),
        ]

    file_name_offset = _FILE_RENAME_INFO_BUFFER.FileName.offset
    buffer = ctypes.create_string_buffer(
        ctypes.sizeof(_FILE_RENAME_INFO_BUFFER) + len(name_bytes)
    )
    rename_info = _FILE_RENAME_INFO_BUFFER.from_buffer(buffer)
    rename_info.Flags = 0
    rename_info.RootDirectory = wintypes.HANDLE(parent_handle)
    rename_info.FileNameLength = len(name_bytes)
    ctypes.memmove(
        ctypes.addressof(buffer) + file_name_offset, name_bytes, len(name_bytes)
    )
    io_status = _IO_STATUS_BLOCK()
    status = int(
        ntdll.NtSetInformationFile(
            wintypes.HANDLE(directory_handle),
            ctypes.byref(io_status),
            buffer,
            len(buffer),
            _FILE_RENAME_INFORMATION_CLASS,
        )
    )
    if status < 0:
        _raise_nt_error("publish audit bundle", status)


def _open_windows_staging(output_path: Path, staging_name: str) -> _WindowsStaging:
    parent_handle = None
    directory_handle = None
    try:
        parent_handle = _win_open_directory_path(output_path, lock_name=True)
        _win_assert_plain_directory(parent_handle, "output parent")
        directory_handle = _win_nt_relative_handle(
            parent_handle, staging_name, directory=True, create=True
        )
        _win_assert_plain_directory(directory_handle, "staging directory")
        return _WindowsStaging(
            parent_handle=parent_handle,
            directory_handle=directory_handle,
            directory_identity=_win_handle_identity(directory_handle),
            files={},
        )
    except Exception:
        _win_close(directory_handle)
        _win_close(parent_handle)
        raise


def _verify_windows_staging(
    staging_state: _WindowsStaging,
    staging_path: Path,
    rendered: dict[str, bytes],
    manifest_bytes: bytes,
) -> None:
    _win_assert_staging_path_identity(staging_path, staging_state.directory_identity)
    entries = _win_directory_entries(staging_state.directory_handle)
    if set(entries) != set(_BUNDLE_NAMES) or len(entries) != len(_BUNDLE_NAMES):
        raise GitInspectionError(
            "staging directory does not contain the exact bundle files"
        )
    expected_payloads = {**rendered, "bundle-manifest.json": manifest_bytes}
    disk_payloads: dict[str, bytes] = {}
    for name in _BUNDLE_NAMES:
        target = staging_state.files.get(name)
        if target is None or target.identity is None:
            raise GitInspectionError(f"missing bound bundle identity: {name}")
        if entries[name] & (_FILE_ATTRIBUTE_DIRECTORY | _FILE_ATTRIBUTE_REPARSE_POINT):
            raise GitInspectionError(f"bundle entry is not a regular file: {name}")
        current_handle = None
        try:
            current_handle = _win_nt_relative_handle(
                staging_state.directory_handle, name, directory=False, create=False
            )
            _win_assert_regular_file(current_handle, name)
            if _win_handle_identity(current_handle) != target.identity:
                raise GitInspectionError(f"bundle entry identity changed: {name}")
            disk_payloads[name] = _win_read_all(current_handle)
        finally:
            _win_close(current_handle)
        if disk_payloads[name] != expected_payloads[name]:
            raise GitInspectionError(f"bundle entry bytes changed: {name}")
    try:
        manifest = json.loads(disk_payloads["bundle-manifest.json"].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise GitInspectionError("invalid on-disk bundle manifest") from error
    if list(manifest.get("files", {})) != list(_BUNDLE_PAYLOAD_NAMES):
        raise GitInspectionError("invalid on-disk bundle manifest file set")
    for name in _BUNDLE_PAYLOAD_NAMES:
        payload = disk_payloads[name]
        expected_binding = {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        }
        if manifest["files"].get(name) != expected_binding:
            raise GitInspectionError(f"on-disk manifest mismatch: {name}")
def _close_windows_staging(staging_state: _WindowsStaging | None) -> None:
    if staging_state is None:
        return
    for target in staging_state.files.values():
        _win_close(target.handle)
        target.handle = None
    _win_close(staging_state.directory_handle)
    _win_close(staging_state.parent_handle)


def _write_exclusive(path: Path | _WindowsFileTarget, payload: bytes) -> None:
    if isinstance(path, _WindowsFileTarget):
        if path.handle is not None or path.identity is not None:
            raise OSError(f"bundle entry already exists: {path.name}")
        path.handle = _win_nt_relative_handle(
            path.directory_handle, path.name, directory=False, create=True
        )
        try:
            _win_assert_regular_file(path.handle, path.name)
            path.identity = _win_handle_identity(path.handle)
            _win_write_all(path.handle, payload)
        finally:
            _win_close(path.handle)
            path.handle = None
        return
    with path.open("xb") as stream:
        offset = 0
        while offset < len(payload):
            written = stream.write(payload[offset:])
            if written is None or written <= 0:
                raise OSError(f"short write: {path}")
            offset += written
        stream.flush()
        os.fsync(stream.fileno())


def _assert_plain_bundle_directory(bundle: Path) -> None:
    try:
        if _is_reparse_point(bundle) or not bundle.is_dir():
            raise GitInspectionError("audit bundle is not an ordinary directory")
    except OSError as error:
        raise GitInspectionError("cannot inspect audit bundle directory") from error


def _read_regular_bundle_file(bundle: Path, name: str) -> bytes:
    path = bundle / name
    try:
        if _is_reparse_point(path) or not path.is_file():
            raise GitInspectionError(f"bundle entry is not a regular file: {name}")
        return path.read_bytes()
    except OSError as error:
        raise GitInspectionError(f"cannot read bundle entry: {name}") from error


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _decode_bundle_json(payload: bytes, context: str) -> dict[str, Any]:
    try:
        decoded = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise GitInspectionError(f"invalid {context} JSON") from error
    if not isinstance(decoded, dict):
        raise GitInspectionError(f"invalid {context} JSON object")
    return decoded


def verify_report_bundle(bundle: Path, audit_id: str) -> dict[str, Any]:
    """Validate an audit bundle's manifest marker and payload bindings.

    The directory remains mutable by its owner after this function returns, so every
    consumer must call this verifier immediately before using a bundle.
    """
    _validate_audit_id(audit_id)
    bundle_path = _absolute_path(bundle)
    if bundle_path.name != audit_id:
        raise GitInspectionError("audit bundle directory does not match audit id")
    _assert_plain_bundle_directory(bundle_path)
    try:
        entries = {entry.name for entry in bundle_path.iterdir()}
    except OSError as error:
        raise GitInspectionError("cannot enumerate audit bundle") from error
    if entries != set(_BUNDLE_NAMES):
        raise GitInspectionError("audit bundle does not contain the exact bundle files")

    payloads = {
        name: _read_regular_bundle_file(bundle_path, name)
        for name in _BUNDLE_PAYLOAD_NAMES
    }
    manifest_bytes = _read_regular_bundle_file(bundle_path, "bundle-manifest.json")
    manifest = _decode_bundle_json(manifest_bytes, "audit bundle manifest")
    if manifest.get("schema") != "health-asset-integrity-bundle-v1":
        raise GitInspectionError("invalid audit bundle manifest schema")
    if manifest.get("audit_id") != audit_id:
        raise GitInspectionError("audit bundle manifest audit id mismatch")
    if manifest.get("report_schema") != "health_asset_integrity.v1":
        raise GitInspectionError("audit bundle manifest report schema mismatch")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(_BUNDLE_PAYLOAD_NAMES):
        raise GitInspectionError("invalid audit bundle manifest file set")
    for name, payload in payloads.items():
        binding = files[name]
        expected = {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        }
        if binding != expected:
            raise GitInspectionError(f"audit bundle manifest mismatch: {name}")
    audit_report = _decode_bundle_json(payloads["audit.json"], "audit report")
    if audit_report.get("schema") != "health_asset_integrity.v1":
        raise GitInspectionError("audit report schema mismatch")
    if audit_report["schema"] != manifest["report_schema"]:
        raise GitInspectionError("audit report schema does not match manifest")
    _assert_plain_bundle_directory(bundle_path)
    try:
        final_entries = {entry.name for entry in bundle_path.iterdir()}
    except OSError as error:
        raise GitInspectionError("cannot enumerate audit bundle") from error
    if final_entries != entries:
        raise GitInspectionError("audit bundle changed during verification")
    return manifest


def write_report_bundle(
    output_parent: Path, audit_id: str, report: AuditReport
) -> Path:
    _validate_audit_id(audit_id)
    output_path = _prepare_output_parent(output_parent)
    target = output_path / audit_id
    staging = output_path / f".{audit_id}.staging"
    if os.path.lexists(target) or os.path.lexists(staging):
        raise GitInspectionError(f"audit output already exists: {audit_id}")
    created = False
    try:
        target.mkdir()
        created = True
        _assert_plain_directory_chain(output_path)
        _assert_plain_bundle_directory(target)
        payload = report_to_dict(report)
        rendered = {
            "audit.json": (
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8"),
            "deleted-assets.csv": render_deleted_assets_csv(report),
            "audit-summary.md": render_audit_summary(report),
        }
        for name in _BUNDLE_PAYLOAD_NAMES:
            _write_exclusive(target / name, rendered[name])
        manifest = {
            "schema": "health-asset-integrity-bundle-v1",
            "audit_id": audit_id,
            "report_schema": report.schema,
            "files": {
                name: {
                    "sha256": hashlib.sha256(rendered[name]).hexdigest(),
                    "bytes": len(rendered[name]),
                }
                for name in _BUNDLE_PAYLOAD_NAMES
            },
        }
        manifest_bytes = (
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        _write_exclusive(target / "bundle-manifest.json", manifest_bytes)
        _assert_plain_directory_chain(output_path)
        verify_report_bundle(target, audit_id)
    except GitInspectionError:
        raise
    except OSError as error:
        if not created and os.path.lexists(target):
            raise GitInspectionError(
                f"audit output already exists: {audit_id}"
            ) from error
        raise GitInspectionError(f"failed to write audit bundle: {error}") from error
    except (UnicodeError, ValueError, TypeError, csv.Error) as error:
        raise GitInspectionError(f"failed to render audit bundle: {error}") from error
    return target
