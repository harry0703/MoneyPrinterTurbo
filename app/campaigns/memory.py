"""SQLite-backed content memory, duplicate checks, and atomic reservations."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
import unicodedata
from abc import ABC, abstractmethod
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from app.campaigns.models import (
    CampaignConfig,
    CampaignPlan,
    LifecycleState,
    MemoryDecision,
    MemoryRecord,
    PlannedContentItem,
    SelectionOutcome,
    SeriesMetadata,
    SimilarityEvidence,
)
from app.campaigns.planner import stable_id
from app.utils import utils


DEFAULT_MEMORY_PATH = Path(utils.root_dir()) / "storage" / "campaigns" / "content-memory.sqlite3"
MIGRATIONS_PATH = Path(__file__).with_name("migrations")
FINGERPRINT_FIELDS = {
    "topic": "topic_fingerprint",
    "concept": "concept_fingerprint",
    "hook": "hook_fingerprint",
    "story_beat": "story_beat_fingerprint",
    "script": "script_fingerprint",
    "caption": "caption_fingerprint",
    "scene_plan": "scene_plan_fingerprint",
    "visual_concept": "scene_plan_fingerprint",
    "visual_prompt": "scene_plan_fingerprint",
    "theme": "topic_fingerprint",
    "story_format": "concept_fingerprint",
}


def normalize_text(
    value: str,
    *,
    stop_phrases: Iterable[str] = (),
    sort_hashtags: bool = False,
) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    for phrase in stop_phrases:
        normalized_phrase = unicodedata.normalize("NFKC", phrase).casefold().strip()
        if normalized_phrase:
            text = text.replace(normalized_phrase, " ")
    hashtags = re.findall(r"(?<!\w)#[\w-]+", text)
    text = re.sub(r"(?<!\w)#[\w-]+", " ", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"_+", " ", text)
    text = " ".join(text.split())
    if sort_hashtags and hashtags:
        normalized_tags = sorted({tag.casefold() for tag in hashtags})
        text = f"{text} {' '.join(normalized_tags)}".strip()
    return text


def fingerprint(
    artifact_type: str,
    value: str | list[Any] | dict[str, Any],
    *,
    stop_phrases: Iterable[str] = (),
) -> str:
    if artifact_type == "media":
        canonical = str(value).strip().casefold()
    elif isinstance(value, str):
        canonical = normalize_text(
            value,
            stop_phrases=stop_phrases,
            sort_hashtags=artifact_type == "caption",
        )
    else:
        canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        canonical = unicodedata.normalize("NFKC", canonical)
    return hashlib.sha256(f"{artifact_type}\x1f{canonical}".encode("utf-8")).hexdigest()


class ApproximateSimilarity(ABC):
    @abstractmethod
    def compare(self, proposed: str, previous: str) -> float: ...

    @property
    @abstractmethod
    def method(self) -> str: ...


class TokenJaccardSimilarity(ApproximateSimilarity):
    @property
    def method(self) -> str:
        return "token_jaccard_v1"

    def compare(self, proposed: str, previous: str) -> float:
        left, right = set(normalize_text(proposed).split()), set(normalize_text(previous).split())
        if not left and not right:
            return 1.0
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)


class ContentMemoryRepository:
    def __init__(
        self,
        database_path: str | Path = DEFAULT_MEMORY_PATH,
        similarity: ApproximateSimilarity | None = None,
    ):
        self.database_path = Path(database_path)
        self.similarity = similarity or TokenJaccardSimilarity()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    def migration_preview(self) -> dict[str, Any]:
        exists = self.database_path.exists()
        applied: list[int] = []
        if exists:
            with self._connect() as connection:
                table = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
                ).fetchone()
                if table:
                    applied = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
        available = sorted(
            int(path.name.split("_", 1)[0])
            for path in MIGRATIONS_PATH.glob("*.up.sql")
        )
        return {
            "database_path": str(self.database_path),
            "database_exists": exists,
            "applied": applied,
            "pending": [version for version in available if version not in applied],
            "mutates_data": False,
        }

    def initialize(self) -> None:
        if self._initialized:
            return
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            for migration in sorted(MIGRATIONS_PATH.glob("*.up.sql")):
                version = int(migration.name.split("_", 1)[0])
                connection.executescript(
                    "CREATE TABLE IF NOT EXISTS schema_migrations "
                    "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL);"
                )
                if connection.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
                ).fetchone():
                    continue
                connection.executescript(migration.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                    (version, migration.name, datetime.now(UTC).isoformat()),
                )
        self._initialized = True

    def _ready(self) -> None:
        if not self._initialized:
            self.initialize()

    def save_plan(self, plan: CampaignPlan) -> dict[str, int | str]:
        self._ready()
        plan_json = plan.model_dump_json()
        inserted = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO campaign_plans(plan_id,campaign_id,start_date,plan_json,created_at) "
                "VALUES (?,?,?,?,?)",
                (plan.plan_id, plan.campaign_id, plan.start_date.isoformat(), plan_json, plan.created_at.isoformat()),
            )
            for item in plan.items:
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO planned_items("
                    "planned_item_id,plan_id,campaign_id,planned_local_date,platform,status,item_json,updated_at"
                    ") VALUES (?,?,?,?,?,?,?,?)",
                    (
                        item.planned_item_id,
                        plan.plan_id,
                        item.campaign_id,
                        item.planned_local_date.isoformat(),
                        item.platform,
                        item.status.value,
                        item.model_dump_json(),
                        item.updated_at.isoformat(),
                    ),
                )
                inserted += cursor.rowcount
            connection.commit()
        return {"plan_id": plan.plan_id, "items_inserted": inserted, "items_existing": len(plan.items) - inserted}

    def get_plan(self, plan_id: str) -> CampaignPlan | None:
        self._ready()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT plan_json FROM campaign_plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
        return CampaignPlan.model_validate_json(row[0]) if row else None

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> PlannedContentItem:
        item = PlannedContentItem.model_validate_json(row["item_json"])
        return item.model_copy(update={"status": LifecycleState(row["status"])})

    def preview_next(self, campaign: CampaignConfig, local_date: date) -> SelectionOutcome:
        self._ready()
        if not campaign.enabled:
            return SelectionOutcome(
                outcome="campaign_disabled",
                campaign_id=campaign.campaign_id,
                local_date=local_date,
                reasons=["campaign enabled is false"],
            )
        with self._connect() as connection:
            complete = connection.execute(
                "SELECT memory_record_id FROM content_memory_records "
                "WHERE campaign_id=? AND planned_date=? AND status='published' LIMIT 1",
                (campaign.campaign_id, local_date.isoformat()),
            ).fetchone()
            if complete:
                return SelectionOutcome(
                    outcome="already_completed_today",
                    campaign_id=campaign.campaign_id,
                    local_date=local_date,
                    reasons=[f"published memory record {complete[0]} already exists"],
                )
            row = connection.execute(
                "SELECT * FROM planned_items WHERE campaign_id=? AND planned_local_date=? "
                "ORDER BY platform, planned_item_id LIMIT 1",
                (campaign.campaign_id, local_date.isoformat()),
            ).fetchone()
        if not row:
            return SelectionOutcome(
                outcome="nothing_eligible",
                campaign_id=campaign.campaign_id,
                local_date=local_date,
                reasons=["no persisted planned item for the campaign date"],
            )
        outcome = "already_reserved" if row["status"] == "reserved" else "selected"
        return SelectionOutcome(
            outcome=outcome,
            campaign_id=campaign.campaign_id,
            local_date=local_date,
            planned_item=self._item_from_row(row),
            reservation_id=row["reservation_id"],
            reasons=["preview only; no reservation was created"],
        )

    def select_and_reserve(
        self,
        campaign: CampaignConfig,
        local_date: date,
        *,
        worker_id: str,
        idempotency_key: str,
        reservation_ttl: timedelta = timedelta(minutes=30),
        now: datetime | None = None,
        duplicate_blocking: bool = True,
    ) -> SelectionOutcome:
        self._ready()
        if not campaign.enabled:
            return SelectionOutcome(
                outcome="campaign_disabled",
                campaign_id=campaign.campaign_id,
                local_date=local_date,
                reasons=["campaign enabled is false"],
            )
        current = (now or datetime.now(UTC)).astimezone(UTC)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                complete = connection.execute(
                    "SELECT memory_record_id FROM content_memory_records WHERE campaign_id=? "
                    "AND planned_date=? AND status='published' LIMIT 1",
                    (campaign.campaign_id, local_date.isoformat()),
                ).fetchone()
                if complete:
                    connection.rollback()
                    return SelectionOutcome(
                        outcome="already_completed_today",
                        campaign_id=campaign.campaign_id,
                        local_date=local_date,
                        reasons=[f"published memory record {complete[0]} already exists"],
                    )
                rows = connection.execute(
                    "SELECT * FROM planned_items WHERE campaign_id=? AND planned_local_date=? "
                    "ORDER BY platform, planned_item_id",
                    (campaign.campaign_id, local_date.isoformat()),
                ).fetchall()
                if not rows:
                    connection.rollback()
                    return SelectionOutcome(
                        outcome="nothing_eligible",
                        campaign_id=campaign.campaign_id,
                        local_date=local_date,
                        reasons=["no persisted planned item for the campaign date"],
                    )
                blocked_decisions: list[MemoryDecision] = []
                for row in rows:
                    if (
                        row["idempotency_key"] == idempotency_key
                        and row["status"] in {"generating", "generated", "awaiting_review", "approved", "failed"}
                    ):
                        connection.rollback()
                        return SelectionOutcome(
                            outcome="selected",
                            campaign_id=campaign.campaign_id,
                            local_date=local_date,
                            planned_item=self._item_from_row(row),
                            reservation_id=row["reservation_id"],
                            idempotent_replay=True,
                            reasons=[f"idempotency key matched an existing {row['status']} attempt"],
                        )
                    expiration = (
                        datetime.fromisoformat(row["reservation_expiration"])
                        if row["reservation_expiration"]
                        else None
                    )
                    active = row["status"] == "reserved" and expiration and expiration > current
                    if active and row["idempotency_key"] == idempotency_key:
                        connection.rollback()
                        return SelectionOutcome(
                            outcome="selected",
                            campaign_id=campaign.campaign_id,
                            local_date=local_date,
                            planned_item=self._item_from_row(row),
                            reservation_id=row["reservation_id"],
                            idempotent_replay=True,
                            reasons=["idempotency key matched the active reservation"],
                        )
                    if active:
                        connection.rollback()
                        return SelectionOutcome(
                            outcome="already_reserved",
                            campaign_id=campaign.campaign_id,
                            local_date=local_date,
                            planned_item=self._item_from_row(row),
                            reservation_id=row["reservation_id"],
                            reasons=[f"reserved by {row['reserved_by']} until {expiration.isoformat()}"],
                        )
                    if row["status"] == "reserved" and (not expiration or expiration <= current):
                        connection.execute(
                            "UPDATE planned_items SET status='planned', reservation_id=NULL, reserved_by=NULL, "
                            "reservation_timestamp=NULL, reservation_expiration=NULL, idempotency_key=NULL "
                            "WHERE planned_item_id=?",
                            (row["planned_item_id"],),
                        )
                    if row["status"] not in {"planned", "reserved"}:
                        continue
                    item = self._item_from_row(row).model_copy(update={"status": LifecycleState.PLANNED})
                    decision = self._check_with_connection(
                        connection,
                        campaign,
                        "topic",
                        item.topic,
                        local_date,
                        item.series,
                    )
                    if decision.blocking and duplicate_blocking:
                        blocked_decisions.append(decision)
                        continue
                    reservation_id = stable_id(
                        "reservation", item.planned_item_id, idempotency_key
                    )
                    expiration = current + reservation_ttl
                    cursor = connection.execute(
                        "UPDATE planned_items SET status='reserved', reservation_id=?, reserved_by=?, "
                        "reservation_timestamp=?, reservation_expiration=?, idempotency_key=?, "
                        "attempt_number=attempt_number+1, updated_at=? "
                        "WHERE planned_item_id=? AND status IN ('planned','reserved')",
                        (
                            reservation_id,
                            worker_id,
                            current.isoformat(),
                            expiration.isoformat(),
                            idempotency_key,
                            current.isoformat(),
                            item.planned_item_id,
                        ),
                    )
                    if cursor.rowcount != 1:
                        connection.rollback()
                        return SelectionOutcome(
                            outcome="selection_conflict",
                            campaign_id=campaign.campaign_id,
                            local_date=local_date,
                            reasons=["atomic status update did not select exactly one row"],
                        )
                    connection.commit()
                    reserved_item = item.model_copy(update={"status": LifecycleState.RESERVED, "updated_at": current})
                    return SelectionOutcome(
                        outcome="selected",
                        campaign_id=campaign.campaign_id,
                        local_date=local_date,
                        planned_item=reserved_item,
                        reservation_id=reservation_id,
                        reasons=["eligible item atomically reserved", decision.reason],
                        memory_decisions=[decision],
                    )
                connection.rollback()
                return SelectionOutcome(
                    outcome="blocked_by_cooldown" if blocked_decisions else "nothing_eligible",
                    campaign_id=campaign.campaign_id,
                    local_date=local_date,
                    reasons=[decision.reason for decision in blocked_decisions]
                    or ["all planned items are in non-selectable lifecycle states"],
                    memory_decisions=blocked_decisions,
                )
            except sqlite3.OperationalError as exc:
                connection.rollback()
                return SelectionOutcome(
                    outcome="selection_conflict",
                    campaign_id=campaign.campaign_id,
                    local_date=local_date,
                    reasons=[f"SQLite reservation conflict: {exc}"],
                )
            except ValueError as exc:
                connection.rollback()
                return SelectionOutcome(
                    outcome="invalid_plan",
                    campaign_id=campaign.campaign_id,
                    local_date=local_date,
                    reasons=[f"persisted planned item is invalid: {exc}"],
                )

    def update_item_status(self, planned_item_id: str, status: LifecycleState) -> bool:
        self._ready()
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT item_json FROM planned_items WHERE planned_item_id=?", (planned_item_id,)
            ).fetchone()
            if not row:
                return False
            item = PlannedContentItem.model_validate_json(row[0]).model_copy(
                update={"status": status, "updated_at": datetime.fromisoformat(now)}
            )
            connection.execute(
                "UPDATE planned_items SET status=?, item_json=?, updated_at=? WHERE planned_item_id=?",
                (status.value, item.model_dump_json(), now, planned_item_id),
            )
        return True

    def release_stale_reservations(self, now: datetime | None = None) -> list[str]:
        self._ready()
        current = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT planned_item_id FROM planned_items WHERE status='reserved' "
                "AND reservation_expiration <= ?", (current,)
            ).fetchall()
            ids = [row[0] for row in rows]
            connection.execute(
                "UPDATE planned_items SET status='planned',reservation_id=NULL,reserved_by=NULL,"
                "reservation_timestamp=NULL,reservation_expiration=NULL,idempotency_key=NULL,updated_at=? "
                "WHERE status='reserved' AND reservation_expiration <= ?",
                (current, current),
            )
        return ids

    def release_reservation(self, planned_item_id: str, *, force: bool = False) -> bool:
        self._ready()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status,reservation_expiration FROM planned_items WHERE planned_item_id=?",
                (planned_item_id,),
            ).fetchone()
            if not row or row["status"] != "reserved":
                return False
            expiration = datetime.fromisoformat(row["reservation_expiration"])
            if not force and expiration > datetime.now(UTC):
                return False
            connection.execute(
                "UPDATE planned_items SET status='planned',reservation_id=NULL,reserved_by=NULL,"
                "reservation_timestamp=NULL,reservation_expiration=NULL,idempotency_key=NULL,updated_at=? "
                "WHERE planned_item_id=?",
                (datetime.now(UTC).isoformat(), planned_item_id),
            )
        return True

    def upsert_memory(self, record: MemoryRecord) -> None:
        self._ready()
        fps = record.fingerprints
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO content_memory_records("
                "memory_record_id,campaign_id,planned_item_id,story_id,story_version_id,status,"
                "planned_date,generated_at,approved_at,published_at,topic_fingerprint,concept_fingerprint,"
                "hook_fingerprint,story_beat_fingerprint,script_fingerprint,caption_fingerprint,"
                "scene_plan_fingerprint,media_hashes_json,parent_version_id,superseded,record_json,updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(memory_record_id) DO UPDATE SET status=excluded.status, approved_at=excluded.approved_at,"
                "published_at=excluded.published_at,media_hashes_json=excluded.media_hashes_json,"
                "superseded=excluded.superseded,record_json=excluded.record_json,updated_at=excluded.updated_at",
                (
                    record.memory_record_id,
                    record.campaign_id,
                    record.planned_item_id,
                    record.story_id,
                    record.story_version_id,
                    record.status.value,
                    record.planned_date.isoformat() if record.planned_date else None,
                    record.generated_at.isoformat() if record.generated_at else None,
                    record.approved_at.isoformat() if record.approved_at else None,
                    record.published_at.isoformat() if record.published_at else None,
                    fps.get("topic"), fps.get("concept"), fps.get("hook"), fps.get("story_beat"),
                    fps.get("script"), fps.get("caption"), fps.get("scene_plan"),
                    json.dumps(record.media_hashes), record.parent_version_id, int(record.superseded),
                    record.model_dump_json(), now,
                ),
            )

    @staticmethod
    def _record_day(record: MemoryRecord) -> date | None:
        if record.published_at:
            return record.published_at.date()
        if record.generated_at:
            return record.generated_at.date()
        return record.planned_date

    def _records(self, connection: sqlite3.Connection, campaign_id: str) -> list[MemoryRecord]:
        rows = connection.execute(
            "SELECT record_json FROM content_memory_records WHERE campaign_id=? AND superseded=0",
            (campaign_id,),
        ).fetchall()
        return [MemoryRecord.model_validate_json(row[0]) for row in rows]

    def _check_with_connection(
        self,
        connection: sqlite3.Connection,
        campaign: CampaignConfig,
        artifact_type: str,
        proposed: str,
        as_of: date,
        series: SeriesMetadata | None = None,
        approximate_threshold: float = 0.82,
    ) -> MemoryDecision:
        if artifact_type == "cta":
            return MemoryDecision(
                decision="allowed",
                reason="only the CTA overlaps; CTA reuse is not an artifact duplicate",
                recommended_next_action="continue",
            )
        records = self._records(connection, campaign.campaign_id)
        if not records:
            return MemoryDecision(
                decision="insufficient_history",
                reason="no prior content-memory records exist for this campaign",
                recommended_next_action="continue and establish history",
            )
        proposed_fp = fingerprint(
            artifact_type, proposed, stop_phrases=campaign.stop_phrases
        )
        cooldown = campaign.cooldowns.get(artifact_type, campaign.duplicate_cooldown_days)
        candidates: list[tuple[MemoryRecord, int | None]] = []
        for record in records:
            prior_fp = (
                proposed.casefold()
                if artifact_type == "media" and proposed in record.media_hashes
                else record.fingerprints.get(artifact_type)
            )
            exact = prior_fp == proposed_fp or (
                artifact_type == "media" and proposed.casefold() in {value.casefold() for value in record.media_hashes}
            )
            if not exact:
                continue
            prior_day = self._record_day(record)
            days_since = (as_of - prior_day).days if prior_day else None
            candidates.append((record, days_since))
        if candidates:
            record, days_since = min(
                candidates,
                key=lambda candidate: candidate[1] if candidate[1] is not None else 10**9,
            )
            if (
                series
                and record.series
                and series.series_id == record.series.series_id
                and series.recurring_format_allowance
                and artifact_type in series.permitted_overlap
            ):
                return MemoryDecision(
                    decision="intentional_series_match",
                    reason=f"{artifact_type} overlap is permitted within series {series.series_id}",
                    matching_record_ids=[record.memory_record_id],
                    cooldown_rule=f"{artifact_type}:{cooldown}d",
                    days_since_previous_use=days_since,
                    recommended_next_action="continue and preserve episode continuity",
                )
            within = days_since is None or days_since < cooldown
            decision_name = {
                "topic": "recent_topic",
                "hook": "recent_hook",
                "script": "recent_script",
                "media": "recent_media",
            }.get(artifact_type, "exact_duplicate")
            return MemoryDecision(
                decision=decision_name if within else "allowed_with_warning",
                reason=(
                    f"blocked because the {artifact_type} was used {days_since} days ago"
                    if within and days_since is not None
                    else f"normalized {artifact_type} duplicate exists outside its cooldown"
                ),
                matching_record_ids=[record.memory_record_id],
                similarity=SimilarityEvidence(
                    method="sha256_normalized_v1",
                    score=1.0,
                    threshold=1.0,
                    compared_artifact=artifact_type,
                ),
                cooldown_rule=f"{artifact_type}:{cooldown}d",
                days_since_previous_use=days_since,
                recommended_next_action="choose another artifact" if within else "review intentional reuse",
                blocking=within,
            )
        text_field = {
            "topic": "original_seed",
            "hook": "hook_text",
            "script": None,
            "caption": None,
        }.get(artifact_type)
        best: tuple[MemoryRecord, float] | None = None
        for record in records:
            previous = getattr(record, text_field) if text_field else record.artifacts.get(artifact_type)
            if not previous:
                continue
            score = self.similarity.compare(proposed, str(previous))
            if best is None or score > best[1]:
                best = (record, score)
        if best and best[1] >= approximate_threshold:
            return MemoryDecision(
                decision="allowed_with_warning",
                reason=f"similar {artifact_type} found by lightweight local comparison",
                matching_record_ids=[best[0].memory_record_id],
                similarity=SimilarityEvidence(
                    method=self.similarity.method,
                    score=round(best[1], 6),
                    threshold=approximate_threshold,
                    compared_artifact=artifact_type,
                ),
                cooldown_rule=f"{artifact_type}:{cooldown}d",
                recommended_next_action="review and increase novelty",
            )
        return MemoryDecision(
            decision="allowed",
            reason=f"no recent exact or normalized {artifact_type} duplicate was found",
            recommended_next_action="continue",
        )

    def check(
        self,
        campaign: CampaignConfig,
        artifact_type: str,
        proposed: str,
        as_of: date,
        *,
        series: SeriesMetadata | None = None,
        audit: bool = False,
    ) -> MemoryDecision:
        self._ready()
        if artifact_type not in {*FINGERPRINT_FIELDS, "media", "cta"}:
            return MemoryDecision(
                decision="comparison_error",
                reason=f"unsupported artifact type: {artifact_type}",
                recommended_next_action="use a registered artifact type",
                blocking=True,
            )
        with self._connect() as connection:
            decision = self._check_with_connection(
                connection, campaign, artifact_type, proposed, as_of, series
            )
            if audit:
                connection.execute(
                    "INSERT INTO duplicate_policy_audit(audit_id,campaign_id,artifact_type,"
                    "proposed_fingerprint,decision_json,created_at) VALUES (?,?,?,?,?,?)",
                    (
                        stable_id("audit", campaign.campaign_id, artifact_type, proposed, datetime.now(UTC)),
                        campaign.campaign_id,
                        artifact_type,
                        fingerprint(artifact_type, proposed, stop_phrases=campaign.stop_phrases),
                        decision.model_dump_json(),
                        datetime.now(UTC).isoformat(),
                    ),
                )
        return decision

    def recent(self, campaign_id: str, limit: int = 20) -> list[MemoryRecord]:
        self._ready()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record_json FROM content_memory_records WHERE campaign_id=? "
                "ORDER BY COALESCE(published_at,generated_at,planned_date) DESC LIMIT ?",
                (campaign_id, limit),
            ).fetchall()
        return [MemoryRecord.model_validate_json(row[0]) for row in rows]

    def activity_summary(self, campaign_id: str) -> dict[str, Any]:
        """Report persisted plan states alongside durable generated/publication memory."""
        self._ready()
        with self._connect() as connection:
            plan_rows = connection.execute(
                "SELECT status, COUNT(*) AS total FROM planned_items WHERE campaign_id=? GROUP BY status",
                (campaign_id,),
            ).fetchall()
            memory_rows = connection.execute(
                "SELECT status, COUNT(*) AS total FROM content_memory_records WHERE campaign_id=? GROUP BY status",
                (campaign_id,),
            ).fetchall()
        records = self.recent(campaign_id, limit=10000)
        return {
            "planned_item_status_counts": {row["status"]: row["total"] for row in plan_rows},
            "memory_status_counts": {row["status"]: row["total"] for row in memory_rows},
            "planned_dates": sorted(
                {record.planned_date.isoformat() for record in records if record.planned_date}
            ),
            "published_dates": sorted(
                {record.published_at.date().isoformat() for record in records if record.published_at}
            ),
            "failed_or_abandoned": [
                record.model_dump(mode="json")
                for record in records
                if record.status in {
                    LifecycleState.FAILED,
                    LifecycleState.REJECTED,
                    LifecycleState.SKIPPED,
                    LifecycleState.CANCELLED,
                }
            ],
        }

    def usage_counts(self, campaign_id: str) -> dict[str, Counter[str]]:
        counts = {name: Counter() for name in ("pillar", "theme", "format", "hook", "cta", "seed")}
        for record in self.recent(campaign_id, limit=10000):
            if record.content_pillar:
                counts["pillar"][record.content_pillar] += 1
            if record.theme:
                counts["theme"][record.theme] += 1
            for dimension in ("format", "hook", "cta", "seed"):
                value = record.artifacts.get(dimension)
                if value:
                    counts[dimension][str(value)] += 1
        return counts

    def last_used(self, campaign_id: str, artifact: str, value: str) -> date | None:
        latest: date | None = None
        for record in self.recent(campaign_id, limit=10000):
            if artifact == "pillar":
                candidate = record.content_pillar
            elif artifact == "theme":
                candidate = record.theme
            else:
                candidate = record.artifacts.get(artifact)
            if candidate != value:
                continue
            record_day = self._record_day(record)
            if record_day and (latest is None or record_day > latest):
                latest = record_day
        return latest

    def state_token(self, campaign_id: str) -> str:
        records = self.recent(campaign_id, limit=10000)
        material = [(record.memory_record_id, record.status.value, record.published_at) for record in records]
        return fingerprint("state", material)

    def rebuild_fingerprints(self, campaign: CampaignConfig) -> int:
        self._ready()
        records = self.recent(campaign.campaign_id, limit=10000)
        for record in records:
            artifacts = record.artifacts
            updated = dict(record.fingerprints)
            for artifact_type in FINGERPRINT_FIELDS:
                value = artifacts.get(artifact_type)
                if value:
                    updated[artifact_type] = fingerprint(
                        artifact_type, value, stop_phrases=campaign.stop_phrases
                    )
            self.upsert_memory(record.model_copy(update={"fingerprints": updated}))
        return len(records)

    def audit_log(self, campaign_id: str, limit: int = 100) -> list[dict[str, Any]]:
        self._ready()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM duplicate_policy_audit WHERE campaign_id=? ORDER BY created_at DESC LIMIT ?",
                (campaign_id, limit),
            ).fetchall()
        return [dict(row) | {"decision": json.loads(row["decision_json"])} for row in rows]

    def export(self, campaign_id: str, format: str = "json") -> str:
        records = [record.model_dump(mode="json") for record in self.recent(campaign_id, limit=100000)]
        if format == "json":
            return json.dumps(records, ensure_ascii=False, indent=2)
        if format != "csv":
            raise ValueError("format must be json or csv")
        output = io.StringIO()
        fields = [
            "memory_record_id", "campaign_id", "planned_item_id", "story_id", "story_version_id",
            "content_pillar", "theme", "original_seed", "platform", "planned_date", "status",
            "generated_at", "approved_at", "published_at", "external_publication_id", "external_url",
            "rejection_reason", "failure_reason", "parent_version_id", "superseded",
        ]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field) for field in fields})
        return output.getvalue()
