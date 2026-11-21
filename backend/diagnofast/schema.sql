-- References waiting to be copied into Neo4j (BUILD.md step 8). Only the source and its ID: the worker
-- reads the finished record from SQLite when it sends, so Neo4j can always be rebuilt from here.
CREATE TABLE IF NOT EXISTS graph_items (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL CHECK (source_type IN ('intake')),
    source_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'sent', 'skipped')),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    next_attempt_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source_type, source_id)
);
CREATE INDEX IF NOT EXISTS graph_items_due ON graph_items (state, next_attempt_at);
