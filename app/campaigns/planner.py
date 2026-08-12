"""Deterministic, explainable campaign planning."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.campaigns.models import (
    CampaignConfig,
    CampaignPlan,
    PlannedContentItem,
    PlanningDecision,
    SeedContent,
)


def stable_id(prefix: str, *parts: object, length: int = 24) -> str:
    serialized = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}-{digest}"


class PlanningHistory(Protocol):
    def usage_counts(self, campaign_id: str) -> dict[str, Counter[str]]: ...

    def last_used(self, campaign_id: str, artifact: str, value: str) -> date | None: ...

    def state_token(self, campaign_id: str) -> str: ...


class EmptyPlanningHistory:
    def usage_counts(self, campaign_id: str) -> dict[str, Counter[str]]:
        return {name: Counter() for name in ("pillar", "theme", "format", "hook", "cta", "seed")}

    def last_used(self, campaign_id: str, artifact: str, value: str) -> date | None:
        return None

    def state_token(self, campaign_id: str) -> str:
        return "empty"


class CampaignPlanningStrategy(ABC):
    @abstractmethod
    def create_plan(
        self,
        campaign: CampaignConfig,
        start_date: date,
        number_of_days: int,
        target_platforms: list[str],
        random_seed: int,
        planning_mode: str,
        regeneration_policy: str,
        history: PlanningHistory,
        now: datetime,
    ) -> CampaignPlan: ...


class BalancedDeterministicStrategy(CampaignPlanningStrategy):
    """Balance underused dimensions and use hashes only as deterministic tie-breakers."""

    @staticmethod
    def _seasonal_multiplier(campaign: CampaignConfig, seed: SeedContent, day: date) -> float:
        current = day.strftime("%m-%d")
        multiplier = 1.0
        for rule in campaign.seasonal_rules:
            in_range = (
                rule.start_month_day <= current <= rule.end_month_day
                if rule.start_month_day <= rule.end_month_day
                else current >= rule.start_month_day or current <= rule.end_month_day
            )
            if in_range and seed.id in rule.eligible_seed_ids:
                multiplier *= rule.weight_multiplier
        return multiplier

    @staticmethod
    def _choice(
        values: list[str],
        key: str,
        counts: Counter[str],
        previous: str | None,
        weights: dict[str, float] | None = None,
    ) -> str:
        eligible = [value for value in values if value != previous] or values
        weights = weights or {}
        return min(
            eligible,
            key=lambda value: (
                counts[value] / max(weights.get(value, 1.0), 0.0001),
                stable_id("choice", key, value),
            ),
        )

    def create_plan(
        self,
        campaign: CampaignConfig,
        start_date: date,
        number_of_days: int,
        target_platforms: list[str],
        random_seed: int,
        planning_mode: str,
        regeneration_policy: str,
        history: PlanningHistory,
        now: datetime,
    ) -> CampaignPlan:
        if number_of_days < 1:
            raise ValueError("number_of_days must be at least one")
        if not target_platforms or not set(target_platforms) <= set(campaign.enabled_platforms):
            raise ValueError("target platforms must be enabled by the campaign")
        try:
            timezone = ZoneInfo(campaign.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown campaign timezone: {campaign.timezone}") from exc

        counts = history.usage_counts(campaign.campaign_id)
        items: list[PlannedContentItem] = []
        decisions: list[PlanningDecision] = []
        previous_theme: str | None = None
        previous_format: str | None = None
        previous_seed: str | None = None
        hook_counts = counts["hook"]
        cta_counts = counts["cta"]
        format_counts = counts["format"]
        local_time = campaign.posting_cadence.local_time
        hour, minute = (int(value) for value in local_time.split(":"))

        for offset in range(number_of_days):
            local_day = start_date + timedelta(days=offset)
            if local_day.weekday() not in campaign.posting_cadence.days_of_week:
                continue
            for platform in target_platforms:
                rejected: dict[str, list[str]] = {}
                candidates: list[tuple[float, SeedContent, list[str]]] = []
                for seed in campaign.seed_content:
                    reasons: list[str] = []
                    seed_pillar = next(
                        pillar for pillar in campaign.content_pillars if pillar.id == seed.pillar_id
                    )
                    seed_theme = next(
                        theme for theme in seed_pillar.themes if theme.id == seed.theme_id
                    )
                    if seed.id == previous_seed:
                        rejected[seed.id] = ["same seed as the adjacent publication"]
                        continue
                    last_topic = history.last_used(campaign.campaign_id, "seed", seed.id)
                    if last_topic is not None:
                        days_since = (local_day - last_topic).days
                        topic_cooldown = campaign.cooldowns.get(
                            "topic", campaign.duplicate_cooldown_days
                        )
                        if days_since < topic_cooldown:
                            rejected[seed.id] = [
                                f"topic cooldown: used {days_since} days ago; requires {topic_cooldown}"
                            ]
                            continue
                    last_theme = history.last_used(campaign.campaign_id, "theme", seed.theme_id)
                    theme_cooldown = campaign.cooldowns.get("theme", 0)
                    if last_theme is not None and (local_day - last_theme).days < theme_cooldown:
                        rejected[seed.id] = [
                            f"theme cooldown: used {(local_day - last_theme).days} days ago; "
                            f"requires {theme_cooldown}"
                        ]
                        continue
                    seasonal = self._seasonal_multiplier(campaign, seed, local_day)
                    jitter_hex = stable_id(
                        "score", random_seed, local_day, platform, seed.id, length=8
                    ).rsplit("-", 1)[-1]
                    jitter = int(jitter_hex, 16) / 0xFFFFFFFF
                    configured_weight = seed.weight * seed_pillar.weight * seed_theme.weight
                    usage_divisor = (
                        1
                        + counts["pillar"][seed.pillar_id] * 2
                        + counts["theme"][seed.theme_id] * 1.5
                    )
                    score = configured_weight * seasonal * 100 / usage_divisor + jitter
                    reasons.extend(
                        [
                            f"pillar prior use count={counts['pillar'][seed.pillar_id]}",
                            f"theme prior use count={counts['theme'][seed.theme_id]}",
                            f"configured seed/pillar/theme weight={configured_weight:g}",
                            f"seasonal multiplier={seasonal:g}",
                            "stable hash used only as final tie-breaker",
                        ]
                    )
                    candidates.append((score, seed, reasons))

                if not candidates:
                    decisions.append(
                        PlanningDecision(
                            local_date=local_day,
                            platform=platform,
                            selected_seed_id=None,
                            score=None,
                            reasons=["seed pool exhausted by adjacency or cooldown rules"],
                            rejected=rejected,
                        )
                    )
                    continue

                if previous_theme and any(
                    seed.theme_id != previous_theme for _, seed, _ in candidates
                ):
                    candidates = [
                        candidate for candidate in candidates
                        if candidate[1].theme_id != previous_theme
                    ]

                score, selected, reasons = max(candidates, key=lambda candidate: candidate[0])
                pillar = next(p for p in campaign.content_pillars if p.id == selected.pillar_id)
                theme = next(t for t in pillar.themes if t.id == selected.theme_id)
                available_formats = [
                    value
                    for value in (pillar.allowed_story_formats or campaign.allowed_formats)
                    if value in campaign.allowed_formats and value not in campaign.disallowed_formats
                ]
                format_cooldown = campaign.cooldowns.get("story_format", 0)
                cooldown_formats = [
                    value for value in available_formats
                    if (
                        history.last_used(campaign.campaign_id, "format", value) is None
                        or (
                            local_day
                            - history.last_used(campaign.campaign_id, "format", value)
                        ).days >= format_cooldown
                    )
                ]
                available_formats = cooldown_formats or available_formats
                format_weights = {
                    value.id: value.weight * (1.25 if value.id in campaign.preferred_formats else 1.0)
                    for value in campaign.story_formats
                }
                story_format = self._choice(
                    available_formats,
                    f"{random_seed}:{local_day}:format",
                    format_counts,
                    previous_format,
                    format_weights,
                )
                hook_pool = pillar.preferred_hooks or campaign.hook_styles
                hook_style = self._choice(
                    hook_pool, f"{random_seed}:{local_day}:hook", hook_counts, None
                )
                cta_pool = pillar.preferred_ctas or campaign.calls_to_action
                cta_style = self._choice(
                    cta_pool, f"{random_seed}:{local_day}:cta", cta_counts, None
                )
                visual_pool = pillar.visual_treatments or campaign.visual_styles
                visual_style = self._choice(
                    visual_pool, f"{random_seed}:{local_day}:visual", Counter(), None
                )
                local_start = datetime(
                    local_day.year, local_day.month, local_day.day, hour, minute, tzinfo=timezone
                )
                duration_range = campaign.max_duration_seconds - campaign.min_duration_seconds
                duration_hash = int(
                    stable_id("duration", random_seed, local_day, selected.id, length=8).split("-")[-1],
                    16,
                )
                target_duration = campaign.min_duration_seconds + (
                    duration_hash % (duration_range + 1)
                )
                item_id = stable_id(
                    "item", campaign.campaign_id, local_day, platform, random_seed, selected.id
                )
                item = PlannedContentItem(
                    planned_item_id=item_id,
                    campaign_id=campaign.campaign_id,
                    planned_local_date=local_day,
                    planned_utc_start=local_start.astimezone(UTC),
                    planned_utc_end=(local_start + timedelta(hours=1)).astimezone(UTC),
                    platform=platform,
                    content_type=campaign.default_content_type,
                    content_pillar=pillar.id,
                    theme=theme.id,
                    seed_id=selected.id,
                    topic=selected.topic,
                    audience_objective=theme.audience_goal,
                    story_format=story_format,
                    hook_style=hook_style,
                    cta_style=cta_style,
                    visual_style=visual_style,
                    target_duration_seconds=target_duration,
                    random_seed=random_seed,
                    created_at=now,
                    updated_at=now,
                    generation_metadata={
                        "strategy": "balanced_deterministic_v1",
                        "planning_mode": planning_mode,
                        "selection_score": round(score, 6),
                    },
                )
                items.append(item)
                decisions.append(
                    PlanningDecision(
                        local_date=local_day,
                        platform=platform,
                        selected_seed_id=selected.id,
                        score=round(score, 6),
                        reasons=reasons,
                        rejected=rejected,
                    )
                )
                for dimension, value in (
                    ("pillar", pillar.id),
                    ("theme", theme.id),
                    ("seed", selected.id),
                    ("format", story_format),
                    ("hook", hook_style),
                    ("cta", cta_style),
                ):
                    counts[dimension][value] += 1
                previous_seed, previous_theme, previous_format = (
                    selected.id,
                    theme.id,
                    story_format,
                )

        state_token = history.state_token(campaign.campaign_id)
        plan_id = stable_id(
            "plan",
            campaign.campaign_id,
            start_date,
            number_of_days,
            ",".join(target_platforms),
            random_seed,
            planning_mode,
            regeneration_policy,
            state_token,
        )
        return CampaignPlan(
            plan_id=plan_id,
            campaign_id=campaign.campaign_id,
            start_date=start_date,
            number_of_days=number_of_days,
            target_platforms=target_platforms,
            random_seed=random_seed,
            planning_mode=planning_mode,
            regeneration_policy=regeneration_policy,
            created_at=now,
            items=items,
            decisions=decisions,
        )


class CampaignPlanner:
    def __init__(self, strategy: CampaignPlanningStrategy | None = None):
        self.strategy = strategy or BalancedDeterministicStrategy()

    def plan(
        self,
        campaign: CampaignConfig,
        start_date: date,
        number_of_days: int,
        target_platforms: list[str] | None = None,
        random_seed: int = 0,
        planning_mode: str = "balanced",
        regeneration_policy: str = "reuse_existing",
        history: PlanningHistory | None = None,
        now: datetime | None = None,
    ) -> CampaignPlan:
        return self.strategy.create_plan(
            campaign=campaign,
            start_date=start_date,
            number_of_days=number_of_days,
            target_platforms=target_platforms or list(campaign.enabled_platforms),
            random_seed=random_seed,
            planning_mode=planning_mode,
            regeneration_policy=regeneration_policy,
            history=history or EmptyPlanningHistory(),
            now=now or datetime.now(UTC),
        )
