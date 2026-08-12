"""Campaign-ID selection boundary with structured invalid-campaign outcomes."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.campaigns.config import CampaignConfigurationError, CampaignRegistry
from app.campaigns.memory import ContentMemoryRepository
from app.campaigns.models import SelectionOutcome


class CampaignSelectionService:
    def __init__(self, registry: CampaignRegistry, memory: ContentMemoryRepository):
        self.registry = registry
        self.memory = memory

    def _campaign_and_date(self, campaign_id: str, local_date: date | None):
        try:
            campaign = self.registry.get(campaign_id)
        except CampaignConfigurationError as exc:
            fallback_date = local_date or date.today()
            return None, fallback_date, SelectionOutcome(
                outcome="invalid_campaign",
                campaign_id=campaign_id,
                local_date=fallback_date,
                reasons=[str(exc)],
            )
        resolved_date = local_date or datetime.now(ZoneInfo(campaign.timezone)).date()
        return campaign, resolved_date, None

    def preview(self, campaign_id: str, local_date: date | None = None) -> SelectionOutcome:
        campaign, resolved_date, error = self._campaign_and_date(campaign_id, local_date)
        return error or self.memory.preview_next(campaign, resolved_date)

    def select(
        self,
        campaign_id: str,
        *,
        worker_id: str,
        idempotency_key: str,
        local_date: date | None = None,
        reservation_ttl: timedelta = timedelta(minutes=30),
        duplicate_blocking: bool = True,
    ) -> SelectionOutcome:
        campaign, resolved_date, error = self._campaign_and_date(campaign_id, local_date)
        if error:
            return error
        return self.memory.select_and_reserve(
            campaign,
            resolved_date,
            worker_id=worker_id,
            idempotency_key=idempotency_key,
            reservation_ttl=reservation_ttl,
            duplicate_blocking=duplicate_blocking,
        )
