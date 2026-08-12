"""Campaign configuration loading and compatibility validation."""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import yaml

from app.campaigns.models import CampaignConfig
from app.utils import utils


DEFAULT_CAMPAIGN_DIRECTORY = Path(utils.root_dir()) / "campaigns"


class CampaignConfigurationError(ValueError):
    pass


class CampaignRegistry:
    def __init__(self, directory: str | Path = DEFAULT_CAMPAIGN_DIRECTORY):
        self.directory = Path(directory)

    def _paths(self) -> list[Path]:
        if not self.directory.exists():
            return []
        return sorted(
            path
            for pattern in ("**/campaign.yaml", "**/campaign.yml", "**/campaign.json")
            for path in self.directory.glob(pattern)
        )

    @staticmethod
    def _load_data(path: Path) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                if path.suffix == ".json":
                    data = json.load(handle)
                else:
                    data = yaml.safe_load(handle)
        except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
            raise CampaignConfigurationError(f"cannot read {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise CampaignConfigurationError(f"campaign file must contain an object: {path}")
        return data

    def load_path(self, path: str | Path) -> CampaignConfig:
        campaign_path = Path(path)
        try:
            return CampaignConfig.model_validate(self._load_data(campaign_path))
        except Exception as exc:
            if isinstance(exc, CampaignConfigurationError):
                raise
            raise CampaignConfigurationError(f"invalid campaign {campaign_path}: {exc}") from exc

    def list(self) -> list[CampaignConfig]:
        campaigns = [self.load_path(path) for path in self._paths()]
        ids = [campaign.campaign_id for campaign in campaigns]
        if len(ids) != len(set(ids)):
            raise CampaignConfigurationError("campaign IDs must be unique across the registry")
        return campaigns

    def get(self, campaign_id: str) -> CampaignConfig:
        for campaign in self.list():
            if campaign.campaign_id == campaign_id:
                return campaign
        raise CampaignConfigurationError(f"unknown campaign: {campaign_id}")

    def validate_all(self) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        for path in self._paths():
            try:
                campaign = self.load_path(path)
                results.append(
                    {"path": str(path), "campaign_id": campaign.campaign_id, "status": "valid"}
                )
            except CampaignConfigurationError as exc:
                results.append({"path": str(path), "campaign_id": "", "status": str(exc)})
        return results


def validate_story_format_compatibility(campaign: CampaignConfig) -> list[str]:
    """Return compatibility errors without mutating configuration."""
    errors: list[str] = []
    templates = {template.id: template for template in campaign.story_formats}
    for format_id in campaign.allowed_formats:
        template = templates.get(format_id)
        if not template:
            errors.append(f"allowed format {format_id!r} has no template")
            continue
        if not template.beat_structure or template.beat_structure[0] != "hook":
            errors.append(f"format {format_id!r} must begin with a hook beat")
        if len(template.beat_structure) < 3:
            errors.append(f"format {format_id!r} needs at least three beats")
    for pillar in campaign.content_pillars:
        unknown = set(pillar.allowed_story_formats) - set(campaign.allowed_formats)
        if unknown:
            errors.append(f"pillar {pillar.id!r} uses unavailable formats: {sorted(unknown)}")
    return errors


def preview_legacy_seed_migration(
    legacy_path: str | Path,
    campaign: CampaignConfig | None = None,
) -> dict[str, Any]:
    """Read the old seed supply and report a non-mutating migration preview."""
    path = Path(legacy_path)
    if not path.exists():
        return {"status": "not_found", "path": str(path), "would_add": [], "already_present": []}
    data = CampaignRegistry._load_data(path)
    raw_seeds = data.get("contentSeeds", data.get("seeds", []))
    existing = {seed.id for seed in campaign.seed_content} if campaign else set()
    would_add: list[dict[str, Any]] = []
    already_present: list[str] = []
    for index, item in enumerate(raw_seeds, start=1):
        seed = item if isinstance(item, dict) else {"topic": str(item)}
        seed_id = seed.get("id") or f"legacy-{index:03d}"
        if seed_id in existing:
            already_present.append(seed_id)
        else:
            would_add.append({"id": seed_id, "topic": seed.get("topic", "")})
    warnings.warn(
        "legacy marketing-plan seed fields are deprecated; previewed without mutation",
        DeprecationWarning,
        stacklevel=2,
    )
    return {
        "status": "preview_only",
        "path": str(path),
        "would_add": would_add,
        "already_present": already_present,
        "legacy_seed_count": len(raw_seeds),
    }
