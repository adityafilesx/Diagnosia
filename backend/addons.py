"""Whether each hackathon add-on may run right now (BUILD.md).

Every add-on starts off. Sarvam and Neo4j also stop completely when real patient data is allowed,
as patient packs do, because neither has a data agreement. Sarvam additionally needs the
sarvam_terms sign-off, since its own terms train on API data unless the account opts out.
"""
import sqlite3
from typing import Optional

from backend import safety, settings_store
from backend.config import settings


def _switch(key: str, db: Optional[sqlite3.Connection]) -> bool:
    return bool(settings_store.get(key, db))


def enabled(key: str, db: Optional[sqlite3.Connection] = None) -> bool:
    """A DiagnoFast add-on switch, such as "diagnofast.bookings"."""
    return _switch(key, db)


def _made_up_patients_only() -> bool:
    return not settings.allow_real_patient_data


def sarvam_ready(db: sqlite3.Connection) -> bool:
    return (
        _made_up_patients_only()
        and _switch("sarvam.enabled", db)
        and bool(settings_store.api_key(db, "sarvam"))
        and safety.signed_off(db, "sarvam_terms")
    )


def neo4j_ready(db: sqlite3.Connection) -> bool:
    return _made_up_patients_only() and _switch("neo4j.enabled", db) and bool(settings.neo4j_uri)


def blockers(db: sqlite3.Connection) -> dict:
    """What each add-on still needs before it can run, in words for the Settings page. An empty list
    means nothing beyond its own switch. Never holds a key or an address, only whether one is there."""
    real_data = [] if _made_up_patients_only() else ["Off while real patient data is allowed"]
    sarvam = list(real_data)
    if not settings_store.api_key(db, "sarvam"):
        sarvam.append("Needs a Sarvam API key")
    if not safety.signed_off(db, "sarvam_terms"):
        sarvam.append("Needs the sarvam_terms sign-off")
    neo4j = list(real_data)
    if not settings.neo4j_uri:
        neo4j.append("Needs NEO4J_URI in the server environment")
    return {
        "sarvam.enabled": sarvam,
        "neo4j.enabled": neo4j,
        "diagnofast.slot_login": [] if _switch("diagnofast.bookings", db) else ["Needs OPD bookings switched on"],
    }
