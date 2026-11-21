"""Numbered schema changes. Each runs once, in one transaction, so a failure leaves
the database as it was and the next start tries again.

New tables go in each tool's schema.sql. Changes to existing tables go here.
Existing staff accounts become unverified: nobody keeps clinical access by default.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from backend.private_files import make_private


def _account_states(db: sqlite3.Connection) -> None:
    db.execute(
        """
        ALTER TABLE users ADD COLUMN account_status TEXT NOT NULL DEFAULT 'pending_verification'
            CHECK (account_status IN ('active', 'pending_verification', 'verified', 'rejected', 'suspended'))
        """
    )
    db.execute("UPDATE users SET account_status = 'active' WHERE role = 'patient'")
    db.execute("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE role = 'doctor')")


def _organization_verification(db: sqlite3.Connection) -> None:
    db.execute(
        """
        ALTER TABLE organizations ADD COLUMN verification_status TEXT NOT NULL DEFAULT 'unverified'
            CHECK (verification_status IN ('unverified', 'verified', 'suspended'))
        """
    )
    db.execute("ALTER TABLE organizations ADD COLUMN verification_reference TEXT")
    db.execute("ALTER TABLE organizations ADD COLUMN verified_at TEXT")


def _practitioner_professions(db: sqlite3.Connection) -> None:
    """The profession a person claims is kept apart from the one an administrator checked."""
    db.execute(
        """
        CREATE TABLE practitioners_new (
            user_id INTEGER PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
            profession TEXT NOT NULL DEFAULT 'doctor'
                CHECK (profession IN ('doctor', 'nurse', 'midwife', 'pharmacist', 'coordinator',
                                      'community_health_worker', 'microbiologist', 'laboratory_professional')),
            speciality TEXT,
            registration_number TEXT,
            verified_profession TEXT
        )
        """
    )
    db.execute(
        """
        INSERT INTO practitioners_new (user_id, profession, speciality, registration_number)
        SELECT user_id, profession, speciality, registration_number FROM practitioners
        """
    )
    db.execute("DROP TABLE practitioners")
    db.execute("ALTER TABLE practitioners_new RENAME TO practitioners")


def _document_encryption(db: sqlite3.Connection) -> None:
    # Rows already here are plaintext until the migration tool has proved each copy.
    db.execute(
        """
        ALTER TABLE clinical_documents ADD COLUMN encryption_state TEXT NOT NULL DEFAULT 'plaintext_legacy'
            CHECK (encryption_state IN ('plaintext_legacy', 'encrypted'))
        """
    )
    db.execute("ALTER TABLE clinical_documents ADD COLUMN key_id TEXT")
    db.execute("ALTER TABLE clinical_documents ADD COLUMN legacy_stored_name TEXT")


def _medication_rule_authority(db: sqlite3.Connection) -> None:
    """Kept so a database that has these tables stays on the same numbers. The medication tools
    were removed, so a new database never has the tables, and there is nothing to change."""
    found = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "medication_alerts" in found:
        db.execute("ALTER TABLE medication_alerts ADD COLUMN authority TEXT NOT NULL DEFAULT 'list_comparison'")
    if "medication_reconciliations" in found:
        db.execute("ALTER TABLE medication_reconciliations ADD COLUMN rule_coverage TEXT")


def _intake_patient_link(db: sqlite3.Connection) -> None:
    """A DiagnoFast link can belong to a patient record, so the report reaches the chart."""
    db.execute("ALTER TABLE intakes ADD COLUMN patient_id TEXT REFERENCES patients (id) ON DELETE SET NULL")
    db.execute("CREATE INDEX intakes_patient ON intakes (patient_id)")


def _delivery_detail(db: sqlite3.Connection) -> None:
    """When each delivery was last tried, what it produced, and whether MongoDB has seen its state yet."""
    db.execute("ALTER TABLE careflow_deliveries ADD COLUMN last_attempt_at TEXT")
    db.execute("ALTER TABLE careflow_deliveries ADD COLUMN result_ref TEXT")
    db.execute("ALTER TABLE careflow_deliveries ADD COLUMN mirrored INTEGER NOT NULL DEFAULT 0")


def _document_description(db: sqlite3.Connection) -> None:
    """A person's words about a file, such as an X-ray, which is what a patient's pack can search."""
    db.execute("ALTER TABLE clinical_documents ADD COLUMN description TEXT NOT NULL DEFAULT ''")


def _intake_expiry_and_answer_key(db: sqlite3.Connection) -> None:
    """Interview links expire, and a retried answer is recognised instead of saved twice.

    Links still open when this runs get a day from now, so nobody's link dies mid-visit.
    """
    db.execute("ALTER TABLE intakes ADD COLUMN expires_at TEXT")
    db.execute("ALTER TABLE intakes ADD COLUMN last_answer_key TEXT")
    db.execute("ALTER TABLE intakes ADD COLUMN last_answer_reply TEXT")
    db.execute(
        "UPDATE intakes SET expires_at = datetime('now', '+24 hours') WHERE status IN ('waiting', 'in_progress')"
    )


def _intake_report_requested_at(db: sqlite3.Connection) -> None:
    """When a report was asked for, so one whose background job died can be found and retried."""
    db.execute("ALTER TABLE intakes ADD COLUMN report_requested_at TEXT")


def _intake_help_requested_at(db: sqlite3.Connection) -> None:
    """When a patient pressed "Tell reception", so the queue can show that someone needs a person."""
    db.execute("ALTER TABLE intakes ADD COLUMN help_requested_at TEXT")


def _notification_link(db: sqlite3.Connection) -> None:
    """Where a notification points in the workspace, such as the interview an alert is about."""
    db.execute("ALTER TABLE notifications ADD COLUMN link TEXT")


def _intake_review_stamp(db: sqlite3.Connection) -> None:
    """Who reviewed a DiagnoFast report and when. Until then it is an unreviewed AI draft."""
    db.execute("ALTER TABLE intakes ADD COLUMN reviewed_by INTEGER REFERENCES users (id)")
    db.execute("ALTER TABLE intakes ADD COLUMN reviewed_at TEXT")


def _session_last_seen(db: sqlite3.Connection) -> None:
    """When a session was last used, for the idle timeout. Old sessions count from their next use."""
    db.execute("ALTER TABLE sessions ADD COLUMN last_seen_at TEXT")


def _barrier_target_date(db: sqlite3.Connection) -> None:
    """When the team means to have a discharge barrier sorted. Empty for barriers recorded before this."""
    db.execute("ALTER TABLE discharge_barriers ADD COLUMN target_date TEXT")


def _scribe_chunks_lost(db: sqlite3.Connection) -> None:
    """How many audio chunks of a ClinScribe session could not be transcribed."""
    db.execute("ALTER TABLE scribe_sessions ADD COLUMN chunks_lost INTEGER NOT NULL DEFAULT 0")


def _one_draft_per_session(db: sqlite3.Connection) -> None:
    """A ClinScribe session has at most one unsigned draft. Where an older database has several, the
    newest stays and the others are marked discarded (nothing is deleted)."""
    db.execute(
        """
        UPDATE clinical_notes SET status = 'discarded'
        WHERE status = 'draft' AND EXISTS (
            SELECT 1 FROM clinical_notes AS newer
            WHERE newer.session_id = clinical_notes.session_id AND newer.status = 'draft'
              AND (newer.created_at > clinical_notes.created_at
                   OR (newer.created_at = clinical_notes.created_at AND newer.rowid > clinical_notes.rowid))
        )
        """
    )
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_draft_per_session ON clinical_notes (session_id) WHERE status = 'draft'")


def _lab_lines_not_read(db: sqlite3.Connection) -> None:
    """How many lines of a lab report could not be read, and the lines themselves, for the reviewer."""
    db.execute("ALTER TABLE lab_reports ADD COLUMN lines_not_read INTEGER NOT NULL DEFAULT 0")
    db.execute("ALTER TABLE lab_reports ADD COLUMN unread_lines TEXT NOT NULL DEFAULT '[]'")


def _intake_graph_state(db: sqlite3.Connection) -> None:
    """Which complaints the question graph matched, and which graph questions were already offered."""
    db.execute("ALTER TABLE intakes ADD COLUMN graph_state TEXT")


MIGRATIONS: List[Tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "account_states", _account_states),
    (2, "organization_verification", _organization_verification),
    (3, "practitioner_professions", _practitioner_professions),
    (4, "document_encryption", _document_encryption),
    (5, "medication_rule_authority", _medication_rule_authority),
    (6, "intake_patient_link", _intake_patient_link),
    (7, "delivery_detail", _delivery_detail),
    (8, "document_description", _document_description),
    (9, "intake_expiry_and_answer_key", _intake_expiry_and_answer_key),
    (10, "intake_report_requested_at", _intake_report_requested_at),
    (11, "intake_help_requested_at", _intake_help_requested_at),
    (12, "notification_link", _notification_link),
    (13, "intake_review_stamp", _intake_review_stamp),
    (14, "session_last_seen", _session_last_seen),
    (15, "barrier_target_date", _barrier_target_date),
    (16, "scribe_chunks_lost", _scribe_chunks_lost),
    (17, "one_draft_per_session", _one_draft_per_session),
    (18, "lab_lines_not_read", _lab_lines_not_read),
    (19, "intake_graph_state", _intake_graph_state),
]


def applied(db: sqlite3.Connection) -> set:
    db.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    return {row[0] for row in db.execute("SELECT version FROM schema_migrations")}


def _has_records(db: sqlite3.Connection) -> bool:
    return db.execute("SELECT EXISTS (SELECT 1 FROM users)").fetchone()[0] == 1


def backup_before_migrating(db: sqlite3.Connection, path: Path) -> Optional[Path]:
    """A plain copy next to the database, which is exactly as sensitive as the database."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = path.with_name(f"{path.name}.pre-migration-{stamp}.bak")
    copy = sqlite3.connect(target)
    try:
        db.backup(copy)
    finally:
        copy.close()
    make_private(target)
    return target


def run(db: sqlite3.Connection, path: Optional[Path] = None, migrations=None) -> List[int]:
    """Applies what is missing, oldest first. Returns the versions applied."""
    steps = MIGRATIONS if migrations is None else migrations
    done = applied(db)
    db.commit()
    pending = [step for step in steps if step[0] not in done]
    if pending and path is not None and _has_records(db):
        backup_before_migrating(db, path)

    previous = db.isolation_level
    db.isolation_level = None  # transactions below are explicit, because DDL must be inside them
    ran = []
    try:
        for version, name, change in pending:
            db.execute("BEGIN IMMEDIATE")
            try:
                if db.execute("SELECT 1 FROM schema_migrations WHERE version = ?", (version,)).fetchone():
                    db.execute("ROLLBACK")  # another process got here first
                    continue
                change(db)
                db.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, datetime.now(timezone.utc).isoformat(timespec="seconds")),
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
            ran.append(version)
    finally:
        db.isolation_level = previous
    return ran
