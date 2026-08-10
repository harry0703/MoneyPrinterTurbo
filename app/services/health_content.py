"""面向35—60岁家庭健康人群的安全内容生产与四平台发布包。"""

from __future__ import annotations

import csv
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Iterable, Mapping


PLATFORMS = ("wechat_channels", "douyin", "xiaohongshu", "kuaishou")
GENERAL_WELLNESS_PROFILE = "general_wellness_uncredentialed"
FORBIDDEN_CLAIMS = (
    "根治",
    "治愈",
    "一招见效",
    "排毒",
    "逆转所有",
    "医生不会告诉你",
    "停药",
    "保证",
    "立即见效",
    "立即有用",
)
GENERAL_WELLNESS_PUBLIC_FORBIDDEN = FORBIDDEN_CLAIMS + (
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
    "诊疗",
    "专家",
    "医师",
    "护士",
    "药师",
    "营养师",
    "处方",
    "药方",
    "诊所",
    "检测",
    "检验",
    "医学曲线",
    "医疗曲线",
)
GENERAL_WELLNESS_SCORE_FLOORS = {
    "topic_value": 18,
    "medical_credibility": 18,
    "retention": 18,
    "visual_explanation": 14,
    "save_value": 13,
    "follow_conversion": 8,
}
_GENERAL_WELLNESS_ACCOUNT_NAME = "生活节奏看得见"
_GENERAL_WELLNESS_ACCOUNT_BIO = "记录睡眠、进餐和日常活动中的小习惯"
_GENERAL_WELLNESS_ONLY_FIELDS = (
    "account_name",
    "account_bio",
    "observations",
    "save_reason",
)
_GENERAL_WELLNESS_PUBLIC_FIELDS = (
    "account_name",
    "account_bio",
    "topic",
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
)
class HealthContentError(ValueError):
    """健康内容合同或数据不合法。"""


class MedicalReviewRequired(HealthContentError):
    """缺少真实医学人工审核。"""


class QualityGateFailed(HealthContentError):
    """发布前质量分未达标。"""


class FinalQARequired(HealthContentError):
    """缺少自动QA或独立人工终审。"""


_SEED_TOPICS = (
    ("metabolism", "饭后总困，先观察这3件事"),
    ("metabolism", "空腹血糖正常，不等于什么"),
    ("metabolism", "腰围为什么值得持续记录"),
    ("metabolism", "久坐之后，最现实的活动方法"),
    ("metabolism", "晚饭时间和份量怎样记录更有用"),
    ("sleep", "睡够8小时为什么还是累"),
    ("sleep", "午睡多久更不容易影响晚上"),
    ("sleep", "打鼾出现哪些情况值得进一步检查"),
    ("family_myth", "无糖食品真的可以随便吃吗"),
    ("family_myth", "父母买保健品前先问这3个问题"),
)


def create_seed_batch(
    date: str,
    topics: Iterable[Mapping] | None = None,
    content_profile: str | None = None,
) -> dict:
    """创建10主题小测试批次，所有内容从资料核验状态开始。"""
    if not isinstance(date, str) or len(date) != 8 or not date.isdigit():
        raise HealthContentError("日期必须为YYYYMMDD")
    if topics is None:
        if content_profile is not None:
            raise HealthContentError("指定内容 profile 时必须提供主题")
        normalized_topics = [
            {
                "slot": index,
                "content_id": f"HC{date}-{index:03d}",
                "category": category,
                "topic": topic,
                "audience": "35-60岁关注家庭健康的人群",
                "state": "research_pending",
            }
            for index, (category, topic) in enumerate(_SEED_TOPICS, start=1)
        ]
    else:
        if content_profile != GENERAL_WELLNESS_PROFILE:
            raise HealthContentError("不支持的内容 profile")
        supplied_topics = list(topics)
        if len(supplied_topics) != 10:
            raise HealthContentError("主题文件必须正好包含10个主题")
        slots = [item.get("slot") for item in supplied_topics if isinstance(item, Mapping)]
        if len(slots) != 10 or any(type(slot) is not int for slot in slots):
            raise HealthContentError("每个主题必须包含整数 slot")
        if len(set(slots)) != 10 or set(slots) != set(range(1, 11)):
            raise HealthContentError("主题 slot 必须唯一且覆盖1到10")

        normalized_topics = []
        for item in sorted(supplied_topics, key=lambda value: value["slot"]):
            _reject_credentials(item)
            if any(
                not _is_nonempty_text(item.get(field))
                for field in ("category", "topic", "audience")
            ):
                raise HealthContentError("每个主题必须包含 category、topic 和 audience")
            _reject_general_wellness_public_terms(
                [item["category"], item["topic"], item["audience"]]
            )
            slot = item["slot"]
            normalized_topics.append(
                {
                    "slot": slot,
                    "content_id": f"HC{date}-{slot:03d}",
                    "category": str(item["category"]).strip(),
                    "topic": str(item["topic"]).strip(),
                    "audience": str(item["audience"]).strip(),
                    "state": "research_pending",
                }
            )

    batch = {
        "schema": "health-batch-v1",
        "batch_id": f"HB{date}",
        "date": date,
        "cadence": "daily",
        "publication_policy": "human_only_all_four",
        "topics": normalized_topics,
    }
    if content_profile is not None:
        batch["content_profile"] = content_profile
    return batch


def _require_text(manifest: Mapping, field: str, label: str) -> None:
    if not _is_nonempty_text(manifest.get(field)):
        raise HealthContentError(f"缺少{label}")


def _is_nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_manifest(manifest: Mapping) -> dict:
    """验证事实卡、边界和安全表述，不会自动推进状态。"""
    _reject_credentials(manifest)
    if (
        "content_profile" in manifest
        and manifest.get("content_profile") != GENERAL_WELLNESS_PROFILE
    ):
        raise HealthContentError("不支持的内容 profile")
    if "content_profile" not in manifest and any(
        field in manifest for field in _GENERAL_WELLNESS_ONLY_FIELDS
    ):
        raise HealthContentError("通用生活方式 manifest 必须显式声明 profile")
    for field, label in (
        ("content_id", "内容ID"),
        ("batch_id", "批次ID"),
        ("category", "内容分类"),
        ("audience", "目标人群"),
        ("topic", "主题"),
        ("scenario", "生活场景"),
        ("hook", "开场表述"),
        ("core_claim", "核心结论"),
        ("mechanism", "解释"),
        ("action", "可执行动作"),
        ("interaction", "互动问题"),
        ("medical_attention", "就医提醒"),
    ):
        _require_text(manifest, field, label)

    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise HealthContentError("至少需要一个权威来源")
    for source in sources:
        if not isinstance(source, Mapping) or not all(
            _is_nonempty_text(source.get(field))
            for field in ("title", "publisher", "url", "published_at")
        ):
            raise HealthContentError("权威来源必须包含标题、发布方、链接和日期")

    for field in ("applicable_to", "not_applicable_to"):
        boundaries = manifest.get(field)
        if (
            not isinstance(boundaries, list)
            or not boundaries
            or any(not _is_nonempty_text(item) for item in boundaries)
        ):
            raise HealthContentError("必须用非空文本列表声明适用与不适用人群")

    _validate_review_contract_text(manifest)
    if manifest.get("content_profile") == GENERAL_WELLNESS_PROFILE:
        _validate_general_wellness_manifest(manifest)
    else:
        public_values = [
            manifest.get(field) for field in _GENERAL_WELLNESS_PUBLIC_FIELDS
        ]
        _reject_public_terms(public_values, FORBIDDEN_CLAIMS, "检测到高风险表述")
    return deepcopy(dict(manifest))


def _validate_general_wellness_manifest(manifest: Mapping) -> None:
    if manifest.get("account_name") != _GENERAL_WELLNESS_ACCOUNT_NAME:
        raise HealthContentError("通用生活方式内容的账号名不匹配")
    if manifest.get("account_bio") != _GENERAL_WELLNESS_ACCOUNT_BIO:
        raise HealthContentError("通用生活方式内容的账号简介不匹配")

    observations = manifest.get("observations")
    if not isinstance(observations, list) or len(observations) != 3:
        raise HealthContentError("通用生活方式内容必须有三条观察")
    for observation in observations:
        if not isinstance(observation, Mapping) or not all(
            _is_nonempty_text(observation.get(field))
            for field in ("label", "detail")
        ):
            raise HealthContentError("观察项必须包含标签和详情")
    _require_text(manifest, "save_reason", "收藏理由")

    public_values = [manifest.get(field) for field in _GENERAL_WELLNESS_PUBLIC_FIELDS]
    _reject_general_wellness_public_terms(public_values)


def _validate_review_contract_text(manifest: Mapping) -> None:
    review_fields = (
        (
            "medical_review",
            ("status", "reviewer", "reviewed_at", "notes"),
            MedicalReviewRequired,
            "医学审核记录",
        ),
        (
            "automated_qa",
            ("status", "checked_at"),
            FinalQARequired,
            "自动QA记录",
        ),
        (
            "final_qa",
            ("status", "reviewer", "reviewed_at"),
            FinalQARequired,
            "人工终审记录",
        ),
    )
    for field, required_keys, error_type, label in review_fields:
        value = manifest.get(field)
        if not isinstance(value, Mapping) or any(
            not _is_nonempty_text(value.get(key)) for key in required_keys
        ):
            raise error_type(f"{label}必须包含完整的非空文本字段")


def _reject_general_wellness_public_terms(value: object) -> None:
    _reject_public_terms(
        value,
        GENERAL_WELLNESS_PUBLIC_FORBIDDEN,
        "通用生活方式内容禁止公开使用",
    )


def _reject_public_terms(value: object, terms: Iterable[str], label: str) -> None:
    texts: list[str] = []

    def collect(nested: object) -> None:
        if isinstance(nested, Mapping):
            for item in nested.values():
                collect(item)
        elif isinstance(nested, (list, tuple)):
            for item in nested:
                collect(item)
        elif nested is not None:
            texts.append(str(nested))

    collect(value)
    searchable = " ".join(texts)
    matched = [term for term in terms if term in searchable]
    if matched:
        raise HealthContentError(f"{label}: {', '.join(matched)}")


_CREDENTIAL_KEYS = {
    "api_key",
    "apikey",
    "access_key",
    "token",
    "secret",
    "password",
    "cookie",
    "session",
    "private_key",
    "seed",
    "client_secret",
    "bearer",
}


def _reject_credentials(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
            if normalized in _CREDENTIAL_KEYS:
                raise HealthContentError(f"内容合同不得保存凭证字段: {key}")
            _reject_credentials(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_credentials(nested)


def calculate_quality_score(manifest: Mapping) -> int:
    quality = manifest.get("quality")
    expected = {
        "topic_value": 20,
        "medical_credibility": 20,
        "retention": 20,
        "visual_explanation": 15,
        "save_value": 15,
        "follow_conversion": 10,
    }
    if not isinstance(quality, Mapping) or set(quality) != set(expected):
        raise HealthContentError("质量评分字段不完整")
    for field, maximum in expected.items():
        value = quality[field]
        if not isinstance(value, int) or not 0 <= value <= maximum:
            raise HealthContentError(f"质量评分{field}超出允许范围")
    return sum(quality.values())


def _require_medical_review(manifest: Mapping) -> Mapping:
    review = manifest.get("medical_review")
    if not isinstance(review, Mapping) or review.get("status") != "approved":
        raise MedicalReviewRequired("必须先完成真实医学人工审核")
    if (
        not _is_nonempty_text(review.get("reviewer"))
        or not _is_nonempty_text(review.get("reviewed_at"))
    ):
        raise MedicalReviewRequired("医学审核记录缺少审核人或时间")
    return review


def _require_final_qa(manifest: Mapping, medical_review: Mapping) -> None:
    final_qa = manifest.get("final_qa")
    if (
        not isinstance(final_qa, Mapping)
        or final_qa.get("status") != "passed"
        or not _is_nonempty_text(final_qa.get("reviewer"))
        or not _is_nonempty_text(final_qa.get("reviewed_at"))
    ):
        raise FinalQARequired("必须有独立人工终审通过记录")
    if final_qa["reviewer"] == medical_review["reviewer"]:
        raise FinalQARequired("医学审核与人工终审必须由不同审核人执行")


def run_automated_qa(manifest: Mapping) -> dict:
    """从当前内容重新计算QA，不信任输入中自报的通过结果。"""
    validated = validate_manifest(manifest)
    _require_medical_review(validated)
    score = calculate_quality_score(validated)
    _require_quality_gate(validated, score, "自动QA")
    return {
        "status": "passed",
        "checks": {
            "manifest_contract": True,
            "medical_review": True,
            "quality_score": score,
            "platform_count": len(PLATFORMS),
            "article_card_count": len(_article_cards(validated)),
        },
    }


def _require_quality_gate(manifest: Mapping, score: int, stage: str) -> None:
    if manifest.get("content_profile") != GENERAL_WELLNESS_PROFILE:
        if score < 85:
            raise QualityGateFailed(f"{stage}要求质量分至少85，当前为{score}")
        return
    if score < 92:
        raise QualityGateFailed(f"{stage}要求通用生活方式质量分至少92，当前为{score}")
    quality = manifest["quality"]
    for field, floor in GENERAL_WELLNESS_SCORE_FLOORS.items():
        if quality[field] < floor:
            raise QualityGateFailed(
                f"{stage}要求{field}至少{floor}，当前为{quality[field]}"
            )


_STATE_TRANSITIONS = {
    "research_pending": "medical_review_pending",
    "medical_review_pending": "approved",
    "approved": "production",
    "production": "automated_qa_passed",
    "automated_qa_passed": "final_qa_passed",
    "final_qa_passed": "ready_to_publish",
}


def advance_topic_state(
    batch: Mapping, content_id: str, target_state: str, manifest: Mapping
) -> dict:
    """按固定门禁推进单期内容，不允许自动进入已发布。"""
    if target_state == "published":
        raise HealthContentError("最终平台提交必须人工发布并另行记录回执")
    updated = deepcopy(dict(batch))
    topic = next(
        (
            item
            for item in updated.get("topics", [])
            if item.get("content_id") == content_id
        ),
        None,
    )
    if topic is None:
        raise HealthContentError(f"批次中不存在内容: {content_id}")
    current_state = topic.get("state")
    if _STATE_TRANSITIONS.get(current_state) != target_state:
        raise HealthContentError(f"非法状态跃迁: {current_state} -> {target_state}")

    _require_manifest_matches_batch(batch, content_id, manifest)
    validated = validate_manifest(manifest)
    if target_state == "approved":
        _require_medical_review(validated)
    elif target_state == "automated_qa_passed":
        run_automated_qa(validated)
    elif target_state == "final_qa_passed":
        review = _require_medical_review(validated)
        run_automated_qa(validated)
        _require_final_qa(validated, review)
    elif target_state == "ready_to_publish":
        build_publish_pack(validated)

    topic["state"] = target_state
    topic.setdefault("state_history", []).append(target_state)
    return updated


def _require_manifest_matches_batch(
    batch: Mapping, content_id: str, manifest: Mapping
) -> None:
    if manifest.get("content_id") != content_id:
        raise HealthContentError("manifest content_id 与当前主题不匹配")
    if manifest.get("batch_id") != batch.get("batch_id"):
        raise HealthContentError("manifest batch_id 与当前批次不匹配")

    batch_has_profile = "content_profile" in batch
    manifest_has_profile = "content_profile" in manifest
    if batch_has_profile != manifest_has_profile:
        raise HealthContentError("manifest profile 与当前批次不匹配")
    if batch_has_profile:
        batch_profile = batch.get("content_profile")
        manifest_profile = manifest.get("content_profile")
        if batch_profile != GENERAL_WELLNESS_PROFILE:
            raise HealthContentError("不支持的批次 profile")
        if manifest_profile != batch_profile:
            raise HealthContentError("manifest profile 与当前批次不匹配")


def _article_cards(manifest: Mapping) -> list[dict]:
    if manifest.get("content_profile") == GENERAL_WELLNESS_PROFILE:
        observations = manifest["observations"]
        cards = (
            ("封面", manifest["topic"]),
            ("场景", manifest["scenario"]),
            ("观察一", f"{observations[0]['label']}：{observations[0]['detail']}"),
            ("观察二", f"{observations[1]['label']}：{observations[1]['detail']}"),
            ("观察三", f"{observations[2]['label']}：{observations[2]['detail']}"),
            ("小尝试", manifest["action"]),
            ("总结", f"{manifest['save_reason']} {manifest['interaction']}"),
        )
        return [
            {"page": page, "role": role, "text": text}
            for page, (role, text) in enumerate(cards, start=1)
        ]
    cards = (
        ("封面", manifest["topic"]),
        ("痛点", manifest["scenario"]),
        ("误区", "单次感受不能直接当作疾病诊断。"),
        ("机制", manifest["mechanism"]),
        ("行动", manifest["action"]),
        ("边界", manifest["medical_attention"]),
        ("总结", f"{manifest['interaction']} 下一期继续讲家庭健康观察方法。"),
    )
    return [
        {"page": page, "role": role, "text": text}
        for page, (role, text) in enumerate(cards, start=1)
    ]


def _platform_package(manifest: Mapping, platform: str) -> dict:
    topic = manifest["topic"]
    hook = manifest["hook"]
    action = manifest["action"]
    interaction = manifest["interaction"]
    attention = manifest["medical_attention"]
    if manifest.get("content_profile") == GENERAL_WELLNESS_PROFILE:
        lifestyle_profiles = {
            "wechat_channels": {
                "prefix": "生活观察：",
                "body": f"{hook}\n{action}\n{manifest['save_reason']}",
                "tags": ["生活观察", "日常习惯", "生活节奏"],
            },
            "douyin": {
                "prefix": "先观察三件事：",
                "body": f"{hook} {action} {interaction}",
                "tags": ["生活小习惯", "日常记录", "状态管理"],
            },
            "xiaohongshu": {
                "prefix": "可收藏的观察清单｜",
                "body": f"{topic}\n\n{action}\n\n{manifest['save_reason']}\n\n{interaction}",
                "tags": ["生活方式", "习惯养成", "日常观察"],
            },
            "kuaishou": {
                "prefix": "过日子的小观察：",
                "body": f"{hook}\n{action}\n{attention}",
                "tags": ["生活经验", "日常习惯", "过日子"],
            },
        }
        profile = lifestyle_profiles[platform]
        return {
            "status": "human_pending",
            "titles": [f"{profile['prefix']}{topic}", hook, f"记下来看一周：{topic}"],
            "cover_texts": [topic, hook],
            "body": profile["body"],
            "tags": profile["tags"],
            "pinned_comment": "你有哪些类似的个人习惯？欢迎在评论区分享。",
            "interaction_question": interaction,
        }
    profiles = {
        "wechat_channels": {
            "prefix": "给家里人看：",
            "body": f"{hook}\n{action}\n{attention}\n觉得有用，可以转给家人一起看。",
            "tags": ["家庭健康", "健康科普", "生活方式"],
        },
        "douyin": {
            "prefix": "先别忽略：",
            "body": f"{hook} {action} {interaction}",
            "tags": ["健康科普", "35岁后健康", "健康生活"],
        },
        "xiaohongshu": {
            "prefix": "可收藏清单｜",
            "body": f"{topic}\n\n先记住一个可执行步骤：{action}\n\n适用边界：{attention}\n\n{interaction}",
            "tags": ["健康笔记", "家庭健康", "健康科普"],
        },
        "kuaishou": {
            "prefix": "大白话讲健康：",
            "body": f"{hook}\n咱们先做一件现实的事：{action}\n{attention}",
            "tags": ["健康大白话", "家庭健康", "生活建议"],
        },
    }
    profile = profiles[platform]
    return {
        "status": "human_pending",
        "titles": [
            f"{profile['prefix']}{topic}",
            hook,
            f"35岁后关注：{topic}",
        ],
        "cover_texts": [topic, hook],
        "body": profile["body"],
        "tags": profile["tags"],
        "pinned_comment": f"{interaction} 本内容不替代个体诊疗。",
        "interaction_question": interaction,
    }


def build_publish_pack(manifest: Mapping) -> dict:
    """仅生成待人工发布资料，不调用任何平台接口。"""
    validated = validate_manifest(manifest)
    review = _require_medical_review(validated)
    run_automated_qa(validated)
    automated_qa = validated.get("automated_qa")
    if not isinstance(automated_qa, Mapping) or automated_qa.get("status") != "passed":
        raise FinalQARequired("自动QA必须通过后才能提交人工终审")
    _require_final_qa(validated, review)
    score = calculate_quality_score(validated)
    _require_quality_gate(validated, score, "发布前")

    pack = {
        "schema": "health-publish-pack-v1",
        "content_id": validated["content_id"],
        "batch_id": validated["batch_id"],
        "status": "human_pending",
        "quality_score": score,
        "video_master": {
            "aspect_ratio": "9:16",
            "resolution": "1080x1920",
            "duration_seconds": {"min": 35, "max": 60},
            "script": [
                {"segment": "0-3s", "text": validated["hook"]},
                {"segment": "3-10s", "text": validated["scenario"]},
                {"segment": "10-30s", "text": validated["mechanism"]},
                {"segment": "30-48s", "text": validated["action"]},
                {
                    "segment": "48-60s",
                    "text": f"{validated['medical_attention']} {validated['interaction']}",
                },
            ],
        },
        "article_cards": _article_cards(validated),
        "platforms": {
            platform: _platform_package(validated, platform) for platform in PLATFORMS
        },
    }
    if validated.get("content_profile") == GENERAL_WELLNESS_PROFILE:
        _reject_general_wellness_public_terms(pack)
    return pack


def validate_metric_snapshots(rows: Iterable[Mapping]) -> list[dict]:
    normalized = [dict(row) for row in rows]
    keys = [
        (
            row.get("content_id"),
            row.get("platform"),
            row.get("format"),
            row.get("window_hours"),
        )
        for row in normalized
    ]
    duplicates = [key for key, count in Counter(keys).items() if count > 1]
    if duplicates:
        raise HealthContentError(f"检测到重复指标快照: {duplicates[0]}")
    for row in normalized:
        if row.get("platform") not in PLATFORMS:
            raise HealthContentError("指标快照包含未支持平台")
        if row.get("window_hours") not in (24, 72, 168):
            raise HealthContentError("指标窗口只允许24、72或168小时")
    return normalized


_METRIC_FIELDS = (
    "content_id",
    "category",
    "platform",
    "format",
    "window_hours",
    "views",
    "completion_rate",
    "save_rate",
    "share_rate",
    "follow_rate",
)


def write_metric_csv(path: str | Path, rows: Iterable[Mapping]) -> Path:
    """不可覆盖地写入平台指标，空值保持为空而不是零。"""
    destination = Path(path)
    normalized = validate_metric_snapshots(rows)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = destination.open("x", encoding="utf-8-sig", newline="")
    except FileExistsError as exc:
        raise HealthContentError(f"指标文件已存在: {destination}") from exc
    with handle:
        writer = csv.DictWriter(handle, fieldnames=_METRIC_FIELDS, extrasaction="raise")
        writer.writeheader()
        for row in normalized:
            writer.writerow(
                {
                    field: "" if row.get(field) is None else row.get(field)
                    for field in _METRIC_FIELDS
                }
            )
    return destination


def parse_metric_csv(path: str | Path) -> list[dict]:
    """严格读取真实快照，不把不可见字段推算为零。"""
    source = Path(path)
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != _METRIC_FIELDS:
                raise HealthContentError("指标CSV字段不完整或顺序错误")
            rows = list(reader)
    except OSError as exc:
        raise HealthContentError(f"无法读取指标文件: {source}") from exc

    parsed = []
    try:
        for row in rows:
            parsed.append(
                {
                    "content_id": row["content_id"],
                    "category": row["category"],
                    "platform": row["platform"],
                    "format": row["format"],
                    "window_hours": int(row["window_hours"]),
                    "views": int(row["views"]),
                    "completion_rate": _optional_float(row["completion_rate"]),
                    "save_rate": _optional_float(row["save_rate"]),
                    "share_rate": _optional_float(row["share_rate"]),
                    "follow_rate": _optional_float(row["follow_rate"]),
                }
            )
    except (TypeError, ValueError) as exc:
        raise HealthContentError("指标CSV包含无效数值") from exc
    return validate_metric_snapshots(parsed)


def _optional_float(value: str) -> float | None:
    return None if value == "" else float(value)


def propose_chase_updates(rows: Iterable[Mapping]) -> list[dict]:
    """只输出人工复核提案；24小时窗口永不自动追击。"""
    snapshots = validate_metric_snapshots(rows)
    proposals = []
    for row in snapshots:
        if row["window_hours"] not in (72, 168):
            continue
        required_rates = (
            row.get("completion_rate"),
            row.get("save_rate"),
            row.get("share_rate"),
            row.get("follow_rate"),
        )
        if any(value is None for value in required_rates):
            continue
        if (
            row.get("completion_rate", 0) >= 0.75
            and row.get("save_rate", 0) >= 0.015
            and row.get("share_rate", 0) >= 0.01
            and row.get("follow_rate", 0) >= 0.008
        ):
            proposals.append(
                {
                    "type": "human_review_chase_slot",
                    "content_id": row["content_id"],
                    "category": row["category"],
                    "reason": "72h完播、收藏、分享和关注指标均达到放大线",
                    "suggested_followups": 3,
                }
            )
    return proposals
