from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path


REMOTE_NAME = "personal"
REMOTE_REF = "refs/heads/feature/health-content-system"


def git(repo: Path, *args: str) -> bytes:
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={repo.resolve()}",
            "-c",
            "core.longpaths=true",
            *args,
        ],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.decode("utf-8", errors="replace"))
    return completed.stdout


def repo(tmp_path: Path) -> Path:
    fixture_repo = tmp_path / "repo"
    fixture_repo.mkdir()
    git(fixture_repo, "init")
    git(fixture_repo, "config", "user.name", "Audit Test")
    git(fixture_repo, "config", "user.email", "audit@example.invalid")
    tracked = fixture_repo / "九期 资产.txt"
    tracked.write_text("锁定资产\n", encoding="utf-8", newline="\n")
    git(fixture_repo, "add", "--", tracked.name)
    git(fixture_repo, "commit", "-m", "fixture")
    tracked.unlink()
    (fixture_repo / "未跟踪.txt").write_text("不应改动\n", encoding="utf-8")
    return fixture_repo


def manual_pack_files(content_id: str) -> dict[str, bytes]:
    root = f"09_泛健康日更/work/{content_id}/production/v01/04_grok_batch/manual_pack"
    payloads: dict[str, bytes] = {}
    for shot in range(1, 11):
        payloads[f"{root}/01_first_frames/{content_id}-v01-S{shot:02d}-firstframe.png"] = (
            b"\x89PNG\r\n\x1a\n" + bytes([shot])
        )
        payloads[f"{root}/02_prompts/{content_id}-v01-S{shot:02d}-prompt-zh-en.txt"] = (
            f"S{shot:02d} prompt\n".encode()
        )
    payloads[f"{root}/{content_id}-v01-Grok-Automation-10条提示词.txt"] = b"merged\n"
    payloads[f"{root}/MANIFEST.csv"] = b"shot,path\n"
    payloads[f"{root}/MANUAL-GENERATION-GUIDE.md"] = b"guide\n"
    payloads[f"{root}/MANUAL-PACK-QA.md"] = b"qa\n"
    return payloads


def write_files(fixture_repo: Path, payloads: dict[str, bytes]) -> None:
    for relative, payload in payloads.items():
        path = fixture_repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def repo_with_one_manual_pack(
    tmp_path: Path, *, source_payload: bytes | None = b"\x89PNG\r\n\x1a\n\x01"
) -> Path:
    fixture_repo = tmp_path / "repo"
    fixture_repo.mkdir(parents=True)
    git(fixture_repo, "init")
    git(fixture_repo, "config", "user.name", "Audit Test")
    git(fixture_repo, "config", "user.email", "audit@example.invalid")
    content_id = "HC20260810-001"
    write_files(fixture_repo, manual_pack_files(content_id))
    if source_payload is not None:
        source = (
            fixture_repo
            / f"09_泛健康日更/work/{content_id}/production/v01/03_first_frames/"
            f"{content_id}-v01-S01-firstframe.png"
        )
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(source_payload)
    git(fixture_repo, "add", "--all", ".")
    git(fixture_repo, "commit", "-m", "manual pack fixture")
    for path in (fixture_repo / "09_泛健康日更").rglob("*"):
        if path.is_file() and "manual_pack" in path.parts:
            path.unlink()
    return fixture_repo


def create_deleted_pack_repo(tmp_path: Path) -> Path:
    fixture_repo = repo_with_one_manual_pack(tmp_path)
    git(fixture_repo, "config", "lfs.repositoryformatversion", "0")
    git(fixture_repo, "branch", "feature/health-content-system", "HEAD")
    git(fixture_repo, "remote", "add", REMOTE_NAME, str(fixture_repo))
    return fixture_repo


def repository_fingerprint(fixture_repo: Path) -> tuple[tuple[str, int, int, str], ...]:
    records = []
    for path in sorted(item for item in fixture_repo.rglob("*") if item.is_file()):
        stat = path.stat()
        records.append((
            path.relative_to(fixture_repo).as_posix(),
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        ))
    return tuple(records)
