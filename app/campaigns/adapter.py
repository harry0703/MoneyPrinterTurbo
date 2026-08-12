"""Backward-compatible adapter from structured story records to MPT fields."""

from __future__ import annotations

import warnings
from typing import Any

from app.campaigns.models import CampaignConfig, LegacyMptPayload, PlannedContentItem, StoryPackage


class LegacyPayloadError(ValueError):
    pass


class StructuredMptPayloadAdapter:
    """Choose one canonical value, then mirror it into legacy aliases."""

    REQUIRED_FIELDS = (
        "script",
        "search_terms",
        "video_subject",
        "video_script",
        "video_terms",
        "video_aspect",
        "video_count",
    )
    TASK_PARAM_FIELDS = {
        "video_subject",
        "video_script",
        "video_terms",
        "video_aspect",
        "video_concat_mode",
        "video_transition_mode",
        "video_clip_duration",
        "match_materials_to_script",
        "video_count",
    }

    @staticmethod
    def _resolve_aliases(
        overrides: dict[str, Any],
        canonical_name: str,
        alias_name: str,
    ) -> tuple[Any, str] | None:
        canonical = overrides.get(canonical_name)
        alias = overrides.get(alias_name)
        if canonical not in (None, "", []) and alias not in (None, "", []) and canonical != alias:
            raise LegacyPayloadError(
                f"contradictory overrides for {canonical_name!r} and {alias_name!r}"
            )
        value = canonical if canonical not in (None, "", []) else alias
        if value not in (None, "", []):
            warnings.warn(
                f"legacy override {canonical_name if canonical else alias_name!r} is deprecated; "
                "prefer structured story-stage overrides",
                DeprecationWarning,
                stacklevel=3,
            )
            return value, f"user_override:{canonical_name if canonical not in (None, '', []) else alias_name}"
        return None

    def adapt(
        self,
        campaign: CampaignConfig,
        item: PlannedContentItem,
        package: StoryPackage,
        *,
        overrides: dict[str, Any] | None = None,
        legacy_fallback: dict[str, Any] | None = None,
    ) -> LegacyMptPayload:
        overrides = overrides or {}
        legacy_fallback = legacy_fallback or {}
        field_sources: dict[str, str] = {}
        adapter_warnings: list[str] = []

        script_override = self._resolve_aliases(overrides, "script", "video_script")
        if script_override:
            canonical_script, source = script_override
        else:
            canonical_script, source = package.script.full_narration, "story.script.full_narration"
        if not canonical_script and legacy_fallback.get("video_script"):
            canonical_script = legacy_fallback["video_script"]
            source = "legacy_fallback:video_script"
            adapter_warnings.append("video_script used a deprecated legacy fallback")

        terms_override = self._resolve_aliases(overrides, "search_terms", "video_terms")
        story_terms = [
            term
            for scene in package.scenes
            for term in scene.stock_search_terms
            if term and term.strip()
        ]
        story_terms = list(dict.fromkeys(story_terms))
        if terms_override:
            canonical_terms, terms_source = terms_override
        else:
            canonical_terms, terms_source = story_terms, "story.scenes[].stock_search_terms"
        if not canonical_terms and legacy_fallback.get("video_terms"):
            canonical_terms = legacy_fallback["video_terms"]
            terms_source = "legacy_fallback:video_terms"
            adapter_warnings.append("video_terms used a deprecated legacy fallback")
        if isinstance(canonical_terms, str):
            canonical_terms = [value.strip() for value in canonical_terms.split(",") if value.strip()]

        defaults = campaign.metadata.get("mpt_defaults", {})
        payload: dict[str, Any] = {
            "script": canonical_script,
            "search_terms": canonical_terms,
            "video_subject": overrides.get("video_subject") or package.script.title or item.topic,
            "video_script": canonical_script,
            "video_terms": canonical_terms,
            "video_aspect": overrides.get("video_aspect") or campaign.default_aspect_ratio,
            "video_concat_mode": overrides.get("video_concat_mode", defaults.get("video_concat_mode", "sequential")),
            "video_transition_mode": overrides.get(
                "video_transition_mode", defaults.get("video_transition_mode") or "None"
            ),
            "video_clip_duration": overrides.get("video_clip_duration", defaults.get("video_clip_duration", 5)),
            "match_materials_to_script": overrides.get(
                "match_materials_to_script", defaults.get("match_materials_to_script", True)
            ),
            "video_count": overrides.get("video_count", defaults.get("video_count", 1)),
            "campaign_context": {
                "campaign_id": campaign.campaign_id,
                "planned_item_id": item.planned_item_id,
                "story_id": package.brief.story_id,
                "story_version_id": package.story_version_id,
                "caption_package": package.caption.model_dump(mode="json"),
                "scene_plan": [scene.model_dump(mode="json") for scene in package.scenes],
            },
        }
        field_sources.update(
            {
                "script": source,
                "video_script": source,
                "search_terms": terms_source,
                "video_terms": terms_source,
                "video_subject": "user_override:video_subject" if overrides.get("video_subject") else "story.script.title",
                "video_aspect": "user_override:video_aspect" if overrides.get("video_aspect") else "campaign.default_aspect_ratio",
            }
        )
        for field in (
            "video_concat_mode", "video_transition_mode", "video_clip_duration",
            "match_materials_to_script", "video_count",
        ):
            field_sources[field] = (
                f"user_override:{field}" if field in overrides else f"campaign.metadata.mpt_defaults.{field}"
            )
        self.validate(payload)
        return LegacyMptPayload(payload=payload, field_sources=field_sources, warnings=adapter_warnings)

    def validate(self, payload: dict[str, Any]) -> None:
        missing = [field for field in self.REQUIRED_FIELDS if payload.get(field) in (None, "", [])]
        if missing:
            raise LegacyPayloadError(f"MPT payload is missing required values: {', '.join(missing)}")
        if payload["script"] != payload["video_script"]:
            raise LegacyPayloadError("script and video_script must come from the same canonical value")
        if payload["search_terms"] != payload["video_terms"]:
            raise LegacyPayloadError("search_terms and video_terms must come from the same canonical value")
        if payload["video_count"] < 1:
            raise LegacyPayloadError("video_count must be at least one")

    def task_params(self, adapted: LegacyMptPayload) -> dict[str, Any]:
        """Return only fields accepted by VideoParams; no generation is triggered."""
        self.validate(adapted.payload)
        return {
            key: value
            for key, value in adapted.payload.items()
            if key in self.TASK_PARAM_FIELDS
        }
