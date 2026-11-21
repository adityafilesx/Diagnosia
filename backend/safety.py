"""Whether this installation may do something riskier than a synthetic-data pilot.

The switches in config.py only ask for something. Each is honoured only if the
evidence below is also present, so nothing is enabled by one setting, and there
is no switch that skips these checks. Human approvals are read from
governance_signoffs, which only the server's command line can write.
"""
import logging
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List

from backend.config import ROOT_DIR, settings

logger = logging.getLogger("curai.safety")

KNOWN_ENVIRONMENTS = ("development", "staging", "production")

# Human approvals needed before real patients. Each names who has to give it.
REQUIRED_SIGNOFFS = {
    "clinical_safety_lead": "Clinician accountable for the pilot's clinical safety",
    "laboratory_mapping_review": "Laboratory professional's approval of LOINC mappings in use",
    "cdsco_classification": "Regulatory determination of medical device status",
    "dpdp_assessment": "Legal review of DPDP notices, rights handling and retention",
    "groq_agreement": "Signed data agreement with Groq covering patient data, with zero retention on",
    "gemini_agreement": "Data terms with Google for Gemini covering patient data, on a plan that doesn't train on content",
    "infrastructure_encryption": "Security sign-off of disk encryption, backups and key custody",
    "security_penetration_test": "Independent security test of this deployment",
    "incident_response": "Named owners for clinical incidents and data breaches",
    "loinc_notice": "LOINC licence notice reviewed and displayed",
    "edge_tts_terms": "Microsoft Edge voice terms reviewed, or the voice replaced (it runs only in demo mode today)",
    "meko_agreement": "Signed data agreement with Meko and Yugabyte before patient packs hold any real record",
}

# Approvals that gate one optional feature, even with made-up patients. They aren't needed for real
# patients, because those features stop completely when real patient data is allowed.
FEATURE_SIGNOFFS = {
    "sarvam_terms": "Sarvam account set to zero retention and opted out of model training (its default is to train)",
}


def signed_off(db: sqlite3.Connection, item: str) -> bool:
    return db.execute("SELECT 1 FROM governance_signoffs WHERE item = ? AND revoked_at IS NULL", (item,)).fetchone() is not None


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    owner: str


def is_production() -> bool:
    return settings.environment not in ("development", "staging")


def _configuration_checks() -> List[Check]:
    from backend.records import vault

    key_ok, key_detail = vault.status()
    return [
        Check("known_environment", settings.environment in KNOWN_ENVIRONMENTS, f"CURAI_ENV is {settings.environment}", "Operations"),
        Check("https_cookies", settings.cookie_secure, "CURAI_HTTPS must be 1", "Operations"),
        Check("document_encryption", key_ok, key_detail, "Security"),
        Check(
            "external_messaging_reviewed",
            not settings.enable_external_messaging or _messaging_ready(),
            "External messaging needs a configured provider with a signed agreement",
            "Vendor",
        ),
    ]


def _messaging_ready() -> bool:
    from backend.reminders.adapters import configured_channels

    return bool(configured_channels())


def _data_checks(db: sqlite3.Connection) -> List[Check]:
    unreviewed = db.execute("SELECT COUNT(*) FROM loinc_mappings WHERE status = 'proposed'").fetchone()[0]
    legacy = db.execute("SELECT COUNT(*) FROM clinical_documents WHERE encryption_state = 'plaintext_legacy'").fetchone()[0]
    return [
        Check("reviewed_loinc_mappings", unreviewed == 0, f"{unreviewed} mappings unreviewed", "Laboratory professional"),
        Check("no_plaintext_documents", legacy == 0, f"{legacy} documents not yet encrypted", "Security"),
    ]


def _signoff_checks(db: sqlite3.Connection) -> List[Check]:
    signed = {
        row["item"]
        for row in db.execute("SELECT item FROM governance_signoffs WHERE revoked_at IS NULL")
    }
    return [Check(f"signoff:{item}", item in signed, description, "See CLINICAL_GOVERNANCE.md") for item, description in REQUIRED_SIGNOFFS.items()]


def readiness(db: sqlite3.Connection) -> List[Check]:
    return _configuration_checks() + _data_checks(db) + _signoff_checks(db)


def ready_for_real_patients(db: sqlite3.Connection) -> bool:
    return all(check.passed for check in readiness(db))


def real_patient_data_allowed(db: sqlite3.Connection) -> bool:
    return settings.allow_real_patient_data and ready_for_real_patients(db)


def pilot_mode(db: sqlite3.Connection) -> bool:
    """Pilot mode only ends with the switch off and every check passing."""
    return settings.clinical_pilot_mode or not ready_for_real_patients(db)


def assert_safe_to_start(db: sqlite3.Connection) -> None:
    """Refuses to start a deployment that asks for more than it has earned."""
    problems: List[str] = []
    if settings.environment not in KNOWN_ENVIRONMENTS:
        problems.append(f"Unknown CURAI_ENV: {settings.environment}")
    if settings.demo_mode and settings.environment != "development" and not settings.demo_outside_development:
        problems.append(
            "Demo mode is on outside development. Set CURAI_DEMO_MODE=0, or CURAI_DEMO_OUTSIDE_DEVELOPMENT=1 "
            "if this really is a public demo with made-up patients"
        )
    if is_production():
        problems += [f"{check.name}: {check.detail}" for check in _configuration_checks() if not check.passed]
    if settings.allow_real_patient_data or not settings.clinical_pilot_mode:
        problems += [f"{check.name}: {check.detail}" for check in readiness(db) if not check.passed]
    if problems:
        raise RuntimeError("Curai refused to start:\n- " + "\n- ".join(dict.fromkeys(problems)))
    if settings.demo_mode or settings.default_consent:
        logger.warning(
            "\n%s\nDEMO SETTINGS ON (demo mode: %s, default consent: %s). Made-up patients only.\n%s",
            "=" * 72, "on" if settings.demo_mode else "off", "on" if settings.default_consent else "off", "=" * 72,
        )


def public_status(db: sqlite3.Connection) -> dict:
    """What the interface shows. It comes from the server, so no browser setting can change it."""
    pilot = pilot_mode(db)
    return {
        "pilot_mode": pilot,
        "real_patient_data_allowed": real_patient_data_allowed(db),
        "external_messaging_enabled": settings.enable_external_messaging,
        "message": "Pilot software. Use synthetic data only. Not for patient care." if pilot else "",
    }


def report(db: sqlite3.Connection) -> dict:
    checks = [asdict(check) for check in readiness(db)]
    return {
        "ready_for_real_patients": all(check["passed"] for check in checks),
        "passed": sum(check["passed"] for check in checks),
        "total": len(checks),
        "checks": checks,
    }


def key_file_is_safe(path: Path) -> bool:
    """A key must not sit in the repository, the web folder or next to the documents."""
    resolved = path.resolve()
    forbidden = (ROOT_DIR.resolve(), settings.documents_dir.resolve(), settings.db_path.resolve().parent)
    return not any(resolved.is_relative_to(folder) for folder in forbidden)
