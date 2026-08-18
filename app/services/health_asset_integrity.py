from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import subprocess
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

_ORDINARY_STATUSES = frozenset({
    " A", " M", " T", " D", " R", " C",
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

MANUAL_PACK_RE = re.compile(
    r"^09_泛健康日更/work/(HC20260810-\d{3})/production/v01/04_grok_batch/manual_pack/(.+)$"
)
LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1\n"
LARGE_BLOB_THRESHOLD = 50 * 1024 * 1024
_CONTROL_FILES = frozenset({
    "MANIFEST.csv",
    "MANUAL-GENERATION-GUIDE.md",
    "MANUAL-PACK-QA.md",
})
_AUDIT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_BUNDLE_PAYLOAD_NAMES = (
    "audit.json",
    "deleted-assets.csv",
    "audit-summary.md",
)


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
        if format_probe.returncode != 0 or format_probe.stdout not in {b"0\n", b"0\r\n"}:
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
        if has_control or re.fullmatch(
            r"git-lfs/\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?"
            r"(?: \([^\r\n]+\))?",
            version_line,
        ) is None:
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
    result["tree_comparison"] = "identical" if remote_tree == local_scoped_tree else "different"
    return result, True


def audit_health_assets(
    inspector: GitInspector,
    remote: str | None,
    remote_ref: str | None,
) -> AuditReport:
    before = inspector.snapshot()
    status = inspector.status()
    head_tree = inspector.tree(before.head_sha, ".")
    head_by_path = {entry.path: entry for entry in head_tree if entry.object_type == "blob"}
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
        deleted_assets.append(DeletedAsset(
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
        ))

    large_blobs: list[LargeBlob] = []
    for entry in head_tree:
        if entry.object_type != "blob" or entry.size is None or entry.size <= LARGE_BLOB_THRESHOLD:
            continue
        try:
            payload = inspector.blob(entry.oid)
        except GitInspectionError:
            evidence_complete = False
            continue
        large_blobs.append(LargeBlob(
            path=entry.path,
            oid=entry.oid,
            size=entry.size,
            lfs_pointer=is_lfs_pointer(payload),
        ))

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
        episode_rows.append({
            "content_id": content_id,
            "deleted_count": len(assets),
            "first_frames": sum(item.asset_kind == "first_frame" for item in assets),
            "prompts": sum(item.asset_kind == "prompt" for item in assets),
            "control_files": sum(item.asset_kind == "control" for item in assets),
        })
    summary = {
        "audit_complete": evidence_complete and lfs_complete and remote_complete,
        "deleted_manual_pack_files": len(deleted_assets),
        "episodes": len(episode_rows),
        "first_frames": sum(item.asset_kind == "first_frame" for item in deleted_assets),
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
            {"id": "restore_exact_from_head", "meaning": "按 HEAD blob 精确恢复，需用户另行授权"},
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
        raise GitInspectionError(f"cannot resolve audited repository: {repo}") from error
    output_path = _absolute_path(output_parent)
    _assert_plain_directory_chain(output_path)
    try:
        resolved_output = output_path.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise GitInspectionError(f"cannot resolve output path: {output_parent}") from error
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
        raise GitInspectionError(f"cannot resolve output path: {output_parent}") from error


def _validate_audit_id(audit_id: str) -> None:
    if _AUDIT_ID_RE.fullmatch(audit_id) is None:
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
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", "").replace(
        "\n", "<br>"
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
    lines.extend([
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
    ])
    for blob in sorted(report.large_blobs, key=lambda item: item.path):
        lines.append(
            f"| {_markdown_cell(blob.path)} | `{_markdown_cell(blob.oid)}` | "
            f"{blob.size} | `{str(blob.lfs_pointer).lower()}` |"
        )
    if not report.large_blobs:
        lines.append("| _None_ | — | — | — |")
    lines.extend([
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
    ])
    for option in report.decision_options:
        lines.append(f"- `{_markdown_cell(option['id'])}` — {_markdown_cell(option['meaning'])}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        offset = 0
        while offset < len(payload):
            written = stream.write(payload[offset:])
            if written is None or written <= 0:
                raise OSError(f"short write: {path}")
            offset += written
        stream.flush()
        os.fsync(stream.fileno())


def write_report_bundle(output_parent: Path, audit_id: str, report: AuditReport) -> Path:
    _validate_audit_id(audit_id)
    output_path = _prepare_output_parent(output_parent)
    target = output_path / audit_id
    staging = output_path / f".{audit_id}.staging"
    if os.path.lexists(target) or os.path.lexists(staging):
        raise GitInspectionError(f"audit output already exists: {audit_id}")
    try:
        staging.mkdir(exist_ok=False)
    except FileExistsError as error:
        raise GitInspectionError(f"audit output already exists: {audit_id}") from error
    except OSError as error:
        raise GitInspectionError(f"cannot create audit staging directory: {staging}") from error
    try:
        payload = report_to_dict(report)
        rendered = {
            "audit.json": (
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8"),
            "deleted-assets.csv": render_deleted_assets_csv(report),
            "audit-summary.md": render_audit_summary(report),
        }
        for name in _BUNDLE_PAYLOAD_NAMES:
            _write_exclusive(staging / name, rendered[name])
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
        _write_exclusive(staging / "bundle-manifest.json", manifest_bytes)
        _assert_plain_directory_chain(output_path)
        if os.path.lexists(target):
            raise GitInspectionError(f"audit output already exists: {audit_id}")
        os.rename(staging, target)
    except GitInspectionError:
        raise
    except OSError as error:
        if os.path.lexists(target):
            raise GitInspectionError(f"audit output already exists: {audit_id}") from error
        raise GitInspectionError(f"failed to write audit bundle: {error}") from error
    except (UnicodeError, ValueError, TypeError, csv.Error) as error:
        raise GitInspectionError(f"failed to render audit bundle: {error}") from error
    return target
