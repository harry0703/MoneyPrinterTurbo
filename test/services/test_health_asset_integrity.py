from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

import app.services.health_asset_integrity as integrity
from app.services.health_asset_integrity import (
    GitInspectionError,
    GitInspector,
    audit_health_assets,
    is_lfs_pointer,
    parse_ls_tree_z,
    parse_porcelain_v1_z,
    report_to_dict,
)
from test.services.health_asset_audit_fixtures import (
    git as _git,
    manual_pack_files as _manual_pack_files,
    repo as _repo,
    repo_with_one_manual_pack as _repo_with_one_manual_pack,
    write_files as _write_files,
)


def _stub_lfs_success(monkeypatch: pytest.MonkeyPatch, paths: tuple[str, ...] = ()) -> None:
    def fake_lfs(_inspector: GitInspector, args: tuple[str, ...]) -> bytes:
        if args == ("version",):
            return b"git-lfs/3.7.0\n"
        if args == ("ls-files", "--all", "-n"):
            return b"".join(path.encode("utf-8") + b"\n" for path in paths)
        raise AssertionError(f"unexpected LFS arguments: {args!r}")

    monkeypatch.setattr(integrity, "_run_lfs_readonly", fake_lfs)


def _stub_lfs_version_output(
    monkeypatch: pytest.MonkeyPatch, version_output: bytes
) -> None:
    def fake_lfs(_inspector: GitInspector, args: tuple[str, ...]) -> bytes:
        if args == ("version",):
            return version_output
        if args == ("ls-files", "--all", "-n"):
            return b""
        raise AssertionError(f"unexpected LFS arguments: {args!r}")

    monkeypatch.setattr(integrity, "_run_lfs_readonly", fake_lfs)


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
    " A", " M", " T", " D", " R", " C",
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
    (" T", True),
    (" D", True),
    (" R", True),
    (" C", True),
    ("M ", True),
    ("MT", True),
    ("AD", True),
    ("R ", True),
    ("CD", True),
    ("D ", True),
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


def test_real_worktree_type_change_is_accepted(tmp_path: Path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Audit Test")
    _git(repo, "config", "user.email", "audit@example.invalid")
    _git(repo, "config", "core.symlinks", "true")
    target = repo / "target.txt"
    target.write_text("target\n", encoding="utf-8")
    kind = repo / "kind"
    kind.write_text(f"{target.name}\n", encoding="utf-8")
    oid = _git(repo, "hash-object", "-w", "--", kind.name).decode("ascii").strip()
    _git(repo, "add", "--", target.name)
    _git(repo, "update-index", "--add", "--cacheinfo", f"120000,{oid},{kind.name}")
    _git(repo, "commit", "-m", "symlink fixture")
    kind.write_text("regular file\n", encoding="utf-8")

    assert _git(repo, "status", "--porcelain=v1", "-z") == b" T kind\0"
    entry = next(item for item in GitInspector(repo).status() if item.path == kind.name)

    assert (entry.index_status, entry.worktree_status) == (" ", "T")


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


def test_audit_classifies_24_deletions_per_episode_and_head_recoverability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Audit Test")
    _git(repo, "config", "user.email", "audit@example.invalid")
    for number in range(1, 11):
        _write_files(repo, _manual_pack_files(f"HC20260810-{number:03d}"))
    _git(repo, "add", "--all", ".")
    _git(repo, "commit", "-m", "manual packs")
    for path in (repo / "09_泛健康日更").rglob("*"):
        if path.is_file() and "manual_pack" in path.parts:
            path.unlink()
    _stub_lfs_success(monkeypatch)

    report = audit_health_assets(GitInspector(repo), remote=None, remote_ref=None)
    payload = report_to_dict(report)

    assert payload["summary"] == {
        "audit_complete": True,
        "deleted_manual_pack_files": 240,
        "episodes": 10,
        "first_frames": 100,
        "prompts": 100,
        "control_files": 40,
        "large_blobs": 0,
    }
    assert {item["deleted_count"] for item in payload["episodes"]} == {24}
    assert {item["head_blob_recoverable"] for item in payload["deleted_assets"]} == {True}
    assert [item["content_id"] for item in payload["episodes"]] == [
        f"HC20260810-{number:03d}" for number in range(1, 11)
    ]


def test_audit_fails_closed_when_24_item_episode_contains_an_unrecognized_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Audit Test")
    _git(repo, "config", "user.email", "audit@example.invalid")
    content_id = "HC20260810-001"
    payloads = _manual_pack_files(content_id)
    expected = (
        f"09_泛健康日更/work/{content_id}/production/v01/04_grok_batch/manual_pack/"
        f"02_prompts/{content_id}-v01-S10-prompt-zh-en.txt"
    )
    unexpected = expected.replace("S10", "S11")
    payloads[unexpected] = payloads.pop(expected)
    assert len(payloads) == 24
    _write_files(repo, payloads)
    _git(repo, "add", "--all", ".")
    _git(repo, "commit", "-m", "unexpected manual pack shape")
    for path in (repo / "09_泛健康日更").rglob("*"):
        if path.is_file():
            path.unlink()
    _stub_lfs_success(monkeypatch)

    with pytest.raises(GitInspectionError, match="unrecognized manual-pack deletion"):
        audit_health_assets(GitInspector(repo), remote=None, remote_ref=None)


def test_first_frame_source_comparison_is_reported_without_copying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _repo_with_one_manual_pack(tmp_path)
    inspector = GitInspector(repo)
    before = inspector.snapshot()
    _stub_lfs_success(monkeypatch)

    report = audit_health_assets(inspector, remote=None, remote_ref=None)

    first_frame = next(item for item in report.deleted_assets if item.asset_kind == "first_frame")
    assert first_frame.source_path.endswith(
        "/03_first_frames/HC20260810-001-v01-S01-firstframe.png"
    )
    assert first_frame.source_exists is True
    assert first_frame.source_sha256 == first_frame.head_blob_sha256
    assert first_frame.source_matches_head is True
    assert inspector.snapshot() == before


@pytest.mark.parametrize(
    ("source_payload", "expected_exists", "expected_matches"),
    [
        (None, False, None),
        (b"different source bytes\n", True, False),
    ],
)
def test_source_missing_or_mismatch_is_evidence_not_a_restore_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_payload: bytes | None,
    expected_exists: bool,
    expected_matches: bool | None,
):
    repo = _repo_with_one_manual_pack(tmp_path, source_payload=source_payload)
    _stub_lfs_success(monkeypatch)

    report = audit_health_assets(GitInspector(repo), remote=None, remote_ref=None)

    first_frame = next(item for item in report.deleted_assets if item.asset_kind == "first_frame")
    assert first_frame.source_exists is expected_exists
    assert first_frame.source_matches_head is expected_matches
    assert [option["id"] for option in report.decision_options] == [
        "restore_exact_from_head",
        "regenerate_outside_repo_and_compare",
        "keep_deletions",
    ]


def test_lfs_pointer_and_plain_large_blob_are_not_confused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pointer = (
        b"version https://git-lfs.github.com/spec/v1\n"
        + b"oid sha256:"
        + b"a" * 64
        + b"\nsize 99\n"
    )
    assert is_lfs_pointer(pointer) is True
    assert is_lfs_pointer(b"\x89PNG\r\n\x1a\n") is False

    repo = _repo_with_one_manual_pack(tmp_path)
    (repo / "plain-large.bin").write_bytes(b"x" * 151)
    (repo / "pointer.lfs").write_bytes(pointer + b"padding" * 8)
    _git(repo, "add", "--", "plain-large.bin", "pointer.lfs")
    _git(repo, "commit", "-m", "large blob fixtures")
    monkeypatch.setattr(integrity, "LARGE_BLOB_THRESHOLD", 100)
    _stub_lfs_success(monkeypatch, ("pointer.lfs",))

    report = audit_health_assets(GitInspector(repo), remote=None, remote_ref=None)
    blobs = {item.path: item for item in report.large_blobs}

    assert blobs["plain-large.bin"].lfs_pointer is False
    assert blobs["pointer.lfs"].lfs_pointer is True
    assert report.lfs["tracked_paths"] == ["pointer.lfs"]


def test_failed_lfs_probe_is_reported_as_incomplete_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _repo_with_one_manual_pack(tmp_path)

    def fail_lfs(_inspector: GitInspector, _args: tuple[str, ...]) -> bytes:
        raise GitInspectionError("git lfs unavailable")

    monkeypatch.setattr(integrity, "_run_lfs_readonly", fail_lfs)

    report = audit_health_assets(GitInspector(repo), remote=None, remote_ref=None)

    assert report.summary["audit_complete"] is False
    assert report.lfs["complete"] is False
    assert report.lfs["tracked_paths"] is None
    assert "unavailable" in report.lfs["error"]


@pytest.mark.parametrize(
    "version_output",
    [
        b"",
        b"git version 2.51.0.windows.1\n",
        b"git-lfs/not-a-version\n",
    ],
)
def test_empty_or_malformed_successful_lfs_version_is_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version_output: bytes,
):
    repo = _repo_with_one_manual_pack(tmp_path)

    def malformed_version(_inspector: GitInspector, args: tuple[str, ...]) -> bytes:
        if args == ("version",):
            return version_output
        if args == ("ls-files", "--all", "-n"):
            return b""
        raise AssertionError(f"unexpected LFS arguments: {args!r}")

    monkeypatch.setattr(integrity, "_run_lfs_readonly", malformed_version)

    report = audit_health_assets(GitInspector(repo), remote=None, remote_ref=None)

    assert report.summary["audit_complete"] is False
    assert report.lfs["complete"] is False
    assert report.lfs["version"] is None
    assert report.lfs["tracked_paths"] is None
    assert report.lfs["error"] == "unrecognized Git LFS version output"


@pytest.mark.parametrize("control", ["\x00", "\x01", "\x1f", "\x80", "\x9f"])
def test_lfs_version_rejects_c0_and_c1_controls_anywhere_in_build_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    control: str,
):
    repo = _repo_with_one_manual_pack(tmp_path)
    version_output = (
        f"git-lfs/3.7.1 (GitHub; windows amd64;{control} injected)\n".encode("utf-8")
    )

    def contaminated_version(_inspector: GitInspector, args: tuple[str, ...]) -> bytes:
        if args == ("version",):
            return version_output
        if args == ("ls-files", "--all", "-n"):
            return b""
        raise AssertionError(f"unexpected LFS arguments: {args!r}")

    monkeypatch.setattr(integrity, "_run_lfs_readonly", contaminated_version)

    report = audit_health_assets(GitInspector(repo), remote=None, remote_ref=None)

    assert report.summary["audit_complete"] is False
    assert report.lfs == {
        "complete": False,
        "version": None,
        "tracked_paths": None,
        "error": "unrecognized Git LFS version output",
    }


@pytest.mark.parametrize(
    "version_line",
    [
        "git-lfs/3.7.1",
        "git-lfs/3.7.1 (GitHub; windows amd64; go 1.25.1; git b84b3384)",
        "git-lfs/3.7.1-rc.1+build.5 (GitHub; linux amd64; go 1.24.0)",
    ],
)
def test_lfs_version_accepts_representative_printable_installed_formats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version_line: str,
):
    repo = _repo_with_one_manual_pack(tmp_path)

    def printable_version(_inspector: GitInspector, args: tuple[str, ...]) -> bytes:
        if args == ("version",):
            return f"{version_line}\n".encode("utf-8")
        if args == ("ls-files", "--all", "-n"):
            return b""
        raise AssertionError(f"unexpected LFS arguments: {args!r}")

    monkeypatch.setattr(integrity, "_run_lfs_readonly", printable_version)

    report = audit_health_assets(GitInspector(repo), remote=None, remote_ref=None)

    assert report.summary["audit_complete"] is True
    assert report.lfs == {
        "complete": True,
        "version": version_line,
        "tracked_paths": [],
        "error": None,
    }


@pytest.mark.parametrize(
    ("name", "terminal"),
    [
        ("VT", "\x0b"),
        ("FF", "\x0c"),
        ("FS", "\x1c"),
        ("GS", "\x1d"),
        ("RS", "\x1e"),
        ("NEL", "\x85"),
    ],
)
def test_lfs_version_rejects_nonstandard_control_terminal_substitutions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    terminal: str,
):
    inspector = GitInspector(_repo(tmp_path))
    _stub_lfs_version_output(
        monkeypatch, f"git-lfs/3.7.1{terminal}".encode("utf-8")
    )

    lfs, complete = integrity._inspect_lfs(inspector)

    assert complete is False, name
    assert lfs["error"] == "unrecognized Git LFS version output"


def test_lfs_version_rejects_every_remaining_c0_and_c1_code_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    inspector = GitInspector(_repo(tmp_path))
    terminal_substitutions = {0x0B, 0x0C, 0x1C, 0x1D, 0x1E, 0x85}
    control_points = [
        code_point
        for code_point in (*range(0x20), *range(0x7F, 0xA0))
        if code_point not in terminal_substitutions
    ]
    accepted: list[str] = []

    for code_point in control_points:
        control = chr(code_point)
        version_output = f"git-lfs/3.7.1 (build{control}metadata)\n".encode("utf-8")
        _stub_lfs_version_output(monkeypatch, version_output)
        _lfs, complete = integrity._inspect_lfs(inspector)
        if complete:
            accepted.append(f"U+{code_point:04X}")

    assert len(control_points) == 59
    assert accepted == []


@pytest.mark.parametrize(
    ("version_line", "terminator"),
    [
        ("git-lfs/3.7.1", b""),
        ("git-lfs/3.7.1", b"\n"),
        ("git-lfs/3.7.1", b"\r\n"),
        ("git-lfs/3.7.1 (GitHub; 可打印构建信息)", b"\n"),
    ],
)
def test_lfs_version_accepts_only_optional_lf_or_crlf_and_printable_unicode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version_line: str,
    terminator: bytes,
):
    inspector = GitInspector(_repo(tmp_path))
    _stub_lfs_version_output(
        monkeypatch, version_line.encode("utf-8") + terminator
    )

    lfs, complete = integrity._inspect_lfs(inspector)

    assert complete is True
    assert lfs == {
        "complete": True,
        "version": version_line,
        "tracked_paths": [],
        "error": None,
    }


def test_requested_remote_object_missing_locally_is_not_fetched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _repo_with_one_manual_pack(tmp_path / "audit")
    remote_repo = tmp_path / "remote"
    remote_repo.mkdir()
    _git(remote_repo, "init")
    _git(remote_repo, "config", "user.name", "Audit Test")
    _git(remote_repo, "config", "user.email", "audit@example.invalid")
    (remote_repo / "remote-only.txt").write_text("remote\n", encoding="utf-8")
    _git(remote_repo, "add", "--", "remote-only.txt")
    _git(remote_repo, "commit", "-m", "remote fixture")
    branch = _git(remote_repo, "symbolic-ref", "--short", "HEAD").decode().strip()
    _stub_lfs_success(monkeypatch)

    report = audit_health_assets(
        GitInspector(repo), str(remote_repo), f"refs/heads/{branch}"
    )

    assert report.summary["audit_complete"] is False
    assert report.remote["object_available_locally"] is False
    assert report.remote["tree_comparison"] == "unavailable_without_fetch"


def test_unavailable_requested_remote_is_incomplete_not_an_empty_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _repo_with_one_manual_pack(tmp_path)
    _stub_lfs_success(monkeypatch)

    report = audit_health_assets(
        GitInspector(repo), str(tmp_path / "missing-remote"), "refs/heads/main"
    )

    assert report.summary["audit_complete"] is False
    assert report.remote["tree_comparison"] == "unavailable"
    assert report.remote["error"]


def test_changed_snapshot_aborts_the_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    inspector = GitInspector(_repo_with_one_manual_pack(tmp_path))
    before = inspector.snapshot()
    snapshots = iter((before, replace(before, status_sha256="0" * 64)))
    monkeypatch.setattr(inspector, "snapshot", lambda: next(snapshots))
    _stub_lfs_success(monkeypatch)

    with pytest.raises(GitInspectionError, match="repository changed during audit"):
        audit_health_assets(inspector, remote=None, remote_ref=None)


@pytest.mark.parametrize(
    "args",
    [
        ("pull",),
        ("ls-files",),
        ("ls-files", "--all"),
        ("version", "--json"),
        ["pull"],
    ],
)
def test_lfs_helper_fails_closed_outside_its_exact_readonly_whitelist(
    tmp_path: Path, args: tuple[str, ...] | list[str]
):
    inspector = GitInspector(_repo(tmp_path))
    with pytest.raises(GitInspectionError, match="not allowed"):
        integrity._run_lfs_readonly(inspector, args)
