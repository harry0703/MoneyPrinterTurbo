from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from app.campaigns.config import CampaignRegistry
from app.campaigns.memory import ContentMemoryRepository, fingerprint
from app.campaigns.models import LifecycleState, MemoryRecord


ROOT = Path(__file__).resolve().parents[2]


def heritage_campaign():
    return CampaignRegistry(ROOT / "campaigns").get("heritage-banner-facebook")


def memory_record(
    campaign_id: str,
    record_id: str,
    *,
    topic: str = "a familiar gathering place",
    hook: str = "What does this place remember?",
    script: str = "A familiar place can hold a shared memory.",
    caption: str = "Share a memory. #Community #History",
    planned_date: date = date(2026, 7, 1),
    status: LifecycleState = LifecycleState.PUBLISHED,
    artifacts: dict | None = None,
    parent: str | None = None,
    series=None,
):
    values = {
        "topic": topic,
        "hook": hook,
        "script": script,
        "caption": caption,
    }
    values.update(artifacts or {})
    return MemoryRecord(
        memory_record_id=record_id,
        campaign_id=campaign_id,
        story_id=f"story-{record_id}",
        story_version_id=f"version-{record_id}",
        original_seed=topic,
        normalized_topic=topic.casefold(),
        hook_text=hook,
        fingerprints={key: fingerprint(key, value) for key, value in values.items() if key in {"topic", "hook", "script", "caption"}},
        media_hashes=[],
        planned_date=planned_date,
        generated_at=datetime.combine(planned_date, datetime.min.time(), UTC),
        published_at=(
            datetime.combine(planned_date, datetime.min.time(), UTC)
            if status == LifecycleState.PUBLISHED else None
        ),
        status=status,
        parent_version_id=parent,
        series=series,
        artifacts=values,
    )


def repository(path: Path) -> ContentMemoryRepository:
    value = ContentMemoryRepository(path)
    value.initialize()
    return value

