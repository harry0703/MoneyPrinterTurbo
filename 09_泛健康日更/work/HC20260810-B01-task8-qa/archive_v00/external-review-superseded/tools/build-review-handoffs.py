#!/usr/bin/env python3
"""Build and verify immutable Task 8 Step 1 review requests."""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import os
import stat
import struct
import tempfile
import unicodedata
import uuid
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

IDS = [f"HC20260810-{n:03d}" for n in range(1, 11)]
BATCH_ID = "HB20260810"
VERSION = "v01"
WORK = Path("09_泛健康日更/work")
BATCH_ROOT = Path("09_泛健康日更/data/01_一般生活方式50集/batch-01")
ACTIVE = BATCH_ROOT / "active-batch.json"
SNAPSHOT = BATCH_ROOT / "batches/20260810/active-batch.json"
REF = BATCH_ROOT / "current-batch-ref.json"
INDEX = WORK / "HC20260810-B01-review-index.md"
HANDOFF = Path("production/v01/01_evidence/review-handoff-v01.md")
QA_ROOT = WORK / "HC20260810-B01-task8-qa"
JOURNAL = QA_ROOT / "task8-step1-publish-journal-v01.json"
JOURNAL_NEXT = QA_ROOT / "task8-step1-publish-journal-v01.next"
JOURNAL_PREVIOUS = QA_ROOT / "task8-step1-publish-journal-v01.previous"
JOURNAL_CLEANUP = QA_ROOT / "task8-step1-publish-journal-v01.committed-cleanup"
TRANSACTION_LOCK = QA_ROOT / "task8-step1-publish.lock"
HANDOFF_STATUS = "awaiting_real_review"
INDEX_STATUS = "awaiting_external_response"
REPARSE_POINT = 0x400
BATCH_QA = (
    ("task6_batch_final_qa", WORK / "HC20260810-B01-task6-qa/HC20260810-B01-first-frame-qa-v01.md"),
    ("task7_batch_final_qa", WORK / "HC20260810-B01-task7-qa/HC20260810-B01-task7-qa-v01.md"),
    ("task7_batch_mechanical_qa", WORK / "HC20260810-B01-task7-qa/HC20260810-B01-task7-mechanical-qa-v01.json"),
    ("task7_batch_reproducibility", WORK / "HC20260810-B01-task7-qa/HC20260810-B01-task7-reproducibility-v01.json"),
)


@dataclass(frozen=True)
class InputEntry:
    relative: Path
    data: bytes
    digest: str
    size: int
    identity: tuple[int, int, int, int, int]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rel_text(path: Path) -> str:
    text = path.as_posix()
    if path.is_absolute() or ".." in path.parts or "\\" in text:
        raise ValueError(f"non-canonical repository-relative path: {path}")
    return text


def nfc(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list) or isinstance(value, tuple):
        return [nfc(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical object keys must be strings")
            normalized = unicodedata.normalize("NFC", key)
            if normalized in result:
                raise ValueError(f"NFC key collision: {normalized}")
            result[normalized] = nfc(item)
        return result
    if isinstance(value, float):
        raise TypeError("canonical payload forbids floating-point numbers")
    if value is None or isinstance(value, (bool, int)):
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(nfc(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def is_reparse(path: Path) -> bool:
    info = path.lstat()
    attrs = getattr(info, "st_file_attributes", 0)
    return path.is_symlink() or stat.S_ISLNK(info.st_mode) or bool(attrs & REPARSE_POINT)


def path_present(path: Path) -> bool:
    return os.path.lexists(path)


def plain_root(root: Path) -> Path:
    lexical = Path(os.path.abspath(root))
    current = Path(lexical.anchor)
    for part in lexical.parts[1:]:
        current = current / part
        if path_present(current) and is_reparse(current):
            raise ValueError(f"root ancestor must not be a symlink/junction/reparse point: {current}")
    resolved = lexical.resolve(strict=True)
    if not resolved.is_dir() or is_reparse(resolved):
        raise ValueError(f"root must be a plain directory: {resolved}")
    return resolved


def plain_path(root: Path, relative: Path, require_file: bool = False) -> Path:
    root = plain_root(root)
    rel_text(relative)
    candidate = root / relative
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes root: {candidate}") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if path_present(current) and is_reparse(current):
            raise ValueError(f"symlink/junction/reparse path forbidden: {current}")
    if require_file:
        if not candidate.exists():
            raise FileNotFoundError(f"required file missing: {rel_text(relative)}")
        info = candidate.lstat()
        if not stat.S_ISREG(info.st_mode) or is_reparse(candidate):
            raise ValueError(f"input is not a plain regular file: {candidate}")
    return candidate


def identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def episode_inputs(content_id: str) -> list[Path]:
    episode = WORK / content_id
    production = episode / "production/v01"
    return [
        episode / "research/fact-card.md",
        production / "02_script_storyboard/narration-v01.md",
        production / "02_script_storyboard/storyboard-v01.md",
        production / "02_script_storyboard/article-cards-v01.md",
        production / "02_script_storyboard/platform-copy-v01.md",
        production / "05_qa/firstframes-contactsheet-v01.png",
        production / "05_qa/article-contactsheet-v01.png",
        production / "03_article_images/cover-v01.png",
        episode / "manifest.json",
        production / "05_qa/first-frame-qa-v01.md",
        production / "05_qa/article-qa-v01.md",
    ]


def input_paths() -> list[Path]:
    paths = [ACTIVE, SNAPSHOT, REF]
    for content_id in IDS:
        paths.extend(episode_inputs(content_id))
    paths.extend(path for _, path in BATCH_QA)
    unique = {rel_text(path): path for path in paths}
    return [unique[key] for key in sorted(unique)]


def ensure_quiescent(root: Path) -> None:
    batch = plain_path(root, BATCH_ROOT)
    lock = batch / ".batch-mutation.lock"
    journals = list(batch.glob(".batch-mutation-*.journal.json"))
    if path_present(lock) or journals:
        evidence = ([str(lock)] if path_present(lock) else []) + [str(path) for path in journals]
        raise RuntimeError(f"batch mutation/recovery evidence present: {evidence}")


def capture(root: Path) -> dict[Path, InputEntry]:
    ensure_quiescent(root)
    result: dict[Path, InputEntry] = {}
    for relative in input_paths():
        path = plain_path(root, relative, True)
        before = path.lstat()
        data = path.read_bytes()
        after = path.lstat()
        if identity(before) != identity(after) or len(data) != after.st_size:
            raise RuntimeError(f"input changed while read: {rel_text(relative)}")
        result[relative] = InputEntry(relative, data, sha256(data), len(data), identity(after))
    return result


def compare_snapshots(first: dict[Path, InputEntry], second: dict[Path, InputEntry]) -> None:
    if set(first) != set(second):
        raise RuntimeError("input path set changed")
    for relative in sorted(first):
        a, b = first[relative], second[relative]
        if a.identity != b.identity or a.size != b.size or a.digest != b.digest or a.data != b.data:
            raise RuntimeError(f"input identity/bytes/hash changed: {rel_text(relative)}")


def json_input(snapshot: dict[Path, InputEntry], relative: Path) -> dict[str, Any]:
    return json.loads(snapshot[relative].data.decode("utf-8"))


def png_size(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("not a valid PNG header")
    return struct.unpack(">II", data[16:24])


def bind(snapshot: dict[Path, InputEntry], role: str, relative: Path, image: bool = False) -> dict[str, Any]:
    entry = snapshot[relative]
    item: dict[str, Any] = {"role": role, "path": rel_text(relative), "bytes": entry.size, "sha256": entry.digest}
    if image:
        item["width"], item["height"] = png_size(entry.data)
    return item


def snapshot_ref(snapshot: dict[Path, InputEntry], relative: Path) -> dict[str, Any]:
    entry = snapshot[relative]
    return {"path": rel_text(relative), "bytes": entry.size, "sha256": entry.digest}


def response_contract() -> dict[str, Any]:
    return {
        "schema": "task8-external-review-response-v01",
        "exact_top_level_fields": [
            "schema", "batch_id", "subject", "reviewer", "reviewed_at", "decision", "scope", "notes", "signatures"
        ],
        "subject": {
            "allowed_modes": ["per_episode", "batch_aggregate"],
            "per_episode_exact_fields": ["mode", "items"],
            "batch_aggregate_exact_fields": ["mode", "batch_payload_sha256", "items"],
            "item_exact_fields": ["content_id", "handoff_sha256"],
            "required_content_ids_in_order": IDS,
            "item_count": 10,
            "aggregate_without_expanded_items_forbidden": True,
        },
        "reviewer": {
            "type": "role_identity_map",
            "exact_fields": ["medical_reviewer", "originality_reviewer"],
            "values_trimmed_nonempty": True,
            "identical_values_allowed": True,
        },
        "reviewed_at": {"format": "RFC3339_with_timezone", "future_forbidden": True},
        "decision": {"enum": ["approved", "changes_required", "rejected"]},
        "scope": {"exact_required_values": ["factual", "originality"]},
        "notes": {"type": "string", "required_nonempty_for": ["changes_required", "rejected"]},
        "signatures": {
            "exact_count": 2,
            "required_roles_in_order": ["medical_reviewer", "originality_reviewer"],
            "record_exact_fields": ["role", "key_id", "signature_algorithm", "signature"],
            "signature_algorithm": "Ed25519",
            "separate_role_signatures_required": True,
            "signed_payload_envelope": {
                "exact_fields": ["response", "signer"],
                "response": "all_exact_top_level_fields_except_signatures",
                "signer_exact_fields": ["role", "key_id", "signature_algorithm"],
                "canonicalization": "recursive_NFC_sorted_Unicode_keys_compact_JSON_UTF8_no_BOM",
            },
            "system_action": "verify_only",
            "repository_forbidden_material": ["private_key", "seed", "signing_capability"],
        },
        "validation": {
            "exact_fields_required": True,
            "all_ten_id_hash_pairs_required": True,
            "both_role_signatures_required_before_manifest_write": True,
            "any_handoff_change_invalidates_response": True,
        },
    }


def validate_batch(snapshot: dict[Path, InputEntry]) -> dict[str, Any]:
    active_entry = snapshot[ACTIVE]
    if active_entry.data != snapshot[SNAPSHOT].data:
        raise ValueError("active batch and immutable snapshot bytes differ")
    active, ref = json_input(snapshot, ACTIVE), json_input(snapshot, REF)
    if active.get("batch_id") != BATCH_ID or ref.get("batch_id") != BATCH_ID:
        raise ValueError("unexpected batch_id")
    if ref.get("path") != "batches/20260810/active-batch.json":
        raise ValueError("current-batch-ref path mismatch")
    if ref.get("sha256") != active_entry.digest or ref.get("active_sha256") != active_entry.digest:
        raise ValueError("current-batch-ref hashes mismatch")
    topics = active.get("topics")
    if not isinstance(topics, list) or [item.get("content_id") for item in topics] != IDS:
        raise ValueError("batch IDs are not the exact continuous sequence")
    if [item.get("state") for item in topics] != ["research_pending"] * 10:
        raise ValueError("batch states changed from research_pending")
    return active


def normalized_topic(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def payload_for(snapshot: dict[Path, InputEntry], content_id: str, active: dict[str, Any]) -> dict[str, Any]:
    episode = WORK / content_id
    production = episode / "production/v01"
    manifest_path = episode / "manifest.json"
    manifest = json_input(snapshot, manifest_path)
    batch_topic = next(item for item in active["topics"] if item["content_id"] == content_id)
    topic, public_topic = manifest.get("topic"), manifest.get("public_topic")
    if manifest.get("content_id") != content_id or manifest.get("batch_id") != BATCH_ID:
        raise ValueError(f"manifest identity mismatch: {content_id}")
    if topic != batch_topic.get("topic"):
        raise ValueError(f"manifest topic mismatch: {content_id}")
    if not isinstance(public_topic, str) or not public_topic.strip() or normalized_topic(public_topic) == normalized_topic(topic):
        raise ValueError(f"public topic missing or not distinct: {content_id}")
    review = manifest.get("medical_review")
    if not isinstance(review, dict) or review.get("status") != "pending" or review.get("reviewer") or review.get("reviewed_at"):
        raise ValueError(f"manifest review gate not pristine pending: {content_id}")
    if manifest.get("automated_qa", {}).get("status") != "pending" or manifest.get("final_qa", {}).get("status") != "pending":
        raise ValueError(f"later QA gate changed: {content_id}")
    artifacts = [
        bind(snapshot, "fact_card", episode / "research/fact-card.md"),
        bind(snapshot, "narration", production / "02_script_storyboard/narration-v01.md"),
        bind(snapshot, "storyboard", production / "02_script_storyboard/storyboard-v01.md"),
        bind(snapshot, "article_cards", production / "02_script_storyboard/article-cards-v01.md"),
        bind(snapshot, "platform_copy", production / "02_script_storyboard/platform-copy-v01.md"),
        bind(snapshot, "formal_first_frame_contact_sheet", production / "05_qa/firstframes-contactsheet-v01.png", True),
        bind(snapshot, "article_contact_sheet", production / "05_qa/article-contactsheet-v01.png", True),
        bind(snapshot, "standalone_cover", production / "03_article_images/cover-v01.png", True),
        bind(snapshot, "episode_manifest", manifest_path),
        bind(snapshot, "batch_active_manifest", ACTIVE),
        bind(snapshot, "batch_snapshot_manifest", SNAPSHOT),
        bind(snapshot, "current_batch_ref", REF),
    ]
    qa = [
        {**bind(snapshot, "task6_episode_first_frame_qa", production / "05_qa/first-frame-qa-v01.md"), "not_task8_approval": True},
        {**bind(snapshot, "task7_episode_article_qa", production / "05_qa/article-qa-v01.md"), "not_task8_approval": True},
    ]
    qa.extend({**bind(snapshot, role, path), "not_task8_approval": True} for role, path in BATCH_QA)
    return nfc({
        "schema": "task8-review-handoff-v01",
        "batch_id": BATCH_ID,
        "content_id": content_id,
        "production_version": VERSION,
        "status": HANDOFF_STATUS,
        "topic": topic,
        "public_topic": public_topic,
        "batch_snapshot": snapshot_ref(snapshot, ACTIVE),
        "manifest_snapshot": snapshot_ref(snapshot, manifest_path),
        "artifacts": artifacts,
        "qa_context": qa,
        "review_requirements": {
            "required_scopes": ["factual", "originality"],
            "allowed_decisions": ["approved", "changes_required", "rejected"],
            "external_response_contract": response_contract(),
        },
        "review_boundary": {
            "real_external_review_required": True,
            "reuse_2026_08_09_v03_approval_forbidden": True,
            "task6_task7_pass_is_not_task8_approval": True,
            "public_review_identity_forbidden": True,
            "public_internal_review_field_label_forbidden": True,
        },
    })


def rows(items: list[dict[str, Any]]) -> list[str]:
    result = []
    for item in items:
        dimensions = "—" if "width" not in item else f'{item["width"]}×{item["height"]}'
        approval = "true" if item.get("not_task8_approval") else "—"
        result.append(f'| `{item["role"]}` | `{item["path"]}` | `{item["sha256"]}` | {item["bytes"]} | {dimensions} | {approval} |')
    return result


def render_handoff(payload: dict[str, Any]) -> tuple[bytes, str]:
    canonical = canonical_json(payload)
    digest = sha256(canonical.encode("utf-8"))
    lines = [
        f'# {payload["content_id"]} 内部事实与原创审核交接包 v01', "",
        f'- 批次：`{payload["batch_id"]}`', f'- 内容 ID：`{payload["content_id"]}`',
        f'- 生产版本：`{payload["production_version"]}`', f'- 状态：`{payload["status"]}`',
        f'- 内部题面：{payload["topic"]}', f'- 公开题面：{payload["public_topic"]}',
        f'- `handoff_sha256`：`{digest}`', "",
        "## 审核合同", "",
        "真实回传必须覆盖 `factual` 与 `originality`，decision 只能是 `approved | changes_required | rejected`。回传必须按 canonical payload 中的精确字段合同展开十个内容 ID 与 handoff hash；批次聚合不得只给 aggregate hash。", "",
        "必须分别由固定角色 `medical_reviewer` 与 `originality_reviewer` 提供 Ed25519 签名；可由同一真实人承担两个角色，但两个角色签名缺一不可。本地系统只验签，仓库绝不保存私钥、seed 或签名能力。", "",
        "本包只冻结待审材料，不构成审核通过、最终 QA 或发布授权。不得复用 2026-08-09 v03 批准，不得自行补写真实 response。公开包装不得暴露审核身份，也不得出现内部兼容字段名 `medical`。", "",
        "## 审核主体与冻结引用", "",
        "| 角色 | 仓库相对路径 | SHA-256 | 字节数 | 图像尺寸 | not_task8_approval |",
        "|---|---|---:|---:|---:|---:|", *rows(payload["artifacts"]), "",
        "## QA 上下文", "", "以下均只是已完成任务的上下文，不是 Task 8 批准。", "",
        "| 角色 | 仓库相对路径 | SHA-256 | 字节数 | 图像尺寸 | not_task8_approval |",
        "|---|---|---:|---:|---:|---:|", *rows(payload["qa_context"]), "",
        "## Canonical payload", "",
        "复算：递归 NFC 后按 Unicode key 排序，使用无 BOM UTF-8 紧凑 JSON；数组保持顺序。取下方标记间唯一 JSON 行且不含行尾换行计算 SHA-256。`handoff_sha256` 不进入 payload。", "",
        "<!-- canonical-payload-start -->", canonical, "<!-- canonical-payload-end -->", "",
    ]
    return "\n".join(lines).encode("utf-8"), digest


def render_index(snapshot: dict[Path, InputEntry], entries: list[dict[str, Any]]) -> tuple[bytes, str]:
    payload = nfc({
        "schema": "task8-review-index-v01",
        "batch_id": BATCH_ID,
        "production_version": VERSION,
        "batch_snapshot": snapshot_ref(snapshot, ACTIVE),
        "entries": entries,
        "review_status": INDEX_STATUS,
        "required_scopes": ["factual", "originality"],
        "allowed_decisions": ["approved", "changes_required", "rejected"],
        "external_response_contract": response_contract(),
    })
    canonical = canonical_json(payload)
    digest = sha256(canonical.encode("utf-8"))
    table = [f'| `{e["content_id"]}` | {e["public_topic"]} | `{e["handoff_path"]}` | `{e["handoff_sha256"]}` | {e["handoff_file_bytes"]} | `{e["handoff_file_sha256"]}` |' for e in entries]
    lines = [
        "# HC20260810-B01 真实外部审核请求索引", "",
        f'- 批次：`{BATCH_ID}`', f'- 生产版本：`{VERSION}`', f'- 状态：`{INDEX_STATUS}`',
        f'- `batch_payload_sha256`：`{digest}`',
        "- 必审范围：`factual`、`originality`。允许决定仅为 `approved | changes_required | rejected`。",
        "- 真实 response 必须精确展开十个 ID 与 handoff hash，并分别具备 `medical_reviewer`、`originality_reviewer` 的 Ed25519 签名；本地仅验签。",
        "- 本索引没有真实 response、审核身份、时间、决定或签名占位；不得复用 2026-08-09 v03 批准。", "",
        "| 内容 ID | 公开题目 | 交接包路径 | handoff hash | 文件字节数 | 文件 SHA-256 |",
        "|---|---|---|---:|---:|---:|", *table, "",
        "## Canonical payload", "",
        "复算：递归 NFC 后按 Unicode key 排序，使用无 BOM UTF-8 紧凑 JSON；数组保持顺序。取下方标记间唯一 JSON 行且不含行尾换行计算 SHA-256。`batch_payload_sha256` 不进入 payload。", "",
        "<!-- canonical-payload-start -->", canonical, "<!-- canonical-payload-end -->", "",
    ]
    return "\n".join(lines).encode("utf-8"), digest


def expected(snapshot: dict[Path, InputEntry]) -> tuple[dict[Path, bytes], list[dict[str, Any]], str]:
    active = validate_batch(snapshot)
    outputs: dict[Path, bytes] = {}
    entries: list[dict[str, Any]] = []
    for content_id in IDS:
        payload = payload_for(snapshot, content_id, active)
        handoff, digest = render_handoff(payload)
        relative = WORK / content_id / HANDOFF
        outputs[relative] = handoff
        entries.append({
            "content_id": content_id,
            "public_topic": payload["public_topic"],
            "handoff_path": rel_text(relative),
            "handoff_sha256": digest,
            "handoff_file_bytes": len(handoff),
            "handoff_file_sha256": sha256(handoff),
        })
    index, batch_digest = render_index(snapshot, entries)
    outputs[INDEX] = index
    return outputs, entries, batch_digest


def compare_outputs(first: dict[Path, bytes], second: dict[Path, bytes]) -> None:
    if set(first) != set(second):
        raise RuntimeError("expected output path set changed")
    for relative in sorted(first):
        if first[relative] != second[relative]:
            raise RuntimeError(f"second expected output differs: {rel_text(relative)}")


def extract_payload(document: bytes) -> tuple[dict[str, Any], str]:
    text = document.decode("utf-8")
    start, end = "<!-- canonical-payload-start -->\n", "\n<!-- canonical-payload-end -->"
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError("document must contain exactly one canonical payload")
    canonical = text.split(start, 1)[1].split(end, 1)[0]
    payload = json.loads(canonical)
    if canonical_json(payload) != canonical or unicodedata.normalize("NFC", canonical) != canonical:
        raise ValueError("embedded payload is not recursive NFC canonical JSON")
    return payload, sha256(canonical.encode("utf-8"))


def verify_tree(root: Path, outputs: dict[Path, bytes]) -> None:
    for relative, wanted in outputs.items():
        actual = plain_path(root, relative, True).read_bytes()
        if actual != wanted:
            raise ValueError(f"output bytes differ: {rel_text(relative)}")
        payload, digest = extract_payload(actual)
        label = "batch_payload_sha256" if relative == INDEX else "handoff_sha256"
        if f'- `{label}`：`{digest}`' not in actual.decode("utf-8"):
            raise ValueError(f"canonical envelope mismatch: {rel_text(relative)}")
        if relative == INDEX:
            if payload.get("review_status") != INDEX_STATUS or payload.get("required_scopes") != ["factual", "originality"]:
                raise ValueError("index review contract mismatch")
            if [item.get("content_id") for item in payload.get("entries", [])] != IDS:
                raise ValueError("index ID coverage mismatch")
            for item in payload["entries"]:
                handoff = outputs.get(Path(item["handoff_path"]))
                if handoff is None or len(handoff) != item["handoff_file_bytes"] or sha256(handoff) != item["handoff_file_sha256"]:
                    raise ValueError(f"index final Markdown binding mismatch: {item['content_id']}")


FaultHook = Callable[[str, dict[str, Any]], None]


class RecoveryRequired(RuntimeError):
    """Raised when a persistent transaction artifact blocks consumption."""


WIN32 = os.name == "nt"
if WIN32:
    import msvcrt

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _KERNEL32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    _KERNEL32.CreateFileW.restype = wintypes.HANDLE
    _KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
    _KERNEL32.CloseHandle.restype = wintypes.BOOL
    _KERNEL32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    _KERNEL32.FlushFileBuffers.restype = wintypes.BOOL
    _KERNEL32.MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    _KERNEL32.MoveFileExW.restype = wintypes.BOOL
    _KERNEL32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    _KERNEL32.GetDriveTypeW.restype = wintypes.UINT
    _KERNEL32.GetVolumeInformationW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    _KERNEL32.GetVolumeInformationW.restype = wintypes.BOOL
    _KERNEL32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    _KERNEL32.CreateMutexW.restype = wintypes.HANDLE
    _KERNEL32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _KERNEL32.WaitForSingleObject.restype = wintypes.DWORD
    _KERNEL32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    _KERNEL32.ReleaseMutex.restype = wintypes.BOOL

    class _FILETIME(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD), ("creation_time", _FILETIME),
            ("last_access_time", _FILETIME), ("last_write_time", _FILETIME),
            ("volume_serial", wintypes.DWORD), ("file_size_high", wintypes.DWORD),
            ("file_size_low", wintypes.DWORD), ("number_of_links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD), ("file_index_low", wintypes.DWORD),
        ]

    _KERNEL32.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION)]
    _KERNEL32.GetFileInformationByHandle.restype = wintypes.BOOL

    class _FILE_DISPOSITION_INFO(ctypes.Structure):
        _fields_ = [("delete_file", wintypes.BOOL)]

    class _FILE_RENAME_INFO(ctypes.Structure):
        _fields_ = [
            ("replace_if_exists", wintypes.BOOLEAN),
            ("root_directory", wintypes.HANDLE),
            ("file_name_length", wintypes.DWORD),
            ("file_name", wintypes.WCHAR * 1),
        ]

    _KERNEL32.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ]
    _KERNEL32.SetFileInformationByHandle.restype = wintypes.BOOL


_INVALID_HANDLE = ctypes.c_void_p(-1).value
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_DELETE = 0x00010000
_FILE_READ_ATTRIBUTES = 0x80
_FILE_SHARE_READ = 0x1
_FILE_SHARE_WRITE = 0x2
_FILE_SHARE_DELETE = 0x4
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_DIRECTORY = 0x10
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_MOVEFILE_REPLACE_EXISTING = 0x1
_MOVEFILE_WRITE_THROUGH = 0x8
_DRIVE_FIXED = 3
_WAIT_OBJECT_0 = 0
_WAIT_ABANDONED = 0x80
_FILE_RENAME_INFO_CLASS = 3
_FILE_DISPOSITION_INFO_CLASS = 4


def win_error(label: str) -> OSError:
    error = ctypes.get_last_error()
    return OSError(error, f"{label}: {ctypes.FormatError(error).strip()}")


def assert_supported_volume(root: Path) -> None:
    if not WIN32:
        raise RuntimeError("Task 8 durable publication requires local Windows NTFS")
    root = plain_root(root)
    volume = root.anchor
    if not volume or _KERNEL32.GetDriveTypeW(volume) != _DRIVE_FIXED:
        raise RuntimeError(f"Task 8 publication requires a fixed local volume: {root}")
    fs_name = ctypes.create_unicode_buffer(64)
    if not _KERNEL32.GetVolumeInformationW(volume, None, 0, None, None, None, fs_name, len(fs_name)):
        raise win_error("GetVolumeInformationW failed")
    if fs_name.value.upper() != "NTFS":
        raise RuntimeError(f"Task 8 publication requires NTFS, found {fs_name.value!r}")


def open_windows_path(
    path: Path,
    *,
    directory: bool,
    deny_delete_share: bool,
    writable: bool = False,
    readable: bool = False,
    delete_access: bool = False,
    deny_write_share: bool = False,
) -> int:
    access = _FILE_READ_ATTRIBUTES
    if readable or writable:
        access |= _GENERIC_READ
    if writable:
        access |= _GENERIC_WRITE
    if delete_access:
        access |= _DELETE
    share = _FILE_SHARE_READ
    if not deny_write_share:
        share |= _FILE_SHARE_WRITE
    if not deny_delete_share:
        share |= _FILE_SHARE_DELETE
    flags = _FILE_FLAG_OPEN_REPARSE_POINT | (_FILE_FLAG_BACKUP_SEMANTICS if directory else 0)
    handle = _KERNEL32.CreateFileW(str(path), access, share, None, _OPEN_EXISTING, flags, None)
    if handle in (None, _INVALID_HANDLE):
        raise win_error(f"CreateFileW failed for {path}")
    info = _BY_HANDLE_FILE_INFORMATION()
    if not _KERNEL32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        _KERNEL32.CloseHandle(handle)
        raise win_error(f"GetFileInformationByHandle failed for {path}")
    is_directory = bool(info.attributes & _FILE_ATTRIBUTE_DIRECTORY)
    if bool(info.attributes & _FILE_ATTRIBUTE_REPARSE_POINT) or is_directory != directory:
        _KERNEL32.CloseHandle(handle)
        raise ValueError(f"plain {'directory' if directory else 'file'} required: {path}")
    return handle


def windows_handle_identity(handle: int) -> dict[str, int]:
    info = _BY_HANDLE_FILE_INFORMATION()
    if not _KERNEL32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        raise win_error("GetFileInformationByHandle failed")
    return {
        "volume_serial": int(info.volume_serial),
        "file_index": (int(info.file_index_high) << 32) | int(info.file_index_low),
    }


def file_ownership(path: Path) -> dict[str, int]:
    if not WIN32:
        info = path.lstat()
        return {"device": info.st_dev, "inode": info.st_ino}
    handle = open_windows_path(path, directory=False, deny_delete_share=False)
    try:
        return windows_handle_identity(handle)
    finally:
        _KERNEL32.CloseHandle(handle)


def read_descriptor(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return b"".join(chunks)


def open_bound_descriptor(
    target: Path,
    *,
    writable: bool,
    delete_access: bool,
) -> tuple[int, int]:
    handle = open_windows_path(
        target,
        directory=False,
        deny_delete_share=True,
        writable=writable,
        readable=True,
        delete_access=delete_access,
        deny_write_share=True,
    )
    try:
        flags = os.O_BINARY | (os.O_RDWR if writable else os.O_RDONLY)
        descriptor = msvcrt.open_osfhandle(handle, flags)
    except Exception:
        _KERNEL32.CloseHandle(handle)
        raise
    return descriptor, msvcrt.get_osfhandle(descriptor)


@contextlib.contextmanager
def guarded_leaf_file(
    root: Path,
    target: Path,
    *,
    writable: bool,
    delete_access: bool,
):
    if not WIN32:
        raise RuntimeError("identity-bound leaf operations require Windows")
    root = plain_root(root)
    target = Path(os.path.abspath(target))
    try:
        relative = target.relative_to(root)
    except ValueError as error:
        raise ValueError(f"guarded leaf escapes root: {target}") from error
    with guarded_directory_chain(root, target.parent) as guards:
        target = plain_path(root, relative, True)
        descriptor: int | None = None
        try:
            descriptor, raw_handle = open_bound_descriptor(
                target,
                writable=writable,
                delete_access=delete_access,
            )
            yield target, descriptor, raw_handle, guards
        finally:
            if descriptor is not None:
                os.close(descriptor)


def bound_file_matches(descriptor: int, handle: int, record: dict[str, Any], wanted: bytes) -> bool:
    before = windows_handle_identity(handle)
    data = read_descriptor(descriptor)
    after = windows_handle_identity(handle)
    return (
        before == after == record["identity"]
        and len(data) == record["bytes"]
        and sha256(data) == record["sha256"]
        and data == wanted
    )


def mark_bound_file_for_delete(handle: int) -> None:
    disposition = _FILE_DISPOSITION_INFO(True)
    if not _KERNEL32.SetFileInformationByHandle(
        handle,
        _FILE_DISPOSITION_INFO_CLASS,
        ctypes.byref(disposition),
        ctypes.sizeof(disposition),
    ):
        raise win_error("SetFileInformationByHandle(FileDispositionInfo) failed")


def rename_bound_file(handle: int, target: Path) -> None:
    encoded = str(target).encode("utf-16-le")
    offset = _FILE_RENAME_INFO.file_name.offset
    buffer = ctypes.create_string_buffer(offset + len(encoded) + ctypes.sizeof(wintypes.WCHAR))
    info = ctypes.cast(buffer, ctypes.POINTER(_FILE_RENAME_INFO)).contents
    info.replace_if_exists = 0
    info.root_directory = None
    info.file_name_length = len(encoded)
    ctypes.memmove(ctypes.addressof(buffer) + offset, encoded, len(encoded))
    if not _KERNEL32.SetFileInformationByHandle(
        handle,
        _FILE_RENAME_INFO_CLASS,
        buffer,
        len(buffer),
    ):
        raise win_error(f"SetFileInformationByHandle(FileRenameInfo) failed for {target}")


@contextlib.contextmanager
def guarded_directory_chain(root: Path, parent: Path):
    root = plain_root(root)
    parent = Path(os.path.abspath(parent))
    try:
        relative = parent.relative_to(root)
    except ValueError as error:
        raise ValueError(f"guarded directory escapes root: {parent}") from error
    if not WIN32:
        descriptors: list[int] = []
        try:
            current = root
            for part in (Path(), *relative.parts):
                if part != Path():
                    current = current / part
                flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
                descriptors.append(os.open(current, flags))
            yield descriptors
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
        return
    handles: list[int] = []
    try:
        current = root
        handles.append(open_windows_path(current, directory=True, deny_delete_share=True, writable=True))
        for part in relative.parts:
            current = current / part
            handles.append(open_windows_path(current, directory=True, deny_delete_share=True, writable=True))
        yield handles
    finally:
        for handle in reversed(handles):
            _KERNEL32.CloseHandle(handle)


def flush_directory_guards(guards: list[int]) -> None:
    if WIN32:
        for handle in reversed(guards):
            if not _KERNEL32.FlushFileBuffers(handle):
                raise win_error("FlushFileBuffers failed for directory")
    else:
        for descriptor in reversed(guards):
            os.fsync(descriptor)


@contextlib.contextmanager
def ensure_guarded_directory(root: Path, directory: Path):
    root = plain_root(root)
    directory = Path(os.path.abspath(directory))
    try:
        relative = directory.relative_to(root)
    except ValueError as error:
        raise ValueError(f"directory creation escapes root: {directory}") from error
    with contextlib.ExitStack() as stack:
        guards = stack.enter_context(guarded_directory_chain(root, root))
        current = root
        for part in relative.parts:
            candidate = current / part
            if not path_present(candidate):
                try:
                    candidate.mkdir()
                except FileExistsError:
                    pass
                flush_directory_guards(guards)
            if not path_present(candidate) or is_reparse(candidate) or not stat.S_ISDIR(candidate.lstat().st_mode):
                raise ValueError(f"plain directory required: {candidate}")
            current = candidate
            guards = stack.enter_context(guarded_directory_chain(root, current))
        yield guards


@contextlib.contextmanager
def transaction_mutex(output: Path):
    assert_supported_volume(output)
    name_hash = sha256(str(plain_root(output)).casefold().encode("utf-8"))
    handle = _KERNEL32.CreateMutexW(None, False, f"Local\\MoneyPrinterTurbo.Task8.{name_hash}")
    if handle in (None, _INVALID_HANDLE):
        raise win_error("CreateMutexW failed")
    acquired = False
    try:
        result = _KERNEL32.WaitForSingleObject(handle, 0)
        if result not in (_WAIT_OBJECT_0, _WAIT_ABANDONED):
            raise RecoveryRequired("another Task 8 build/verify/recovery operation is active")
        acquired = True
        yield
    finally:
        if acquired and not _KERNEL32.ReleaseMutex(handle):
            raise win_error("ReleaseMutex failed")
        _KERNEL32.CloseHandle(handle)


def durable_move(source: Path, target: Path, *, replace: bool) -> None:
    if WIN32:
        flags = _MOVEFILE_WRITE_THROUGH | (_MOVEFILE_REPLACE_EXISTING if replace else 0)
        if not _KERNEL32.MoveFileExW(str(source), str(target), flags):
            raise win_error(f"MoveFileExW failed: {source} -> {target}")
    else:
        if replace:
            os.replace(source, target)
        else:
            os.link(source, target)
            source.unlink()


def durable_unlink(root: Path, target: Path) -> None:
    with guarded_directory_chain(root, target.parent) as guards:
        target = plain_path(root, target.relative_to(plain_root(root)), True)
        target.unlink()
        flush_directory_guards(guards)


def durable_unlink_owned(
    root: Path,
    target: Path,
    record: dict[str, Any],
    wanted: bytes,
    fault: FaultHook | None = None,
) -> None:
    root = plain_root(root)
    relative = Path(os.path.abspath(target)).relative_to(root)
    with guarded_directory_chain(root, target.parent) as outer_guards:
        with guarded_leaf_file(root, target, writable=False, delete_access=True) as (bound_path, descriptor, handle, _):
            if not bound_file_matches(descriptor, handle, record, wanted):
                raise RecoveryRequired(f"refusing to delete target not provably owned by transaction: {rel_text(relative)}")
            fire(fault, "after_owned_validation_before_delete", path=rel_text(relative))
            if not bound_file_matches(descriptor, handle, record, wanted):
                raise RecoveryRequired(f"owned target changed before identity-bound delete: {rel_text(relative)}")
            mark_bound_file_for_delete(handle)
        if path_present(bound_path):
            raise RecoveryRequired(f"identity-bound delete did not remove the recorded target: {rel_text(relative)}")
        flush_directory_guards(outer_guards)


def write_stage(root: Path, outputs: dict[Path, bytes], fault: FaultHook | None = None) -> None:
    root = plain_root(root)
    with guarded_directory_chain(root, root):
        for sequence, (relative, data) in enumerate(outputs.items(), 1):
            target = plain_path(root, relative)
            with ensure_guarded_directory(root, target.parent) as guards:
                target = plain_path(root, relative)
                fire(fault, "before_stage_file_open", path=rel_text(relative), sequence=sequence)
                if path_present(target):
                    raise FileExistsError(f"staging target already exists: {target}")
                with target.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                flush_directory_guards(guards)


def journal_envelope(payload: dict[str, Any]) -> bytes:
    canonical = canonical_json(payload)
    envelope = {"journal_payload": payload, "journal_payload_sha256": sha256(canonical.encode("utf-8"))}
    return canonical_json(envelope).encode("utf-8")


JOURNAL_PHASES = {
    "prepared", "publishing_handoffs", "handoffs_published", "ready_to_commit",
    "publishing_index", "index_visible", "committed_postcheck_passed", "rolled_back",
}


def payload_digest(payload: dict[str, Any]) -> str:
    return sha256(canonical_json(payload).encode("utf-8"))


def is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def fixed_output_paths() -> list[Path]:
    return [WORK / content_id / HANDOFF for content_id in IDS] + [INDEX]


def validate_journal_payload(payload: dict[str, Any]) -> None:
    fields = {
        "schema", "transaction_id", "generation", "previous_payload_sha256", "phase",
        "input_snapshot", "expected_outputs", "initial_targets", "created", "adopted", "pending_create",
    }
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError("journal payload has an unexpected field set")
    transaction_id = payload["transaction_id"]
    if not isinstance(transaction_id, str) or len(transaction_id) != 32 or any(c not in "0123456789abcdef" for c in transaction_id):
        raise ValueError("invalid journal transaction_id")
    generation = payload["generation"]
    previous = payload["previous_payload_sha256"]
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
        raise ValueError("invalid journal generation")
    if (generation == 0 and previous is not None) or (generation > 0 and not is_digest(previous)):
        raise ValueError("invalid journal predecessor hash")
    if payload["phase"] not in JOURNAL_PHASES:
        raise ValueError("invalid journal phase")

    snapshot = payload["input_snapshot"]
    if not isinstance(snapshot, dict) or set(snapshot) != {"count", "entries", "summary_sha256"}:
        raise ValueError("invalid journal input snapshot")
    entries = snapshot["entries"]
    if snapshot["count"] != 117 or not isinstance(entries, list) or len(entries) != 117:
        raise ValueError("journal input snapshot must contain 117 entries")
    if snapshot["summary_sha256"] != sha256(canonical_json(entries).encode("utf-8")):
        raise ValueError("journal input snapshot summary mismatch")
    input_paths_seen: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256", "identity"}:
            raise ValueError("invalid journal input entry")
        path = rel_text(Path(entry["path"]))
        if path != entry["path"] or not isinstance(entry["bytes"], int) or entry["bytes"] < 0 or not is_digest(entry["sha256"]):
            raise ValueError("invalid journal input binding")
        if not isinstance(entry["identity"], list) or len(entry["identity"]) != 5 or not all(isinstance(v, int) for v in entry["identity"]):
            raise ValueError("invalid journal input identity")
        input_paths_seen.append(path)
    if input_paths_seen != sorted(input_paths_seen) or len(set(input_paths_seen)) != 117:
        raise ValueError("journal input paths are not unique canonical order")

    expected = payload["expected_outputs"]
    fixed = [rel_text(path) for path in fixed_output_paths()]
    if not isinstance(expected, list) or len(expected) != 11 or [item.get("path") for item in expected] != fixed:
        raise ValueError("journal expected output paths mismatch")
    for position, item in enumerate(expected):
        if set(item) != {"path", "bytes", "sha256", "kind"} or not isinstance(item["bytes"], int) or item["bytes"] < 0 or not is_digest(item["sha256"]):
            raise ValueError("invalid journal expected output binding")
        wanted_kind = "index_commit_marker" if position == 10 else "handoff"
        if item["kind"] != wanted_kind:
            raise ValueError("invalid journal expected output kind")

    initial = payload["initial_targets"]
    if not isinstance(initial, list) or len(initial) != 11 or [item.get("path") for item in initial] != fixed:
        raise ValueError("journal initial target paths mismatch")
    missing_paths: set[str] = set()
    for item, expected_item in zip(initial, expected):
        if set(item) != {"path", "state", "bytes", "sha256", "identity"}:
            raise ValueError("invalid initial target entry")
        if item["state"] == "missing":
            if any(item[key] is not None for key in ("bytes", "sha256", "identity")):
                raise ValueError("missing target must not carry an identity")
            missing_paths.add(item["path"])
        elif item["state"] == "preexisting":
            if item["bytes"] != expected_item["bytes"] or item["sha256"] != expected_item["sha256"]:
                raise ValueError("preexisting target binding differs from expected")
            if not isinstance(item["identity"], dict) or set(item["identity"]) != {"volume_serial", "file_index"}:
                raise ValueError("invalid preexisting target identity")
        else:
            raise ValueError("invalid initial target state")

    created = payload["created"]
    if not isinstance(created, list):
        raise ValueError("journal created list must be an array")
    created_paths: set[str] = set()
    for item in created:
        if set(item) != {"path", "bytes", "sha256", "identity"} or item["path"] not in missing_paths:
            raise ValueError("invalid journal created entry")
        if item["path"] in created_paths or not isinstance(item["identity"], dict) or set(item["identity"]) != {"volume_serial", "file_index"}:
            raise ValueError("duplicate or invalid journal created identity")
        expected_item = expected[fixed.index(item["path"])]
        if item["bytes"] != expected_item["bytes"] or item["sha256"] != expected_item["sha256"]:
            raise ValueError("created target binding differs from expected")
        created_paths.add(item["path"])
    adopted = payload["adopted"]
    if not isinstance(adopted, list):
        raise ValueError("journal adopted list must be an array")
    adopted_paths: set[str] = set()
    for item in adopted:
        if set(item) != {"path", "bytes", "sha256", "identity"} or item["path"] not in missing_paths:
            raise ValueError("invalid journal adopted entry")
        if item["path"] in created_paths or item["path"] in adopted_paths or not isinstance(item["identity"], dict) or set(item["identity"]) != {"volume_serial", "file_index"}:
            raise ValueError("duplicate or invalid journal adopted identity")
        expected_item = expected[fixed.index(item["path"])]
        if item["bytes"] != expected_item["bytes"] or item["sha256"] != expected_item["sha256"]:
            raise ValueError("adopted target binding differs from expected")
        adopted_paths.add(item["path"])
    pending = payload["pending_create"]
    if pending is not None:
        if set(pending) != {"path", "bytes", "sha256", "identity"} or pending["path"] not in missing_paths or pending["path"] in created_paths or pending["path"] in adopted_paths:
            raise ValueError("invalid journal pending intent")
        if not isinstance(pending["identity"], dict) or set(pending["identity"]) != {"volume_serial", "file_index"}:
            raise ValueError("invalid pending source identity")
        expected_item = expected[fixed.index(pending["path"])]
        if pending["bytes"] != expected_item["bytes"] or pending["sha256"] != expected_item["sha256"]:
            raise ValueError("pending target binding differs from expected")


def decode_journal(data: bytes) -> dict[str, Any]:
    envelope = json.loads(data.decode("utf-8"))
    if set(envelope) != {"journal_payload", "journal_payload_sha256"}:
        raise ValueError("journal envelope has an unexpected field set")
    payload = envelope["journal_payload"]
    if payload.get("schema") != "task8-step1-publish-transaction-v01":
        raise ValueError("unexpected transaction journal schema")
    digest = sha256(canonical_json(payload).encode("utf-8"))
    if envelope["journal_payload_sha256"] != digest:
        raise ValueError("transaction journal payload hash mismatch")
    validate_journal_payload(payload)
    return payload


def transaction_artifacts(output: Path) -> list[Path]:
    return [
        relative
        for relative in (JOURNAL, JOURNAL_NEXT, JOURNAL_PREVIOUS, JOURNAL_CLEANUP, TRANSACTION_LOCK)
        if path_present(output / relative)
    ]


def require_clean_gate(output: Path, require_commit_marker: bool) -> None:
    artifacts = transaction_artifacts(output)
    if artifacts:
        raise RecoveryRequired(f"Task 8 transaction recovery required: {[rel_text(path) for path in artifacts]}")
    if require_commit_marker and not plain_path(output, INDEX).is_file():
        raise RecoveryRequired("Task 8 index commit marker is absent")


def write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short write while persisting transaction journal")
        view = view[written:]


def write_journal_candidate(
    output: Path,
    payload: dict[str, Any],
    fault: FaultHook | None = None,
) -> Path:
    validate_journal_payload(payload)
    next_path = plain_path(output, JOURNAL_NEXT)
    with ensure_guarded_directory(output, next_path.parent) as guards:
        next_path = plain_path(output, JOURNAL_NEXT)
        if path_present(next_path):
            raise RecoveryRequired("orphan journal next-file requires explicit recovery")
        fire(fault, "before_journal_candidate_open", transaction_id=payload["transaction_id"])
        descriptor = os.open(next_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            write_all(descriptor, journal_envelope(payload))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        flush_directory_guards(guards)
    return next_path


def publish_journal_candidate(output: Path, target: Path, *, replace: bool) -> None:
    if replace:
        raise RecoveryRequired("journal publication must never replace an existing leaf")
    next_path = plain_path(output, JOURNAL_NEXT, True)
    target_path = plain_path(output, target)
    with guarded_directory_chain(output, target_path.parent) as guards:
        durable_move(next_path, target_path, replace=replace)
        with target_path.open("r+b") as stream:
            os.fsync(stream.fileno())
        flush_directory_guards(guards)


def atomic_create_journal(output: Path, payload: dict[str, Any], fault: FaultHook | None = None) -> None:
    journal = plain_path(output, JOURNAL)
    if transaction_artifacts(output):
        raise RecoveryRequired("cannot start while a transaction artifact exists")
    write_journal_candidate(output, payload, fault)
    fire(
        fault,
        "before_journal_candidate_publish",
        phase=payload["phase"],
        generation=payload["generation"],
    )
    publish_journal_candidate(output, JOURNAL, replace=False)
    fire(fault, "after_journal_publish", transaction_id=payload["transaction_id"])


def read_journal(output: Path) -> dict[str, Any]:
    journal = plain_path(output, JOURNAL, True)
    return decode_journal(journal.read_bytes())


def read_bound_journal(
    descriptor: int,
    handle: int,
    *,
    expected_payload: dict[str, Any] | None = None,
    label: str,
) -> tuple[dict[str, Any], dict[str, int], bytes]:
    before = windows_handle_identity(handle)
    data = read_descriptor(descriptor)
    after = windows_handle_identity(handle)
    if before != after:
        raise RecoveryRequired(f"{label} identity changed while held")
    try:
        payload = decode_journal(data)
    except Exception as error:
        raise RecoveryRequired(f"{label} is not an exact valid journal: {error}") from error
    if expected_payload is not None and data != journal_envelope(expected_payload):
        raise RecoveryRequired(f"{label} differs from the expected exact journal envelope")
    return payload, before, data


def require_exact_successor(current: dict[str, Any], candidate: dict[str, Any]) -> None:
    if (
        current["transaction_id"] != candidate["transaction_id"]
        or candidate["generation"] != current["generation"] + 1
        or candidate["previous_payload_sha256"] != payload_digest(current)
    ):
        raise RecoveryRequired("journal candidate is not the exact successor generation")


def rotate_current_journal_successor(
    output: Path,
    *,
    prepare_candidate: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    expected_current: dict[str, Any] | None = None,
    expected_candidate: dict[str, Any] | None = None,
    fault: FaultHook | None = None,
) -> dict[str, Any]:
    """Rotate JOURNAL + NEXT without ever replacing or path-deleting a leaf.

    JOURNAL remains held against write/delete from its identity validation until it
    is renamed to PREVIOUS.  NEXT is likewise held while it is renamed no-replace
    to JOURNAL.  A crash therefore leaves one of the explicitly gated states:
    JOURNAL+NEXT, PREVIOUS+NEXT, PREVIOUS+JOURNAL, or JOURNAL.
    """
    output = plain_root(output)
    journal_path = plain_path(output, JOURNAL, True)
    next_path = plain_path(output, JOURNAL_NEXT)
    previous_path = plain_path(output, JOURNAL_PREVIOUS)
    current_descriptor: int | None = None
    candidate_descriptor: int | None = None
    current_handle: int | None = None
    candidate_handle: int | None = None
    current_identity: dict[str, int] | None = None
    candidate_identity: dict[str, int] | None = None
    current_bytes = b""
    candidate_bytes = b""
    current_payload: dict[str, Any]
    candidate_payload: dict[str, Any]
    predecessor_delete_marked = False

    with guarded_directory_chain(output, journal_path.parent) as guards:
        if path_present(previous_path):
            raise RecoveryRequired("journal predecessor artifact requires explicit recovery")
        current_descriptor, current_handle = open_bound_descriptor(
            journal_path, writable=False, delete_access=True,
        )
        try:
            current_payload, current_identity, current_bytes = read_bound_journal(
                current_descriptor,
                current_handle,
                expected_payload=expected_current,
                label="current journal",
            )
            if prepare_candidate is not None:
                if path_present(next_path):
                    raise RecoveryRequired("orphan journal next-file requires explicit recovery")
                candidate_payload = prepare_candidate(current_payload)
            else:
                if not path_present(next_path):
                    raise RecoveryRequired("journal successor candidate is absent")
                candidate_payload = expected_candidate if expected_candidate is not None else {}

            if path_present(previous_path):
                raise RecoveryRequired("journal predecessor appeared before generation rotation")
            next_path = plain_path(output, JOURNAL_NEXT, True)
            candidate_descriptor, candidate_handle = open_bound_descriptor(
                next_path, writable=True, delete_access=True,
            )
            decoded_candidate, candidate_identity, candidate_bytes = read_bound_journal(
                candidate_descriptor,
                candidate_handle,
                expected_payload=(candidate_payload if candidate_payload else None),
                label="journal successor candidate",
            )
            if not candidate_payload:
                candidate_payload = decoded_candidate
            elif decoded_candidate != candidate_payload:
                raise RecoveryRequired("journal successor payload changed before rotation")
            require_exact_successor(current_payload, candidate_payload)

            if windows_handle_identity(current_handle) != current_identity or read_descriptor(current_descriptor) != current_bytes:
                raise RecoveryRequired("current journal changed before predecessor move")
            rename_bound_file(current_handle, previous_path)
            if path_present(journal_path):
                raise RecoveryRequired("journal path was not vacated by predecessor move")
            if file_ownership(previous_path) != current_identity:
                raise RecoveryRequired("journal predecessor path identity mismatch")
            flush_directory_guards(guards)
            fire(
                fault,
                "after_journal_predecessor_visible_before_candidate_publish",
                phase=candidate_payload["phase"],
                generation=candidate_payload["generation"],
            )

            if path_present(journal_path):
                raise RecoveryRequired("journal leaf appeared before no-replace successor publication")
            if windows_handle_identity(candidate_handle) != candidate_identity or read_descriptor(candidate_descriptor) != candidate_bytes:
                raise RecoveryRequired("journal successor changed before no-replace publication")
            rename_bound_file(candidate_handle, journal_path)
            os.fsync(candidate_descriptor)
            if path_present(next_path):
                raise RecoveryRequired("journal next-file remained visible after successor publication")
            if file_ownership(journal_path) != candidate_identity:
                raise RecoveryRequired("published journal successor path identity mismatch")
            if windows_handle_identity(current_handle) != current_identity or read_descriptor(current_descriptor) != current_bytes:
                raise RecoveryRequired("journal predecessor changed before cleanup")
            flush_directory_guards(guards)
            fire(
                fault,
                "after_journal_successor_visible_before_predecessor_cleanup",
                phase=candidate_payload["phase"],
                generation=candidate_payload["generation"],
            )
            if windows_handle_identity(candidate_handle) != candidate_identity or read_descriptor(candidate_descriptor) != candidate_bytes:
                raise RecoveryRequired("published journal successor changed before predecessor cleanup")
            if windows_handle_identity(current_handle) != current_identity or read_descriptor(current_descriptor) != current_bytes:
                raise RecoveryRequired("journal predecessor changed at cleanup boundary")
            mark_bound_file_for_delete(current_handle)
            predecessor_delete_marked = True
        except BaseException:
            if candidate_descriptor is not None:
                os.close(candidate_descriptor)
                candidate_descriptor = None
            if current_descriptor is not None:
                os.close(current_descriptor)
                current_descriptor = None
            flush_directory_guards(guards)
            raise

        try:
            os.close(current_descriptor)
            current_descriptor = None
            flush_directory_guards(guards)
            if not predecessor_delete_marked or path_present(previous_path) or path_present(next_path):
                raise RecoveryRequired("journal predecessor cleanup did not complete exactly")
            if candidate_handle is None or candidate_identity is None:
                raise RecoveryRequired("published journal successor handle was lost")
            if windows_handle_identity(candidate_handle) != candidate_identity or read_descriptor(candidate_descriptor) != candidate_bytes:
                raise RecoveryRequired("published journal successor changed after predecessor cleanup")
            if file_ownership(journal_path) != candidate_identity:
                raise RecoveryRequired("final journal path is not the held successor identity")
        finally:
            if candidate_descriptor is not None:
                os.close(candidate_descriptor)
                candidate_descriptor = None
            if current_descriptor is not None:
                os.close(current_descriptor)
                current_descriptor = None
            flush_directory_guards(guards)
    return candidate_payload


def update_journal(output: Path, payload: dict[str, Any], fault: FaultHook | None = None) -> None:
    validate_journal_payload(payload)

    def prepare(current: dict[str, Any]) -> dict[str, Any]:
        if current["transaction_id"] != payload["transaction_id"]:
            raise RecoveryRequired("transaction_id changed while updating journal")
        if (
            current["generation"] != payload["generation"]
            or current["previous_payload_sha256"] != payload["previous_payload_sha256"]
        ):
            raise RecoveryRequired("caller journal lineage differs from the held current generation")
        for field in ("schema", "input_snapshot", "expected_outputs", "initial_targets"):
            if current[field] != payload[field]:
                raise RecoveryRequired(f"immutable journal field changed while updating: {field}")
        payload["generation"] = current["generation"] + 1
        payload["previous_payload_sha256"] = payload_digest(current)
        write_journal_candidate(output, payload)
        fire(
            fault,
            "before_journal_candidate_publish",
            phase=payload["phase"],
            generation=payload["generation"],
        )
        return payload

    persisted = rotate_current_journal_successor(
        output,
        prepare_candidate=prepare,
        fault=fault,
    )
    if persisted != payload:
        raise RecoveryRequired("persisted journal successor differs after identity-bound rotation")


def finish_predecessor_rotation(output: Path, successor_relative: Path) -> dict[str, Any]:
    """Finish PREVIOUS+NEXT or PREVIOUS+JOURNAL without overwriting either."""
    if successor_relative not in (JOURNAL_NEXT, JOURNAL):
        raise ValueError("unsupported journal successor artifact")
    output = plain_root(output)
    previous_path = plain_path(output, JOURNAL_PREVIOUS, True)
    successor_path = plain_path(output, successor_relative, True)
    journal_path = plain_path(output, JOURNAL)
    next_path = plain_path(output, JOURNAL_NEXT)
    if successor_relative == JOURNAL_NEXT and path_present(journal_path):
        raise RecoveryRequired("journal path coexists with predecessor + next recovery state")
    if successor_relative == JOURNAL and path_present(next_path):
        raise RecoveryRequired("journal next-file coexists with predecessor + published successor")

    previous_descriptor: int | None = None
    successor_descriptor: int | None = None
    previous_handle: int | None = None
    successor_handle: int | None = None
    previous_identity: dict[str, int] | None = None
    successor_identity: dict[str, int] | None = None
    previous_bytes = b""
    successor_bytes = b""
    predecessor_delete_marked = False

    with guarded_directory_chain(output, previous_path.parent) as guards:
        previous_descriptor, previous_handle = open_bound_descriptor(
            previous_path, writable=False, delete_access=True,
        )
        try:
            current_payload, previous_identity, previous_bytes = read_bound_journal(
                previous_descriptor,
                previous_handle,
                label="journal predecessor",
            )
            successor_descriptor, successor_handle = open_bound_descriptor(
                successor_path, writable=True, delete_access=True,
            )
            candidate_payload, successor_identity, successor_bytes = read_bound_journal(
                successor_descriptor,
                successor_handle,
                label="journal successor",
            )
            require_exact_successor(current_payload, candidate_payload)
            if successor_relative == JOURNAL_NEXT:
                if path_present(journal_path):
                    raise RecoveryRequired("journal leaf appeared before recovery publication")
                rename_bound_file(successor_handle, journal_path)
                os.fsync(successor_descriptor)
                if path_present(next_path):
                    raise RecoveryRequired("recovered successor remained at journal next path")
            if file_ownership(journal_path) != successor_identity:
                raise RecoveryRequired("recovered journal path identity mismatch")
            if windows_handle_identity(successor_handle) != successor_identity or read_descriptor(successor_descriptor) != successor_bytes:
                raise RecoveryRequired("recovered journal successor changed while held")
            if windows_handle_identity(previous_handle) != previous_identity or read_descriptor(previous_descriptor) != previous_bytes:
                raise RecoveryRequired("journal predecessor changed while held")
            flush_directory_guards(guards)
            mark_bound_file_for_delete(previous_handle)
            predecessor_delete_marked = True
        except BaseException:
            if successor_descriptor is not None:
                os.close(successor_descriptor)
                successor_descriptor = None
            if previous_descriptor is not None:
                os.close(previous_descriptor)
                previous_descriptor = None
            flush_directory_guards(guards)
            raise

        try:
            os.close(previous_descriptor)
            previous_descriptor = None
            flush_directory_guards(guards)
            if not predecessor_delete_marked or path_present(previous_path) or path_present(next_path):
                raise RecoveryRequired("recovery predecessor cleanup did not complete exactly")
            if successor_handle is None or successor_identity is None:
                raise RecoveryRequired("recovered successor handle was lost")
            if windows_handle_identity(successor_handle) != successor_identity or read_descriptor(successor_descriptor) != successor_bytes:
                raise RecoveryRequired("recovered successor changed after predecessor cleanup")
            if file_ownership(journal_path) != successor_identity:
                raise RecoveryRequired("final recovered journal path identity mismatch")
        finally:
            if successor_descriptor is not None:
                os.close(successor_descriptor)
                successor_descriptor = None
            if previous_descriptor is not None:
                os.close(previous_descriptor)
                previous_descriptor = None
            flush_directory_guards(guards)
    return candidate_payload


def promote_initial_journal_candidate(output: Path) -> dict[str, Any]:
    """Promote a generation-zero NEXT via its held identity, no replace."""
    output = plain_root(output)
    journal_path = plain_path(output, JOURNAL)
    next_path = plain_path(output, JOURNAL_NEXT, True)
    if path_present(journal_path) or path_present(output / JOURNAL_PREVIOUS):
        raise RecoveryRequired("initial journal candidate coexists with another generation artifact")
    descriptor: int | None = None
    with guarded_directory_chain(output, next_path.parent) as guards:
        descriptor, handle = open_bound_descriptor(next_path, writable=True, delete_access=True)
        try:
            candidate, candidate_identity, candidate_bytes = read_bound_journal(
                descriptor,
                handle,
                label="initial journal candidate",
            )
            if candidate["generation"] != 0 or candidate["previous_payload_sha256"] is not None:
                raise RecoveryRequired("orphan next-file is not an initial journal generation")
            if path_present(journal_path):
                raise RecoveryRequired("journal leaf appeared before initial no-replace publication")
            rename_bound_file(handle, journal_path)
            os.fsync(descriptor)
            if path_present(next_path):
                raise RecoveryRequired("initial next-file remained after publication")
            if windows_handle_identity(handle) != candidate_identity or read_descriptor(descriptor) != candidate_bytes:
                raise RecoveryRequired("initial published journal changed while held")
            if file_ownership(journal_path) != candidate_identity:
                raise RecoveryRequired("initial published journal path identity mismatch")
            flush_directory_guards(guards)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            flush_directory_guards(guards)
    return candidate


def promote_recovery_journal(output: Path) -> dict[str, Any]:
    journal = output / JOURNAL
    next_path = output / JOURNAL_NEXT
    previous = output / JOURNAL_PREVIOUS
    cleanup = output / JOURNAL_CLEANUP
    if path_present(output / TRANSACTION_LOCK):
        raise RecoveryRequired("unknown transaction lock cannot be auto-deleted")
    if path_present(cleanup):
        cleanup_payload = decode_journal(plain_path(output, JOURNAL_CLEANUP, True).read_bytes())
        if path_present(journal) or path_present(next_path) or path_present(previous):
            raise RecoveryRequired("cleanup marker coexists with another journal artifact")
        with guarded_directory_chain(output, cleanup.parent) as guards:
            durable_move(cleanup, journal, replace=False)
            flush_directory_guards(guards)
        if read_journal(output) != cleanup_payload:
            raise RecoveryRequired("cleanup marker promotion changed journal payload")
    has_journal = path_present(journal)
    has_next = path_present(next_path)
    has_previous = path_present(previous)
    if has_previous:
        if has_next and not has_journal:
            finish_predecessor_rotation(output, JOURNAL_NEXT)
        elif has_journal and not has_next:
            finish_predecessor_rotation(output, JOURNAL)
        else:
            raise RecoveryRequired("journal predecessor has an ambiguous successor artifact set")
    elif has_next:
        if has_journal:
            rotate_current_journal_successor(output)
        else:
            promote_initial_journal_candidate(output)
    return read_journal(output)


def remove_journal(output: Path, expected_payload: dict[str, Any], fault: FaultHook | None = None) -> None:
    validate_journal_payload(expected_payload)
    if (
        path_present(output / JOURNAL_NEXT)
        or path_present(output / JOURNAL_PREVIOUS)
        or path_present(output / JOURNAL_CLEANUP)
        or path_present(output / TRANSACTION_LOCK)
    ):
        raise RecoveryRequired("refusing journal cleanup while another transaction artifact exists")
    journal, cleanup = plain_path(output, JOURNAL, True), plain_path(output, JOURNAL_CLEANUP)
    expected_bytes = journal_envelope(expected_payload)
    cleanup_interrupt: BaseException | None = None
    with guarded_directory_chain(output, journal.parent) as outer_guards:
        with guarded_leaf_file(output, journal, writable=False, delete_access=True) as (_, descriptor, handle, _):
            identity = windows_handle_identity(handle)
            if read_descriptor(descriptor) != expected_bytes or decode_journal(expected_bytes) != expected_payload:
                raise RecoveryRequired("refusing to remove a journal whose exact payload changed")
            fire(
                fault,
                "after_journal_identity_validation_before_cleanup_move",
                transaction_id=expected_payload["transaction_id"],
            )
            if windows_handle_identity(handle) != identity or read_descriptor(descriptor) != expected_bytes:
                raise RecoveryRequired("journal identity/bytes changed before handle-bound cleanup move")
            if path_present(cleanup):
                raise RecoveryRequired("cleanup marker appeared before handle-bound journal move")
            rename_bound_file(handle, cleanup)
            identity_matches = windows_handle_identity(handle) == identity
            bytes_match = read_descriptor(descriptor) == expected_bytes
            if not identity_matches or not bytes_match:
                raise RecoveryRequired(
                    "handle-bound cleanup marker verification failed: "
                    f"identity_matches={identity_matches}, bytes_match={bytes_match}"
                )
            flush_directory_guards(outer_guards)
            try:
                fire(
                    fault,
                    "after_journal_cleanup_marker",
                    transaction_id=expected_payload["transaction_id"],
                )
            except BaseException as error:
                cleanup_interrupt = error
            if cleanup_interrupt is None:
                mark_bound_file_for_delete(handle)
        flush_directory_guards(outer_guards)
        if cleanup_interrupt is not None:
            if path_present(journal) or not path_present(cleanup):
                raise RecoveryRequired("interrupted cleanup marker did not persist at its fixed path") from cleanup_interrupt
            raise cleanup_interrupt
        if path_present(journal) or path_present(cleanup):
            raise RecoveryRequired("cleanup marker deletion did not complete")


def snapshot_manifest(snapshot: dict[Path, InputEntry]) -> dict[str, Any]:
    entries = [
        {
            "path": rel_text(relative), "bytes": item.size, "sha256": item.digest,
            "identity": list(item.identity),
        }
        for relative, item in sorted(snapshot.items())
    ]
    return {"count": len(entries), "entries": entries, "summary_sha256": sha256(canonical_json(entries).encode("utf-8"))}


def output_manifest(outputs: dict[Path, bytes]) -> list[dict[str, Any]]:
    return [
        {"path": rel_text(relative), "bytes": len(data), "sha256": sha256(data), "kind": "index_commit_marker" if relative == INDEX else "handoff"}
        for relative, data in outputs.items()
    ]


def compare_journal_contract(payload: dict[str, Any], snapshot: dict[Path, InputEntry], outputs: dict[Path, bytes]) -> None:
    if payload["input_snapshot"] != snapshot_manifest(snapshot):
        raise RecoveryRequired("current inputs do not match transaction snapshot")
    if payload["expected_outputs"] != output_manifest(outputs):
        raise RecoveryRequired("current expected outputs do not match transaction journal")


def owned(path: Path, record: dict[str, Any], wanted: bytes) -> bool:
    if not path_present(path) or not stat.S_ISREG(path.lstat().st_mode) or is_reparse(path):
        return False
    before = file_ownership(path)
    data = path.read_bytes()
    after = file_ownership(path)
    return before == after == record["identity"] and len(data) == record["bytes"] and sha256(data) == record["sha256"] and data == wanted


def journal_record(items: list[dict[str, Any]], relative: Path) -> dict[str, Any] | None:
    text = rel_text(relative)
    return next((item for item in items if item["path"] == text), None)


def initial_record(journal: dict[str, Any], relative: Path) -> dict[str, Any]:
    record = journal_record(journal["initial_targets"], relative)
    if record is None:
        raise RecoveryRequired(f"journal lacks initial target binding: {rel_text(relative)}")
    return record


def audit_transaction_targets(
    output: Path,
    outputs: dict[Path, bytes],
    journal: dict[str, Any],
    *,
    adopt_pending: bool,
) -> None:
    validate_journal_payload(journal)
    if journal["expected_outputs"] != output_manifest(outputs):
        raise RecoveryRequired("current expected outputs do not match transaction journal")
    created = {item["path"]: item for item in journal["created"]}
    adopted = {item["path"]: item for item in journal["adopted"]}
    pending = journal["pending_create"]
    for relative, wanted in outputs.items():
        text = rel_text(relative)
        target = plain_path(output, relative)
        initial = initial_record(journal, relative)
        record = created.get(text) or adopted.get(text)
        if initial["state"] == "preexisting":
            if record is not None or (pending is not None and pending["path"] == text) or not owned(target, initial, wanted):
                raise RecoveryRequired(f"preexisting target identity/bytes changed: {text}")
        elif record is not None:
            if not owned(target, record, wanted):
                raise RecoveryRequired(f"recorded target identity/bytes changed: {text}")
        elif pending is not None and pending["path"] == text:
            if path_present(target):
                if not owned(target, pending, wanted):
                    raise RecoveryRequired(f"pending target has an unexpected identity/bytes: {text}")
                if not adopt_pending:
                    raise RecoveryRequired(f"pending target is ambiguous and requires explicit finish recovery: {text}")
                journal["adopted"].append(pending)
                journal["pending_create"] = None
                update_journal(output, journal)
                adopted[text] = pending
                pending = None
            else:
                journal["pending_create"] = None
                update_journal(output, journal)
                pending = None
        elif path_present(target):
            raise RecoveryRequired(f"target appeared after missing preflight: {text}")


def fire(fault: FaultHook | None, point: str, **context: Any) -> None:
    if fault is not None:
        fault(point, context)


def transaction_link(
    stage: Path,
    output: Path,
    relative: Path,
    wanted: bytes,
    journal: dict[str, Any],
    fault: FaultHook | None,
    sequence: int,
) -> bool:
    target = plain_path(output, relative)
    initial = initial_record(journal, relative)
    created_record = journal_record(journal["created"], relative)
    adopted_record = journal_record(journal["adopted"], relative)
    pending_record = journal["pending_create"] if journal["pending_create"] is not None and journal["pending_create"]["path"] == rel_text(relative) else None
    if path_present(target):
        record = initial if initial["state"] == "preexisting" else created_record or adopted_record
        if record is None or pending_record is not None or not owned(plain_path(output, relative, True), record, wanted):
            raise RecoveryRequired(f"existing target is not bound to the transaction state: {rel_text(relative)}")
        return False
    if initial["state"] == "preexisting" or created_record is not None or adopted_record is not None:
        raise RecoveryRequired(f"journal-bound target disappeared: {rel_text(relative)}")
    if pending_record is not None:
        journal["pending_create"] = None
        update_journal(output, journal, fault)
    source = plain_path(stage, relative, True)
    with guarded_directory_chain(stage, source.parent) as source_guards:
        source = plain_path(stage, relative, True)
        with ensure_guarded_directory(output, target.parent) as target_guards:
            target = plain_path(output, relative)
            if path_present(target):
                raise RecoveryRequired(f"target appeared before transaction intent: {rel_text(relative)}")
            pending = {
                "path": rel_text(relative), "bytes": len(wanted), "sha256": sha256(wanted),
                "identity": file_ownership(source),
            }
            journal["pending_create"] = pending
            journal["phase"] = "publishing_index" if relative == INDEX else "publishing_handoffs"
            update_journal(output, journal, fault)
            if path_present(target) or not owned(source, pending, wanted):
                raise RecoveryRequired(f"source or target changed before durable move: {rel_text(relative)}")
            fire(fault, "before_link", path=rel_text(relative), sequence=sequence)
            if path_present(target) or not owned(source, pending, wanted):
                raise RecoveryRequired(f"source or target changed at durable-move boundary: {rel_text(relative)}")
            durable_move(source, target, replace=False)
            with guarded_leaf_file(output, target, writable=True, delete_access=False) as (_, descriptor, handle, _):
                fire(fault, "after_move_before_created_journal", path=rel_text(relative), sequence=sequence)
                if not bound_file_matches(descriptor, handle, pending, wanted):
                    raise RuntimeError(f"new durable target identity/bytes mismatch: {target}")
                os.fsync(descriptor)
                flush_directory_guards(target_guards)
                flush_directory_guards(source_guards)
                created = {**pending, "identity": windows_handle_identity(handle)}
                journal["created"].append(created)
                journal["pending_create"] = None
                update_journal(output, journal, fault)
                fire(fault, "after_link", path=rel_text(relative), sequence=sequence)
    return True


def verify_subset(root: Path, outputs: dict[Path, bytes], paths: list[Path]) -> None:
    verify_tree(root, {path: outputs[path] for path in paths})


def preflight_targets(output: Path, outputs: dict[Path, bytes]) -> tuple[int, list[Path], list[dict[str, Any]]]:
    existing, missing, initial = 0, [], []
    for relative, wanted in outputs.items():
        target = plain_path(output, relative)
        if path_present(target):
            target = plain_path(output, relative, True)
            before = file_ownership(target)
            data = target.read_bytes()
            after = file_ownership(target)
            if before != after or data != wanted:
                raise FileExistsError(f"immutable target differs: {target}")
            existing += 1
            initial.append({
                "path": rel_text(relative), "state": "preexisting", "bytes": len(data),
                "sha256": sha256(data), "identity": after,
            })
        else:
            missing.append(relative)
            initial.append({"path": rel_text(relative), "state": "missing", "bytes": None, "sha256": None, "identity": None})
    if path_present(output / INDEX) and missing:
        raise RecoveryRequired("index commit marker exists while package targets are missing")
    return existing, missing, initial


def rollback_transaction(
    output: Path,
    outputs: dict[Path, bytes],
    fault: FaultHook | None = None,
) -> dict[str, int]:
    journal = promote_recovery_journal(output)
    pending = journal["pending_create"]
    if pending is not None:
        pending_target = plain_path(output, Path(pending["path"]))
        if path_present(pending_target):
            raise RecoveryRequired(f"ambiguous pending target retained for explicit finish: {pending['path']}")
        journal["pending_create"] = None
        update_journal(output, journal, fault)
    if any(item["path"] == rel_text(INDEX) for item in journal["adopted"]):
        raise RecoveryRequired("adopted index cannot be rolled back; explicit finish is required")
    removed = 0
    for record in list(reversed(journal["created"])):
        relative_text = record["path"]
        relative = Path(relative_text)
        target = plain_path(output, relative)
        if path_present(target):
            wanted = outputs.get(relative)
            if wanted is None:
                raise RecoveryRequired(f"refusing to delete target not provably owned by transaction: {relative_text}")
            durable_unlink_owned(output, target, record, wanted, fault)
            removed += 1
        journal["created"].remove(record)
        update_journal(output, journal, fault)
    if path_present(output / INDEX):
        raise RecoveryRequired("rollback left an unowned index commit marker; journal retained")
    journal["phase"] = "rolled_back"
    update_journal(output, journal, fault)
    remove_journal(output, journal, fault)
    return {"removed_owned_files": removed}


def complete_transaction(
    source: Path,
    output: Path,
    stage: Path,
    snapshot: dict[Path, InputEntry],
    outputs: dict[Path, bytes],
    journal: dict[str, Any],
    fault: FaultHook | None,
) -> dict[str, int]:
    handoffs = [path for path in outputs if path != INDEX]
    audit_transaction_targets(output, outputs, journal, adopt_pending=False)
    created_count = 0
    existing_count = 0
    for sequence, relative in enumerate(handoffs, 1):
        if transaction_link(stage, output, relative, outputs[relative], journal, fault, sequence):
            created_count += 1
        else:
            existing_count += 1
        if sequence == 1:
            fire(fault, "after_first_handoff", transaction_id=journal["transaction_id"])
    journal["phase"] = "handoffs_published"
    update_journal(output, journal, fault)
    fire(fault, "after_all_handoffs_before_index", transaction_id=journal["transaction_id"])

    current = capture(source)
    compare_snapshots(snapshot, current)
    current_outputs, _, _ = expected(current)
    compare_outputs(outputs, current_outputs)
    audit_transaction_targets(output, outputs, journal, adopt_pending=False)
    verify_subset(output, outputs, handoffs)
    journal["phase"] = "ready_to_commit"
    update_journal(output, journal, fault)
    persisted = read_journal(output)
    if persisted != journal or persisted["phase"] != "ready_to_commit":
        raise RecoveryRequired("ready_to_commit journal did not persist exactly")
    fire(fault, "ready_to_commit", transaction_id=journal["transaction_id"])

    if transaction_link(stage, output, INDEX, outputs[INDEX], journal, fault, len(handoffs) + 1):
        created_count += 1
    else:
        existing_count += 1
    journal["phase"] = "index_visible"
    update_journal(output, journal, fault)
    fire(fault, "after_index_visible", transaction_id=journal["transaction_id"])

    post = capture(source)
    compare_snapshots(snapshot, post)
    post_outputs, _, _ = expected(post)
    compare_outputs(outputs, post_outputs)
    audit_transaction_targets(output, outputs, journal, adopt_pending=False)
    verify_tree(output, outputs)
    journal["phase"] = "committed_postcheck_passed"
    update_journal(output, journal, fault)
    if read_journal(output) != journal:
        raise RecoveryRequired("committed journal did not persist exactly")
    audit_transaction_targets(output, outputs, journal, adopt_pending=False)
    fire(fault, "before_journal_cleanup", transaction_id=journal["transaction_id"])
    remove_journal(output, journal, fault)
    require_clean_gate(output, require_commit_marker=True)
    verify_tree(output, outputs)
    return {"created": created_count, "verified_existing_without_rewrite": existing_count}


def new_journal(
    snapshot: dict[Path, InputEntry],
    outputs: dict[Path, bytes],
    initial_targets: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": "task8-step1-publish-transaction-v01",
        "transaction_id": uuid.uuid4().hex,
        "generation": 0,
        "previous_payload_sha256": None,
        "phase": "prepared",
        "input_snapshot": snapshot_manifest(snapshot),
        "expected_outputs": output_manifest(outputs),
        "initial_targets": initial_targets,
        "created": [],
        "adopted": [],
        "pending_create": None,
    }


def _build_release(
    source: Path,
    output: Path,
    fault: FaultHook | None = None,
) -> tuple[dict[Path, bytes], list[dict[str, Any]], str, dict[str, int], int]:
    source, output = plain_root(source), plain_root(output)
    require_clean_gate(output, require_commit_marker=False)
    first_snapshot = capture(source)
    first_outputs, entries, batch_digest = expected(first_snapshot)
    existing, missing, initial_targets = preflight_targets(output, first_outputs)
    if not missing:
        verify_tree(output, first_outputs)
        second_snapshot = capture(source)
        compare_snapshots(first_snapshot, second_snapshot)
        second_outputs, _, _ = expected(second_snapshot)
        compare_outputs(first_outputs, second_outputs)
        verify_tree(output, second_outputs)
        fire(fault, "before_noop_final_gate")
        require_clean_gate(output, require_commit_marker=True)
        return first_outputs, entries, batch_digest, {"created": 0, "verified_existing_without_rewrite": existing}, len(first_snapshot)

    with tempfile.TemporaryDirectory(prefix=".task8-step1-stage-", dir=output) as temp:
        stage = plain_root(Path(temp))
        write_stage(stage, first_outputs, fault)
        verify_tree(stage, first_outputs)
        second_snapshot = capture(source)
        compare_snapshots(first_snapshot, second_snapshot)
        second_outputs, second_entries, second_digest = expected(second_snapshot)
        compare_outputs(first_outputs, second_outputs)
        if entries != second_entries or batch_digest != second_digest:
            raise RuntimeError("second expected output metadata differs")
        journal = new_journal(first_snapshot, first_outputs, initial_targets)
        journal_parent = plain_path(output, JOURNAL).parent
        with ensure_guarded_directory(output, journal_parent):
            atomic_create_journal(output, journal, fault)
            try:
                publication = complete_transaction(source, output, stage, first_snapshot, first_outputs, journal, fault)
            except Exception as error:
                try:
                    rollback_transaction(output, first_outputs, fault=fault)
                except Exception as cleanup_error:
                    raise RecoveryRequired(f"transaction failed and rollback requires recovery: {cleanup_error}") from error
                raise
    return first_outputs, entries, batch_digest, publication, len(first_snapshot)


def _verify_release(source: Path, output: Path) -> tuple[dict[Path, bytes], list[dict[str, Any]], str, int]:
    source, output = plain_root(source), plain_root(output)
    require_clean_gate(output, require_commit_marker=True)
    first_snapshot = capture(source)
    first_outputs, entries, batch_digest = expected(first_snapshot)
    verify_tree(output, first_outputs)
    second_snapshot = capture(source)
    compare_snapshots(first_snapshot, second_snapshot)
    second_outputs, second_entries, second_digest = expected(second_snapshot)
    compare_outputs(first_outputs, second_outputs)
    if entries != second_entries or batch_digest != second_digest:
        raise RuntimeError("second expected output metadata differs")
    verify_tree(output, second_outputs)
    require_clean_gate(output, require_commit_marker=True)
    return first_outputs, entries, batch_digest, len(first_snapshot)


def assert_consumable_review_package(source: Path, output: Path) -> dict[str, Any]:
    outputs, entries, batch_digest, count = verify_release(source, output)
    return {"input_count": count, "output_count": len(outputs), "entry_count": len(entries), "batch_payload_sha256": batch_digest}


def inspect_transaction(output: Path) -> dict[str, Any]:
    output = plain_root(output)
    artifacts = [rel_text(path) for path in transaction_artifacts(output)]
    result: dict[str, Any] = {
        "status": "recovery_required" if artifacts else "clean",
        "transaction_artifacts": artifacts,
        "index_commit_marker_visible": (output / INDEX).is_file(),
    }
    journal_artifact = next(
        (
            relative
            for relative in (JOURNAL, JOURNAL_NEXT, JOURNAL_PREVIOUS, JOURNAL_CLEANUP)
            if (output / relative).is_file()
        ),
        None,
    )
    if journal_artifact is not None:
        try:
            payload = decode_journal(plain_path(output, journal_artifact, True).read_bytes())
            result.update({
                "journal_valid": True,
                "journal_artifact": rel_text(journal_artifact),
                "transaction_id": payload["transaction_id"],
                "phase": payload["phase"],
                "generation": payload["generation"],
                "created_count": len(payload["created"]),
                "adopted_count": len(payload["adopted"]),
                "pending_create": payload["pending_create"],
            })
        except Exception as error:
            result.update({"journal_valid": False, "journal_error": str(error)})
    return result


def _recover_finish(source: Path, output: Path) -> tuple[dict[Path, bytes], list[dict[str, Any]], str, dict[str, int], int]:
    source, output = plain_root(source), plain_root(output)
    journal = promote_recovery_journal(output)
    current = capture(source)
    outputs, entries, batch_digest = expected(current)
    compare_journal_contract(journal, current, outputs)
    audit_transaction_targets(output, outputs, journal, adopt_pending=True)
    with tempfile.TemporaryDirectory(prefix=".task8-step1-recovery-", dir=output) as temp:
        stage = plain_root(Path(temp))
        write_stage(stage, outputs)
        verify_tree(stage, outputs)
        publication = complete_transaction(source, output, stage, current, outputs, journal, None)
    _verify_release(source, output)
    return outputs, entries, batch_digest, publication, len(current)


def _recover_rollback(
    source: Path,
    output: Path,
    fault: FaultHook | None = None,
) -> dict[str, Any]:
    source, output = plain_root(source), plain_root(output)
    journal = promote_recovery_journal(output)
    current = capture(source)
    outputs, _, _ = expected(current)
    expected_from_journal = {Path(item["path"]): item for item in journal["expected_outputs"]}
    if set(expected_from_journal) != set(outputs):
        raise RecoveryRequired("journal output path set does not match current contract")
    # Rollback does not require current input hashes to match, but deletion remains identity/hash-bound.
    journal_outputs: dict[Path, bytes] = {}
    for relative, data in outputs.items():
        record = expected_from_journal[relative]
        if len(data) == record["bytes"] and sha256(data) == record["sha256"]:
            journal_outputs[relative] = data
        else:
            target = output / relative
            if target.exists():
                journal_outputs[relative] = target.read_bytes()
            else:
                journal_outputs[relative] = b""
    rollback_result = rollback_transaction(output, journal_outputs, fault)
    rollback_result.update({"status": "rolled_back", "index_commit_marker_visible": (output / INDEX).exists()})
    return rollback_result


def _prove_repro(source: Path, live: Path) -> tuple[dict[str, Any], list[dict[str, Any]], str, int, dict[Path, bytes]]:
    live_outputs, entries, batch_digest, count = _verify_release(source, live)
    with tempfile.TemporaryDirectory(prefix="task8-step1-a-") as a, tempfile.TemporaryDirectory(prefix="task8-step1-b-") as b:
        outputs_a, entries_a, digest_a, _, count_a = build_release(source, Path(a))
        outputs_b, entries_b, digest_b, _, count_b = build_release(source, Path(b))
        verify_release(source, Path(a))
        verify_release(source, Path(b))
        compare_outputs(outputs_a, outputs_b)
        compare_outputs(outputs_a, live_outputs)
        if entries != entries_a or entries != entries_b or batch_digest != digest_a or batch_digest != digest_b:
            raise RuntimeError("rebuild metadata differs")
        result = {
            "status": "PASS", "generated_files": len(live_outputs),
            "rebuild_a_vs_b_byte_identical": True, "rebuilds_vs_live_byte_identical": True,
            "mismatches": [], "input_snapshot_files_each_run": [count, count_a, count_b],
            "journal_absent_after_each_build": True, "index_commit_marker_verified": True,
        }
    return result, entries, batch_digest, count, live_outputs


def build_release(
    source: Path,
    output: Path,
    fault: FaultHook | None = None,
) -> tuple[dict[Path, bytes], list[dict[str, Any]], str, dict[str, int], int]:
    output = plain_root(output)
    with transaction_mutex(output):
        return _build_release(source, output, fault)


def verify_release(source: Path, output: Path) -> tuple[dict[Path, bytes], list[dict[str, Any]], str, int]:
    output = plain_root(output)
    with transaction_mutex(output):
        return _verify_release(source, output)


def recover_finish(source: Path, output: Path) -> tuple[dict[Path, bytes], list[dict[str, Any]], str, dict[str, int], int]:
    output = plain_root(output)
    with transaction_mutex(output):
        journal_parent = plain_path(output, JOURNAL).parent
        with guarded_directory_chain(output, journal_parent):
            return _recover_finish(source, output)


def recover_rollback(
    source: Path,
    output: Path,
    fault: FaultHook | None = None,
) -> dict[str, Any]:
    output = plain_root(output)
    with transaction_mutex(output):
        journal_parent = plain_path(output, JOURNAL).parent
        with guarded_directory_chain(output, journal_parent):
            return _recover_rollback(source, output, fault)


def prove_repro(source: Path, live: Path) -> tuple[dict[str, Any], list[dict[str, Any]], str, int, dict[Path, bytes]]:
    live = plain_root(live)
    with transaction_mutex(live):
        return _prove_repro(source, live)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--mode", choices=("build", "verify", "prove-repro", "inspect", "recover"), default="verify")
    parser.add_argument("--recover-action", choices=("finish", "rollback"))
    args = parser.parse_args()
    default_root = Path(__file__).resolve().parents[3]
    source = (args.source_root or default_root).resolve()
    output = (args.output_root or source).resolve()
    if args.mode == "inspect":
        print(json.dumps(inspect_transaction(output), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.mode == "recover":
        if args.recover_action == "finish":
            outputs, entries, batch_digest, publication, count = recover_finish(source, output)
            result: dict[str, Any] = {"status": "PASS", "recovery": "finished", "publication": publication}
        elif args.recover_action == "rollback":
            print(json.dumps(recover_rollback(source, output), ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        else:
            parser.error("--mode recover requires --recover-action finish|rollback")
    elif args.mode == "build":
        outputs, entries, batch_digest, publication, count = build_release(source, output)
        result = {"status": "PASS", "generated_files": len(outputs), "publication": publication}
    elif args.mode == "verify":
        outputs, entries, batch_digest, count = verify_release(source, output)
        result = {"status": "PASS", "verified_files": len(outputs), "commit_marker_verified": True}
    else:
        result, entries, batch_digest, count, outputs = prove_repro(source, output)
    result.update({
        "content_ids": IDS, "states": ["research_pending"] * 10, "input_snapshot_files": count,
        "artifact_bindings_per_handoff": 12, "qa_context_bindings_per_handoff": 6,
        "handoff_sha256": {item["content_id"]: item["handoff_sha256"] for item in entries},
        "handoff_file_sha256": {item["content_id"]: item["handoff_file_sha256"] for item in entries},
        "batch_payload_sha256": batch_digest, "index_file_sha256": sha256(outputs[INDEX]),
        "transaction_journal_absent": not transaction_artifacts(output),
    })
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
