CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS asset (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    rel_path TEXT NOT NULL UNIQUE,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    caption TEXT NOT NULL DEFAULT '',
    caption_manual BOOLEAN NOT NULL DEFAULT FALSE,
    has_text BOOLEAN,
    min_display REAL,
    min_display_manual BOOLEAN NOT NULL DEFAULT FALSE,
    origin TEXT NOT NULL DEFAULT 'manual',
    source_query TEXT,
    source_url TEXT,
    embedding vector(768),
    embed_model TEXT,
    annotate_model TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    use_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS asset_embedding_idx
    ON asset USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS asset_tag (
    asset_id BIGINT NOT NULL REFERENCES asset (id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    manual BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (asset_id, tag)
);

CREATE INDEX IF NOT EXISTS asset_tag_tag_idx ON asset_tag (tag);

CREATE TABLE IF NOT EXISTS asset_usage (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asset_id BIGINT NOT NULL REFERENCES asset (id) ON DELETE CASCADE,
    task_id TEXT NOT NULL,
    used_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS asset_usage_asset_idx ON asset_usage (asset_id, used_at DESC);
