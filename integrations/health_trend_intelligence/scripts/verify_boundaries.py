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
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import BinaryIO

sys.dont_write_bytecode = True

try:
    from health_trend_intelligence.curation import verify_curated_batch
    from health_trend_intelligence.exchange import verify_approved_exchange
    from health_trend_intelligence.storage import DataLayout
except ImportError:
    sys.stderr.write("boundary_verification_failed\n")
    raise SystemExit(2) from None

SCHEMA = "health_trend_foundation_qa.v1"
PINNED_TASK8_BASE = "f5f6d900b78cc583272d3f29bb1c6e3976b1109e"
PINNED_MEDIA_CRAWLER_COMMIT = "d6f7c5bb906b6dac40ddf343ef9e26438a3de092"
PINNED_MANUAL_DELETION_COUNT = 240
PINNED_MANUAL_DELETION_SHA256 = (
    "391aa69f5238ab573788c248ced49824a51a5fa08b4c3c9477d9bbf2eda26db6"
)
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
MANUAL_PACK_PATHSPEC = (
    "09_泛健康日更/work/HC20260810-*/production/v01/04_grok_batch/"
    "manual_pack/**"
)
TASK8_ALLOWED_PATHS = frozenset(
    {
        b"integrations/health_trend_intelligence/tests/test_foundation_e2e.py",
        b"integrations/health_trend_intelligence/RUNBOOK.md",
        b"integrations/health_trend_intelligence/scripts/verify_boundaries.py",
        b"integrations/health_trend_intelligence/README.md",
        "09_泛健康日更/data/trend-intelligence/README.md".encode(),
    }
)
PROTECTED_PATHSPECS = (
    ".python-version",
    "pyproject.toml",
    "uv.lock",
    ":(top,glob)requirements*.txt",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    ":(top,glob)config*.toml",
    ":(top,glob)config*.yaml",
    ":(top,glob)config*.yml",
    ":(top,glob)config*.json",
    ".github/ISSUE_TEMPLATE/config.yml",
    "app/config/__init__.py",
    "app/config/config.py",
    "integrations/health_trend_intelligence/.python-version",
    "integrations/health_trend_intelligence/pyproject.toml",
    "integrations/health_trend_intelligence/uv.lock",
    "webui/.streamlit/config.toml",
)
RAW_REPOSITORY_PATHSPECS = (
    "raw/**",
    "health-trend-intelligence/raw/**",
    "integrations/health_trend_intelligence/raw/**",
    "integrations/health_trend_intelligence/data/raw/**",
    "09_泛健康日更/data/trend-intelligence/raw/**",
)
RAW_REPOSITORY_DIRECTORIES = (
    "raw",
    "health-trend-intelligence/raw",
    "integrations/health_trend_intelligence/raw",
    "integrations/health_trend_intelligence/data/raw",
    "09_泛健康日更/data/trend-intelligence/raw",
)
MEDIA_SUFFIXES = frozenset(
    {
        ".aac",
        ".avi",
        ".bmp",
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
        ".mpg",
        ".oga",
        ".ogg",
        ".ogv",
        ".png",
        ".tif",
        ".tiff",
        ".wav",
        ".webm",
        ".webp",
        ".wmv",
    }
)
CREDENTIAL_KEY_TERMS = (
    "authorization",
    "cookie",
    "credential",
    "session",
    "token",
    "apikey",
    "secret",
    "password",
    "passwd",
    "proxy",
)
CREDENTIAL_TEXT_RE = re.compile(
    rb"(?i)[\"']?(?:authorization|cookie|credential|session|token|"
    rb"api[_-]?key|secret|password|passwd|proxy)[\"']?\s*[:=]"
)


class BoundaryFailure(RuntimeError):
    """One deliberately payload-free fail-closed verification failure."""


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise BoundaryFailure from None


@dataclass(frozen=True, slots=True)
class CheckedDirectory:
    lexical: Path
    resolved: Path
    identity: tuple[int, int]


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description="Verify synthetic health-trend boundaries without mutating inputs"
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--media-crawler-root", type=Path, required=True)
    parser.add_argument("--raw-path", type=Path, required=True)
    parser.add_argument("--curated-path", type=Path, required=True)
    parser.add_argument("--approved-path", type=Path, required=True)
    parser.add_argument("--imported-path", type=Path, required=True)
    parser.add_argument("--external-manifest-sha256", required=True)
    return parser


def _is_reparse(status: os.stat_result) -> bool:
    attributes = getattr(status, "st_file_attributes", 0)
    return stat.S_ISLNK(status.st_mode) or bool(attributes & 0x400)


def _lstat_chain(path: Path) -> os.stat_result:
    current = Path(path.anchor)
    try:
        status = current.lstat()
        if _is_reparse(status) or not stat.S_ISDIR(status.st_mode):
            raise BoundaryFailure
        for part in path.parts[1:]:
            current /= part
            status = current.lstat()
            if _is_reparse(status):
                raise BoundaryFailure
            is_last = current == path
            if not is_last and not stat.S_ISDIR(status.st_mode):
                raise BoundaryFailure
        return status
    except OSError as error:
        raise BoundaryFailure from error


def _existing_absolute_directory(path: Path) -> CheckedDirectory:
    if (
        not path.is_absolute()
        or any(part in {".", ".."} for part in path.parts)
        or not path.anchor
    ):
        raise BoundaryFailure
    lexical = Path(os.path.abspath(os.fspath(path)))
    lexical_status = _lstat_chain(lexical)
    if not stat.S_ISDIR(lexical_status.st_mode):
        raise BoundaryFailure
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as error:
        raise BoundaryFailure from error
    resolved_status = _lstat_chain(resolved)
    if not stat.S_ISDIR(resolved_status.st_mode):
        raise BoundaryFailure
    lexical_identity = (lexical_status.st_dev, lexical_status.st_ino)
    resolved_identity = (resolved_status.st_dev, resolved_status.st_ino)
    if lexical_identity != resolved_identity:
        raise BoundaryFailure
    return CheckedDirectory(lexical, resolved, lexical_identity)


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


def _git_status_code(root: Path, *arguments: str) -> int:
    command = [
        "git",
        "-c",
        f"safe.directory={root.as_posix()}",
        "-C",
        os.fspath(root),
        *arguments,
    ]
    try:
        return subprocess.run(command, capture_output=True, check=False).returncode
    except OSError as error:
        raise BoundaryFailure from error


def _git_text(root: Path, *arguments: str) -> str:
    try:
        return _run_git(root, *arguments).decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise BoundaryFailure from error


def _normalized_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _is_within(path: Path, root: Path) -> bool:
    candidate = _normalized_path(path)
    boundary = _normalized_path(root)
    try:
        return os.path.commonpath((candidate, boundary)) == boundary
    except ValueError:
        return False


def _assert_external(
    path: CheckedDirectory,
    repo_root: CheckedDirectory,
    media_crawler_root: CheckedDirectory,
) -> None:
    for candidate in (path.lexical, path.resolved):
        for boundary in (
            repo_root.lexical,
            repo_root.resolved,
            media_crawler_root.lexical,
            media_crawler_root.resolved,
        ):
            if _is_within(candidate, boundary):
                raise BoundaryFailure


def _manual_deletion_digest(repo_root: Path) -> tuple[int, str]:
    payload = _run_git(
        repo_root,
        "diff",
        "--name-only",
        "--diff-filter=D",
        "-z",
        PINNED_TASK8_BASE,
        "--",
        MANUAL_PACK_PATHSPEC,
    )
    paths = sorted(item for item in payload.split(b"\0") if item)
    digest_payload = b"\n".join(paths) + (b"\n" if paths else b"")
    return len(paths), hashlib.sha256(digest_payload).hexdigest()


def _assert_task8_repository_boundary(repo_root: Path) -> bool:
    if _git_text(repo_root, "rev-parse", "--show-prefix"):
        raise BoundaryFailure
    _run_git(repo_root, "cat-file", "-e", f"{PINNED_TASK8_BASE}^{{commit}}")
    if (
        _git_status_code(
            repo_root,
            "merge-base",
            "--is-ancestor",
            PINNED_TASK8_BASE,
            "HEAD",
        )
        != 0
    ):
        raise BoundaryFailure

    changed = {
        path
        for path in _run_git(
            repo_root,
            "diff",
            "--name-only",
            "-z",
            f"{PINNED_TASK8_BASE}..HEAD",
            "--",
        ).split(b"\0")
        if path
    }
    if changed != TASK8_ALLOWED_PATHS:
        raise BoundaryFailure

    protected_committed = _run_git(
        repo_root,
        "diff",
        "--name-only",
        "-z",
        f"{PINNED_TASK8_BASE}..HEAD",
        "--",
        *PROTECTED_PATHSPECS,
    )
    protected_dirty = _run_git(
        repo_root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--",
        *PROTECTED_PATHSPECS,
    )
    if protected_committed or protected_dirty:
        raise BoundaryFailure

    raw_tracked = _run_git(
        repo_root,
        "ls-files",
        "-z",
        "--",
        *RAW_REPOSITORY_PATHSPECS,
    )
    raw_status = _run_git(
        repo_root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--",
        *RAW_REPOSITORY_PATHSPECS,
    )
    raw_on_disk = any(
        _path_entry_exists(repo_root / item) for item in RAW_REPOSITORY_DIRECTORIES
    )
    raw_in_git = bool(raw_tracked or raw_status or raw_on_disk)
    if raw_in_git:
        raise BoundaryFailure
    return raw_in_git


def _path_entry_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as error:
        raise BoundaryFailure from error
    return True


def _compact_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _credential_key(value: str) -> bool:
    compact = _compact_key(value)
    return any(term in compact for term in CREDENTIAL_KEY_TERMS)


def _unique_nfc_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        normalized = unicodedata.normalize("NFC", key)
        if key != normalized or normalized in result:
            raise BoundaryFailure
        result[normalized] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise BoundaryFailure


def _load_strict_json(payload: bytes) -> object:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_nfc_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise BoundaryFailure from error


def _json_has_credential_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            _credential_key(key) or _json_has_credential_key(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_json_has_credential_key(child) for child in value)
    return False


def _iter_regular_files(root: Path) -> Iterator[Path]:
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                ordered = sorted(entries, key=lambda entry: entry.name)
        except OSError as error:
            raise BoundaryFailure from error
        for entry in ordered:
            try:
                status = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise BoundaryFailure from error
            if _is_reparse(status):
                raise BoundaryFailure
            if stat.S_ISDIR(status.st_mode):
                pending.append(Path(entry.path))
            elif stat.S_ISREG(status.st_mode):
                yield Path(entry.path)
            else:
                raise BoundaryFailure


def _read_regular_file(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            _assert_open_regular(handle)
            return handle.read()
    except OSError as error:
        raise BoundaryFailure from error


def _assert_open_regular(handle: BinaryIO) -> None:
    status = os.fstat(handle.fileno())
    if _is_reparse(status) or not stat.S_ISREG(status.st_mode):
        raise BoundaryFailure


def _media_header(payload: bytes) -> bool:
    return (
        (len(payload) >= 8 and payload[4:8] == b"ftyp")
        or payload.startswith(
            (
                b"\x1aE\xdf\xa3",
                b"OggS",
                b"ID3",
                b"\x89PNG\r\n\x1a\n",
                b"\xff\xd8\xff",
                b"GIF87a",
                b"GIF89a",
                b"RIFF",
            )
        )
        or (
            len(payload) >= 2
            and payload[0] == 0xFF
            and payload[1] & 0xE0 == 0xE0
        )
    )


def _scan_artifacts(paths: tuple[Path, ...]) -> tuple[bool, bool]:
    credentials = False
    media = False
    for root in paths:
        for child in _iter_regular_files(root):
            payload = _read_regular_file(child)
            file_media = (
                child.suffix.casefold() in MEDIA_SUFFIXES
                or _media_header(payload[:32])
            )
            file_credentials = _credential_key(child.name)
            suffix = child.suffix.casefold()
            if suffix == ".json":
                file_credentials = (
                    _json_has_credential_key(_load_strict_json(payload))
                    or file_credentials
                )
            elif suffix == ".jsonl":
                lines = payload.splitlines()
                if any(not line.strip() for line in lines):
                    raise BoundaryFailure
                for line in lines:
                    file_credentials = (
                        _json_has_credential_key(_load_strict_json(line))
                        or file_credentials
                    )
            else:
                file_credentials = (
                    CREDENTIAL_TEXT_RE.search(payload) is not None
                    or file_credentials
                )
            credentials = credentials or file_credentials
            media = media or file_media
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
    for child in _iter_regular_files(path):
        payload = _read_regular_file(child)
        snapshot[child.relative_to(path).as_posix()] = (
            len(payload),
            hashlib.sha256(payload).hexdigest(),
        )
    return snapshot


def _assert_media_crawler_boundary(
    repo_root: CheckedDirectory,
    media_root: CheckedDirectory,
) -> tuple[str, bool]:
    expected = Path(
        os.path.abspath(os.fspath(repo_root.lexical.parents[2] / "MediaCrawler"))
    )
    if _normalized_path(media_root.lexical) != _normalized_path(expected):
        raise BoundaryFailure
    if _git_text(media_root.resolved, "rev-parse", "--show-prefix"):
        raise BoundaryFailure
    commit = _git_text(media_root.resolved, "rev-parse", "HEAD")
    if commit != PINNED_MEDIA_CRAWLER_COMMIT:
        raise BoundaryFailure
    modified = bool(
        _run_git(
            media_root.resolved,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        )
    )
    if modified:
        raise BoundaryFailure
    return commit, modified


def _verify(args: argparse.Namespace) -> dict[str, object]:
    repo_root = _existing_absolute_directory(args.repo_root)
    media_root = _existing_absolute_directory(args.media_crawler_root)
    raw = _existing_absolute_directory(args.raw_path)
    curated = _existing_absolute_directory(args.curated_path)
    approved = _existing_absolute_directory(args.approved_path)
    imported = _existing_absolute_directory(args.imported_path)

    if SHA256_RE.fullmatch(args.external_manifest_sha256) is None:
        raise BoundaryFailure
    raw_in_git = _assert_task8_repository_boundary(repo_root.resolved)
    media_commit, media_modified = _assert_media_crawler_boundary(
        repo_root, media_root
    )

    for path in (raw, curated, approved, imported):
        _assert_external(path, repo_root, media_root)
    for variant in ("lexical", "resolved"):
        raw_path = getattr(raw, variant)
        curated_path = getattr(curated, variant)
        approved_path = getattr(approved, variant)
        if (
            raw_path.name != "raw"
            or curated_path.parent.name != "curated"
            or approved_path.parent.name != "approved"
            or curated_path.parent.parent != raw_path.parent
            or approved_path.parent.parent != raw_path.parent
            or curated_path.name != approved_path.name
        ):
            raise BoundaryFailure

    expected_tail = (
        "09_泛健康日更",
        "data",
        "trend-intelligence",
        approved.resolved.name,
        "v01",
    )
    if (
        tuple(imported.lexical.parts[-5:]) != expected_tail
        or tuple(imported.resolved.parts[-5:]) != expected_tail
    ):
        raise BoundaryFailure

    credentials, media = _scan_artifacts(
        (raw.resolved, curated.resolved, approved.resolved, imported.resolved)
    )
    if credentials or media:
        raise BoundaryFailure

    layout = DataLayout.from_root(raw.resolved.parent)
    curated_result = verify_curated_batch(layout, curated.resolved.name)
    approved_result = verify_approved_exchange(
        approved.resolved, args.external_manifest_sha256
    )
    if (
        curated_result.path != curated.resolved
        or approved_result.path != approved.resolved
    ):
        raise BoundaryFailure

    task7 = _load_task7_module(repo_root.resolved)
    try:
        task7.verify_trend_exchange(
            approved.resolved, args.external_manifest_sha256
        )
        imported_result = task7.verify_trend_exchange(
            imported.resolved, args.external_manifest_sha256
        )
    except Exception as error:
        raise BoundaryFailure from error
    if (
        imported_result.batch_id != approved_result.batch_id
        or _tree_snapshot(imported.resolved) != _tree_snapshot(approved.resolved)
    ):
        raise BoundaryFailure

    deletion_count, deletion_sha256 = _manual_deletion_digest(repo_root.resolved)
    deletion_unchanged = (
        deletion_count == PINNED_MANUAL_DELETION_COUNT
        and deletion_sha256 == PINNED_MANUAL_DELETION_SHA256
    )
    if not deletion_unchanged:
        raise BoundaryFailure

    return {
        "schema": SCHEMA,
        "media_crawler_commit": media_commit,
        "media_crawler_modified": media_modified,
        "raw_in_git": raw_in_git,
        "credentials_detected": credentials,
        "media_detected": media,
        "curated_verified": True,
        "approved_verified": True,
        "moneyprinter_import_verified": True,
        "manual_pack_deletion_status_unchanged": deletion_unchanged,
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
    except Exception:  # noqa: BLE001 - every unverifiable state must fail closed
        sys.stderr.write("boundary_verification_failed\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
