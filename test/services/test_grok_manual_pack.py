from __future__ import annotations

import csv
import copy as copy_module
import hashlib
import importlib.util
import os
import re
import subprocess
from pathlib import Path

import pytest
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "09_泛健康日更" / "scripts" / "build_grok_manual_packs.py"
CONTENT_ID = "HC20260810-001"
EPISODE_ROOT = REPO_ROOT / "09_泛健康日更" / "work" / CONTENT_ID
PRODUCTION_ROOT = EPISODE_ROOT / "production" / "v01"
MANUAL_PACK = PRODUCTION_ROOT / "04_grok_batch" / "manual_pack"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_grok_manual_packs", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _directory_symlink_or_skip(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink unavailable: {exc}")


def test_builds_and_verifies_production_sample() -> None:
    builder = _load_builder()
    result = builder.build_manual_pack(CONTENT_ID, repo_root=REPO_ROOT)
    assert result == MANUAL_PACK
    builder.verify_manual_pack(CONTENT_ID, repo_root=REPO_ROOT)

    active_batch = (
        REPO_ROOT
        / "09_泛健康日更"
        / "data"
        / "01_一般生活方式50集"
        / "batch-01"
        / "active-batch.json"
    )
    assert '"content_id": "HC20260810-001"' in active_batch.read_text(encoding="utf-8")
    assert '"state": "production"' in active_batch.read_text(encoding="utf-8")

    first_frames = MANUAL_PACK / "01_first_frames"
    copies = sorted(first_frames.glob("*-firstframe.png"))
    assert [path.name for path in copies] == [
        f"{CONTENT_ID}-v01-S{number:02d}-firstframe.png" for number in range(1, 11)
    ]

    source_root = PRODUCTION_ROOT / "03_first_frames"
    source_hashes: list[str] = []
    for copy in copies:
        source = source_root / copy.name
        assert source.parent == source_root
        assert copy.read_bytes() == source.read_bytes()
        with Image.open(copy) as image:
            assert image.size == (1080, 1920)
        source_hashes.append(_sha256(source))
    assert len(set(source_hashes)) == 10

    combined = (
        MANUAL_PACK / f"{CONTENT_ID}-v01-Grok-Automation-10条提示词.txt"
    ).read_bytes()
    assert combined.startswith(b"S01")
    assert b"\r" not in combined
    text = combined.decode("utf-8")
    assert "\n\n\n" not in text
    assert text.count("\n\n") == 9
    assert len(text.splitlines()) == 19
    prompt_lines = text.rstrip("\n").split("\n\n")
    assert len(prompt_lines) == 10
    assert all("\n" not in line and line.strip() for line in prompt_lines)

    deterministic = {"S03", "S08", "S10"}
    for number, line in enumerate(prompt_lines, start=1):
        shot = f"S{number:02d}"
        assert line.startswith(f"{shot}｜")
        assert re.search(r"[\u4e00-\u9fff]", line)
        assert re.search(r"[A-Za-z]", line)
        assert "中文指令：" in line and "English instruction:" in line
        assert "低幅动作：" in line and "Low-amplitude action:" in line
        assert "保持人物身份与场景" in line
        assert "Preserve identity and scene" in line
        for forbidden in ("不新增文字", "Logo", "水印", "纸张", "纸笔", "本册"):
            assert forbidden in line
        if shot in deterministic:
            assert "generation_mode=deterministic_post" in line
            assert "无需上传 Grok" in line
        else:
            assert "generation_mode=grok_manual" in line
            assert "手动上传" in line

    per_shot = sorted((MANUAL_PACK / "02_prompts").glob("*-prompt-zh-en.txt"))
    assert len(per_shot) == 10
    assert [path.read_text(encoding="utf-8").rstrip("\n") for path in per_shot] == prompt_lines
    assert all(b"\r" not in path.read_bytes() for path in per_shot)

    with (MANUAL_PACK / "MANIFEST.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["shot"] for row in rows] == [f"S{number:02d}" for number in range(1, 11)]
    required_columns = {
        "batch_id",
        "content_id",
        "version",
        "shot",
        "source_path",
        "copy_path",
        "bytes",
        "sha256",
        "prompt_path",
        "prompt_sha256",
        "timeline_start",
        "timeline_end",
        "generation_mode",
        "minimum_grok_source_seconds",
        "output_template",
        "storyboard_sha256",
        "episode_qa_sha256",
        "batch_qa_sha256",
    }
    assert required_columns <= set(rows[0])
    for row in rows:
        source = REPO_ROOT / row["source_path"]
        copied = REPO_ROOT / row["copy_path"]
        prompt = REPO_ROOT / row["prompt_path"]
        assert int(row["bytes"]) == source.stat().st_size == copied.stat().st_size
        assert row["sha256"] == _sha256(source) == _sha256(copied)
        assert row["prompt_sha256"] == _sha256(prompt)
        if row["generation_mode"] == "grok_manual":
            assert float(row["minimum_grok_source_seconds"]) <= 5.8
        else:
            assert row["generation_mode"] == "deterministic_post"
            assert float(row["minimum_grok_source_seconds"]) == 0.0

    guide = (MANUAL_PACK / "MANUAL-GENERATION-GUIDE.md").read_text(encoding="utf-8")
    assert "Grok 浏览器扩展" in guide
    for phrase in ("慢动作", "循环", "插帧", "模型生成 UI"):
        assert phrase in guide
    assert "S03、S08、S10 无需上传 Grok" in guide

    qa = (MANUAL_PACK / "MANUAL-PACK-QA.md").read_text(encoding="utf-8")
    assert "first-frame-qa-v01.md" in qa
    assert "HC20260810-B01-first-frame-qa-v01.md" in qa
    assert "不是外部审批" in qa


def test_identical_rerun_is_byte_idempotent() -> None:
    builder = _load_builder()
    builder.build_manual_pack(CONTENT_ID, repo_root=REPO_ROOT)
    before = _tree_bytes(MANUAL_PACK)
    builder.build_manual_pack(CONTENT_ID, repo_root=REPO_ROOT)
    assert _tree_bytes(MANUAL_PACK) == before


def test_different_existing_bytes_fail_closed(tmp_path: Path) -> None:
    builder = _load_builder()
    output = tmp_path / "manual_pack"
    builder.build_manual_pack(CONTENT_ID, repo_root=REPO_ROOT, output_dir=output)
    target = output / "MANUAL-GENERATION-GUIDE.md"
    target.write_bytes(b"foreign bytes\n")

    with pytest.raises(builder.ManualPackError, match="different existing bytes"):
        builder.build_manual_pack(CONTENT_ID, repo_root=REPO_ROOT, output_dir=output)

    assert target.read_bytes() == b"foreign bytes\n"


def test_invalid_inputs_create_no_output_directory(tmp_path: Path) -> None:
    builder = _load_builder()
    output = tmp_path / "must-not-exist" / "manual_pack"
    with pytest.raises(builder.ManualPackError):
        builder.build_manual_pack(CONTENT_ID, repo_root=tmp_path, output_dir=output)
    assert not output.exists()


def test_storyboard_parser_resolves_columns_by_header_name(tmp_path: Path) -> None:
    builder = _load_builder()
    source = PRODUCTION_ROOT / "02_script_storyboard" / "storyboard-v01.md"
    lines = source.read_text(encoding="utf-8").splitlines()
    header_index = next(
        index for index, line in enumerate(lines) if line.startswith("|") and "镜号" in line
    )

    def cells(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip().strip("|").split("|")]

    order = [3, 0, 11, 1, 2, 4, 5, 6, 7, 8, 9, 10, 12, 13]
    reordered = lines[:header_index]
    for line in lines[header_index : header_index + 12]:
        values = cells(line)
        reordered.append("| " + " | ".join(values[index] for index in order) + " |")
    path = tmp_path / "storyboard.md"
    path.write_text("\n".join(reordered) + "\n", encoding="utf-8", newline="\n")

    rows = builder._parse_storyboard(path)
    assert [row["镜号"] for row in rows] == [f"S{number:02d}" for number in range(1, 11)]
    assert rows[5]["人物动作"] == "人物手持黑屏手机，拇指点按三个空白位置"


def test_approved_prompt_phases_match_locked_first_frames() -> None:
    builder = _load_builder()
    prompts = {shot: builder._prompt_line(shot) for shot in ("S01", "S02", "S04", "S05", "S09")}

    assert "一次轻靠椅背并缓慢自然眨眼的连贯小动作" in prompts["S01"]
    assert "手保持在已经离开餐盘的位置" in prompts["S02"]
    assert "继续完成放勺的最后阶段" in prompts["S04"]
    assert "勺子只做极小幅落稳，随即手轻轻收回" in prompts["S04"]
    assert "人物已经站起" in prompts["S05"]
    assert "镜头轻微横移跟随" in prompts["S05"]
    assert "钥匙保持在置物盘中" in prompts["S09"]
    assert "朝沙发方向只迈一小步" in prompts["S09"]
    assert "镜头先固定，后轻微跟随" in prompts["S09"]


def test_semantic_contract_binds_storyboard_and_prompt_mapping() -> None:
    builder = _load_builder()
    assert hasattr(builder, "SHOT_SEMANTIC_CONTRACTS"), "explicit shot contracts are required"
    assert hasattr(builder, "_validate_semantic_contracts"), "contract validator is required"
    storyboard = PRODUCTION_ROOT / "02_script_storyboard" / "storyboard-v01.md"
    rows = builder._parse_storyboard(storyboard)
    prompts = {shot: builder._prompt_line(shot) for shot in builder.EXPECTED_SHOTS}
    builder._validate_semantic_contracts(rows, prompts)

    contracts = builder.SHOT_SEMANTIC_CONTRACTS
    assert set(contracts) == set(builder.EXPECTED_SHOTS)
    for row in rows:
        contract = contracts[row["镜号"]]
        for column in ("人物动作", "相机", "ai_source_layer"):
            assert contract["storyboard"][column]
            for fragment in contract["storyboard"][column]:
                assert fragment in row[column]
        for fragment in contract["prompt_zh"]:
            assert fragment in prompts[row["镜号"]]

    drifted_rows = copy_module.deepcopy(rows)
    drifted_rows[3]["ai_source_layer"] = "人物只挥手"
    with pytest.raises(builder.ManualPackError, match="semantic contract.*S04.*ai_source_layer"):
        builder._validate_semantic_contracts(drifted_rows, prompts)

    drifted_prompts = dict(prompts)
    drifted_prompts["S09"] = drifted_prompts["S09"].replace("朝沙发方向只迈一小步", "保持原地不动")
    with pytest.raises(builder.ManualPackError, match="semantic contract.*S09.*prompt"):
        builder._validate_semantic_contracts(rows, drifted_prompts)


def test_repo_root_link_is_rejected_before_output_creation(tmp_path: Path) -> None:
    builder = _load_builder()
    linked_repo = tmp_path / "linked-repo"
    _directory_symlink_or_skip(REPO_ROOT, linked_repo)
    output = tmp_path / "output" / "manual_pack"

    with pytest.raises(builder.ManualPackError, match="reparse"):
        builder.build_manual_pack(CONTENT_ID, repo_root=linked_repo, output_dir=output)

    assert not output.exists()
    assert not list(tmp_path.glob(".manual_pack.staging-*"))


def test_output_parent_link_is_rejected_before_staging(tmp_path: Path) -> None:
    builder = _load_builder()
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    _directory_symlink_or_skip(real_parent, linked_parent)
    output = linked_parent / "manual_pack"

    with pytest.raises(builder.ManualPackError, match="reparse"):
        builder.build_manual_pack(CONTENT_ID, repo_root=REPO_ROOT, output_dir=output)

    assert not output.exists()
    assert list(real_parent.iterdir()) == []


def test_lf_attributes_are_scoped_to_001_manual_pack() -> None:
    targets = {
        "001": "09_泛健康日更/work/HC20260810-001/production/v01/04_grok_batch/manual_pack/MANIFEST.csv",
        "002": "09_泛健康日更/work/HC20260810-002/production/v01/04_grok_batch/manual_pack/MANIFEST.csv",
    }

    def attributes(path: str) -> dict[str, str]:
        result = subprocess.run(
            ["git", "check-attr", "text", "eol", "--", path],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return {
            line.rsplit(": ", 2)[-2]: line.rsplit(": ", 1)[-1]
            for line in result.stdout.splitlines()
        }

    assert attributes(targets["001"]) == {"text": "set", "eol": "lf"}
    assert attributes(targets["002"]) == {"text": "auto", "eol": "unspecified"}


def test_manual_pack_qa_contains_reproducible_view_image_log() -> None:
    qa = (MANUAL_PACK / "MANUAL-PACK-QA.md").read_text(encoding="utf-8")
    assert "审阅方式：`view_image`" in qa
    assert "审阅日期：`2026-08-17`" in qa
    source_root = PRODUCTION_ROOT / "03_first_frames"
    for shot in (f"S{number:02d}" for number in range(1, 11)):
        source = source_root / f"{CONTENT_ID}-v01-{shot}-firstframe.png"
        assert f"| {shot} | `{_sha256(source)}` |" in qa
    assert "storyboard-with-copy-contactsheet-v01.png" in qa
    assert "不是 Grok 动态或最终 QA 批准" in qa
