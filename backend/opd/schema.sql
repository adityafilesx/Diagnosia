-- OPD bookings for DiagnoFast (BUILD.md step 4). Made-up patients only, behind diagnofast.bookings.
CREATE TABLE IF NOT EXISTS opd_slots (
    id TEXT PRIMARY KEY,
    doctor_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    form_id TEXT NOT NULL,               -- the department: one of DiagnoFast's specialty forms
    starts_at TEXT NOT NULL,             -- local time, YYYY-MM-DDTHH:MM
    ends_at TEXT NOT NULL,
    -- Printed in the slot's QR code. Public by design: the OTP is the secret, never this.
    slot_code TEXT NOT NULL UNIQUE,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS opd_slots_doctor ON opd_slots (doctor_id, starts_at);

CREATE TABLE IF NOT EXISTS opd_bookings (
    id TEXT PRIMARY KEY,
    slot_id TEXT REFERENCES opd_slots (id) ON DELETE CASCADE,  -- empty for a walk-in
    doctor_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    visit_date TEXT NOT NULL,
    queue_number INTEGER NOT NULL,
    form_id TEXT,                        -- the department; empty for a walk-in until staff confirm one
    department_confirmed_by INTEGER,     -- walk-ins only: who confirmed the department
    walk_in INTEGER NOT NULL DEFAULT 0,
    patient_id TEXT REFERENCES patients (id) ON DELETE SET NULL,
    patient_name TEXT NOT NULL,
    patient_age INTEGER,
    patient_sex TEXT,
    phone TEXT NOT NULL,                 -- ten digits, no prefix
    intake_id INTEGER REFERENCES intakes (id) ON DELETE SET NULL,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (doctor_id, visit_date, queue_number)
);
CREATE INDEX IF NOT EXISTS opd_bookings_slot ON opd_bookings (slot_id);
CREATE INDEX IF NOT EXISTS opd_bookings_intake ON opd_bookings (intake_id);

-- What would be sent by SMS or WhatsApp. Nothing is sent: no provider is connected
-- (reminders/adapters.py). The link is never stored here, only "[link hidden]".
CREATE TABLE IF NOT EXISTS opd_outbox (
    id TEXT PRIMARY KEY,
    booking_id TEXT NOT NULL REFERENCES opd_bookings (id) ON DELETE CASCADE,
    doctor_id INTEGER NOT NULL,
    channel TEXT NOT NULL CHECK (channel IN ('sms', 'whatsapp')),
    phone_masked TEXT NOT NULL,
    text TEXT NOT NULL,
    send_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS opd_outbox_doctor ON opd_outbox (doctor_id, created_at);
