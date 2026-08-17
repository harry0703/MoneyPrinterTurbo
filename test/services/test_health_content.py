from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from app.services import health_content


def _approved_manifest() -> dict:
    return {
        "content_id": "HC20260809-001",
        "batch_id": "HB20260809",
        "category": "metabolism",
        "audience": "35-60岁关注家庭健康的人群",
        "topic": "饭后容易困，先观察这3件事",
        "scenario": "午饭后明显困倦",
        "hook": "吃完午饭总想睡，问题可能不只是没休息好。",
        "core_claim": "饭后困倦可能与进食速度、膳食结构和睡眠状态等多种因素有关。",
        "mechanism": "单次症状不能用来自我诊断，应结合生活场景持续观察。",
        "action": "记录一周的进食时间、膳食结构和困倦程度。",
        "interaction": "你是早饭后困，还是午饭后更明显？",
        "applicable_to": ["偶发饭后困倦、希望观察生活习惯的成年人"],
        "not_applicable_to": ["已确诊糖尿病且正在调整用药的人群"],
        "medical_attention": "如果困倦持续加重，或伴明显口渴、体重异常变化，应及时就医。",
        "sources": [
            {
                "title": "中国公民健康素养——基本知识与技能（2024年版）",
                "publisher": "国家卫生健康委员会",
                "url": "https://www.nhc.gov.cn/xcs/c100123/202405/73a4927142f34152abed875634a3c13b.shtml",
                "published_at": "2024-05-28",
            }
        ],
        "medical_review": {
            "status": "approved",
            "reviewer": "内部医学审核人",
            "reviewed_at": "2026-08-09T09:00:00+08:00",
            "notes": "核心结论仅用于健康教育。",
        },
        "automated_qa": {"status": "passed", "checked_at": "2026-08-09T10:00:00+08:00"},
        "final_qa": {
            "status": "passed",
            "reviewer": "内部成片终审人",
            "reviewed_at": "2026-08-09T10:30:00+08:00",
        },
        "quality": {
            "topic_value": 18,
            "medical_credibility": 20,
            "retention": 18,
            "visual_explanation": 13,
            "save_value": 14,
            "follow_conversion": 8,
        },
    }


def _general_wellness_manifest() -> dict:
    manifest = _approved_manifest()
    manifest.update(
        {
            "content_id": "HC20260810-001",
            "batch_id": "HB20260810",
            "category": "afternoon_rhythm",
            "audience": "35-60岁关注日常生活习惯的人群",
            "content_profile": "general_wellness_uncredentialed",
            "account_name": "生活节奏看得见",
            "account_bio": "记录睡眠、进餐和日常活动中的小习惯",
            "topic": "午饭后总想打盹，先观察3件事",
            "public_topic": "午后犯困先看三件事",
            "scenario": "午饭后明显困倦",
            "hook": "吃完午饭总想睡，先别急着归因。",
            "core_claim": "饭后困倦可以从睡眠、进餐和饭后安排三个方向观察。",
            "mechanism": "同一种感受可能对应不同的生活节奏，连续对比更容易看到规律。",
            "action": "用手机闹钟或日历留下时间点，连续观察一周。",
            "interaction": "你午饭后有哪个小习惯？",
            "applicable_to": ["希望观察日常生活节奏的成年人"],
            "not_applicable_to": ["正在驾驶或操作机器的人"],
            "observations": [
                {"label": "昨晚睡眠", "detail": "回想入睡和起床时间"},
                {"label": "午餐状态", "detail": "留意速度和饱足感"},
                {"label": "饭后安排", "detail": "对比久坐和轻松活动"},
            ],
            "medical_attention": "困倦时不要继续驾驶或操作机器，先停下来休息。",
            "save_reason": "收藏这三个观察方向，连续看一周。",
            "quality": {
                "topic_value": 18,
                "medical_credibility": 19,
                "retention": 18,
                "visual_explanation": 14,
                "save_value": 14,
                "follow_conversion": 9,
            },
            "medical_review": {
                "status": "not_required",
                "reviewer": "",
                "reviewed_at": "",
                "notes": "一般生活方式内容不要求外部医学审核。",
            },
            "automated_qa": {
                "status": "passed",
                "checked_at": "2026-08-17T15:30:00+08:00",
            },
            "final_qa": {
                "status": "not_required",
                "reviewer": "",
                "reviewed_at": "",
            },
        }
    )
    return manifest


def _recursive_key_set(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for nested in value.values():
            keys.update(_recursive_key_set(nested))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for nested in value:
            keys.update(_recursive_key_set(nested))
        return keys
    return set()


def _general_wellness_topics() -> list[dict]:
    return [
        {
            "slot": slot,
            "category": f"lifestyle_{slot}",
            "topic": f"第{slot}个日常习惯观察",
            "audience": "35-60岁关注日常生活习惯的人群",
        }
        for slot in range(1, 11)
    ]


def _write_quality_only_artifact_evidence(episode_root: Path, manifest: dict) -> Path:
    artifacts = {
        "final_video": [("production/v01/06_final/final.mp4", b"final video")],
        "audio": [("production/v01/06_final/voice.wav", b"final audio")],
        "subtitle": [("production/v01/06_final/subtitles.srt", b"1\\n00:00:00,000 --> 00:00:01,000\\n" )],
        "cover": [("production/v01/06_final/cover.png", b"cover image")],
        "article_cards": [
            (f"production/v01/06_final/card-{page}.png", f"card {page}".encode())
            for page in range(1, 8)
        ],
        "edit_manifest": [("production/v01/06_final/edit-manifest.json", b"{}")],
    }
    serialized_artifacts = {}
    for kind, files in artifacts.items():
        serialized_artifacts[kind] = []
        for relative_path, content in files:
            path = episode_root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            serialized_artifacts[kind].append(
                {
                    "path": relative_path,
                    "bytes": len(content),
                    "sha256": sha256(content).hexdigest(),
                }
            )
    evidence = {
        "schema_version": "automated-qa-evidence-v01",
        "content_id": manifest["content_id"],
        "content_profile": manifest["content_profile"],
        "status": "passed",
        "artifacts": serialized_artifacts,
        "checks": {
            "video_technical": "passed",
            "video_content": "passed",
            "audio": "passed",
            "subtitles": "passed",
            "cover": "passed",
            "article_cards": "passed",
            "package": "passed",
        },
    }
    evidence_path = episode_root / "production/v01/05_qa/automated-qa-evidence-v01.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    return episode_root


def test_seed_batch_has_ten_unique_topics_with_approved_mix():
    batch = health_content.create_seed_batch("20260809")

    assert batch["batch_id"] == "HB20260809"
    assert len(batch["topics"]) == 10
    assert len({item["content_id"] for item in batch["topics"]}) == 10
    assert [item["category"] for item in batch["topics"]].count("metabolism") == 5
    assert [item["category"] for item in batch["topics"]].count("sleep") == 3
    assert [item["category"] for item in batch["topics"]].count("family_myth") == 2
    assert {item["state"] for item in batch["topics"]} == {"research_pending"}


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda item: item.update(sources=[]), "权威来源"),
        (lambda item: item.update(core_claim="一招根治所有慢性病"), "高风险表述"),
        (lambda item: item.update(medical_attention=""), "就医提醒"),
    ],
)
def test_manifest_validation_blocks_unsafe_or_incomplete_health_content(
    mutation, message
):
    manifest = _approved_manifest()
    mutation(manifest)

    with pytest.raises(health_content.HealthContentError, match=message):
        health_content.validate_manifest(manifest)


def test_general_wellness_requires_not_required_human_review_records():
    manifest = _general_wellness_manifest()
    assert health_content.validate_manifest(manifest)["medical_review"]["status"] == "not_required"
    assert health_content.validate_manifest(manifest)["final_qa"]["status"] == "not_required"


@pytest.mark.parametrize("field", ("medical_review", "final_qa"))
def test_general_wellness_rejects_fake_human_approval(field):
    manifest = _general_wellness_manifest()
    manifest[field]["status"] = "approved" if field == "medical_review" else "passed"
    manifest[field]["reviewer"] = "某审核人"
    manifest[field]["reviewed_at"] = "2026-08-17T15:30:00+08:00"
    with pytest.raises(health_content.HealthContentError, match="not_required"):
        health_content.validate_manifest(manifest)


def test_legacy_manifest_still_rejects_not_required_review_records():
    manifest = _approved_manifest()
    manifest["medical_review"].update(status="not_required", reviewer="", reviewed_at="")
    with pytest.raises(health_content.MedicalReviewRequired):
        health_content.build_publish_pack(manifest)


def test_publish_pack_requires_medical_approval_and_quality_score_85():
    manifest = _approved_manifest()
    manifest["medical_review"]["status"] = "pending"
    with pytest.raises(health_content.MedicalReviewRequired):
        health_content.build_publish_pack(manifest)

    manifest = _approved_manifest()
    manifest["quality"]["follow_conversion"] = 1
    with pytest.raises(health_content.QualityGateFailed, match="85"):
        health_content.build_publish_pack(manifest)


def test_publish_pack_requires_automated_qa_and_independent_final_review():
    manifest = _approved_manifest()
    manifest["automated_qa"]["status"] = "failed"
    with pytest.raises(health_content.FinalQARequired, match="自动QA"):
        health_content.build_publish_pack(manifest)

    manifest = _approved_manifest()
    manifest["final_qa"] = {"status": "pending"}
    with pytest.raises(health_content.FinalQARequired, match="人工终审"):
        health_content.build_publish_pack(manifest)


@pytest.mark.parametrize(
    ("medical_reviewer", "final_reviewer"),
    (
        ("reviewer-a", " reviewer-a "),
        (" reviewer-a ", "reviewer-a"),
        ("Reviewer-A", "reviewer-a"),
        ("Ｒｅｖｉｅｗｅｒ－Ａ", "reviewer-a"),
        ("KELVIN", "kelvin"),
        ("审核人", "　审核人　"),
    ),
)
def test_independent_reviewer_gate_rejects_canonical_identity_equivalents(
    medical_reviewer, final_reviewer
):
    manifest = _approved_manifest()
    manifest["medical_review"]["reviewer"] = medical_reviewer
    manifest["final_qa"]["reviewer"] = final_reviewer

    with pytest.raises(health_content.HealthContentError, match="审核人|前后空白"):
        health_content.build_publish_pack(manifest)


def test_reviewer_gate_rejects_noncanonical_boundary_whitespace():
    manifest = _approved_manifest()
    manifest["medical_review"]["reviewer"] = " reviewer-a "
    manifest["final_qa"]["reviewer"] = "reviewer-b"

    with pytest.raises(health_content.HealthContentError, match="前后空白"):
        health_content.build_publish_pack(manifest)


def test_independent_reviewer_gate_allows_distinct_chinese_names_and_internal_spaces():
    manifest = _approved_manifest()
    manifest["medical_review"]["reviewer"] = "王 小明"
    manifest["final_qa"]["reviewer"] = "李 小红"

    pack = health_content.build_publish_pack(manifest)

    assert pack["status"] == "human_pending"


def test_manifest_rejects_credential_fields_at_any_depth():
    manifest = _approved_manifest()
    manifest["sources"][0]["api_key"] = "must-not-be-stored"

    with pytest.raises(health_content.HealthContentError, match="凭证"):
        health_content.validate_manifest(manifest)


def test_automated_qa_rechecks_content_instead_of_trusting_reported_status():
    manifest = _approved_manifest()
    report = health_content.run_automated_qa(manifest)
    assert report["status"] == "passed"
    assert report["checks"] == {
        "manifest_contract": True,
        "medical_review": True,
        "quality_score": 91,
        "platform_count": 4,
        "article_card_count": 7,
    }

    manifest["core_claim"] = "一招根治所有慢性病"
    manifest["automated_qa"]["status"] = "passed"
    with pytest.raises(health_content.HealthContentError, match="高风险表述"):
        health_content.run_automated_qa(manifest)


def test_state_transition_enforces_medical_and_final_gates():
    batch = health_content.create_seed_batch("20260809")
    content_id = batch["topics"][0]["content_id"]
    manifest = _approved_manifest()

    pending_manifest = deepcopy(manifest)
    pending_manifest["medical_review"]["status"] = "pending"
    pending_batch = health_content.advance_topic_state(
        batch, content_id, "medical_review_pending", pending_manifest
    )
    with pytest.raises(health_content.MedicalReviewRequired):
        health_content.advance_topic_state(
            pending_batch, content_id, "approved", pending_manifest
        )

    batch = health_content.advance_topic_state(
        batch, content_id, "medical_review_pending", manifest
    )
    batch = health_content.advance_topic_state(batch, content_id, "approved", manifest)
    batch = health_content.advance_topic_state(
        batch, content_id, "production", manifest
    )
    batch = health_content.advance_topic_state(
        batch, content_id, "automated_qa_passed", manifest
    )
    batch = health_content.advance_topic_state(
        batch, content_id, "final_qa_passed", manifest
    )
    batch = health_content.advance_topic_state(
        batch, content_id, "ready_to_publish", manifest
    )

    topic = next(item for item in batch["topics"] if item["content_id"] == content_id)
    assert topic["state"] == "ready_to_publish"
    with pytest.raises(health_content.HealthContentError, match="人工发布"):
        health_content.advance_topic_state(batch, content_id, "published", manifest)


def test_general_wellness_uses_three_step_quality_only_flow(tmp_path):
    batch = health_content.create_seed_batch(
        "20260810",
        topics=_general_wellness_topics(),
        content_profile=health_content.GENERAL_WELLNESS_PROFILE,
    )
    manifest = _general_wellness_manifest()
    content_id = manifest["content_id"]
    artifact_root = _write_quality_only_artifact_evidence(tmp_path, manifest)

    batch = health_content.advance_topic_state(batch, content_id, "production", manifest)
    batch = health_content.advance_topic_state(
        batch, content_id, "automated_qa_passed", manifest, artifact_root
    )
    batch = health_content.advance_topic_state(
        batch, content_id, "ready_to_publish", manifest, artifact_root
    )
    assert batch["topics"][0]["state_history"][-3:] == [
        "production", "automated_qa_passed", "ready_to_publish"
    ]


def test_general_wellness_self_reported_qa_cannot_bypass_missing_artifacts():
    batch = health_content.create_seed_batch(
        "20260810",
        topics=_general_wellness_topics(),
        content_profile=health_content.GENERAL_WELLNESS_PROFILE,
    )
    manifest = _general_wellness_manifest()
    content_id = manifest["content_id"]
    batch = health_content.advance_topic_state(batch, content_id, "production", manifest)
    before = deepcopy(batch)

    with pytest.raises(health_content.FinalQARequired, match="制品证据"):
        health_content.advance_topic_state(
            batch, content_id, "automated_qa_passed", manifest
        )
    assert batch == before

    with pytest.raises(health_content.FinalQARequired, match="制品证据"):
        health_content.build_publish_pack(manifest)


def test_general_wellness_automated_qa_recomputes_bound_artifact_evidence(tmp_path):
    manifest = _general_wellness_manifest()
    artifact_root = _write_quality_only_artifact_evidence(tmp_path, manifest)
    batch = health_content.create_seed_batch(
        "20260810",
        topics=_general_wellness_topics(),
        content_profile=health_content.GENERAL_WELLNESS_PROFILE,
    )

    report = health_content.run_automated_qa(manifest, artifact_root)
    batch = health_content.advance_topic_state(
        batch, manifest["content_id"], "production", manifest, artifact_root
    )
    batch = health_content.advance_topic_state(
        batch, manifest["content_id"], "automated_qa_passed", manifest, artifact_root
    )
    pack = health_content.build_publish_pack(manifest, artifact_root)

    assert report["checks"]["artifact_evidence"] is True
    assert batch["topics"][0]["state"] == "automated_qa_passed"
    assert pack["status"] == "human_pending"


def test_general_wellness_ready_to_publish_rechecks_artifact_evidence(tmp_path):
    manifest = _general_wellness_manifest()
    artifact_root = _write_quality_only_artifact_evidence(tmp_path, manifest)
    batch = health_content.create_seed_batch(
        "20260810",
        topics=_general_wellness_topics(),
        content_profile=health_content.GENERAL_WELLNESS_PROFILE,
    )
    batch = health_content.advance_topic_state(
        batch, manifest["content_id"], "production", manifest, artifact_root
    )
    batch = health_content.advance_topic_state(
        batch, manifest["content_id"], "automated_qa_passed", manifest, artifact_root
    )
    (artifact_root / "production/v01/05_qa/automated-qa-evidence-v01.json").unlink()
    before = deepcopy(batch)

    with pytest.raises(health_content.FinalQARequired, match="制品证据"):
        health_content.advance_topic_state(
            batch, manifest["content_id"], "ready_to_publish", manifest, artifact_root
        )

    assert batch == before


@pytest.mark.parametrize("mutation", ("escape", "wrong_hash", "missing_audio", "wrong_extension", "duplicate"))
def test_general_wellness_rejects_tampered_artifact_evidence(tmp_path, mutation):
    manifest = _general_wellness_manifest()
    artifact_root = _write_quality_only_artifact_evidence(tmp_path, manifest)
    evidence_path = artifact_root / "production/v01/05_qa/automated-qa-evidence-v01.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    if mutation == "escape":
        evidence["artifacts"]["final_video"][0]["path"] = "../outside.mp4"
    elif mutation == "wrong_hash":
        evidence["artifacts"]["audio"][0]["sha256"] = "0" * 64
    elif mutation == "missing_audio":
        evidence["artifacts"].pop("audio")
    elif mutation == "wrong_extension":
        path = artifact_root / "production/v01/06_final/voice.txt"
        content = b"final audio"
        path.write_bytes(content)
        evidence["artifacts"]["audio"][0] = {
            "path": "production/v01/06_final/voice.txt",
            "bytes": len(content),
            "sha256": sha256(content).hexdigest(),
        }
    else:
        evidence["artifacts"]["cover"].append(
            evidence["artifacts"]["cover"][0].copy()
        )
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    with pytest.raises(health_content.FinalQARequired, match="制品证据"):
        health_content.run_automated_qa(manifest, artifact_root)


@pytest.mark.parametrize("illegal", ("medical_review_pending", "approved", "final_qa_passed"))
def test_general_wellness_rejects_removed_human_states(illegal):
    batch = health_content.create_seed_batch(
        "20260810",
        topics=_general_wellness_topics(),
        content_profile=health_content.GENERAL_WELLNESS_PROFILE,
    )
    with pytest.raises(health_content.HealthContentError, match="非法状态跃迁"):
        health_content.advance_topic_state(
            batch, "HC20260810-001", illegal, _general_wellness_manifest()
        )


def test_legacy_pending_review_records_are_filled_only_as_each_gate_is_reached():
    batch = health_content.create_seed_batch("20260809")
    manifest = _approved_manifest()

    content_id = batch["topics"][0]["content_id"]
    manifest["medical_review"] = {
        "status": "pending",
        "reviewer": "",
        "reviewed_at": "",
        "notes": "",
    }
    manifest["automated_qa"] = {"status": "pending", "checked_at": ""}
    manifest["final_qa"] = {
        "status": "pending",
        "reviewer": "",
        "reviewed_at": "",
    }

    batch = health_content.advance_topic_state(
        batch, content_id, "medical_review_pending", manifest
    )

    manifest["medical_review"].update(
        status="approved",
        reviewer="内部事实审核人",
        reviewed_at="2026-08-10T09:00:00+08:00",
    )
    batch = health_content.advance_topic_state(batch, content_id, "approved", manifest)

    downgraded_review = deepcopy(manifest)
    downgraded_review["medical_review"].update(
        status="pending", reviewer="", reviewed_at=""
    )
    with pytest.raises(health_content.MedicalReviewRequired):
        health_content.advance_topic_state(
            batch, content_id, "production", downgraded_review
        )
    batch = health_content.advance_topic_state(batch, content_id, "production", manifest)

    with pytest.raises(health_content.FinalQARequired, match="自动QA"):
        health_content.advance_topic_state(
            batch, content_id, "automated_qa_passed", manifest
        )
    manifest["automated_qa"].update(
        status="passed", checked_at="2026-08-10T10:00:00+08:00"
    )
    batch = health_content.advance_topic_state(
        batch, content_id, "automated_qa_passed", manifest
    )

    with pytest.raises(health_content.FinalQARequired, match="人工终审"):
        health_content.advance_topic_state(
            batch, content_id, "final_qa_passed", manifest
        )
    manifest["final_qa"].update(
        status="passed",
        reviewer="内部成片终审人",
        reviewed_at="2026-08-10T10:30:00+08:00",
    )
    batch = health_content.advance_topic_state(
        batch, content_id, "final_qa_passed", manifest
    )
    batch = health_content.advance_topic_state(
        batch, content_id, "ready_to_publish", manifest
    )

    assert batch["topics"][0]["state"] == "ready_to_publish"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda manifest: manifest.update(content_id="HC20260810-002"),
        lambda manifest: manifest.update(batch_id="HB20260809"),
        lambda manifest: manifest.pop("content_profile"),
        lambda manifest: manifest.update(content_profile="unknown_profile"),
    ],
)
def test_general_batch_rejects_manifest_identity_or_profile_mismatch(mutation):
    batch = health_content.create_seed_batch(
        "20260810",
        topics=_general_wellness_topics(),
        content_profile=health_content.GENERAL_WELLNESS_PROFILE,
    )
    manifest = _general_wellness_manifest()
    mutation(manifest)

    with pytest.raises(health_content.HealthContentError, match="匹配|profile"):
        health_content.advance_topic_state(
            batch,
            "HC20260810-001",
            "medical_review_pending",
            manifest,
        )


def test_explicit_unknown_manifest_profile_fails_closed_for_direct_packaging():
    manifest = _general_wellness_manifest()
    manifest["content_profile"] = "unknown_profile"
    manifest["quality"] = _approved_manifest()["quality"]
    manifest["action"] = "去医院检查"

    with pytest.raises(health_content.HealthContentError, match="profile"):
        health_content.build_publish_pack(manifest)


def test_profileless_direct_call_is_legacy_only_not_general_shaped():
    manifest = _general_wellness_manifest()
    manifest.pop("content_profile")

    with pytest.raises(health_content.HealthContentError, match="profile"):
        health_content.build_publish_pack(manifest)


def test_legacy_91_point_manifest_cannot_advance_general_batch():
    batch = health_content.create_seed_batch(
        "20260810",
        topics=_general_wellness_topics(),
        content_profile=health_content.GENERAL_WELLNESS_PROFILE,
    )
    legacy_manifest = _approved_manifest()
    legacy_manifest["content_id"] = "HC20260810-001"
    legacy_manifest["batch_id"] = "HB20260810"

    with pytest.raises(health_content.HealthContentError, match="profile"):
        health_content.advance_topic_state(
            batch,
            "HC20260810-001",
            "medical_review_pending",
            legacy_manifest,
        )


def test_publish_pack_contains_seven_cards_and_four_distinct_platform_packages():
    pack = health_content.build_publish_pack(_approved_manifest())

    assert pack["status"] == "human_pending"
    assert len(pack["article_cards"]) == 7
    assert [card["page"] for card in pack["article_cards"]] == list(range(1, 8))
    assert set(pack["platforms"]) == {
        "wechat_channels",
        "douyin",
        "xiaohongshu",
        "kuaishou",
    }
    assert {item["status"] for item in pack["platforms"].values()} == {"human_pending"}
    assert all(len(item["titles"]) == 3 for item in pack["platforms"].values())
    assert all(len(item["cover_texts"]) == 2 for item in pack["platforms"].values())
    assert len({item["body"] for item in pack["platforms"].values()}) == 4


def test_general_wellness_publish_pack_uses_only_lifestyle_public_copy(tmp_path):
    manifest = _general_wellness_manifest()
    pack = health_content.build_publish_pack(
        manifest, _write_quality_only_artifact_evidence(tmp_path, manifest)
    )
    serialized = str(pack)

    assert [card["role"] for card in pack["article_cards"]] == [
        "封面",
        "场景",
        "观察一",
        "观察二",
        "观察三",
        "小尝试",
        "总结",
    ]
    for term in (
        "疾病",
        "诊断",
        "治疗",
        "医生",
        "医务",
        "医院",
        "门诊",
        "检查",
        "血糖",
        "血压",
        "血脂",
        "尿酸",
        "血氧",
        "体温",
        "减重云",
        "健康卫士",
        "体脂秤",
        "医疗器械",
        "健康科普",
        "不替代诊疗",
    ):
        assert term not in serialized
    assert all(
        "习惯" in package["pinned_comment"]
        for package in pack["platforms"].values()
    )
    assert {
        platform: package["tags"] for platform, package in pack["platforms"].items()
    } == {
        "wechat_channels": ["生活观察", "日常习惯", "生活节奏"],
        "douyin": ["生活小习惯", "日常记录", "状态管理"],
        "xiaohongshu": ["生活方式", "习惯养成", "日常观察"],
        "kuaishou": ["生活经验", "日常习惯", "过日子"],
    }


def test_general_wellness_pack_uses_verified_artifacts_but_not_human_review(tmp_path):
    manifest = _general_wellness_manifest()

    pack = health_content.build_publish_pack(
        manifest, _write_quality_only_artifact_evidence(tmp_path, manifest)
    )

    assert pack["status"] == "human_pending"
    assert _recursive_key_set(pack).isdisjoint(
        {
            "medical_review",
            "automated_qa",
            "final_qa",
            "reviewer",
            "reviewed_at",
            "checked_at",
            "notes",
        }
    )


def test_general_wellness_pack_does_not_trust_pending_manifest_qa_status(tmp_path):
    manifest = _general_wellness_manifest()
    manifest["automated_qa"]["status"] = "pending"

    pack = health_content.build_publish_pack(
        manifest, _write_quality_only_artifact_evidence(tmp_path, manifest)
    )

    assert pack["status"] == "human_pending"


def test_general_wellness_pack_does_not_trust_manifest_qa_timestamp(tmp_path):
    manifest = _general_wellness_manifest()
    manifest["automated_qa"]["checked_at"] = ""

    pack = health_content.build_publish_pack(
        manifest, _write_quality_only_artifact_evidence(tmp_path, manifest)
    )

    assert pack["status"] == "human_pending"


def test_general_wellness_profile_requires_identity_observations_and_save_reason():
    mutations = (
        lambda item: item.update(account_name="其他账号"),
        lambda item: item.update(account_bio="其他简介"),
        lambda item: item.update(observations=item["observations"][:2]),
        lambda item: item.update(save_reason=""),
        lambda item: item.pop("public_topic"),
        lambda item: item.pop("medical_review"),
        lambda item: item["automated_qa"].pop("checked_at"),
        lambda item: item["final_qa"].pop("reviewer"),
    )

    for mutation in mutations:
        manifest = _general_wellness_manifest()
        mutation(manifest)
        with pytest.raises(health_content.HealthContentError):
            health_content.validate_manifest(manifest)


def test_general_wellness_quality_gate_requires_92_total(tmp_path):
    score_91 = _general_wellness_manifest()
    score_91["quality"]["follow_conversion"] = 8
    with pytest.raises(health_content.QualityGateFailed, match="92"):
        health_content.build_publish_pack(score_91)

    manifest = _general_wellness_manifest()
    pack = health_content.build_publish_pack(
        manifest, _write_quality_only_artifact_evidence(tmp_path, manifest)
    )
    assert pack["quality_score"] == 92


@pytest.mark.parametrize(
    ("field", "below_floor", "compensation_field", "compensation_value"),
    (
        ("topic_value", 17, "medical_credibility", 20),
        ("medical_credibility", 17, "topic_value", 20),
        ("retention", 17, "medical_credibility", 20),
        ("visual_explanation", 13, "medical_credibility", 20),
        ("save_value", 12, "topic_value", 20),
        ("follow_conversion", 7, "topic_value", 20),
    ),
)
def test_general_wellness_quality_gate_requires_each_floor_above_92_total(
    field, below_floor, compensation_field, compensation_value
):
    manifest = _general_wellness_manifest()
    manifest["quality"][field] = below_floor
    manifest["quality"][compensation_field] = compensation_value

    assert sum(manifest["quality"].values()) == 92
    with pytest.raises(health_content.QualityGateFailed, match=field):
        health_content.build_publish_pack(manifest)


def test_general_wellness_forbidden_terms_are_checked_only_in_public_fields(tmp_path):
    internal_only = _general_wellness_manifest()
    internal_only["medical_review"]["notes"] = "医生已检查内部事实依据。"
    health_content.validate_manifest(internal_only)
    assert "医生" not in str(
        health_content.build_publish_pack(
            internal_only, _write_quality_only_artifact_evidence(tmp_path, internal_only)
        )
    )

    public_copy = _general_wellness_manifest()
    public_copy["action"] = "建议去医院检查。"
    with pytest.raises(health_content.HealthContentError, match="禁止公开使用"):
        health_content.validate_manifest(public_copy)


@pytest.mark.parametrize(
    "term",
    (
        "根治",
        "治愈",
        "一招见效",
        "排毒",
        "逆转所有",
        "医生不会告诉你",
        "停药",
        "保证立即有用",
        "疾病",
        "诊断",
        "治疗",
        "医生",
        "医务",
        "医院",
        "门诊",
        "检查",
        "血糖",
        "血压",
        "血脂",
        "尿酸",
        "血氧",
        "体温",
        "减重云",
        "健康卫士",
        "体脂秤",
        "医疗器械",
        "健康科普",
        "不替代诊疗",
        "专家",
        "处方",
        "医学曲线",
    ),
)
def test_general_wellness_rejects_complete_public_policy_vocabulary(term):
    manifest = _general_wellness_manifest()
    manifest["interaction"] = f"请分享你的习惯：{term}"

    with pytest.raises(health_content.HealthContentError, match="禁止公开使用"):
        health_content.validate_manifest(manifest)


def test_general_wellness_rejects_exact_immediate_effect_phrase_in_input():
    manifest = _general_wellness_manifest()
    manifest["interaction"] = "承诺立刻见效"

    with pytest.raises(health_content.HealthContentError, match="禁止公开使用"):
        health_content.validate_manifest(manifest)


def test_general_wellness_rejects_exact_immediate_effect_phrase_in_final_pack(
    monkeypatch, tmp_path
):
    original = health_content._platform_package

    def unsafe_generated_package(manifest, platform):
        package = original(manifest, platform)
        package["body"] = f"{package['body']} 承诺立刻见效"
        return package

    monkeypatch.setattr(health_content, "_platform_package", unsafe_generated_package)

    with pytest.raises(health_content.HealthContentError, match="禁止公开使用"):
        manifest = _general_wellness_manifest()
        health_content.build_publish_pack(
            manifest, _write_quality_only_artifact_evidence(tmp_path, manifest)
        )


@pytest.mark.parametrize(
    "field",
    (
        "public_topic",
        "scenario",
        "hook",
        "core_claim",
        "mechanism",
        "action",
        "interaction",
        "applicable_to",
        "not_applicable_to",
        "medical_attention",
        "observations",
        "save_reason",
    ),
)
def test_general_wellness_scans_every_public_content_field(field):
    manifest = _general_wellness_manifest()
    if field in {"applicable_to", "not_applicable_to"}:
        manifest[field] = ["一招见效"]
    elif field == "observations":
        manifest[field][0]["detail"] = "一招见效"
    else:
        manifest[field] = "一招见效"

    with pytest.raises(health_content.HealthContentError, match="禁止公开使用"):
        health_content.validate_manifest(manifest)


def test_general_wellness_internal_policy_terms_are_allowed_but_never_published(tmp_path):
    manifest = _general_wellness_manifest()
    internal_terms = "医院专家核对处方与医学曲线，仅作内部审核。"
    manifest["sources"][0]["title"] = internal_terms
    manifest["medical_review"]["notes"] = internal_terms

    pack = health_content.build_publish_pack(
        manifest, _write_quality_only_artifact_evidence(tmp_path, manifest)
    )

    assert "医院" not in str(pack)
    assert "专家" not in str(pack)
    assert "处方" not in str(pack)
    assert "医学曲线" not in str(pack)


@pytest.mark.parametrize(
    "field",
    (
        "content_id",
        "batch_id",
        "category",
        "audience",
        "topic",
        "public_topic",
        "scenario",
        "hook",
        "core_claim",
        "mechanism",
        "action",
        "interaction",
        "medical_attention",
        "save_reason",
    ),
)
@pytest.mark.parametrize("invalid_value", (None, 42, True, [], {}, "   "))
def test_general_wellness_rejects_non_string_or_blank_manifest_text(
    field, invalid_value
):
    manifest = _general_wellness_manifest()
    manifest[field] = invalid_value

    with pytest.raises(health_content.HealthContentError):
        health_content.validate_manifest(manifest)


@pytest.mark.parametrize("invalid_value", (None, 42, True, [], {}, "   "))
def test_general_wellness_requires_nonblank_string_public_topic(invalid_value):
    manifest = _general_wellness_manifest()
    manifest["public_topic"] = invalid_value

    with pytest.raises(health_content.HealthContentError, match="公开题面"):
        health_content.validate_manifest(manifest)


def test_general_wellness_rejects_forbidden_public_topic():
    manifest = _general_wellness_manifest()
    manifest["public_topic"] = "专家教你看午后状态"

    with pytest.raises(health_content.HealthContentError, match="禁止公开使用"):
        health_content.validate_manifest(manifest)


def test_general_wellness_rejects_public_topic_equal_to_internal_topic_after_normalization():
    manifest = _general_wellness_manifest()
    manifest["topic"] = "下午最难的任务，什么时候做更顺"
    manifest["public_topic"] = "  下午最难的任务，什么时候做更顺  "

    with pytest.raises(health_content.HealthContentError, match="公开题面.*内部题面"):
        health_content.validate_manifest(manifest)
    with pytest.raises(health_content.HealthContentError, match="公开题面.*内部题面"):
        health_content.build_publish_pack(manifest)


def test_general_wellness_rejects_exact_most_difficult_phrase_without_blocking_recent():
    manifest = _general_wellness_manifest()
    manifest["public_topic"] = "下午最难的任务何时做"

    with pytest.raises(health_content.HealthContentError, match="禁止公开使用"):
        health_content.validate_manifest(manifest)

    safe_manifest = _general_wellness_manifest()
    safe_manifest["public_topic"] = "最近午后感受怎样记录"

    health_content.validate_manifest(safe_manifest)


@pytest.mark.parametrize(
    ("internal_topic", "public_topic"),
    (
        ("午后嘴馋，先分清饿、渴还是习惯", "午后嘴馋先记三类线索"),
        ("下午最难的任务，什么时候做更顺", "下午难任务何时做更顺"),
        ("连续7天，找到自己的午后规律", "连续七天记录午后变化"),
    ),
)
def test_general_wellness_publish_pack_never_leaks_internal_approved_topic(
    internal_topic, public_topic, tmp_path
):
    manifest = _general_wellness_manifest()
    manifest["topic"] = internal_topic
    manifest["public_topic"] = public_topic

    pack = health_content.build_publish_pack(
        manifest, _write_quality_only_artifact_evidence(tmp_path, manifest)
    )
    serialized = str(pack)

    assert internal_topic not in serialized
    assert public_topic in serialized


@pytest.mark.parametrize("invalid_value", (None, 42, True, [], {}, "   "))
def test_general_wellness_rejects_non_string_nested_text(invalid_value):
    manifests = []

    source = _general_wellness_manifest()
    source["sources"][0]["title"] = invalid_value
    manifests.append(source)

    observation = _general_wellness_manifest()
    observation["observations"][0]["detail"] = invalid_value
    manifests.append(observation)

    audience_boundary = _general_wellness_manifest()
    audience_boundary["applicable_to"][0] = invalid_value
    manifests.append(audience_boundary)

    medical_review = _general_wellness_manifest()
    medical_review["medical_review"]["notes"] = invalid_value
    manifests.append(medical_review)

    automated_qa = _general_wellness_manifest()
    automated_qa["automated_qa"]["checked_at"] = invalid_value
    manifests.append(automated_qa)

    final_qa = _general_wellness_manifest()
    final_qa["final_qa"]["reviewer"] = invalid_value
    manifests.append(final_qa)

    for manifest in manifests:
        with pytest.raises(health_content.HealthContentError):
            health_content.validate_manifest(manifest)


def test_metric_snapshots_are_unique_per_content_platform_format_and_window():
    rows = [
        {
            "content_id": "HC20260809-001",
            "platform": "douyin",
            "format": "video",
            "window_hours": 72,
            "views": 1000,
            "completion_rate": 0.66,
            "save_rate": 0.018,
            "share_rate": 0.011,
            "follow_rate": 0.009,
        }
    ]
    duplicate = deepcopy(rows[0])

    with pytest.raises(health_content.HealthContentError, match="重复指标"):
        health_content.validate_metric_snapshots(rows + [duplicate])


def test_chase_suggestions_ignore_24h_and_promote_strong_72h_series():
    observations = [
        {
            "content_id": "HC20260809-001",
            "category": "metabolism",
            "platform": "douyin",
            "format": "video",
            "window_hours": 24,
            "views": 800,
            "completion_rate": 0.80,
            "save_rate": 0.02,
            "share_rate": 0.012,
            "follow_rate": 0.01,
        },
        {
            "content_id": "HC20260809-001",
            "category": "metabolism",
            "platform": "douyin",
            "format": "video",
            "window_hours": 72,
            "views": 3000,
            "completion_rate": 0.78,
            "save_rate": 0.018,
            "share_rate": 0.012,
            "follow_rate": 0.009,
        },
    ]

    proposals = health_content.propose_chase_updates(observations)

    assert proposals == [
        {
            "type": "human_review_chase_slot",
            "content_id": "HC20260809-001",
            "category": "metabolism",
            "reason": "72h完播、收藏、分享和关注指标均达到放大线",
            "suggested_followups": 3,
        }
    ]


def test_chase_suggestions_skip_incomplete_72h_metrics():
    observations = [
        {
            "content_id": "HC20260809-001",
            "category": "metabolism",
            "platform": "douyin",
            "format": "video",
            "window_hours": 72,
            "views": 3000,
            "completion_rate": 0.78,
            "save_rate": None,
            "share_rate": 0.012,
            "follow_rate": 0.009,
        }
    ]

    assert health_content.propose_chase_updates(observations) == []
