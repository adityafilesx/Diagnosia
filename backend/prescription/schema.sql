-- What the AI read from a prescription photo, kept so the server can check a confirmation against its
-- own reading instead of trusting what the browser sends back. No photo, and not the doctor's notes.
-- Short-lived: rows older than a day are removed by the sweep (routes.forget_old_readings).
CREATE TABLE IF NOT EXISTS prescription_readings (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    medicines TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS prescription_readings_age ON prescription_readings (created_at);

-- Which medicines a patient ticked as matching their prescription, each time they asked for an
-- explanation or saved to their record. Only the ticked medicines' fields: no photo, no notes.
CREATE TABLE IF NOT EXISTS prescription_confirmations (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    reading_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('explain', 'save')),
    confirmed TEXT NOT NULL,
    offered INTEGER NOT NULL,
    read_count INTEGER NOT NULL,
    language TEXT NOT NULL DEFAULT '',
    app_version TEXT NOT NULL,
    read_model TEXT NOT NULL,
    explain_model TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS prescription_confirmations_user ON prescription_confirmations (user_id, created_at);
