CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaign_plans (
    plan_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    start_date TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS planned_items (
    planned_item_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES campaign_plans(plan_id),
    campaign_id TEXT NOT NULL,
    planned_local_date TEXT NOT NULL,
    platform TEXT NOT NULL,
    status TEXT NOT NULL,
    item_json TEXT NOT NULL,
    reservation_id TEXT,
    reserved_by TEXT,
    reservation_timestamp TEXT,
    reservation_expiration TEXT,
    idempotency_key TEXT,
    attempt_number INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE(campaign_id, planned_local_date, platform)
);

CREATE INDEX IF NOT EXISTS idx_planned_items_selection
ON planned_items(campaign_id, planned_local_date, platform, status);

CREATE TABLE IF NOT EXISTS content_memory_records (
    memory_record_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    planned_item_id TEXT,
    story_id TEXT,
    story_version_id TEXT,
    status TEXT NOT NULL,
    planned_date TEXT,
    generated_at TEXT,
    approved_at TEXT,
    published_at TEXT,
    topic_fingerprint TEXT,
    concept_fingerprint TEXT,
    hook_fingerprint TEXT,
    story_beat_fingerprint TEXT,
    script_fingerprint TEXT,
    caption_fingerprint TEXT,
    scene_plan_fingerprint TEXT,
    media_hashes_json TEXT NOT NULL DEFAULT '[]',
    parent_version_id TEXT,
    superseded INTEGER NOT NULL DEFAULT 0,
    record_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_campaign_date
ON content_memory_records(campaign_id, planned_date, status);
CREATE INDEX IF NOT EXISTS idx_memory_topic
ON content_memory_records(campaign_id, topic_fingerprint);
CREATE INDEX IF NOT EXISTS idx_memory_hook
ON content_memory_records(campaign_id, hook_fingerprint);
CREATE INDEX IF NOT EXISTS idx_memory_script
ON content_memory_records(campaign_id, script_fingerprint);

CREATE TABLE IF NOT EXISTS duplicate_policy_audit (
    audit_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    proposed_fingerprint TEXT,
    decision_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

