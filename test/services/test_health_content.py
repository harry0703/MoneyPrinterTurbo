from __future__ import annotations

from copy import deepcopy

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
        }
    )
    return manifest


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


def test_general_wellness_publish_pack_uses_only_lifestyle_public_copy():
    pack = health_content.build_publish_pack(_general_wellness_manifest())
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


def test_general_wellness_profile_requires_identity_observations_and_save_reason():
    mutations = (
        lambda item: item.update(account_name="其他账号"),
        lambda item: item.update(account_bio="其他简介"),
        lambda item: item.update(observations=item["observations"][:2]),
        lambda item: item.update(save_reason=""),
        lambda item: item.pop("medical_review"),
        lambda item: item["automated_qa"].pop("checked_at"),
        lambda item: item["final_qa"].pop("reviewer"),
    )

    for mutation in mutations:
        manifest = _general_wellness_manifest()
        mutation(manifest)
        with pytest.raises(health_content.HealthContentError):
            health_content.validate_manifest(manifest)


def test_general_wellness_quality_gate_requires_92_total_and_each_floor():
    score_91 = _general_wellness_manifest()
    score_91["quality"]["follow_conversion"] = 8
    with pytest.raises(health_content.QualityGateFailed, match="92"):
        health_content.build_publish_pack(score_91)

    pack = health_content.build_publish_pack(_general_wellness_manifest())
    assert pack["quality_score"] == 92

    below_floor = _general_wellness_manifest()
    below_floor["quality"]["visual_explanation"] = 13
    below_floor["quality"]["medical_credibility"] = 20
    with pytest.raises(health_content.QualityGateFailed, match="visual_explanation"):
        health_content.build_publish_pack(below_floor)


def test_general_wellness_forbidden_terms_are_checked_only_in_public_fields():
    internal_only = _general_wellness_manifest()
    internal_only["medical_review"]["notes"] = "医生已检查内部事实依据。"
    health_content.validate_manifest(internal_only)
    assert "医生" not in str(health_content.build_publish_pack(internal_only))

    public_copy = _general_wellness_manifest()
    public_copy["action"] = "建议去医院检查。"
    with pytest.raises(health_content.HealthContentError, match="禁止公开使用"):
        health_content.validate_manifest(public_copy)


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
