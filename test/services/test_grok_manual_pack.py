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
CONTENT_IDS = [f"HC20260810-{number:03d}" for number in range(1, 11)]
CONTENT_ID = CONTENT_IDS[0]
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


@pytest.mark.parametrize("content_id", CONTENT_IDS)
def test_all_production_manual_packs_exist_and_verify(content_id: str) -> None:
    pack = (
        REPO_ROOT
        / "09_泛健康日更"
        / "work"
        / content_id
        / "production"
        / "v01"
        / "04_grok_batch"
        / "manual_pack"
    )
    assert pack.is_dir(), f"missing production manual pack: {content_id}"
    _load_builder().verify_manual_pack(content_id, repo_root=REPO_ROOT)


def test_batch_manual_pack_inventory_has_exact_100_shot_bindings() -> None:
    inventory_path = (
        REPO_ROOT
        / "09_泛健康日更"
        / "work"
        / "HC20260810-B01-task9-qa"
        / "HC20260810-B01-grok-manual-pack-inventory-v01.csv"
    )
    with inventory_path.open(encoding="utf-8", newline="") as handle:
        inventory = list(csv.DictReader(handle))
    assert len(inventory) == 100
    assert list(inventory[0]) == [
        "content_id",
        "shot_id",
        "generation_mode",
        "source_first_frame",
        "copy_first_frame",
        "source_sha256",
        "copy_sha256",
        "prompt_file",
        "prompt_sha256",
        "timeline",
        "minimum_grok_source_seconds",
        "raw_output_template",
        "pack_status",
    ]
    assert {(row["content_id"], row["shot_id"]) for row in inventory} == {
        (content_id, f"S{number:02d}")
        for content_id in CONTENT_IDS
        for number in range(1, 11)
    }
    assert {row["pack_status"] for row in inventory} == {"verified"}

    total_copies = 0
    total_prompts = 0
    total_combined = 0
    for content_id in CONTENT_IDS:
        production = (
            REPO_ROOT / "09_泛健康日更" / "work" / content_id / "production" / "v01"
        )
        pack = production / "04_grok_batch" / "manual_pack"
        with (pack / "MANIFEST.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert [row["shot"] for row in rows] == [f"S{number:02d}" for number in range(1, 11)]
        copies = sorted((pack / "01_first_frames").glob("*-firstframe.png"))
        prompts = sorted((pack / "02_prompts").glob("*-prompt-zh-en.txt"))
        combined = list(pack.glob("*-Grok-Automation-10条提示词.txt"))
        assert len(copies) == len(prompts) == len(rows) == 10
        assert len(combined) == 1
        total_copies += len(copies)
        total_prompts += len(prompts)
        total_combined += len(combined)
        for row in rows:
            source = REPO_ROOT / row["source_path"]
            copied = REPO_ROOT / row["copy_path"]
            prompt = REPO_ROOT / row["prompt_path"]
            assert "storyboard_with_copy" not in row["source_path"]
            assert "05_qa" not in row["source_path"]
            assert source.read_bytes() == copied.read_bytes()
            assert row["sha256"] == _sha256(source) == _sha256(copied)
            assert row["prompt_sha256"] == _sha256(prompt)
            with Image.open(copied) as image:
                assert image.size == (1080, 1920)
            if row["generation_mode"] == "grok_manual":
                assert 0.0 < float(row["minimum_grok_source_seconds"]) <= 5.8
            else:
                assert row["generation_mode"] == "deterministic_post"
                assert float(row["minimum_grok_source_seconds"]) == 0.0
    assert (total_copies, total_prompts, total_combined) == (100, 100, 10)


def test_all_prompt_documents_are_safe_and_use_exact_blank_line_format() -> None:
    for content_id in CONTENT_IDS:
        pack = (
            REPO_ROOT
            / "09_泛健康日更"
            / "work"
            / content_id
            / "production"
            / "v01"
            / "04_grok_batch"
            / "manual_pack"
        )
        combined = (pack / f"{content_id}-v01-Grok-Automation-10条提示词.txt").read_bytes()
        assert b"\r" not in combined
        text = combined.decode("utf-8")
        assert text.count("\n\n") == 9
        assert "\n\n\n" not in text
        lines = text.rstrip("\n").split("\n\n")
        assert len(lines) == 10
        for shot, line in zip((f"S{number:02d}" for number in range(1, 11)), lines, strict=True):
            assert line.startswith(f"{shot}｜")
            assert "不新增文字、数字、Logo、水印、UI、纸张、纸笔、本册、人物或物体" in line
            assert "add no text, numbers, Logo, watermark, UI, paper, pen, notebook, person, or object" in line
            for clause in re.split(r"[。；.;]", line):
                if re.search(r"(?:新增|添加|加入)(?:一名|一个|一只|额外)", clause):
                    assert re.search(r"不|不得|禁止|无|只", clause)
                if re.search(
                    r"\b(?:add|create|introduce) (?:a|an|another|extra)\b",
                    clause,
                    re.I,
                ):
                    assert re.search(
                        r"\b(?:not|never|no|without|reject|forbid)\b",
                        clause,
                        re.I,
                    )


def test_all_100_actions_are_unique_and_every_shot_contract_is_bound() -> None:
    builder = _load_builder()
    chinese_actions: set[str] = set()
    english_actions: set[str] = set()

    for content_id in CONTENT_IDS:
        production = (
            REPO_ROOT / "09_泛健康日更" / "work" / content_id / "production" / "v01"
        )
        rows = builder._parse_storyboard(
            production / "02_script_storyboard" / "storyboard-v01.md"
        )
        deterministic = {
            row["镜号"] for row in rows if row["复用状态"] == "deterministic-board"
        }
        prompts = {
            shot: builder._prompt_line(
                shot,
                content_id=content_id,
                deterministic_shots=deterministic,
            )
            for shot in builder.EXPECTED_SHOTS
        }
        builder._validate_semantic_contracts(rows, prompts, content_id=content_id)

        contracts = builder.SHOT_SEMANTIC_CONTRACTS_BY_CONTENT[content_id]
        assert set(contracts) == set(builder.EXPECTED_SHOTS)
        assert len({tuple(contracts[shot]["storyboard"]["相机"]) for shot in builder.EXPECTED_SHOTS}) >= 6
        for shot in builder.EXPECTED_SHOTS:
            action_zh, action_en = builder.PROMPT_ACTIONS_BY_CONTENT[content_id][shot]
            assert action_zh not in chinese_actions
            assert action_en not in english_actions
            chinese_actions.add(action_zh)
            english_actions.add(action_en)
            assert action_zh in prompts[shot]
            assert action_en in prompts[shot]

    assert len(chinese_actions) == len(english_actions) == 100


def test_batch_high_risk_counts_phases_and_objects_are_hard_locked() -> None:
    builder = _load_builder()
    required = {
        ("HC20260810-002", "S01"): ("同一人物", "同一餐盒", "两侧不同步"),
        ("HC20260810-002", "S07"): ("唯一一把叉子", "不在餐盒内", "手完全离开"),
        ("HC20260810-003", "S04"): ("唯一一把叉子", "未接触食物", "另一只手保持静止"),
        ("HC20260810-003", "S09"): ("半起身相位", "仍保持半起身", "不站直、不迈步"),
        ("HC20260810-004", "S01"): ("七块纵向色板", "坐、走、坐、走、坐、走、坐"),
        ("HC20260810-004", "S06"): ("严格完成三步", "第三步后停止"),
        ("HC20260810-005", "S01"): ("唯一台纯深青色显示器", "两手都离开唯一键盘"),
        ("HC20260810-005", "S09"): ("恰好一把大汽车钥匙", "第二把钥匙"),
        ("HC20260810-006", "S06"): ("三次低幅点按", "手机外框约2.05"),
        ("HC20260810-006", "S09"): ("恰好三张同一人物", "三种不同状态"),
        ("HC20260810-007", "S01"): ("唯一一只无品牌陶瓷咖啡杯", "不拿起、不喝"),
        ("HC20260810-007", "S07"): ("恰好三只同型陶瓷咖啡杯", "唯一差异只保留现有光线位置"),
        ("HC20260810-009", "S03"): ("唯一一个触控板", "一次短距离单向拖动"),
        ("HC20260810-009", "S10"): ("恰好七个无字圆角色块", "其余六块完全不动"),
    }
    for (content_id, shot), fragments in required.items():
        prompt = builder._prompt_line(shot, content_id=content_id)
        for fragment in fragments:
            assert fragment in prompt, f"missing hard lock {content_id}/{shot}: {fragment}"


def test_phone_shots_preserve_task6_constraints_and_010_s02_is_static_back_shell() -> None:
    builder = _load_builder()
    for content_id in CONTENT_IDS:
        production = (
            REPO_ROOT / "09_泛健康日更" / "work" / content_id / "production" / "v01"
        )
        rows = builder._parse_storyboard(production / "02_script_storyboard" / "storyboard-v01.md")
        prompt_root = production / "04_grok_batch" / "manual_pack" / "02_prompts"
        for row in rows:
            if "手机" not in " ".join(row.values()):
                continue
            prompt = (prompt_root / f"{content_id}-v01-{row['镜号']}-prompt-zh-en.txt").read_text(
                encoding="utf-8"
            )
            assert "手机" in prompt
            assert "不新增文字、数字、Logo、水印、UI" in prompt
    prompt_010_s02 = (
        REPO_ROOT
        / "09_泛健康日更"
        / "work"
        / "HC20260810-010"
        / "production"
        / "v01"
        / "04_grok_batch"
        / "manual_pack"
        / "02_prompts"
        / "HC20260810-010-v01-S02-prompt-zh-en.txt"
    ).read_text(encoding="utf-8")
    assert "手机背壳" in prompt_010_s02
    assert "静态" in prompt_010_s02
    assert "trackable UI" not in prompt_010_s02
    assert "可跟踪 UI" not in prompt_010_s02


def test_source_public_copy_remains_free_of_medical_and_device_terms() -> None:
    forbidden = (
        "疾病", "诊断", "治疗", "医生", "医务", "医院", "门诊", "检查", "血糖", "血压",
        "血脂", "尿酸", "血氧", "体温", "减重云", "健康卫士", "体脂秤", "医疗器械",
        "健康科普", "不替代诊疗", "专家", "处方", "医学曲线",
    )
    for content_id in CONTENT_IDS:
        copy_root = (
            REPO_ROOT
            / "09_泛健康日更"
            / "work"
            / content_id
            / "production"
            / "v01"
            / "02_script_storyboard"
        )
        public_text = "\n".join(
            (copy_root / name).read_text(encoding="utf-8")
            for name in ("narration-v01.md", "platform-copy-v01.md", "article-cards-v01.md")
        )
        for term in forbidden:
            assert term not in public_text, f"public forbidden term {term!r} in {content_id}"


def test_batch_qa_reports_exact_ten_pack_gates_without_claiming_generation() -> None:
    qa_path = (
        REPO_ROOT
        / "09_泛健康日更"
        / "work"
        / "HC20260810-B01-task9-qa"
        / "HC20260810-B01-grok-manual-pack-qa-v01.md"
    )
    qa = qa_path.read_text(encoding="utf-8")
    for phrase in (
        "production 状态：10/10",
        "提示词文档：10/10",
        "镜头行：100/100",
        "复制首帧：100/100，全部 1080×1920",
        "源图/复制图字节一致：100/100",
        "空行格式：10/10",
        "动态时长门：100/100 适用行",
        "deterministic-board 不上传 Grok",
        "用户手动生成",
        "output_template",
        "尚未生成视频",
        "尚未通过最终 QA",
    ):
        assert phrase in qa


def test_008_prompt_contract_locks_counts_phone_and_noncausal_boards() -> None:
    builder = _load_builder()
    content_id = "HC20260810-008"
    production = REPO_ROOT / "09_泛健康日更" / "work" / content_id / "production" / "v01"
    storyboard = production / "02_script_storyboard" / "storyboard-v01.md"
    rows = builder._parse_storyboard(storyboard)
    deterministic = {
        row["镜号"] for row in rows if row["复用状态"] == "deterministic-board"
    }
    assert deterministic == {"S02", "S05", "S07", "S08", "S10"}
    prompts = {
        shot: builder._prompt_line(
            shot,
            content_id=content_id,
            deterministic_shots=deterministic,
        )
        for shot in builder.EXPECTED_SHOTS
    }
    builder._validate_semantic_contracts(rows, prompts, content_id=content_id)

    assert "唯一一只普通无品牌玻璃水杯" in prompts["S04"]
    assert "不伸手、不拿杯、不喝水" in prompts["S04"]
    assert "恰好三张彼此独立的无字环境板" in prompts["S05"]
    assert "不得加入人物或人物剪影" in prompts["S05"]
    for fragment in (
        "外框高宽比保持约2.05",
        "四角、外框和边框完整",
        "均匀纯深青色空屏",
        "指尖始终停在屏幕边框外",
        "中央70%始终留空",
        "不缩放、不拉伸",
        "2.23、2.36或2.50宽屏比例均一票淘汰",
    ):
        assert fragment in prompts["S06"]
    assert "恰好三张无字结果板" in prompts["S07"]
    assert "不让同一人物连续表演三项" in prompts["S07"]
    assert "不加因果箭头" in prompts["S07"]
    assert "不画因果箭头、连接路径、趋势线、流程图" in prompts["S08"]
    assert "恰好1只远处大水壶、1只手中普通玻璃杯、1碗前景零食" in prompts["S09"]
    assert "零食碗不得被遮住" in prompts["S09"]
    assert "不新增任何物体" in prompts["S09"]
    assert "医学建议" in prompts["S10"]


def test_010_prompt_contract_locks_back_shell_one_item_and_observation_window() -> None:
    builder = _load_builder()
    content_id = "HC20260810-010"
    production = REPO_ROOT / "09_泛健康日更" / "work" / content_id / "production" / "v01"
    rows = builder._parse_storyboard(production / "02_script_storyboard" / "storyboard-v01.md")
    deterministic = {
        row["镜号"] for row in rows if row["复用状态"] == "deterministic-board"
    }
    assert deterministic == {"S01", "S03", "S06", "S07", "S09", "S10"}
    prompts = {
        shot: builder._prompt_line(
            shot,
            content_id=content_id,
            deterministic_shots=deterministic,
        )
        for shot in builder.EXPECTED_SHOTS
    }
    builder._validate_semantic_contracts(rows, prompts, content_id=content_id)

    assert set(builder.PROMPT_ACTIONS_010) == set(builder.EXPECTED_SHOTS)
    assert set(builder.SHOT_SEMANTIC_CONTRACTS_010) == set(builder.EXPECTED_SHOTS)
    assert set(builder.VISUAL_REVIEW_NOTES_010) == set(builder.EXPECTED_SHOTS)
    assert "手机背壳持续朝向镜头" in prompts["S02"]
    assert "全部保持静态" in prompts["S02"]
    assert "马克杯、第二部手机" in prompts["S02"]
    for forbidden in ("屏幕", "比例", "跟踪", "screen", "ratio", "tracking", "trackable"):
        action_zh, action_en = builder.PROMPT_ACTIONS_010["S02"]
        assert forbidden not in f"{action_zh}\n{action_en}"
    assert "唯一一只正面可见餐盘" in prompts["S04"]
    assert "不再迈第二步" in prompts["S04"]
    assert "两个彼此独立的时点" in prompts["S05"]
    assert "诊断暗示" in prompts["S05"]
    assert "恰好三件普通生活物" in prompts["S08"]
    assert "只让灰色陶杯" in prompts["S08"]
    assert "折叠布和木杯垫从头到尾完全不动" in prompts["S08"]
    assert "不同时移动第二件物品" in prompts["S08"]
    assert "七天的编辑观察窗" in prompts["S09"]
    assert "不得画周历" in prompts["S09"]
    assert "待办界面" in prompts["S09"]
    assert "不形成习惯或稳定结论" in prompts["S09"]
    for shot in builder.EXPECTED_SHOTS:
        assert "纸张、纸笔、本册" in prompts[shot]
