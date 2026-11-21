"""Possible medicine and allergy conflicts across doctors (stretch B, BUILD.md). Staff only.

Behind conflicts.medicine_checks, which starts off. For a doctor or pharmacist who can open the patient's
record, this lists:
- the same medicine name in records from different doctors or sources (a possible duplicate), and
- a recorded allergy whose name appears in a medicine's name (a possible allergy conflict).

Only finished, confirmed records count: DiagnoFast reports a doctor has marked reviewed, prescriptions
the patient ticked and saved, and active allergy records. Never a draft, an unreviewed report, a
transcript or an unconfirmed medicine. Each flag says "Possible conflict: check" and nothing more: no
advice, no alternative, and no other medicine name. Patients never see this.

Matching is by exact name only (the first word, ignoring case). Spotting two medicines that share an
ingredient (salt) needs a licensed drug database. The local medicine list is scraped and its permission
unconfirmed, so its ingredient column is never used here, and the answer says salt matching is unavailable.

With Neo4j on, the patient's reviewed visits are found through the history graph; every word is still
read from SQLite, behind the same access gate. With Neo4j off or down, everything comes from SQLite.
"""
import json
import logging
import re
import sqlite3
from collections import defaultdict
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, status

from backend import addons
from backend.auth import require_doctor
from backend.db import get_db
from backend.integrations import graph
from backend.records.access import READ, open_patient

logger = logging.getLogger("curai.conflicts")
router = APIRouter(prefix="/api/conflicts")

WORD = re.compile(r"[A-Za-zऀ-ॿ]+")
SALT_CHECK = {
    "available": False,
    "reason": "Matching medicines that share an ingredient (salt) is not available without a licensed drug database. "
              "Only exact names are compared here.",
}


def _code(text: str) -> str:
    found = WORD.search(text or "")
    return found.group(0).lower() if found else ""


def _doctor(db: sqlite3.Connection, user_id) -> str:
    row = db.execute("SELECT first_name, last_name FROM users WHERE id = ?", (user_id,)).fetchone()
    return f"{row['first_name']} {row['last_name']}" if row else "Unknown"


def _reviewed_visit_ids(db: sqlite3.Connection, patient_id: str) -> tuple:
    """Which reviewed visits to read: from the history graph when Neo4j is on, else from SQLite."""
    from_sqlite = [row["id"] for row in db.execute(
        "SELECT id FROM intakes WHERE patient_id = ? AND status = 'done' AND reviewed_at IS NOT NULL AND report IS NOT NULL",
        (patient_id,),
    )]
    client = graph.client(db)
    if client is None:
        return from_sqlite, "sqlite"
    try:
        db.commit()  # no lock held while Neo4j answers
        visits = client.history(f"patient:{patient_id}")
    except graph.GraphUnavailable as error:
        logger.warning("Neo4j unavailable, conflict checks read SQLite: %s", error)
        return from_sqlite, "sqlite"
    allowed = set(from_sqlite)  # SQLite decides; the graph may only narrow
    found = [int(v["visit_ref"][7:]) for v in visits if str(v.get("visit_ref", "")).startswith("intake:") and v["visit_ref"][7:].isdigit()]
    return [visit_id for visit_id in found if visit_id in allowed], "neo4j"


def _records(db: sqlite3.Connection, patient_id: str) -> tuple:
    medicines: List[dict] = []
    allergies: List[dict] = []
    visit_ids, source = _reviewed_visit_ids(db, patient_id)
    for visit_id in visit_ids:
        row = db.execute("SELECT id, doctor_id, report, created_at FROM intakes WHERE id = ? AND patient_id = ?", (visit_id, patient_id)).fetchone()
        if row is None:
            continue
        report = json.loads(row["report"])
        where = f"DiagnoFast visit, {(row['created_at'] or '')[:10]} (reviewed)"
        for text in report.get("current_medicines", []):
            medicines.append({"text": text, "doctor": _doctor(db, row["doctor_id"]), "doctor_id": row["doctor_id"], "where": where})
        for text in report.get("allergies", []):
            allergies.append({"text": text, "where": where})
    for row in db.execute("SELECT medicines, created_at FROM saved_prescriptions WHERE patient_id = ?", (patient_id,)):
        for medicine in json.loads(row["medicines"]):
            name = (medicine.get("name") or {}).get("value", "")
            if name.strip():  # only the name the patient confirmed; the ingredient list is never read
                medicines.append({"text": name, "doctor": "Prescriber not recorded", "doctor_id": None,
                                  "where": f"Prescription saved by the patient, {row['created_at'][:10]}"})
    for row in db.execute("SELECT substance, created_at FROM allergies WHERE patient_id = ? AND status = 'active'", (patient_id,)):
        allergies.append({"text": row["substance"], "where": f"Allergy record, {row['created_at'][:10]}"})
    return medicines, allergies, source


def flags_for(medicines: List[dict], allergies: List[dict]) -> List[dict]:
    flags: List[dict] = []
    by_code: Dict[str, List[dict]] = defaultdict(list)
    for medicine in medicines:
        code = _code(medicine["text"])
        if code:
            by_code[code].append(medicine)
    for code, entries in sorted(by_code.items()):
        sources = {(entry["doctor_id"], entry["where"]) for entry in entries}
        if len(entries) > 1 and len(sources) > 1:
            names = ", ".join(sorted({f"'{entry['text']}'" for entry in entries}))
            flags.append({
                "kind": "possible_duplicate",
                "message": f"Possible conflict: check. The same medicine name appears in {len(entries)} records: {names}.",
                "records": [{key: entry[key] for key in ("text", "doctor", "where")} for entry in entries],
            })
    for item in allergies:
        substance = _code(item["text"])
        if not substance:
            continue
        pattern = re.compile(rf"(?<![A-Za-zऀ-ॿ]){re.escape(substance)}(?![A-Za-zऀ-ॿ])", re.IGNORECASE)
        for medicine in medicines:
            if pattern.search(medicine["text"]):
                flags.append({
                    "kind": "allergy_conflict",
                    "message": f"Possible conflict: check. A recorded allergy to '{item['text']}' and the medicine '{medicine['text']}'.",
                    "records": [{"text": item["text"], "doctor": "", "where": item["where"]},
                                {key: medicine[key] for key in ("text", "doctor", "where")}],
                })
    return flags


@router.get("/patients/{patient_id}")
def patient_conflicts(patient_id: str, user=Depends(require_doctor), db: sqlite3.Connection = Depends(get_db)) -> dict:
    """For the doctor or pharmacist only. Patients never see this."""
    if not addons.enabled("conflicts.medicine_checks", db):
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "addon_off", "message": "Medicine checks are switched off."})
    open_patient(db, user, patient_id, "conflicts.viewed", READ)
    medicines, allergies, source = _records(db, patient_id)
    return {"source": source, "flags": flags_for(medicines, allergies), "salt_check": SALT_CHECK,
            "checked": {"medicines": len(medicines), "allergies": len(allergies)}}
