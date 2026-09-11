CREATE EXTENSION IF NOT EXISTS vector;

-- Task/agent runs: history, cost, provenance.
CREATE TABLE IF NOT EXISTS runs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind         TEXT NOT NULL,                 -- ask | vault_audit | research | ...
    status       TEXT NOT NULL DEFAULT 'queued',-- queued|running|done|error
    model        TEXT,
    input        TEXT,
    result_path  TEXT,                          -- vault-relative path if it wrote a file
    result_text  TEXT,
    tokens_in    INT DEFAULT 0,
    tokens_out   INT DEFAULT 0,
    cost_usd     NUMERIC(10,4) DEFAULT 0,
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ
);

-- Awareness layer: normalized signals from pollers (Phase 1).
CREATE TABLE IF NOT EXISTS signals (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT NOT NULL,     -- stripe|sentry|vercel|indeed|calendar|...
    key         TEXT NOT NULL,     -- e.g. 'acme.signups'
    value_json  JSONB NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_signals_key_time ON signals (key, observed_at DESC);

-- Claim ledger: the backbone of a healthy, non-rotting second brain.
CREATE TABLE IF NOT EXISTS claims (
    id            BIGSERIAL PRIMARY KEY,
    statement     TEXT NOT NULL,
    source_path   TEXT,            -- vault-relative note this came from
    confidence    REAL DEFAULT 0.5,
    freshness     TIMESTAMPTZ DEFAULT now(),
    contradicts_id BIGINT REFERENCES claims(id),
    review_state  TEXT DEFAULT 'unreviewed',  -- unreviewed|kept|stale|killed
    embedding     vector(384)      -- local embedding dim; adjust to your model
);

-- Personal CRM (Phase 2).
CREATE TABLE IF NOT EXISTS people (
    id             BIGSERIAL PRIMARY KEY,
    name           TEXT NOT NULL,
    aliases        TEXT[],
    context        TEXT,
    last_contact_at TIMESTAMPTZ,
    notes_path     TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_created ON runs (created_at);

-- Retrieval chunks (hybrid pgvector side). Local embeddings; dim must match config.
CREATE TABLE IF NOT EXISTS chunks (
    id           TEXT PRIMARY KEY,          -- path::ordinal::hash8
    path         TEXT NOT NULL,
    ordinal      INT NOT NULL,
    content_hash TEXT NOT NULL,
    text         TEXT NOT NULL,
    embedding    vector(384),  -- MUST equal EMBEDDING_DIM; change both together
    mtime_ns     BIGINT,
    indexed_at   TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops);
