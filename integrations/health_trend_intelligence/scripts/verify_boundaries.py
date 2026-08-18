"""Read-only fail-closed boundary verification for the synthetic foundation QA."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType

try:
    from health_trend_intelligence.curation import verify_curated_batch
    from health_trend_intelligence.exchange import verify_approved_exchange
    from health_trend_intelligence.storage import DataLayout
except ImportError:
    sys.stderr.write("boundary_verification_failed\n")
    raise SystemExit(2) from None

SCHEMA = "health_trend_foundation_qa.v1"
PINNED_MEDIA_CRAWLER_COMMIT = "d6f7c5bb906b6dac40ddf343ef9e26438a3de092"
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
GIT_OBJECT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
MEDIA_SUFFIXES = frozenset(
    {
        ".aac",
        ".avi",
        ".flac",
        ".gif",
        ".jpeg",
        ".jpg",
        ".m4a",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".mpeg",
        ".png",
        ".wav",
        ".webm",
        ".webp",
    }
)
CREDENTIAL_NAME_RE = re.compile(
    r"(?:^|[._-])(?:cookie|credential|secret|token)(?:$|[._-])|^\.env(?:\.|$)",
    re.IGNORECASE,
)
CREDENTIAL_VALUE_RE = re.compile(
    rb"(?:authorization|cookie|(?:access|refresh|xsec)[_-]?token|api[_-]?key)\s*[:=]",
    re.IGNORECASE,
)
MANUAL_PACK_PATHSPEC = (
    "09_泛健康日更/work/HC20260810-*/production/v01/04_grok_batch/"
    "manual_pack/**"
)


class BoundaryFailure(RuntimeError):
    """One deliberately payload-free fail-closed verification failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify synthetic health-trend boundaries without mutating inputs"
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--media-crawler-root", type=Path, required=True)
    parser.add_argument("--raw-path", type=Path, required=True)
    parser.add_argument("--curated-path", type=Path, required=True)
    parser.add_argument("--approved-path", type=Path, required=True)
    parser.add_argument("--imported-path", type=Path, required=True)
    parser.add_argument("--external-manifest-sha256", required=True)
    parser.add_argument("--task8-base", required=True)
    parser.add_argument("--expected-media-crawler-commit", required=True)
    parser.add_argument("--expected-manual-deletion-count", type=int, required=True)
    parser.add_argument("--expected-manual-deletion-sha256", required=True)
    return parser


def _is_reparse(status: os.stat_result) -> bool:
    attributes = getattr(status, "st_file_attributes", 0)
    return stat.S_ISLNK(status.st_mode) or bool(attributes & 0x400)


def _existing_absolute_directory(path: Path) -> Path:
    if not path.is_absolute() or any(part == ".." for part in path.parts):
        raise BoundaryFailure
    try:
        resolved = path.resolve(strict=True)
        status = resolved.lstat()
    except OSError as error:
        raise BoundaryFailure from error
    if _is_reparse(status) or not stat.S_ISDIR(status.st_mode):
        raise BoundaryFailure
    return resolved


def _run_git(root: Path, *arguments: str) -> bytes:
    command = [
        "git",
        "-c",
        f"safe.directory={root.as_posix()}",
        "-C",
        os.fspath(root),
        *arguments,
    ]
    try:
        completed = subprocess.run(command, capture_output=True, check=False)
    except OSError as error:
        raise BoundaryFailure from error
    if completed.returncode != 0:
        raise BoundaryFailure
    return completed.stdout


def _git_text(root: Path, *arguments: str) -> str:
    try:
        return _run_git(root, *arguments).decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise BoundaryFailure from error


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((os.fspath(path), os.fspath(root))) == os.fspath(root)
    except ValueError:
        return False


def _assert_external(path: Path, repo_root: Path, media_crawler_root: Path) -> None:
    if _is_within(path, repo_root) or _is_within(path, media_crawler_root):
        raise BoundaryFailure


def _manual_deletion_digest(repo_root: Path, task8_base: str) -> tuple[int, str]:
    payload = _run_git(
        repo_root,
        "diff",
        "--name-only",
        "--diff-filter=D",
        "-z",
        task8_base,
        "--",
        MANUAL_PACK_PATHSPEC,
    )
    paths = sorted(item for item in payload.split(b"\0") if item)
    digest_payload = b"\n".join(paths) + (b"\n" if paths else b"")
    return len(paths), hashlib.sha256(digest_payload).hexdigest()


def _is_dependency_or_config(path: bytes) -> bool:
    normalized = path.replace(b"\\", b"/").lower()
    name = normalized.rsplit(b"/", 1)[-1]
    suffix = b"." + name.rsplit(b".", 1)[-1] if b"." in name else b""
    return (
        name in {b"pyproject.toml", b"uv.lock", b".python-version"}
        or name.startswith(b"requirements")
        or suffix in {b".cfg", b".ini", b".toml", b".yaml", b".yml"}
        or b"/config/" in b"/" + normalized
        or b"/configs/" in b"/" + normalized
    )


def _assert_task8_repository_boundary(repo_root: Path, task8_base: str) -> None:
    if GIT_OBJECT_RE.fullmatch(task8_base) is None:
        raise BoundaryFailure
    _run_git(repo_root, "cat-file", "-e", f"{task8_base}^{{commit}}")
    if subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={repo_root.as_posix()}",
            "-C",
            os.fspath(repo_root),
            "merge-base",
            "--is-ancestor",
            task8_base,
            "HEAD",
        ],
        capture_output=True,
        check=False,
    ).returncode != 0:
        raise BoundaryFailure
    changed = _run_git(repo_root, "diff", "--name-only", "-z", task8_base, "--")
    if any(_is_dependency_or_config(path) for path in changed.split(b"\0") if path):
        raise BoundaryFailure


def _scan_artifacts(paths: tuple[Path, ...]) -> tuple[bool, bool]:
    credentials = False
    media = False
    for root in paths:
        for child in root.rglob("*"):
            try:
                status = child.lstat()
            except OSError as error:
                raise BoundaryFailure from error
            if _is_reparse(status):
                raise BoundaryFailure
            if stat.S_ISDIR(status.st_mode):
                continue
            if not stat.S_ISREG(status.st_mode):
                raise BoundaryFailure
            media = media or child.suffix.casefold() in MEDIA_SUFFIXES
            credentials = credentials or CREDENTIAL_NAME_RE.search(child.name) is not None
            try:
                payload = child.read_bytes()
            except OSError as error:
                raise BoundaryFailure from error
            credentials = credentials or CREDENTIAL_VALUE_RE.search(payload) is not None
            media = media or payload.startswith(
                (b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"RIFF")
            )
    return credentials, media


def _load_task7_module(repo_root: Path) -> ModuleType:
    module_path = repo_root / "app" / "services" / "health_trend_exchange.py"
    try:
        status = module_path.lstat()
    except OSError as error:
        raise BoundaryFailure from error
    if _is_reparse(status) or not stat.S_ISREG(status.st_mode):
        raise BoundaryFailure
    spec = importlib.util.spec_from_file_location("_hti_task8_task7_verifier", module_path)
    if spec is None or spec.loader is None:
        raise BoundaryFailure
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        raise BoundaryFailure from error
    finally:
        sys.modules.pop(spec.name, None)
    return module


def _tree_snapshot(path: Path) -> dict[str, tuple[int, str]]:
    snapshot: dict[str, tuple[int, str]] = {}
    for child in sorted(path.rglob("*")):
        if child.is_file():
            payload = child.read_bytes()
            snapshot[child.relative_to(path).as_posix()] = (
                len(payload),
                hashlib.sha256(payload).hexdigest(),
            )
    return snapshot


def _verify(args: argparse.Namespace) -> dict[str, object]:
    repo_root = _existing_absolute_directory(args.repo_root)
    media_root = _existing_absolute_directory(args.media_crawler_root)
    raw_path = _existing_absolute_directory(args.raw_path)
    curated_path = _existing_absolute_directory(args.curated_path)
    approved_path = _existing_absolute_directory(args.approved_path)
    imported_path = _existing_absolute_directory(args.imported_path)

    if (
        args.expected_media_crawler_commit != PINNED_MEDIA_CRAWLER_COMMIT
        or SHA256_RE.fullmatch(args.external_manifest_sha256) is None
        or SHA256_RE.fullmatch(args.expected_manual_deletion_sha256) is None
        or args.expected_manual_deletion_count < 0
    ):
        raise BoundaryFailure

    _assert_task8_repository_boundary(repo_root, args.task8_base)
    if _git_text(media_root, "rev-parse", "HEAD") != args.expected_media_crawler_commit:
        raise BoundaryFailure
    media_modified = bool(
        _run_git(media_root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    )
    if media_modified:
        raise BoundaryFailure

    for path in (raw_path, curated_path, approved_path, imported_path):
        _assert_external(path, repo_root, media_root)
    if (
        raw_path.name != "raw"
        or curated_path.parent.name != "curated"
        or approved_path.parent.name != "approved"
        or curated_path.parent.parent != raw_path.parent
        or approved_path.parent.parent != raw_path.parent
        or curated_path.name != approved_path.name
    ):
        raise BoundaryFailure

    layout = DataLayout.from_root(raw_path.parent)
    curated = verify_curated_batch(layout, curated_path.name)
    approved = verify_approved_exchange(approved_path, args.external_manifest_sha256)
    if curated.path != curated_path or approved.path != approved_path:
        raise BoundaryFailure

    imported_parts = imported_path.parts
    expected_tail = (
        "09_泛健康日更",
        "data",
        "trend-intelligence",
        approved.batch_id,
        "v01",
    )
    if tuple(imported_parts[-5:]) != expected_tail:
        raise BoundaryFailure
    task7 = _load_task7_module(repo_root)
    try:
        task7.verify_trend_exchange(approved_path, args.external_manifest_sha256)
        imported = task7.verify_trend_exchange(
            imported_path, args.external_manifest_sha256
        )
    except Exception as error:
        raise BoundaryFailure from error
    if (
        imported.batch_id != approved.batch_id
        or _tree_snapshot(imported_path) != _tree_snapshot(approved_path)
    ):
        raise BoundaryFailure

    deletion_count, deletion_sha256 = _manual_deletion_digest(
        repo_root, args.task8_base
    )
    deletion_unchanged = (
        deletion_count == args.expected_manual_deletion_count
        and deletion_sha256 == args.expected_manual_deletion_sha256
    )
    if not deletion_unchanged:
        raise BoundaryFailure

    credentials, media = _scan_artifacts(
        (raw_path, curated_path, approved_path, imported_path)
    )
    if credentials or media:
        raise BoundaryFailure

    return {
        "schema": SCHEMA,
        "media_crawler_commit": args.expected_media_crawler_commit,
        "media_crawler_modified": False,
        "raw_in_git": False,
        "credentials_detected": False,
        "media_detected": False,
        "curated_verified": True,
        "approved_verified": True,
        "moneyprinter_import_verified": True,
        "manual_pack_deletion_status_unchanged": True,
    }


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        report = _verify(args)
        sys.stdout.buffer.write(_canonical_json(report))
        return 0
    except (BoundaryFailure, OSError, TypeError, ValueError):
        sys.stderr.write("boundary_verification_failed\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
