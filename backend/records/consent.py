"""The consent words patients see, and the record of what they agreed to.

Each wording has a version. Change the words, change the version: a stored record then still says
which words the person saw. The pages show these words from the API (the interview) or repeat them
exactly (the prescription page, checked by a test), so what is stored is what was shown.

The Hindi wording still needs approval from a Hindi speaker before real use (audit plan WI-101).
"""
import sqlite3
from typing import Optional

INTERVIEW = "diagnofast_interview"
ABHA = "abha_records"
PRESCRIPTION = "prescription_photo"

VERSION = "2026-11-13"

WORDS = {
    INTERVIEW: {
        "en-IN": [
            "Your answers are recorded and kept for your doctor.",
            "To understand your answers, they are sent to outside AI services (Groq and Google, in the United States).",
            "A doctor checks everything. This interview does not diagnose you.",
        ],
        "hi-IN": [
            "आपके जवाब रिकॉर्ड करके आपके डॉक्टर के लिए रखे जाते हैं।",
            "आपके जवाब समझने के लिए उन्हें बाहरी AI सेवाओं (Groq और Google, अमेरिका में) को भेजा जाता है।",
            "डॉक्टर सब कुछ जाँचेंगे। यह बातचीत आपकी बीमारी नहीं बताती।",
        ],
    },
    ABHA: {
        "en-IN": ["Your past health records can be fetched from ABHA for your doctor. Fetch them?"],
        "hi-IN": ["आपके पुराने स्वास्थ्य रिकॉर्ड ABHA से आपके डॉक्टर के लिए लाए जा सकते हैं। क्या लाएँ?"],
    },
    PRESCRIPTION: {
        "en-IN": ["I agree to my photo being sent to outside AI services to read it. Curai doesn't keep the photo."],
    },
}


def words(kind: str) -> dict:
    """What the page shows for one kind of consent."""
    return {"version": VERSION, "lines": WORDS[kind]}


def record(
    db: sqlite3.Connection,
    kind: str,
    language: str,
    agreed: bool,
    *,
    intake_id: Optional[int] = None,
    user_id: Optional[int] = None,
    version: str = VERSION,
) -> None:
    db.execute(
        """
        INSERT INTO consent_records (kind, text_version, language, agreed, intake_id, user_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (kind, version, language, 1 if agreed else 0, intake_id, user_id),
    )


def given(db: sqlite3.Connection, kind: str, *, intake_id: Optional[int] = None) -> bool:
    return db.execute(
        "SELECT 1 FROM consent_records WHERE kind = ? AND intake_id = ? AND agreed = 1", (kind, intake_id)
    ).fetchone() is not None
