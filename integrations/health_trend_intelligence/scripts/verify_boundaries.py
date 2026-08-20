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
PINNED_LOCAL_CONFIG_PATH = b"config.toml"
PINNED_LOCAL_CONFIG_BYTES = 3114
PINNED_LOCAL_CONFIG_SHA256 = (
    "f60060a50740bb7f1c6b09caaba6022fc3e9187700eb6de23e55fa02f66eb997"
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
ROOT_CONFIG_SUFFIXES = frozenset({".json", ".toml", ".yaml", ".yml"})
CONFIG_DIRECTORY_SUFFIXES = frozenset(
    {".cfg", ".conf", ".env", ".ini", ".json", ".py", ".toml", ".yaml", ".yml"}
)
CONFIG_DIRECTORY_NAMES = frozenset({".config", ".streamlit", "config", "configs"})
DEPENDENCY_FILENAMES = frozenset(
    {
        ".python-version",
        "bun.lock",
        "bun.lockb",
        "npm-shrinkwrap.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "poetry.lock",
        "pyproject.toml",
        "uv.lock",
        "yarn.lock",
    }
)
# These are audited repository-relative roots, not basename/prefix patterns.
# The first group contains only local runtime metadata that is not project data.
EXACT_RUNTIME_METADATA_ROOTS = frozenset(
    {
        (".cache",),
        (".git",),
        (".pytest_cache",),
        (".ruff_cache",),
        (".uv-cache",),
        (".uv-cache-cycle2",),
        (".uv-cache-r3",),
        (".uv-cache-review-task2",),
        (".venv",),
        ("__pycache__",),
        ("app", "config", "__pycache__"),
        ("integrations", "health_trend_intelligence", ".pytest_cache"),
        ("integrations", "health_trend_intelligence", ".ruff_cache"),
        ("integrations", "health_trend_intelligence", ".uv-cache"),
        ("integrations", "health_trend_intelligence", ".uv-cache-task5"),
        ("integrations", "health_trend_intelligence", ".uv-cache-task5-fix1"),
        ("integrations", "health_trend_intelligence", ".uv-cache-task6"),
        ("integrations", "health_trend_intelligence", ".uv-cache-task6-fix1"),
        ("integrations", "health_trend_intelligence", ".venv"),
        (
            "integrations",
            "health_trend_intelligence",
            "moneyprinterturbo-3期.review-pytest-cache",
        ),
    }
)
# These exact roots are retained test basetemps from Tasks 5/6. They contain
# synthetic Raw fixtures and are excluded only by their complete relative path.
EXACT_LEGACY_TEST_CACHE_ROOTS = frozenset(
    ("integrations", "health_trend_intelligence", name)
    for name in (
        ".test-tmp-task5",
        ".test-tmp-task5-fix1",
        ".test-tmp-task5-fix1-final-all",
        ".test-tmp-task5-fix1-final-focused",
        ".test-tmp-task5-fix1-focused",
        ".test-tmp-task5-fix1-green",
        ".test-tmp-task5-fix1-matrix",
        ".test-tmp-task5-fix1-postcommit",
        ".test-tmp-task5-fix1-red",
        ".test-tmp-task5-fix1-red-published",
        ".test-tmp-task5-fix2-all",
        ".test-tmp-task5-fix2-focused",
        ".test-tmp-task5-fix2-green-focused",
        ".test-tmp-task5-fix2-postcommit",
        ".test-tmp-task5-fix2-red",
        ".test-tmp-task5-fix2-red-verifier",
        ".test-tmp-task5-fix2-red-verifier2",
        ".test-tmp-task6-all",
        ".test-tmp-task6-final-all",
        ".test-tmp-task6-final-focused",
        ".test-tmp-task6-fix1-all",
        ".test-tmp-task6-fix1-final-focused",
        ".test-tmp-task6-fix1-focused2",
        ".test-tmp-task6-fix1-focused3",
        ".test-tmp-task6-fix1-green-cli",
        ".test-tmp-task6-fix1-green-counts",
        ".test-tmp-task6-fix1-green-evidence",
        ".test-tmp-task6-fix1-green-focused",
        ".test-tmp-task6-fix1-green-identity",
        ".test-tmp-task6-fix1-green-identity2",
        ".test-tmp-task6-fix1-green-matrix",
        ".test-tmp-task6-fix1-green-medical",
        ".test-tmp-task6-fix1-green-scan",
        ".test-tmp-task6-fix1-green-sentinel2",
        ".test-tmp-task6-fix1-red",
        ".test-tmp-task6-fix1-red-matrix",
        ".test-tmp-task6-fix1-red-media",
        ".test-tmp-task6-fix1-red-sentinel2",
        ".test-tmp-task6-fix1-repro",
        ".test-tmp-task6-focused",
        ".test-tmp-task6-green",
        ".test-tmp-task6-green2",
        ".test-tmp-task6-green3",
        ".test-tmp-task6-green4",
        ".test-tmp-task6-postcommit",
        ".test-tmp-task6-red2",
    )
)
# Four malformed legacy pytest basetemp paths exist at the repository root.
# Their full names are pinned so a new name containing `.uv-cache` is not trusted.
LEGACY_ROOT_CACHE_PREFIX = (
    "moneyprinterturbo-3期moneyprinterturbo.worktreeshealth-content-system"
    "integrationshealth_trend_intelligence.uv-cache"
)
EXACT_LEGACY_ROOT_CACHE_ROOTS = frozenset(
    {
        (LEGACY_ROOT_CACHE_PREFIX + "fix1-final-focused",),
        (LEGACY_ROOT_CACHE_PREFIX + "fix1-final-full",),
        (LEGACY_ROOT_CACHE_PREFIX + "pytest-final-focused",),
        (LEGACY_ROOT_CACHE_PREFIX + "pytest-final-full",),
    }
)
EXACT_CONTROLLED_NON_DATA_ROOTS = (
    EXACT_RUNTIME_METADATA_ROOTS
    | EXACT_LEGACY_TEST_CACHE_ROOTS
    | EXACT_LEGACY_ROOT_CACHE_ROOTS
)
KNOWN_RAW_DATA_DIRECTORY_NAMES = frozenset({"raw-data", "raw_data"})
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
CREDENTIAL_COMPACT_KEYS = frozenset(
    {
        "accesskey",
        "authkey",
        "clientsecret",
        "decryptionkey",
        "encryptionkey",
        "hashkey",
        "hmackey",
        "hmacsecret",
        "privatekey",
        "secretkey",
        "signingkey",
    }
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


def _manual_deletion_paths(repo_root: Path) -> tuple[bytes, ...]:
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
    return tuple(sorted(item for item in payload.split(b"\0") if item))


def _manual_deletion_digest(repo_root: Path) -> tuple[int, str]:
    paths = _manual_deletion_paths(repo_root)
    digest_payload = b"\n".join(paths) + (b"\n" if paths else b"")
    return len(paths), hashlib.sha256(digest_payload).hexdigest()


def _repository_path_parts(path: bytes) -> tuple[str, ...]:
    try:
        text = path.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BoundaryFailure from error
    parts = tuple(text.split("/"))
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise BoundaryFailure
    return parts


def _normalized_component(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _is_exact_controlled_non_data_root(parts: tuple[str, ...]) -> bool:
    normalized = tuple(_normalized_component(part) for part in parts)
    return normalized in EXACT_CONTROLLED_NON_DATA_ROOTS


def _is_under_exact_controlled_non_data_root(parts: tuple[str, ...]) -> bool:
    normalized = tuple(_normalized_component(part) for part in parts)
    return any(normalized[: len(root)] == root for root in EXACT_CONTROLLED_NON_DATA_ROOTS)


def _is_raw_directory_name(value: str) -> bool:
    normalized = _normalized_component(value)
    return normalized == "raw" or normalized in KNOWN_RAW_DATA_DIRECTORY_NAMES


def _is_raw_repository_file(path: bytes) -> bool:
    parts = _repository_path_parts(path)
    directories = parts[:-1]
    return any(_is_raw_directory_name(part) for part in directories)


def _is_protected_repository_file(path: bytes) -> bool:
    parts = _repository_path_parts(path)
    directories = tuple(_normalized_component(part) for part in parts[:-1])
    if directories[:3] == ("app", "config", "__pycache__"):
        return False
    name = _normalized_component(parts[-1])
    suffix = Path(name).suffix
    if directories[:2] == ("app", "config"):
        return True
    if name in DEPENDENCY_FILENAMES:
        return True
    if name.startswith("requirements") and name.endswith(".txt"):
        return True
    if len(parts) == 1 and name == "package.json":
        return True
    if len(parts) == 1 and name.startswith("config") and suffix in ROOT_CONFIG_SUFFIXES:
        return True
    if any(component in CONFIG_DIRECTORY_NAMES for component in directories):
        return suffix in CONFIG_DIRECTORY_SUFFIXES
    return (
        directories == (".github", "issue_template")
        and name == "config.yml"
    )


def _porcelain_paths(payload: bytes) -> tuple[bytes, ...]:
    fields = payload.split(b"\0")
    paths: list[bytes] = []
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue
        if len(field) < 4 or field[2:3] != b" ":
            raise BoundaryFailure
        status = field[:2]
        path = field[3:]
        if not path:
            raise BoundaryFailure
        paths.append(path)
        if b"R" in status or b"C" in status:
            if index >= len(fields) or not fields[index]:
                raise BoundaryFailure
            paths.append(fields[index])
            index += 1
    return tuple(paths)


def _manual_pack_roots(repo_root: Path) -> frozenset[tuple[str, ...]]:
    roots: set[tuple[str, ...]] = set()
    for path in _manual_deletion_paths(repo_root):
        parts = _repository_path_parts(path)
        normalized = tuple(_normalized_component(part) for part in parts)
        try:
            marker = normalized.index("manual_pack")
        except ValueError as error:
            raise BoundaryFailure from error
        roots.add(normalized[: marker + 1])
    return frozenset(roots)


def _matches_pinned_local_config(
    path: Path,
    relative_path: bytes,
    initial_status: os.stat_result,
) -> bool:
    if relative_path != PINNED_LOCAL_CONFIG_PATH:
        return False
    if (
        _is_reparse(initial_status)
        or not stat.S_ISREG(initial_status.st_mode)
        or initial_status.st_nlink != 1
        or initial_status.st_size != PINNED_LOCAL_CONFIG_BYTES
    ):
        return False
    initial_identity = (initial_status.st_dev, initial_status.st_ino)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            opened_status = os.fstat(handle.fileno())
            if (
                _is_reparse(opened_status)
                or not stat.S_ISREG(opened_status.st_mode)
                or opened_status.st_nlink != 1
                or (opened_status.st_dev, opened_status.st_ino) != initial_identity
                or opened_status.st_size != PINNED_LOCAL_CONFIG_BYTES
            ):
                raise BoundaryFailure
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
            final_status = os.fstat(handle.fileno())
            if (
                final_status.st_nlink != 1
                or (final_status.st_dev, final_status.st_ino) != initial_identity
                or final_status.st_size != PINNED_LOCAL_CONFIG_BYTES
            ):
                raise BoundaryFailure
    except OSError as error:
        raise BoundaryFailure from error
    return digest.hexdigest() == PINNED_LOCAL_CONFIG_SHA256


def _scan_repository_disk(
    repo_root: Path,
    tracked_paths: frozenset[tuple[str, ...]],
    manual_pack_roots: frozenset[tuple[str, ...]],
) -> tuple[bool, bool]:
    raw_found = False
    protected_untracked = False
    pending: list[tuple[Path, tuple[str, ...], bool]] = [(repo_root, (), False)]
    while pending:
        directory, relative_parts, inside_raw = pending.pop()
        try:
            with os.scandir(directory) as entries:
                ordered = sorted(entries, key=lambda entry: entry.name)
        except OSError as error:
            raise BoundaryFailure from error
        for entry in ordered:
            child_parts = (*relative_parts, entry.name)
            normalized_parts = tuple(
                _normalized_component(part) for part in child_parts
            )
            child_inside_raw = inside_raw or any(
                _is_raw_directory_name(part) for part in child_parts
            )
            if not child_inside_raw and (
                normalized_parts in manual_pack_roots
                or _is_exact_controlled_non_data_root(child_parts)
            ):
                continue
            try:
                status = Path(entry.path).lstat()
            except OSError as error:
                raise BoundaryFailure from error
            if _is_reparse(status):
                raise BoundaryFailure
            if stat.S_ISDIR(status.st_mode):
                pending.append(
                    (
                        Path(entry.path),
                        child_parts,
                        child_inside_raw,
                    )
                )
            elif stat.S_ISREG(status.st_mode):
                raw_found = raw_found or inside_raw
                encoded = "/".join(child_parts).encode("utf-8")
                protected_untracked = protected_untracked or (
                    _is_protected_repository_file(encoded)
                    and normalized_parts not in tracked_paths
                    and not _matches_pinned_local_config(
                        Path(entry.path), encoded, status
                    )
                )
            else:
                raise BoundaryFailure
    return raw_found, protected_untracked


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

    changed_payload = tuple(
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
    )
    if set(changed_payload) != TASK8_ALLOWED_PATHS:
        raise BoundaryFailure

    if any(_is_protected_repository_file(path) for path in changed_payload):
        raise BoundaryFailure

    tracked_payload = tuple(
        path
        for path in _run_git(repo_root, "ls-files", "-z", "--").split(b"\0")
        if path
    )
    status_payload = _run_git(
        repo_root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--",
    )
    status_paths = _porcelain_paths(status_payload)
    audited_status_paths = tuple(
        path
        for path in status_paths
        if not _is_under_exact_controlled_non_data_root(
            _repository_path_parts(path)[:-1]
        )
    )
    if any(_is_protected_repository_file(path) for path in audited_status_paths):
        raise BoundaryFailure

    raw_tracked = any(_is_raw_repository_file(path) for path in tracked_payload)
    raw_status = any(_is_raw_repository_file(path) for path in audited_status_paths)
    tracked_paths = frozenset(
        tuple(_normalized_component(part) for part in _repository_path_parts(path))
        for path in tracked_payload
    )
    raw_on_disk, protected_untracked_on_disk = _scan_repository_disk(
        repo_root,
        tracked_paths,
        _manual_pack_roots(repo_root),
    )
    if protected_untracked_on_disk:
        raise BoundaryFailure

    raw_in_git = bool(raw_tracked or raw_status or raw_on_disk)
    if raw_in_git:
        raise BoundaryFailure
    return raw_in_git


def _compact_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _credential_key(value: str) -> bool:
    compact = _compact_key(value)
    return compact in CREDENTIAL_COMPACT_KEYS or any(
        term in compact for term in CREDENTIAL_KEY_TERMS
    )


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
                status = Path(entry.path).lstat()
            except OSError as error:
                raise BoundaryFailure from error
            if _is_reparse(status):
                raise BoundaryFailure
            if stat.S_ISDIR(status.st_mode):
                pending.append(Path(entry.path))
            elif stat.S_ISREG(status.st_mode):
                if status.st_nlink != 1:
                    raise BoundaryFailure
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
    if (
        _is_reparse(status)
        or not stat.S_ISREG(status.st_mode)
        or status.st_nlink != 1
    ):
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
    if (
        _is_reparse(status)
        or not stat.S_ISREG(status.st_mode)
        or status.st_nlink != 1
    ):
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
