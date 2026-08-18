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
