# Health Asset Integrity Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个可重复、失败关闭的只读审计工具，查明当前健康内容工作树中 240 个 Grok 手动包删除记录的 Git blob、原始资产、远程分支、大文件与 LFS 可恢复性，且不恢复、删除、移动、暂存或提交任何现有资产。

**Architecture:** 在新的隔离 Git worktree 中以 TDD 开发 `GitInspector` 和健康资产分类器，然后将 CLI 指向当前脏工作树。审计只调用白名单 Git 读命令，对 HEAD、index 和 porcelain status 做前后指纹；报告原子写入仓库外部目录。

**Tech Stack:** Python 3.11、`subprocess`、`dataclasses`、`hashlib`、`csv`、`json`、`pytest`、Git 2.55、Git LFS 3.7、PowerShell 7。

**Spec:** `docs/superpowers/specs/2026-08-18-media-intelligence-premium-video-design.md`

## Global Constraints

- 实施时必须先用 `superpowers:using-git-worktrees` 创建 `E:\MoneyPrinterTurbo-3期\MoneyPrinterTurbo\.worktrees\health-asset-integrity-audit`，不在当前脏工作树中编辑代码。
- 待审计目标固定为 `E:\MoneyPrinterTurbo-3期\MoneyPrinterTurbo\.worktrees\health-content-system`。
- 禁止调用 `git checkout`、`restore`、`reset`、`clean`、`fetch`、`pull`、`lfs pull`、`add`、`commit`、`rm` 或任何写仓库命令来处理待审计工作树。
- 所有 Git 子进程必须设置 `GIT_OPTIONAL_LOCKS=0`；远程只使用 `git ls-remote`，不更新本地 refs。
- 审计输出固定为 `E:\MoneyPrinterTurbo-3期\audit-evidence\HCAS-20260818-01`，必须不存在于执行前；输出目录不得位于目标仓库内。
- 审计只读取文件名、Git object ID、字节数、哈希、属性和状态；不把 Cookie、凭据、媒体内容或用户数据写入报告。
- 如果当前删除总数不再是 240，或者不再是 HC20260810-001–010 每期 24 个，停止真实审计执行并向用户报告新快照；不自动更改预期值。
- 审计结果只提供“精确从 HEAD 恢复”、“在外部临时目录重生并比对”、“确认保留删除”三类后续决策证据；本计划不执行任何一类决策。

---

### Task 1: Read-only Git inspector

**Files:**
- Create: `app/services/health_asset_integrity.py`
- Create: `test/services/test_health_asset_integrity.py`

**Interfaces:**
- Produces: `StatusEntry`, `TreeEntry`, `RepoSnapshot`, `GitInspectionError`, `GitInspector.status()`, `GitInspector.tree()`, `GitInspector.blob()`, `GitInspector.remote_head()`, `GitInspector.snapshot()`.
- Consumes: Python standard library and an existing Git repository path only.

- [ ] **Step 1: Write failing parser and immutability tests**

Add these tests to `test/services/test_health_asset_integrity.py`:

```python
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from app.services.health_asset_integrity import (
    GitInspectionError,
    GitInspector,
    parse_ls_tree_z,
    parse_porcelain_v1_z,
)


def _git(repo: Path, *args: str) -> bytes:
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
    ).stdout


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Audit Test")
    _git(repo, "config", "user.email", "audit@example.invalid")
    tracked = repo / "九期 资产.txt"
    tracked.write_text("锁定资产\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "--", tracked.name)
    _git(repo, "commit", "-m", "fixture")
    tracked.unlink()
    (repo / "未跟踪.txt").write_text("不应改动\n", encoding="utf-8")
    return repo


def test_parse_porcelain_v1_z_preserves_unicode_and_spaces():
    entries = parse_porcelain_v1_z(" D 九期 资产.txt\0?? 未跟踪.txt\0".encode("utf-8"))
    assert [(item.index_status, item.worktree_status, item.path) for item in entries] == [
        (" ", "D", "九期 资产.txt"),
        ("?", "?", "未跟踪.txt"),
    ]


def test_parse_ls_tree_z_keeps_blob_size_and_path():
    raw = b"100644 blob 0123456789012345678901234567890123456789 12\tfoo bar.txt\0"
    assert parse_ls_tree_z(raw)[0].size == 12
    assert parse_ls_tree_z(raw)[0].path == "foo bar.txt"


def test_inspector_does_not_change_head_index_or_status(tmp_path: Path):
    repo = _repo(tmp_path)
    inspector = GitInspector(repo)
    before = inspector.snapshot()
    entries = inspector.status()
    tree = inspector.tree(before.head_sha, ".")
    assert any(item.path == "九期 资产.txt" for item in entries)
    assert any(item.path == "九期 资产.txt" for item in tree)
    assert inspector.snapshot() == before


def test_inspector_rejects_non_whitelisted_git_subcommand(tmp_path: Path):
    inspector = GitInspector(_repo(tmp_path))
    with pytest.raises(GitInspectionError, match="not allowed"):
        inspector._run(("restore", "."))
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
& 'E:\MoneyPrinterTurbo-3期\MoneyPrinterTurbo\.venv\Scripts\python.exe' -m pytest test/services/test_health_asset_integrity.py -q
```

Expected: collection fails because `app.services.health_asset_integrity` does not exist.

- [ ] **Step 3: Implement the inspector and null-delimited parsers**

Create `app/services/health_asset_integrity.py` with these public types and behaviors:

```python
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
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.repo,
                capture_output=True,
                text=True,
                check=False,
            )
            if probe.returncode != 0 or probe.stdout.strip() != "true":
                raise GitInspectionError(f"not a git worktree: {self.repo}")

    def _run(self, args: Sequence[str], *, allowed_exit_codes: tuple[int, ...] = (0,)) -> bytes:
        if not args or args[0] not in ALLOWED_GIT_SUBCOMMANDS:
            raise GitInspectionError(f"git subcommand not allowed: {args[0] if args else '<empty>'}")
        env = os.environ.copy()
        env["GIT_OPTIONAL_LOCKS"] = "0"
        completed = subprocess.run(
            ["git", *args], cwd=self.repo, env=env, capture_output=True, check=False
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
```

The absolute Git directory is resolved as a read-only linked-worktree validation and is intentionally absent from the returned model. Do not add any generic command escape hatch.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
& 'E:\MoneyPrinterTurbo-3期\MoneyPrinterTurbo\.venv\Scripts\python.exe' -m pytest test/services/test_health_asset_integrity.py -q
```

Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add -- app/services/health_asset_integrity.py test/services/test_health_asset_integrity.py
git diff --cached --check
git commit -m 'feat: add read-only git asset inspector'
```

### Task 2: Health manual-pack classification and recoverability model

**Files:**
- Modify: `app/services/health_asset_integrity.py`
- Modify: `test/services/test_health_asset_integrity.py`

**Interfaces:**
- Consumes: `GitInspector`, `StatusEntry`, `TreeEntry`, `RepoSnapshot` from Task 1.
- Produces: `DeletedAsset`, `LargeBlob`, `AuditReport`, `audit_health_assets(inspector, remote, remote_ref)` and `report_to_dict(report)`.

- [ ] **Step 1: Add failing domain tests**

Append tests that create ten fixture episodes with the exact 24-file shape and assert classification:

```python
from app.services.health_asset_integrity import (
    audit_health_assets,
    is_lfs_pointer,
    report_to_dict,
)


def _manual_pack_files(content_id: str) -> dict[str, bytes]:
    root = f"09_泛健康日更/work/{content_id}/production/v01/04_grok_batch/manual_pack"
    payloads: dict[str, bytes] = {}
    for shot in range(1, 11):
        payloads[f"{root}/01_first_frames/{content_id}-v01-S{shot:02d}-firstframe.png"] = b"\x89PNG\r\n\x1a\n" + bytes([shot])
        payloads[f"{root}/02_prompts/{content_id}-v01-S{shot:02d}-prompt-zh-en.txt"] = f"S{shot:02d} prompt\n".encode()
    payloads[f"{root}/{content_id}-v01-Grok-Automation-10条提示词.txt"] = b"merged\n"
    payloads[f"{root}/MANIFEST.csv"] = b"shot,path\n"
    payloads[f"{root}/MANUAL-GENERATION-GUIDE.md"] = b"guide\n"
    payloads[f"{root}/MANUAL-PACK-QA.md"] = b"qa\n"
    return payloads


def test_audit_classifies_24_deletions_per_episode_and_head_recoverability(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Audit Test")
    _git(repo, "config", "user.email", "audit@example.invalid")
    for number in range(1, 11):
        for relative, payload in _manual_pack_files(f"HC20260810-{number:03d}").items():
            path = repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
    _git(repo, "add", "--", "09_泛健康日更")
    _git(repo, "commit", "-m", "manual packs")
    for path in (repo / "09_泛健康日更").rglob("*"):
        if path.is_file() and "manual_pack" in path.parts:
            path.unlink()
    report = audit_health_assets(GitInspector(repo), remote=None, remote_ref=None)
    payload = report_to_dict(report)
    assert payload["summary"]["deleted_manual_pack_files"] == 240
    assert payload["summary"]["episodes"] == 10
    assert {item["deleted_count"] for item in payload["episodes"]} == {24}
    assert {item["head_blob_recoverable"] for item in payload["deleted_assets"]} == {True}
    assert payload["summary"]["first_frames"] == 100
    assert payload["summary"]["prompts"] == 100
    assert payload["summary"]["control_files"] == 40


def test_first_frame_source_comparison_is_reported_without_copying(tmp_path: Path):
    repo = _repo_with_one_manual_pack_and_matching_formal(tmp_path)
    before = GitInspector(repo).snapshot()
    report = audit_health_assets(GitInspector(repo), remote=None, remote_ref=None)
    first_frame = next(item for item in report.deleted_assets if item.asset_kind == "first_frame")
    assert first_frame.source_path.endswith("/03_first_frames/HC20260810-001-v01-S01-firstframe.png")
    assert first_frame.source_exists is True
    assert first_frame.source_sha256 == first_frame.head_blob_sha256
    assert GitInspector(repo).snapshot() == before


def test_lfs_pointer_and_plain_large_blob_are_not_confused():
    pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"a" * 64 + b"\nsize 99\n"
    assert is_lfs_pointer(pointer) is True
    assert is_lfs_pointer(b"\x89PNG\r\n\x1a\n") is False
```

Implement `_repo_with_one_manual_pack_and_matching_formal()` in the test using a committed formal PNG with identical bytes and a deleted copied manual-pack PNG.

- [ ] **Step 2: Run the domain tests and verify RED**

Run the same focused pytest command. Expected: imports or assertions fail because the domain model does not exist.

- [ ] **Step 3: Implement exact classification and report fields**

Add these domain models and constants:

```python
import re
from dataclasses import asdict
from typing import Any

MANUAL_PACK_RE = re.compile(
    r"^09_泛健康日更/work/(HC20260810-\d{3})/production/v01/04_grok_batch/manual_pack/(.+)$"
)
LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1\n"
LARGE_BLOB_THRESHOLD = 50 * 1024 * 1024


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


def is_lfs_pointer(payload: bytes) -> bool:
    return payload.startswith(LFS_PREFIX) and b"\noid sha256:" in payload and b"\nsize " in payload
```

Implement `audit_health_assets()` with this exact behavior:

1. Snapshot before inspection.
2. Filter worktree deletions whose `path` matches `MANUAL_PACK_RE` and whose `worktree_status == "D"` or `index_status == "D"`.
3. Read the corresponding HEAD tree entry and blob through `GitInspector`; never read the missing worktree path.
4. Classify `01_first_frames/*.png` as `first_frame`, `02_prompts/*.txt` as `prompt`, and the four root files as `control`.
5. Map a first-frame source by replacing `/04_grok_batch/manual_pack/01_first_frames/` with `/03_first_frames/`. Hash an existing source in place without copying it.
6. Enumerate all HEAD blobs above 50 MiB using `git ls-tree -r -z -l HEAD` and identify pointer content separately from large underlying media.
7. Call `git lfs version` and `git lfs ls-files --all -n` through a dedicated `_run_lfs_readonly()` that only allows `version` and `ls-files`; report failure as incomplete evidence, not as an empty LFS set.
8. If `remote` and `remote_ref` are provided, call only `ls-remote`; if the remote SHA object already exists locally, compare the scoped tree. Do not fetch a missing remote object. Mark `remote.tree_comparison="unavailable_without_fetch"` when it is absent.
9. Snapshot after inspection and require byte-for-byte dataclass equality. If not equal, raise `GitInspectionError("repository changed during audit")` and do not produce a complete report.
10. Return decision options, never an automatic decision:

```python
(
    {"id": "restore_exact_from_head", "meaning": "按 HEAD blob 精确恢复，需用户另行授权"},
    {"id": "regenerate_outside_repo_and_compare", "meaning": "在外部临时目录重生，逐字节比对后再决策"},
    {"id": "keep_deletions", "meaning": "确认删除意图并另行更新下游清单"},
)
```

`report_to_dict()` must recursively convert dataclasses and tuples into JSON-safe dictionaries/lists without changing order.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the full `test_health_asset_integrity.py`; expected all tests pass and the fixture repository snapshot remains unchanged.

- [ ] **Step 5: Commit Task 2**

```powershell
git add -- app/services/health_asset_integrity.py test/services/test_health_asset_integrity.py
git diff --cached --check
git commit -m 'feat: classify health asset deletion evidence'
```

### Task 3: Fail-closed CLI and external audit bundle

**Files:**
- Create: `09_泛健康日更/scripts/audit_health_assets.py`
- Create: `test/services/test_health_asset_integrity_cli.py`
- Create: `docs/runbooks/health-asset-integrity-audit.md`
- Modify: `app/services/health_asset_integrity.py`

**Interfaces:**
- Consumes: `audit_health_assets()` and `report_to_dict()` from Task 2.
- Produces: `write_report_bundle(output_parent, audit_id, report) -> Path` and CLI command `audit`.
- CLI output bundle: `audit.json`, `deleted-assets.csv`, `audit-summary.md`, `bundle-manifest.json`.

- [ ] **Step 1: Write failing CLI safety tests**

Create `test/services/test_health_asset_integrity_cli.py` with tests that invoke the CLI using `sys.executable`:

```python
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLI = PROJECT_ROOT / "09_泛健康日更" / "scripts" / "audit_health_assets.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def test_cli_rejects_output_inside_audited_repo(tmp_path: Path):
    repo = create_deleted_pack_repo(tmp_path)
    result = _run(
        "audit", "--repo", str(repo), "--output-parent", str(repo / "reports"),
        "--audit-id", "HCAS-TEST-01",
    )
    assert result.returncode == 3
    assert "outside audited repository" in result.stdout
    assert not (repo / "reports").exists()


def test_cli_writes_new_bundle_without_mutating_repo(tmp_path: Path):
    repo = create_deleted_pack_repo(tmp_path)
    output_parent = tmp_path / "evidence"
    before = repository_fingerprint(repo)
    result = _run(
        "audit", "--repo", str(repo), "--output-parent", str(output_parent),
        "--audit-id", "HCAS-TEST-01",
    )
    assert result.returncode == 0, result.stdout
    bundle = output_parent / "HCAS-TEST-01"
    assert {path.name for path in bundle.iterdir()} == {
        "audit.json", "deleted-assets.csv", "audit-summary.md", "bundle-manifest.json"
    }
    assert repository_fingerprint(repo) == before
    manifest = json.loads((bundle / "bundle-manifest.json").read_text("utf-8"))
    for name in ("audit.json", "deleted-assets.csv", "audit-summary.md"):
        assert manifest["files"][name]["sha256"] == hashlib.sha256((bundle / name).read_bytes()).hexdigest()


def test_cli_refuses_existing_audit_id_without_rewrite(tmp_path: Path):
    repo = create_deleted_pack_repo(tmp_path)
    output_parent = tmp_path / "evidence"
    first = _run("audit", "--repo", str(repo), "--output-parent", str(output_parent), "--audit-id", "HCAS-TEST-01")
    assert first.returncode == 0
    before = {p.name: p.read_bytes() for p in (output_parent / "HCAS-TEST-01").iterdir()}
    second = _run("audit", "--repo", str(repo), "--output-parent", str(output_parent), "--audit-id", "HCAS-TEST-01")
    assert second.returncode == 3
    assert {p.name: p.read_bytes() for p in (output_parent / "HCAS-TEST-01").iterdir()} == before
```

Reuse fixture helpers by moving them to `test/services/health_asset_audit_fixtures.py`; do not import one test module from another.

- [ ] **Step 2: Run CLI tests and verify RED**

Run:

```powershell
& 'E:\MoneyPrinterTurbo-3期\MoneyPrinterTurbo\.venv\Scripts\python.exe' -m pytest test/services/test_health_asset_integrity_cli.py -q
```

Expected: CLI file is missing.

- [ ] **Step 3: Implement atomic external bundle writer**

Add concrete byte renderers for the CSV and Markdown plus an exclusive writer, then implement `write_report_bundle()` with this structure:

```python
def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def write_report_bundle(output_parent: Path, audit_id: str, report: AuditReport) -> Path:
    output_parent = output_parent.resolve()
    target = output_parent / audit_id
    staging = output_parent / f".{audit_id}.staging"
    if target.exists() or staging.exists():
        raise GitInspectionError(f"audit output already exists: {audit_id}")
    staging.mkdir(parents=True, exist_ok=False)
    payload = report_to_dict(report)
    rendered = {
        "audit.json": (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        "deleted-assets.csv": render_deleted_assets_csv(report),
        "audit-summary.md": render_audit_summary(report),
    }
    for name, content in rendered.items():
        _write_exclusive(staging / name, content)
    manifest = {
        "schema": "health-asset-integrity-bundle-v1",
        "audit_id": audit_id,
        "report_schema": report.schema,
        "files": {
            name: {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
            for name, content in rendered.items()
        },
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _write_exclusive(staging / "bundle-manifest.json", manifest_bytes)
    os.replace(staging, target)
    return target
```

Implement `render_deleted_assets_csv()` and `render_audit_summary()` so that:

- `audit.json`: `json.dumps(payload, ensure_ascii=False, indent=2) + "\n"`.
- `deleted-assets.csv`: fixed columns matching every `DeletedAsset` field; use `csv.DictWriter(..., lineterminator="\n")`.
- `audit-summary.md`: counts, per-episode table, remote state, LFS state, large-blob table, mutation guard, and the three user decision options. It must not include blob contents.
- `bundle-manifest.json`: schema `health-asset-integrity-bundle-v1`, audit ID, report schema, and SHA-256/bytes for the other three files.
- Open files in exclusive create mode. Flush and call `os.fsync()` before directory rename.
- On a write failure, keep the staging directory as evidence and fail closed; do not recursively delete it.

Add `ensure_external_output(repo, output_parent)` that rejects equality, descendants of the repo, symlinks, and Windows reparse points in the output path chain.

- [ ] **Step 4: Implement the CLI and exact exit codes**

Create `09_泛健康日更/scripts/audit_health_assets.py`:

```python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.health_asset_integrity import (
    GitInspectionError,
    GitInspector,
    audit_health_assets,
    ensure_external_output,
    write_report_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only health asset integrity audit")
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit")
    audit.add_argument("--repo", required=True, type=Path)
    audit.add_argument("--output-parent", required=True, type=Path)
    audit.add_argument("--audit-id", required=True)
    audit.add_argument("--remote", default="personal")
    audit.add_argument("--remote-ref", default="refs/heads/feature/health-content-system")
    args = parser.parse_args()
    try:
        ensure_external_output(args.repo, args.output_parent)
        report = audit_health_assets(
            GitInspector(args.repo), remote=args.remote, remote_ref=args.remote_ref
        )
        bundle = write_report_bundle(args.output_parent, args.audit_id, report)
    except GitInspectionError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 3
    exit_code = 0 if report.summary["audit_complete"] else 4
    status = "complete" if exit_code == 0 else "incomplete"
    print(json.dumps({"status": status, "bundle": str(bundle)}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
```

Use exit code 4 instead of 0 when local evidence is complete but remote evidence is unavailable. The report bundle is still written with `summary.audit_complete=false`; no restoration recommendation may be marked preferred.

- [ ] **Step 5: Write the runbook**

Create `docs/runbooks/health-asset-integrity-audit.md` containing:

- the exact production command from Task 4;
- the four output filenames and schemas;
- exit codes 0, 3 and 4;
- the prohibited Git commands from Global Constraints;
- the rule that only the user may choose a disposition after reading the report;
- the rule that an existing audit ID is never overwritten.

- [ ] **Step 6: Run focused and existing health tests**

```powershell
$python='E:\MoneyPrinterTurbo-3期\MoneyPrinterTurbo\.venv\Scripts\python.exe'
& $python -m pytest test/services/test_health_asset_integrity.py test/services/test_health_asset_integrity_cli.py -q
& $python -m pytest test/services/test_health_content.py test/services/test_health_batch_cli.py test/services/test_grok_manual_pack.py -q
& $python -m ruff check app/services/health_asset_integrity.py '09_泛健康日更/scripts/audit_health_assets.py' test/services/test_health_asset_integrity.py test/services/test_health_asset_integrity_cli.py
& $python -m py_compile app/services/health_asset_integrity.py '09_泛健康日更/scripts/audit_health_assets.py'
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit Task 3**

```powershell
git add -- app/services/health_asset_integrity.py '09_泛健康日更/scripts/audit_health_assets.py' test/services/test_health_asset_integrity.py test/services/test_health_asset_integrity_cli.py test/services/health_asset_audit_fixtures.py docs/runbooks/health-asset-integrity-audit.md
git diff --cached --check
git commit -m 'feat: add fail-closed health asset audit CLI'
```

### Task 4: Audit the current dirty worktree and hand back the evidence

**Files:**
- External output only: `E:\MoneyPrinterTurbo-3期\audit-evidence\HCAS-20260818-01\*`

**Interfaces:**
- Consumes: the Task 3 CLI and the current target worktree.
- Produces: an external immutable evidence bundle and a user decision handoff; creates no repository files.

- [ ] **Step 1: Assert the target snapshot before running**

Run from the isolated implementation worktree:

```powershell
$target='E:\MoneyPrinterTurbo-3期\MoneyPrinterTurbo\.worktrees\health-content-system'
$status=@(git -C $target -c core.quotepath=false status --porcelain=v1)
$deletions=@($status | Where-Object { $_ -match '^ D|^D ' })
if($deletions.Count -ne 240){ throw "Expected 240 deletions, found $($deletions.Count)" }
$groups=$deletions | ForEach-Object {
  if($_ -match 'HC20260810-(\d{3})'){ "HC20260810-$($matches[1])" } else { 'OTHER' }
} | Group-Object
if($groups.Count -ne 10 -or @($groups | Where-Object Count -ne 24).Count -ne 0){
  throw 'Deletion distribution is no longer 10 episodes x 24 files'
}
```

Expected: no output and exit 0. Any mismatch stops the task.

- [ ] **Step 2: Run the real read-only audit**

```powershell
$python='E:\MoneyPrinterTurbo-3期\MoneyPrinterTurbo\.venv\Scripts\python.exe'
& $python '09_泛健康日更/scripts/audit_health_assets.py' audit `
  --repo 'E:\MoneyPrinterTurbo-3期\MoneyPrinterTurbo\.worktrees\health-content-system' `
  --output-parent 'E:\MoneyPrinterTurbo-3期\audit-evidence' `
  --audit-id 'HCAS-20260818-01' `
  --remote personal `
  --remote-ref 'refs/heads/feature/health-content-system'
```

Expected: exit 0 with `status=complete`; exit 4 is allowed only as an incomplete remote-evidence result and must be reported without proceeding to a disposition recommendation.

- [ ] **Step 3: Independently validate bundle bytes and the mutation guard**

```powershell
$bundle='E:\MoneyPrinterTurbo-3期\audit-evidence\HCAS-20260818-01'
$python='E:\MoneyPrinterTurbo-3期\MoneyPrinterTurbo\.venv\Scripts\python.exe'
& $python -c "import hashlib,json,pathlib; p=pathlib.Path(r'$bundle'); m=json.loads((p/'bundle-manifest.json').read_text('utf-8')); assert all(hashlib.sha256((p/n).read_bytes()).hexdigest()==v['sha256'] and len((p/n).read_bytes())==v['bytes'] for n,v in m['files'].items()); a=json.loads((p/'audit.json').read_text('utf-8')); assert a['summary']['deleted_manual_pack_files']==240; assert a['mutation_guard']['unchanged'] is True; print('BUNDLE_PASS')"
```

Then rerun the Step 1 status count. Expected: still 240 and 10×24.

- [ ] **Step 4: Run final verification and hand the decision back to the user**

```powershell
$python='E:\MoneyPrinterTurbo-3期\MoneyPrinterTurbo\.venv\Scripts\python.exe'
& $python -m pytest test/services/test_health_asset_integrity.py test/services/test_health_asset_integrity_cli.py -q
& $python -m pytest test/services/test_health_content.py test/services/test_health_batch_cli.py test/services/test_grok_manual_pack.py -q
& $python -m ruff check app/services/health_asset_integrity.py '09_泛健康日更/scripts/audit_health_assets.py' test/services/test_health_asset_integrity.py test/services/test_health_asset_integrity_cli.py
& $python -m py_compile app/services/health_asset_integrity.py '09_泛健康日更/scripts/audit_health_assets.py'
git diff --check
```

Expected: all tests and static checks pass; the target status still reports 240 deletions distributed as 10 episodes × 24 files. Report the exact bundle path, manifest hash, HEAD/remote relationship, 240-file recoverability counts, source-match counts, LFS status, large-blob findings and the unchanged mutation guard. Ask the user to select one of the three dispositions. Do not create a repository receipt and do not execute the selected disposition in this plan.
