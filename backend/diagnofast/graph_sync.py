"""Copies finished DiagnoFast visits into Neo4j, and reads the history and evidence graphs back (step 8).

The same pattern as patient packs (patient_pack/sync.py): a finished change queues a reference in the
same SQLite transaction, and this worker reads the record from SQLite when it sends. CareFlow events
carry no free text, so they can't supply content. Neo4j receives IDs and coded terms only: complaint
codes from the question graph's seed, the first word of each medicine and allergy, the department's
form ID, and which answers each report row cites. No names, no transcripts, no free text.

Reading back, Neo4j only says WHICH visits and rows are linked. Every word shown to the doctor is read
again from SQLite, for visits of the same patient, behind the access gate the route has already passed.
With Neo4j off or down, the same views are built from SQLite alone.
"""
import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from backend import addons
from backend.careflow.delivery import retry_delay
from backend.db import connect
from backend.diagnofast import guidance
from backend.integrations import graph
from backend.records.store import now_iso

logger = logging.getLogger("curai.graph")

BATCH = 20
MAX_HISTORY = 10
WORD = re.compile(r"[A-Za-zऀ-ॿ]+")


def enqueue(db: sqlite3.Connection, source_type: str, source_id) -> None:
    """A reference only, written with the change itself. Nothing is queued while the Neo4j switch is off."""
    if not addons.enabled("neo4j.enabled", db):
        return
    stamp = now_iso()
    db.execute(
        """
        INSERT INTO graph_items (id, source_type, source_id, next_attempt_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (source_type, source_id) DO UPDATE SET
            state = 'queued', attempts = 0, last_error = NULL, next_attempt_at = excluded.next_attempt_at, updated_at = excluded.updated_at
        """,
        (str(uuid.uuid4()), source_type, str(source_id), stamp, stamp, stamp),
    )


def _code(text: str) -> Optional[str]:
    """A coded term: the first word, lowercased. "Metformin 500 mg twice a day" becomes "metformin"."""
    found = WORD.search(text or "")
    return found.group(0).lower() if found else None


def visit_for(row: sqlite3.Row) -> Optional[dict]:
    """The Neo4j copy of one finished visit: IDs and coded terms only."""
    if row["status"] != "done" or not row["report"]:
        return None
    report = json.loads(row["report"])
    transcript = json.loads(row["transcript"])
    visit_ref = f"intake:{row['id']}"
    terms = [{"kind": "complaint", "code": code, "source": "patient"}
             for code in guidance.match_complaints([report.get("chief_complaint", "")] + [turn["answer"] for turn in transcript])]
    for kind, key in (("medicine", "current_medicines"), ("allergy", "allergies")):
        for item in report.get(key, []):
            code = _code(item)
            if code:
                terms.append({"kind": kind, "code": code, "source": "patient"})
    return {
        "patient_ref": f"patient:{row['patient_id']}" if row["patient_id"] else f"link:{row['id']}",
        "visit_ref": visit_ref,
        "doctor_ref": f"doctor:{row['doctor_id']}",
        "day": (row["created_at"] or "")[:10],
        "department": row["form_id"],
        "reviewed": bool(row["reviewed_at"]),
        "terms": terms,
        "answers": [{"ref": f"{visit_ref}:turn:{index}", "turn": index, "has_recording": bool(turn.get("audio"))}
                    for index, turn in enumerate(transcript, start=1)],
        "rows": [{"ref": f"{visit_ref}:row:{index}", "index": index, "flag": item.get("flag"), "turns": list(item.get("evidence_turns", []))}
                 for index, item in enumerate(report.get("review_of_systems", []))],
    }


def run_once(now: Optional[datetime] = None) -> int:
    """Sends what is due. Returns how many were sent. Stops completely when real patient data is allowed."""
    now = now or datetime.now(timezone.utc)
    db = connect()
    sent = 0
    try:
        if not addons.neo4j_ready(db):
            return 0
        client = graph.client(db)
        if client is None:
            return 0
        due = db.execute(
            "SELECT * FROM graph_items WHERE state = 'queued' AND next_attempt_at <= ? ORDER BY created_at LIMIT ?",
            (now.isoformat(timespec="seconds"), BATCH),
        ).fetchall()
        for item in due:
            if item["source_type"] == "referral":
                from backend.referralloop import network

                row = db.execute("SELECT * FROM referrals WHERE id = ?", (item["source_id"],)).fetchone()
                payload = network.referral_for(row) if row is not None else None
                send = client.merge_referral
            else:
                row = db.execute("SELECT * FROM intakes WHERE id = ?", (item["source_id"],)).fetchone()
                payload = visit_for(row) if row is not None else None
                send = client.merge_visit
            visit = payload
            if visit is None:
                db.execute("UPDATE graph_items SET state = 'skipped', updated_at = ? WHERE id = ?", (now_iso(), item["id"]))
                db.commit()
                continue
            db.commit()  # no lock held while Neo4j answers
            try:
                send(visit)
            except graph.GraphUnavailable as error:
                attempts = item["attempts"] + 1
                later = now + timedelta(seconds=retry_delay(attempts))
                db.execute(
                    "UPDATE graph_items SET attempts = ?, last_error = ?, next_attempt_at = ?, updated_at = ? WHERE id = ?",
                    (attempts, str(error)[:80], later.isoformat(timespec="seconds"), now_iso(), item["id"]),
                )
                db.commit()
                logger.warning("Neo4j unavailable, will retry: %s", error)
                break  # the rest wait for the next pass
            db.execute("UPDATE graph_items SET state = 'sent', last_error = NULL, updated_at = ? WHERE id = ?", (now_iso(), item["id"]))
            db.commit()
            sent += 1
        return sent
    finally:
        db.close()


def background_pass() -> int:
    """For the app's delivery loop. Tests replace it, and call run_once themselves."""
    return run_once()


def rebuild() -> int:
    """Empties the projection and queues every finished visit again. Returns how many were queued."""
    db = connect()
    try:
        client = graph.client(db)
        if client is None:
            return -1
        client.clear()
        stamp = now_iso()
        count = 0
        for row in db.execute("SELECT id FROM intakes WHERE status = 'done' AND report IS NOT NULL").fetchall():
            enqueue(db, "intake", row["id"])
            count += 1
        for row in db.execute("SELECT id FROM referrals").fetchall():
            enqueue(db, "referral", row["id"])
            count += 1
        db.execute("UPDATE graph_items SET next_attempt_at = ? WHERE state = 'queued'", (stamp,))
        db.commit()
        return count
    finally:
        db.close()


# Reading back for the doctor's report


def _row_view(item: dict) -> dict:
    return {key: item.get(key) for key in ("system", "parameter", "finding", "flag")}


def _sqlite_evidence(row: sqlite3.Row) -> List[dict]:
    report = json.loads(row["report"]) if row["report"] else {}
    return [{"row": index, "turns": list(item.get("evidence_turns", []))} for index, item in enumerate(report.get("review_of_systems", []))]


def _sqlite_history(db: sqlite3.Connection, row: sqlite3.Row) -> List[int]:
    if not row["patient_id"]:
        return [row["id"]]
    return [item["id"] for item in db.execute(
        "SELECT id FROM intakes WHERE patient_id = ? AND status = 'done' ORDER BY id DESC LIMIT ?", (row["patient_id"], MAX_HISTORY),
    )]


def views(db: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """The evidence and history graphs for one visit. The caller has already passed the access gate."""
    source = "sqlite"
    evidence_links = _sqlite_evidence(row)
    history_ids = _sqlite_history(db, row)
    client = graph.client(db)
    if client is not None and row["status"] == "done":
        try:
            found = client.evidence(f"intake:{row['id']}")
            patient_ref = f"patient:{row['patient_id']}" if row["patient_id"] else f"link:{row['id']}"
            visits = client.history(patient_ref)
            if found:
                evidence_links = [{"row": item["row"], "turns": [answer["turn"] for answer in item["answers"] if answer.get("turn")]} for item in found]
                history_ids = []
                for visit in visits[:MAX_HISTORY]:
                    ref = visit.get("visit_ref") or ""
                    if ref.startswith("intake:") and ref[7:].isdigit():
                        history_ids.append(int(ref[7:]))
                source = "neo4j"
        except graph.GraphUnavailable as error:
            logger.warning("Neo4j unavailable, graphs drawn from SQLite: %s", error)

    report = json.loads(row["report"]) if row["report"] else {}
    rows = report.get("review_of_systems", [])
    transcript = json.loads(row["transcript"])
    evidence = []
    for link in evidence_links:
        if not 0 <= link["row"] < len(rows):
            continue
        answers = [
            {"turn": turn, "question": transcript[turn - 1]["question"], "answer": transcript[turn - 1]["answer"], "has_recording": bool(transcript[turn - 1].get("audio"))}
            for turn in link["turns"] if isinstance(turn, int) and 1 <= turn <= len(transcript)
        ]
        evidence.append({"index": link["row"], "row": _row_view(rows[link["row"]]), "answers": answers})

    # Words for each visit come from SQLite, and only for visits of this same patient.
    history = []
    for intake_id in dict.fromkeys(history_ids):
        if row["patient_id"]:
            visit = db.execute("SELECT * FROM intakes WHERE id = ? AND patient_id = ? AND status = 'done'", (intake_id, row["patient_id"])).fetchone()
        else:
            visit = row if intake_id == row["id"] else None
        if visit is None or not visit["report"]:
            continue
        summary = json.loads(visit["report"])
        history.append({
            "intake_id": visit["id"], "day": (visit["created_at"] or "")[:10], "department": visit["form_id"],
            "reviewed": bool(visit["reviewed_at"]), "doctor_id": visit["doctor_id"], "current": visit["id"] == row["id"],
            "chief_complaint": summary.get("chief_complaint", ""),
            "medicines": summary.get("current_medicines", []), "allergies": summary.get("allergies", []),
        })
    return {"source": source, "evidence": evidence, "history": history}
