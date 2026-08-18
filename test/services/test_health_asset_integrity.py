from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import app.services.health_asset_integrity as integrity
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
        ["git", "-c", f"safe.directory={repo.resolve()}", *args],
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


@pytest.mark.parametrize("raw", [
    b"MM changed.txt\0",
    b"UU conflicted.txt\0",
    b"?? untracked.txt\0",
    b"!! ignored.txt\0",
])
def test_parse_porcelain_v1_z_accepts_valid_status_combinations(raw: bytes):
    assert len(parse_porcelain_v1_z(raw)) == 1


@pytest.mark.parametrize("status", [
    " A", " M", " D", " R", " C",
    "M ", "MM", "MT", "MD",
    "T ", "TM", "TT", "TD",
    "A ", "AM", "AT", "AD",
    "D ",
    "R ", "RM", "RT", "RD",
    "C ", "CM", "CT", "CD",
])
def test_parse_porcelain_v1_z_accepts_every_documented_ordinary_status(status: str):
    raw = f"{status} path.txt\0".encode("utf-8")
    if "R" in status or "C" in status:
        raw += b"original.txt\0"
    assert parse_porcelain_v1_z(raw)[0].path == "path.txt"


@pytest.mark.parametrize(("status", "accepted"), [
    (" A", True),
    (" M", True),
    (" D", True),
    (" R", True),
    (" C", True),
    ("M ", True),
    ("MT", True),
    ("AD", True),
    ("R ", True),
    ("CD", True),
    ("D ", True),
    (" T", False),
    ("DM", False),
    ("DT", False),
    ("DA", False),
])
def test_parse_porcelain_v1_z_enforces_documented_ordinary_status_boundaries(
    status: str, accepted: bool
):
    raw = f"{status} path.txt\0".encode("utf-8")
    if "R" in status or "C" in status:
        raw += b"original.txt\0"
    if accepted:
        assert parse_porcelain_v1_z(raw)[0].path == "path.txt"
    else:
        with pytest.raises(GitInspectionError):
            parse_porcelain_v1_z(raw)


def test_inspector_status_accepts_intent_to_add_from_real_git(tmp_path: Path):
    repo = _repo(tmp_path)
    intent = repo / "intent.txt"
    intent.write_text("intent\n", encoding="utf-8")
    _git(repo, "add", "-N", "--", intent.name)

    entry = next(item for item in GitInspector(repo).status() if item.path == intent.name)

    assert (entry.index_status, entry.worktree_status) == (" ", "A")


@pytest.mark.parametrize("raw", [
    b"ZZ impossible.txt\0",
    b"?  impossible.txt\0",
    b"!  impossible.txt\0",
    b"U  impossible.txt\0",
    b"   impossible.txt\0",
])
def test_parse_porcelain_v1_z_rejects_impossible_status_combinations(raw: bytes):
    with pytest.raises(GitInspectionError):
        parse_porcelain_v1_z(raw)


@pytest.mark.parametrize(("status", "destination", "original"), [
    ("R ", "新 名称.txt", "旧 名称.txt"),
    ("C ", "副本 文件.txt", "原始 文件.txt"),
])
def test_parse_porcelain_v1_z_keeps_unicode_rename_and_copy_paths(
    status: str, destination: str, original: str
):
    raw = f"{status} {destination}\0{original}\0".encode("utf-8")
    entry = parse_porcelain_v1_z(raw)[0]
    assert (entry.index_status, entry.worktree_status, entry.path, entry.original_path) == (
        status[0],
        status[1],
        destination,
        original,
    )


@pytest.mark.parametrize(("parser", "raw"), [
    (parse_porcelain_v1_z, b"?? truncated"),
    (parse_porcelain_v1_z, b"?? visible\0\0?? hidden\0"),
    (parse_ls_tree_z, b"100644 blob 0123456789012345678901234567890123456789 1\ttruncated"),
    (parse_ls_tree_z, b"100644 blob not-an-oid 1\tbad.txt\0"),
])
def test_nul_parsers_reject_truncated_or_malformed_machine_records(parser, raw: bytes):
    with pytest.raises(GitInspectionError):
        parser(raw)


def test_parse_ls_tree_z_keeps_blob_size_and_path():
    raw = b"100644 blob 0123456789012345678901234567890123456789 12\tfoo bar.txt\0"
    assert parse_ls_tree_z(raw)[0].size == 12
    assert parse_ls_tree_z(raw)[0].path == "foo bar.txt"


def test_parse_ls_tree_z_accepts_valid_mode_type_size_combinations():
    oid = b"0123456789012345678901234567890123456789"
    raw = b"".join([
        b"100644 blob " + oid + b"      12\tregular.txt\0",
        b"100755 blob " + oid + b"       3\texecutable.sh\0",
        b"120000 blob " + oid + b"       8\tlink\0",
        b"040000 tree " + oid + b" -\tdirectory\0",
        b"160000 commit " + oid + b" -\tsubmodule\0",
    ])
    assert [(entry.mode, entry.object_type, entry.size) for entry in parse_ls_tree_z(raw)] == [
        ("100644", "blob", 12),
        ("100755", "blob", 3),
        ("120000", "blob", 8),
        ("040000", "tree", None),
        ("160000", "commit", None),
    ]


@pytest.mark.parametrize("record", [
    b"999999 blob 0123456789012345678901234567890123456789 1\tbad.txt\0",
    b"100644 tree 0123456789012345678901234567890123456789 1\tbad.txt\0",
    b"100644 blob 0123456789012345678901234567890123456789 -\tbad.txt\0",
    b"040000 tree 0123456789012345678901234567890123456789 1\tbad.txt\0",
    b"160000 commit 0123456789012345678901234567890123456789 1\tbad.txt\0",
    b"100644 blob 0123456789012345678901234567890123456789 -1\tbad.txt\0",
    b"100644 blob 0123456789012345678901234567890123456789 nope\tbad.txt\0",
    b"040000 blob 0123456789012345678901234567890123456789 -\tbad.txt\0",
])
def test_parse_ls_tree_z_rejects_impossible_mode_type_size_combinations(record: bytes):
    with pytest.raises(GitInspectionError):
        parse_ls_tree_z(record)


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


def test_remote_head_terminates_options_and_requires_exact_requested_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    inspector = GitInspector(_repo(tmp_path))
    oid = "0123456789012345678901234567890123456789"
    calls: list[tuple[str, ...]] = []

    def fake_run(args, **_kwargs):
        calls.append(tuple(args))
        return f"{oid}\trefs/heads/main\n".encode("ascii")

    monkeypatch.setattr(inspector, "_run", fake_run)
    assert inspector.remote_head("origin", "refs/heads/main") == oid
    assert calls == [("ls-remote", "--exit-code", "--", "origin", "refs/heads/main")]

    with pytest.raises(GitInspectionError):
        inspector.remote_head("--get-url", "refs/heads/main")

    monkeypatch.setattr(inspector, "_run", lambda _args: b"not-an-oid\trefs/heads/main\n")
    with pytest.raises(GitInspectionError):
        inspector.remote_head("origin", "refs/heads/main")

    monkeypatch.setattr(inspector, "_run", lambda _args: f"{oid}\trefs/heads/other\n".encode("ascii"))
    with pytest.raises(GitInspectionError):
        inspector.remote_head("origin", "refs/heads/main")


def test_constructor_probe_and_normal_call_use_read_only_git_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = tmp_path / "probe-repo"
    repo.mkdir()
    calls: list[tuple[list[str], dict]] = []

    def fake_subprocess_run(command, **kwargs):
        calls.append((command, kwargs))
        if kwargs.get("text"):
            return subprocess.CompletedProcess(command, 0, "true\n", "")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(integrity.subprocess, "run", fake_subprocess_run)
    inspector = GitInspector(repo)
    inspector._run(("status",))

    assert len(calls) == 2
    for command, kwargs in calls:
        assert command[:3] == ["git", "-c", f"safe.directory={repo.resolve()}"]
        assert kwargs["env"]["GIT_OPTIONAL_LOCKS"] == "0"
