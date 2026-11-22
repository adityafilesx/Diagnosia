-- References waiting to be copied into Neo4j (BUILD.md step 8). Only the source and its ID: the worker
-- reads the finished record from SQLite when it sends, so Neo4j can always be rebuilt from here.
CREATE TABLE IF NOT EXISTS graph_items (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL CHECK (source_type IN ('intake', 'referral')),
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

-- The reviewing doctor's answer to "Anything you wish had been asked?" (BUILD.md step 9). It is scored in
-- diagnofast_eval. A good question becomes a prompt example only after a person promotes it from the
-- command line (operator_cli feedback-promote). No fine-tuning until there is reviewed real data.
CREATE TABLE IF NOT EXISTS diagnofast_feedback (
    id INTEGER PRIMARY KEY,
    intake_id INTEGER NOT NULL REFERENCES intakes (id) ON DELETE CASCADE,
    doctor_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    wished_asked TEXT NOT NULL,
    good_question TEXT,
    promoted_by TEXT,
    promoted_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS diagnofast_feedback_intake ON diagnofast_feedback (intake_id);
