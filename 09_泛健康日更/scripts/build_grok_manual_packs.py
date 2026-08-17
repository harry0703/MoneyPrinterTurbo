from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image


SUPPORTED_CONTENT_ID = "HC20260810-001"
VERSION = "v01"
EXPECTED_SHOTS = [f"S{number:02d}" for number in range(1, 11)]
DETERMINISTIC_SHOTS = {"S03", "S08", "S10"}
REPARSE_POINT_FLAG = 0x400


class ManualPackError(RuntimeError):
    """Raised when a manual pack cannot be built or verified safely."""


PROMPT_ACTIONS: dict[str, tuple[str, str]] = {
    "S01": (
        "餐后坐在藤编餐椅上的45岁中国女性只完成一次轻靠椅背并缓慢自然眨眼的连贯小动作，手部保持原位，镜头只做极轻微推近",
        "The seated 45-year-old Chinese woman makes one connected, low-amplitude action: a light settle back into the chair with one slow natural blink; keep her hands in place, with an extremely subtle camera push-in",
    ),
    "S02": (
        "餐桌旁的同一位女性只将视线缓慢抬向左侧窗光，手保持在已经离开餐盘的位置，餐盘、椅子与侧后方构图均不动",
        "The same woman beside the dining table slowly raises only her gaze toward the window light on the left; keep her hand in its already-away-from-the-plate position, and keep the plate, chair, and rear-side framing still",
    ),
    "S03": (
        "后期将左侧夜间暗光和右侧早晨窗光做一次缓慢交叉淡化，中央深青分隔、灯、窗帘和家具保持原位",
        "In post-production, make one slow crossfade between the dark night side and the morning window-light side; keep the central teal divider, lamps, curtains, and furniture fixed",
    ),
    "S04": (
        "餐桌前的同一位女性从当前首帧手部位置继续完成放勺的最后阶段：指尖轻触勺柄，勺子只做极小幅落稳，随即手轻轻收回，不重新拿起餐具；剩余菜品和餐盘不动，俯侧45度近景固定",
        "From the current first-frame hand position, the same woman completes only the final phase of setting down and releasing the spoon: fingertips lightly contact the handle, the spoon makes a tiny settling motion, then the hand gently withdraws without picking the utensil up again; keep the remaining greens and plate still, with a fixed 45-degree high oblique close view",
    ),
    "S05": (
        "同一位女性人物已经站起，只沿当前方向从餐区朝客厅迈一小步，镜头轻微横移跟随；米色开衫、蓝色上衣、深蓝长裤与家具位置不变",
        "The same woman is already standing and takes only one small step in the current direction from the dining area toward the living room, with a slight lateral camera follow; preserve her beige cardigan, blue top, navy trousers, and all furniture positions",
    ),
    "S06": (
        "越肩视角中的同一位女性只用拇指依次轻点黑屏上三个空白位置，手机四角、纯黑屏幕、另一只手和木桌不动",
        "From the over-shoulder view, the same woman makes one restrained sequence of three light thumb taps on blank positions of the black screen; keep all four phone corners, the pure black screen, other hand, and wooden table fixed",
    ),
    "S07": (
        "手机已放在桌面，同一位女性只完成一次自然呼吸，闭眼、双手和坐姿保持稳定，镜头只做轻微后拉",
        "With the phone already resting on the table, the same woman makes one natural breath only; keep her eyes closed, hands and seated posture stable, with a very slight camera pull-back",
    ),
    "S08": (
        "后期让深青、浅桃和青绿三块日光场景依次各做一次轻微亮度提示，三个坐姿剪影、拱形板和植物保持不动",
        "In post-production, give the deep-teal, peach, and green daylight panels one gentle sequential brightness cue; keep the three seated silhouettes, arch panels, and plants motionless",
    ),
    "S09": (
        "在当前已把车钥匙放入盘中的状态下，钥匙保持在置物盘中，同一位女性朝沙发方向只迈一小步，镜头先固定，后轻微跟随；青绿柜体、沙发和行走方向不变",
        "With the car key already placed in the tray, keep the key in the tray while the same woman takes only one small step toward the sofa; keep the camera fixed first, then follow slightly, preserving the teal cabinet, sofa, and travel direction",
    ),
    "S10": (
        "后期让暖米白结束板上的三枚青绿圆点按从下到上的顺序各淡入一次，浅桃拱形、植物影子和背景完全不动",
        "In post-production, fade in each of the three teal dots once from bottom to top on the warm off-white end board; keep the peach arches, plant shadow, and background completely still",
    ),
}


SHOT_SEMANTIC_CONTRACTS: dict[str, dict[str, Any]] = {
    "S01": {
        "storyboard": {
            "人物动作": ("短暂眨眼",),
            "相机": ("85mm中近景固定", "缓慢推近"),
            "ai_source_layer": ("自然眨眼", "轻靠椅背"),
        },
        "prompt_zh": ("轻靠椅背", "缓慢自然眨眼", "极轻微推近"),
    },
    "S02": {
        "storyboard": {
            "人物动作": ("抬眼看向窗光", "手离开餐盘"),
            "相机": ("侧后方中景",),
            "ai_source_layer": ("只做抬眼动作",),
        },
        "prompt_zh": ("视线缓慢抬向左侧窗光", "手保持在已经离开餐盘的位置"),
    },
    "S03": {
        "storyboard": {
            "人物动作": ("夜晚关灯", "早晨拉帘"),
            "相机": ("无相机运动",),
            "ai_source_layer": ("无AI动态源",),
        },
        "prompt_zh": ("夜间暗光", "早晨窗光", "交叉淡化"),
    },
    "S04": {
        "storyboard": {
            "人物动作": ("放慢一口后停下餐具",),
            "相机": ("俯侧45度近景", "餐具与手同框"),
            "ai_source_layer": ("放下餐具一个动作",),
        },
        "prompt_zh": ("放勺的最后阶段", "勺子只做极小幅落稳", "手轻轻收回", "俯侧45度近景固定"),
    },
    "S05": {
        "storyboard": {
            "人物动作": ("从餐椅起身", "朝客厅方向迈一步"),
            "相机": ("全身中景", "小幅横移跟随"),
            "ai_source_layer": ("起身并迈一步", "方向固定"),
        },
        "prompt_zh": ("人物已经站起", "朝客厅迈一小步", "镜头轻微横移跟随"),
    },
    "S06": {
        "storyboard": {
            "人物动作": ("拇指点按三个空白位置",),
            "相机": ("越肩近景固定",),
            "ai_source_layer": ("黑屏手机", "单手点按", "不生成界面"),
        },
        "prompt_zh": ("拇指依次轻点", "黑屏上三个空白位置", "手机四角"),
    },
    "S07": {
        "storyboard": {
            "人物动作": ("放下手机", "闭眼感受片刻"),
            "相机": ("正面中近景", "轻微后拉"),
            "ai_source_layer": ("放下手机", "一次自然呼吸"),
        },
        "prompt_zh": ("手机已放在桌面", "一次自然呼吸", "轻微后拉"),
    },
    "S08": {
        "storyboard": {
            "人物动作": ("三次不同日光色块并列", "人物剪影保持一致"),
            "相机": ("无相机运动",),
            "ai_source_layer": ("无AI动态源", "纯色日光", "人物剪影"),
        },
        "prompt_zh": ("三块日光场景", "依次各做一次轻微亮度提示"),
    },
    "S09": {
        "storyboard": {
            "人物动作": ("把车钥匙放回置物盘", "走向沙发"),
            "相机": ("腰部中景", "先定后短跟"),
            "ai_source_layer": ("放下钥匙后离开一步",),
        },
        "prompt_zh": ("钥匙保持在置物盘中", "朝沙发方向只迈一小步", "镜头先固定，后轻微跟随"),
    },
    "S10": {
        "storyboard": {
            "人物动作": ("三枚青绿圆点依次出现",),
            "相机": ("无相机运动",),
            "ai_source_layer": ("无AI动态源", "纯确定性结束板"),
        },
        "prompt_zh": ("三枚青绿圆点", "从下到上的顺序各淡入一次"),
    },
}


VISUAL_REVIEW_NOTES = {
    "S01": "暖光餐桌旁坐姿人物，闭眼、手与餐盘关系清楚",
    "S02": "同一人物侧后坐姿，手已离盘，视线面向窗光",
    "S03": "夜间暗光与早晨窗光双板，中央分隔稳定",
    "S04": "餐具已在桌面，手在勺子附近，支持放勺最后落稳阶段",
    "S05": "人物已站立行走，从餐区朝客厅的方向清楚",
    "S06": "越肩黑屏手机，四角完整，拇指点按位置清楚",
    "S07": "手机已平放桌面，人物闭眼静坐",
    "S08": "三块色板与三个一致坐姿剪影，适合确定性亮度提示",
    "S09": "车钥匙在置物盘中，人物朝沙发方向处于离开姿态",
    "S10": "暖米白结束板与三枚青绿圆点，无文字",
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _as_posix(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _require_regular_file(path: Path, label: str) -> None:
    _assert_no_reparse_ancestors(path)
    if not path.is_file() or path.is_symlink():
        raise ManualPackError(f"missing or unsafe {label}: {path}")
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    if attributes & REPARSE_POINT_FLAG:
        raise ManualPackError(f"reparse point forbidden for {label}: {path}")


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _inspect_lexical_chain(path: Path) -> None:
    current = path
    while True:
        if os.path.lexists(current):
            attributes = getattr(current.lstat(), "st_file_attributes", 0)
            if current.is_symlink() or attributes & REPARSE_POINT_FLAG:
                raise ManualPackError(f"reparse path forbidden: {current}")
        if current.parent == current:
            break
        current = current.parent


def _assert_no_reparse_ancestors(path: Path) -> Path:
    lexical = _lexical_absolute(path)
    _inspect_lexical_chain(lexical)
    resolved = lexical.resolve(strict=False)
    _inspect_lexical_chain(resolved)
    return resolved


def _require_within(path: Path, parent: Path, label: str) -> None:
    try:
        path.relative_to(parent)
    except ValueError as exc:
        raise ManualPackError(f"{label} escapes required root: {path}") from exc


def _load_json(path: Path, label: str) -> dict[str, Any]:
    _require_regular_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManualPackError(f"invalid {label}: {path}") from exc
    if not isinstance(value, dict):
        raise ManualPackError(f"{label} must be an object: {path}")
    return value


def _parse_storyboard(path: Path) -> list[dict[str, str]]:
    _require_regular_file(path, "storyboard")
    lines = path.read_text(encoding="utf-8").splitlines()
    header_index = next(
        (index for index, line in enumerate(lines) if line.startswith("|") and "镜号" in line),
        None,
    )
    if header_index is None or header_index + 1 >= len(lines):
        raise ManualPackError("storyboard shot table not found")

    def cells(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip().strip("|").split("|")]

    headers = cells(lines[header_index])
    required = {
        "镜号",
        "起点",
        "终点",
        "画面目的",
        "人物动作",
        "相机",
        "ai_source_layer",
        "禁物",
        "复用状态",
        "minimum_grok_source_seconds",
        "final_visual_seconds",
        "extension_strategy",
    }
    if not required <= set(headers):
        missing = sorted(required - set(headers))
        raise ManualPackError(f"storyboard missing columns: {missing}")

    separator = cells(lines[header_index + 1])
    if len(separator) != len(headers) or not all(re.fullmatch(r":?-{3,}:?", item) for item in separator):
        raise ManualPackError("invalid storyboard table separator")

    rows: list[dict[str, str]] = []
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            break
        values = cells(line)
        if len(values) != len(headers):
            raise ManualPackError("storyboard row width does not match headers")
        rows.append(dict(zip(headers, values, strict=True)))
    if [row["镜号"] for row in rows] != EXPECTED_SHOTS:
        raise ManualPackError("storyboard must contain exactly S01-S10 in order")
    return rows


def _validate_semantic_contracts(
    storyboard_rows: list[dict[str, str]], prompts: dict[str, str]
) -> None:
    rows_by_shot = {row["镜号"]: row for row in storyboard_rows}
    if set(rows_by_shot) != set(EXPECTED_SHOTS) or set(prompts) != set(EXPECTED_SHOTS):
        raise ManualPackError("semantic contract requires exact S01-S10 storyboard and prompt sets")
    if set(SHOT_SEMANTIC_CONTRACTS) != set(EXPECTED_SHOTS):
        raise ManualPackError("semantic contract mapping must cover exact S01-S10")

    for shot in EXPECTED_SHOTS:
        contract = SHOT_SEMANTIC_CONTRACTS[shot]
        row = rows_by_shot[shot]
        for column, fragments in contract["storyboard"].items():
            value = row[column]
            for fragment in fragments:
                if fragment not in value:
                    raise ManualPackError(
                        f"semantic contract mismatch: {shot} storyboard {column} missing {fragment!r}"
                    )
        for fragment in contract["prompt_zh"]:
            if fragment not in prompts[shot]:
                raise ManualPackError(
                    f"semantic contract mismatch: {shot} prompt missing {fragment!r}"
                )


def _validate_batch(repo_root: Path, content_id: str) -> dict[str, Any]:
    batch_root = _assert_no_reparse_ancestors(
        repo_root / "09_泛健康日更" / "data" / "01_一般生活方式50集" / "batch-01"
    )
    _require_within(batch_root, repo_root, "batch root")
    active_path = batch_root / "active-batch.json"
    ref_path = batch_root / "current-batch-ref.json"
    active = _load_json(active_path, "active batch")
    reference = _load_json(ref_path, "current batch reference")
    if reference.get("active_sha256") != _sha256_file(active_path):
        raise ManualPackError("current batch reference does not bind active batch bytes")
    snapshot_value = reference.get("path")
    if not isinstance(snapshot_value, str) or Path(snapshot_value).is_absolute():
        raise ManualPackError("invalid batch snapshot path")
    snapshot_path = batch_root / Path(snapshot_value)
    snapshot_resolved = _assert_no_reparse_ancestors(snapshot_path)
    _require_within(snapshot_resolved, batch_root, "batch snapshot")
    snapshot_path = snapshot_resolved
    _require_regular_file(snapshot_path, "batch snapshot")
    if reference.get("sha256") != _sha256_file(snapshot_path):
        raise ManualPackError("current batch reference does not bind snapshot bytes")
    if reference.get("batch_id") != active.get("batch_id"):
        raise ManualPackError("batch identity mismatch")
    topics = active.get("topics")
    if not isinstance(topics, list):
        raise ManualPackError("active batch topics are missing")
    matches = [topic for topic in topics if isinstance(topic, dict) and topic.get("content_id") == content_id]
    if len(matches) != 1 or matches[0].get("state") != "production":
        raise ManualPackError(f"active topic is not production: {content_id}")
    return {
        "batch_id": active["batch_id"],
        "active_path": active_path,
        "active_sha256": _sha256_file(active_path),
        "snapshot_path": snapshot_path,
        "snapshot_sha256": _sha256_file(snapshot_path),
        "reference_path": ref_path,
        "reference_sha256": _sha256_file(ref_path),
    }


def _validate_inputs(content_id: str, repo_root: Path) -> dict[str, Any]:
    if content_id != SUPPORTED_CONTENT_ID:
        raise ManualPackError(f"unsupported sample content id: {content_id}")
    repo_root = _assert_no_reparse_ancestors(repo_root)
    batch = _validate_batch(repo_root, content_id)
    episode_root = repo_root / "09_泛健康日更" / "work" / content_id
    production_root = episode_root / "production" / VERSION
    _require_within(_assert_no_reparse_ancestors(production_root), repo_root, "production root")
    episode_manifest_path = episode_root / "manifest.json"
    episode_manifest = _load_json(episode_manifest_path, "episode manifest")
    if episode_manifest.get("content_id") != content_id or episode_manifest.get("batch_id") != batch["batch_id"]:
        raise ManualPackError("episode manifest identity does not match active batch")

    storyboard_path = production_root / "02_script_storyboard" / "storyboard-v01.md"
    storyboard_rows = _parse_storyboard(storyboard_path)
    prompts = {shot: _prompt_line(shot) for shot in EXPECTED_SHOTS}
    _validate_semantic_contracts(storyboard_rows, prompts)
    first_frame_root = production_root / "03_first_frames"
    _assert_no_reparse_ancestors(first_frame_root)
    expected_names = [f"{content_id}-{VERSION}-{shot}-firstframe.png" for shot in EXPECTED_SHOTS]
    actual_names = sorted(path.name for path in first_frame_root.glob("*-firstframe.png") if path.is_file())
    if actual_names != expected_names:
        raise ManualPackError("formal first-frame root must contain exactly the expected S01-S10 inputs")

    images: dict[str, dict[str, Any]] = {}
    hashes: set[str] = set()
    for shot, name in zip(EXPECTED_SHOTS, expected_names, strict=True):
        path = first_frame_root / name
        _require_regular_file(path, f"formal first frame {shot}")
        if path.parent != first_frame_root:
            raise ManualPackError(f"first frame is not root-level: {path}")
        data = path.read_bytes()
        digest = _sha256_bytes(data)
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format != "PNG" or image.size != (1080, 1920):
                    raise ManualPackError(f"invalid first-frame format or dimensions: {path}")
                image.verify()
        except (OSError, SyntaxError) as exc:
            raise ManualPackError(f"invalid PNG first frame: {path}") from exc
        hashes.add(digest)
        images[shot] = {"path": path, "bytes": data, "sha256": digest}
    if len(hashes) != len(EXPECTED_SHOTS):
        raise ManualPackError("formal first frames must have ten unique SHA-256 values")

    episode_qa_path = production_root / "05_qa" / "first-frame-qa-v01.md"
    batch_qa_path = (
        repo_root
        / "09_泛健康日更"
        / "work"
        / "HC20260810-B01-task6-qa"
        / "HC20260810-B01-first-frame-qa-v01.md"
    )
    contact_sheet_path = production_root / "05_qa" / "storyboard-with-copy-contactsheet-v01.png"
    _require_regular_file(episode_qa_path, "episode Task 6 QA")
    _require_regular_file(batch_qa_path, "batch Task 6 QA")
    _require_regular_file(contact_sheet_path, "storyboard-with-copy contact sheet")
    episode_qa_text = episode_qa_path.read_text(encoding="utf-8")
    batch_qa_text = batch_qa_path.read_text(encoding="utf-8")
    if not all(image["sha256"] in episode_qa_text for image in images.values()):
        raise ManualPackError("episode Task 6 QA does not bind all current first-frame hashes")
    if "BATCH R3 EVIDENCE CURRENT" not in batch_qa_text or "not Task 8 factual approval" not in batch_qa_text:
        raise ManualPackError("batch Task 6 QA is not the required current non-approval evidence")

    for row in storyboard_rows:
        shot = row["镜号"]
        expected_deterministic = shot in DETERMINISTIC_SHOTS
        if (row["复用状态"] == "deterministic-board") != expected_deterministic:
            raise ManualPackError(f"unexpected generation mode in storyboard: {shot}")
        try:
            seconds = float(row["minimum_grok_source_seconds"])
        except ValueError as exc:
            raise ManualPackError(f"invalid minimum Grok source seconds: {shot}") from exc
        if expected_deterministic and seconds != 0.0:
            raise ManualPackError(f"deterministic shot must require zero Grok seconds: {shot}")
        if not expected_deterministic and not 0.0 < seconds <= 5.8:
            raise ManualPackError(f"dynamic minimum Grok source seconds exceeds 5.8: {shot}")

    return {
        "repo_root": repo_root,
        "content_id": content_id,
        "episode_root": episode_root,
        "production_root": production_root,
        "episode_manifest_path": episode_manifest_path,
        "storyboard_path": storyboard_path,
        "storyboard_rows": storyboard_rows,
        "prompts": prompts,
        "images": images,
        "episode_qa_path": episode_qa_path,
        "batch_qa_path": batch_qa_path,
        "contact_sheet_path": contact_sheet_path,
        "batch": batch,
    }


def _prompt_line(shot: str) -> str:
    chinese_action, english_action = PROMPT_ACTIONS[shot]
    deterministic = shot in DETERMINISTIC_SHOTS
    mode = "deterministic_post" if deterministic else "grok_manual"
    operation_zh = (
        "无需上传 Grok，只在后期按本条制作确定性动效"
        if deterministic
        else "使用 Grok 浏览器扩展手动上传对应无字首帧，首帧是唯一构图参考"
    )
    operation_en = (
        "Do not upload to Grok; create only this deterministic motion in post-production"
        if deterministic
        else "Manually upload the matching text-free first frame with the Grok browser extension; the first frame is the sole composition reference"
    )
    return (
        f"{shot}｜generation_mode={mode}｜中文指令：{operation_zh}。低幅动作：{chinese_action}。"
        "保持人物身份与场景、服装、道具数量、结构、路径、光线与竖屏构图；"
        "不新增文字、数字、Logo、水印、UI、纸张、纸笔、本册、人物或物体。"
        f" English instruction: {operation_en}. Low-amplitude action: {english_action}. "
        "Preserve identity and scene, clothing, prop count, structure, direction, lighting, and vertical framing; "
        "add no text, numbers, Logo, watermark, UI, paper, pen, notebook, person, or object."
    )


def _csv_bytes(fieldnames: list[str], rows: list[dict[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _render_expected(inputs: dict[str, Any], output_dir: Path) -> dict[str, bytes]:
    repo_root: Path = inputs["repo_root"]
    content_id: str = inputs["content_id"]
    rows_by_shot = {row["镜号"]: row for row in inputs["storyboard_rows"]}
    prompts = inputs["prompts"]
    artifacts: dict[str, bytes] = {}
    manifest_rows: list[dict[str, str]] = []
    storyboard_sha = _sha256_file(inputs["storyboard_path"])
    episode_qa_sha = _sha256_file(inputs["episode_qa_path"])
    batch_qa_sha = _sha256_file(inputs["batch_qa_path"])

    for shot in EXPECTED_SHOTS:
        image = inputs["images"][shot]
        image_name = image["path"].name
        copy_relative = Path("01_first_frames") / image_name
        prompt_name = f"{content_id}-{VERSION}-{shot}-prompt-zh-en.txt"
        prompt_relative = Path("02_prompts") / prompt_name
        prompt_bytes = (prompts[shot] + "\n").encode("utf-8")
        artifacts[copy_relative.as_posix()] = image["bytes"]
        artifacts[prompt_relative.as_posix()] = prompt_bytes
        storyboard_row = rows_by_shot[shot]
        deterministic = shot in DETERMINISTIC_SHOTS
        mode = "deterministic_post" if deterministic else "grok_manual"
        output_template = (
            f"09_泛健康日更/work/{content_id}/production/{VERSION}/06_edit/01_rough_cut/"
            f"{content_id}-{VERSION}-{shot}-deterministic-post.mp4"
            if deterministic
            else f"09_泛健康日更/work/{content_id}/production/{VERSION}/05_grok_videos/01_raw/"
            f"{content_id}-{VERSION}-{shot}-grok-source.mp4"
        )
        manifest_rows.append(
            {
                "batch_id": inputs["batch"]["batch_id"],
                "content_id": content_id,
                "version": VERSION,
                "shot": shot,
                "source_path": _as_posix(image["path"], repo_root),
                "copy_path": _as_posix(output_dir / copy_relative, repo_root),
                "bytes": str(len(image["bytes"])),
                "sha256": image["sha256"],
                "prompt_path": _as_posix(output_dir / prompt_relative, repo_root),
                "prompt_sha256": _sha256_bytes(prompt_bytes),
                "timeline_start": storyboard_row["起点"],
                "timeline_end": storyboard_row["终点"],
                "generation_mode": mode,
                "minimum_grok_source_seconds": storyboard_row["minimum_grok_source_seconds"],
                "output_template": output_template,
                "storyboard_sha256": storyboard_sha,
                "episode_qa_sha256": episode_qa_sha,
                "batch_qa_sha256": batch_qa_sha,
            }
        )

    combined_name = f"{content_id}-{VERSION}-Grok-Automation-10条提示词.txt"
    artifacts[combined_name] = ("\n\n".join(prompts[shot] for shot in EXPECTED_SHOTS) + "\n").encode("utf-8")
    fields = list(manifest_rows[0])
    artifacts["MANIFEST.csv"] = _csv_bytes(fields, manifest_rows)

    guide = f"""# {content_id} {VERSION} Grok 手动生成指南

## 边界

- 本包是用户操作的浏览器扩展输入包，不包含已生成视频，也不代表外部审批或最终 QA。
- 动态镜头 S01、S02、S04、S05、S06、S07、S09：使用 **Grok 浏览器扩展**手动上传 `01_first_frames/` 中的对应图片，并粘贴 `02_prompts/` 中的同号提示词。
- S03、S08、S10 无需上传 Grok；它们标记为 `generation_mode=deterministic_post`，只按提示词在后期制作确定性动效。

## 手动操作

1. 按 S01 到 S10 顺序处理；动态镜头的无字首帧是唯一构图参考。
2. 每个动态镜头只执行提示词中的一个低幅动作，不生成文字、Logo、水印、纸张、纸笔、本册或 UI。
3. 手动保存动态输出到 `05_grok_videos/01_raw/`，使用 `MANIFEST.csv` 的 `output_template` 文件名。
4. 保持 1.0 倍速；禁止慢动作、循环、插帧或模型生成 UI。S09 所需的 0.70 秒延长只能用末帧短停和确定性叠加。
5. 生成完成不等于通过质检；后续必须保留原文件并逐镜检查首、中、尾帧。
"""
    artifacts["MANUAL-GENERATION-GUIDE.md"] = guide.encode("utf-8")

    visual_review_rows = "\n".join(
        f"| {shot} | `{inputs['images'][shot]['sha256']}` | {VISUAL_REVIEW_NOTES[shot]} |"
        for shot in EXPECTED_SHOTS
    )
    contact_sheet_path = inputs["contact_sheet_path"]
    qa = f"""# {content_id} {VERSION} Grok 手动包 QA

## 结果

- 活动主题状态：`production`；批次：`{inputs['batch']['batch_id']}`。
- 分镜：`{_as_posix(inputs['storyboard_path'], repo_root)}`，SHA-256 `{storyboard_sha}`，按表头名解析并确认恰好 S01–S10。
- 正式首帧：仅消费 `03_first_frames/` 根目录中 10 张无字 PNG；全部 1080×1920、哈希唯一，拷贝后字节与源文件相同。
- 排除：未消费 `storyboard_with_copy/`、带字联系表、UI 预览或候选图。
- 提示词：10 条中英双语单行，S03/S08/S10 为 `deterministic_post` 且无需上传 Grok；其余 7 镜为 `grok_manual`，最小 Grok 源时长均不超过 5.8 秒。
- 合并 TXT：恰好 10 条非空提示词，相邻恰好一个空行，UTF-8 + LF。

## 必需源质量证据

- 单期 Task 6：`{_as_posix(inputs['episode_qa_path'], repo_root)}`，SHA-256 `{episode_qa_sha}`。
- 批次 Task 6：`{_as_posix(inputs['batch_qa_path'], repo_root)}`，SHA-256 `{batch_qa_sha}`。
- 两份 QA 只是必需的当前源质量证据，**不是外部审批**、Task 8 事实批准、最终 QA 授权或发布许可。

## 视觉核对边界

- 审阅方式：`view_image`。
- 审阅日期：`2026-08-17`。
- 审阅者：`Codex Task 7 implementation review`。
- 带字联系表：`{_as_posix(contact_sheet_path, repo_root)}`，SHA-256 `{_sha256_file(contact_sheet_path)}`；只用于理解文案/动作上下文，不会被复制。

| 镜号 | 正式首帧 SHA-256 | `view_image` 逐镜结论 |
|---|---|---|
{visual_review_rows}

- 上述记录不是 Grok 动态或最终 QA 批准，也不是外部审批或发布许可。
"""
    artifacts["MANUAL-PACK-QA.md"] = qa.encode("utf-8")
    return artifacts


def _tree_bytes(root: Path) -> dict[str, bytes]:
    if not root.is_dir() or root.is_symlink():
        raise ManualPackError(f"manual pack is missing or unsafe: {root}")
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or getattr(path.stat(), "st_file_attributes", 0) & REPARSE_POINT_FLAG:
            raise ManualPackError(f"reparse path forbidden inside manual pack: {path}")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def _compare_tree(output_dir: Path, expected: dict[str, bytes]) -> None:
    actual = _tree_bytes(output_dir)
    if actual.keys() != expected.keys():
        raise ManualPackError("manual pack has different existing bytes or file set")
    differences = [name for name, data in expected.items() if actual[name] != data]
    if differences:
        raise ManualPackError(f"manual pack has different existing bytes: {differences[0]}")


def _write_staging(staging: Path, artifacts: dict[str, bytes]) -> None:
    for relative, data in artifacts.items():
        target = staging / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_output(inputs: dict[str, Any]) -> Path:
    return inputs["production_root"] / "04_grok_batch" / "manual_pack"


def build_manual_pack(
    content_id: str,
    *,
    repo_root: Path | str | None = None,
    output_dir: Path | str | None = None,
) -> Path:
    root_input = Path(repo_root) if repo_root is not None else _default_repo_root()
    root = _assert_no_reparse_ancestors(root_input)
    inputs = _validate_inputs(content_id, root)
    destination_input = Path(output_dir) if output_dir is not None else _default_output(inputs)
    destination = _assert_no_reparse_ancestors(destination_input)
    if output_dir is None:
        _require_within(destination, inputs["production_root"], "manual pack output")
    expected = _render_expected(inputs, destination)

    destination.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_reparse_ancestors(destination.parent)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent))
    try:
        _write_staging(staging, expected)
        _compare_tree(staging, expected)
        if destination.exists():
            _compare_tree(destination, expected)
            return destination
        _assert_no_reparse_ancestors(destination.parent)
        try:
            os.replace(staging, destination)
        except OSError:
            if destination.exists():
                _compare_tree(destination, expected)
            else:
                raise
        return destination
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def verify_manual_pack(
    content_id: str,
    *,
    repo_root: Path | str | None = None,
    output_dir: Path | str | None = None,
) -> Path:
    root_input = Path(repo_root) if repo_root is not None else _default_repo_root()
    root = _assert_no_reparse_ancestors(root_input)
    inputs = _validate_inputs(content_id, root)
    destination_input = Path(output_dir) if output_dir is not None else _default_output(inputs)
    destination = _assert_no_reparse_ancestors(destination_input)
    if output_dir is None:
        _require_within(destination, inputs["production_root"], "manual pack output")
    expected = _render_expected(inputs, destination)
    _compare_tree(destination, expected)
    return destination


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or verify a deterministic Grok browser-extension manual pack.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "verify"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--content-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        path = (
            build_manual_pack(args.content_id)
            if args.command == "build"
            else verify_manual_pack(args.content_id)
        )
    except ManualPackError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 3
    print(json.dumps({"status": "ok", "command": args.command, "path": str(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
