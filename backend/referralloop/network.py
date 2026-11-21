"""The referral network view (stretch A, BUILD.md): who refers to whom, overdue loops, specialist load.

Staff only, behind referrals.network_view (off by default). SQLite decides which referrals a person may
see: ones they sent, or ones sent to them or to their organization with the patient's referral-sharing
consent still active, as the inbox does. Neo4j holds only IDs and coded terms (graph_sync.py copies them)
and is asked about those referrals and no others. Every word shown, names and specialties, is read again
from SQLite. With Neo4j off or down, the same view is built from SQLite alone.
"""
import logging
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date
from typing import Dict, List

from backend.integrations import graph

logger = logging.getLogger("curai.referralloop")

TERMINAL = ("closed", "cancelled")
WAITING = ("sent", "acknowledged", "accepted")


def _code(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_") or "unspecified"


def _destination_ref(row: sqlite3.Row) -> str:
    if row["receiving_user_id"]:
        return f"doctor:{row['receiving_user_id']}"
    if row["receiving_organization_id"]:
        return f"org:{row['receiving_organization_id']}"
    return f"manual:{_code(row['specialty'])}"  # an outside service typed by hand: grouped by specialty


def referral_for(row: sqlite3.Row) -> dict:
    """The Neo4j copy of one referral: references and codes only. No reason, question, note or patient."""
    return {
        "ref": f"referral:{row['id']}",
        "from_ref": f"doctor:{row['referring_user_id']}",
        "to_ref": _destination_ref(row),
        "specialty": _code(row["specialty"]),
        "priority": row["priority"],
        "status": row["status"],
        "open": row["status"] not in TERMINAL,
        "respond_by": row["respond_by"][:10],
        "day": (row["created_at"] or "")[:10],
    }


def _network_scope(db: sqlite3.Connection, user: sqlite3.Row) -> List[sqlite3.Row]:
    """The access gate: every referral this person may see, from SQLite."""
    return db.execute(
        """
        SELECT DISTINCT referrals.* FROM referrals
        LEFT JOIN organization_members AS member
          ON member.organization_id = referrals.receiving_organization_id AND member.user_id = ?
        WHERE referrals.referring_user_id = ?
           OR ((referrals.receiving_user_id = ? OR member.user_id IS NOT NULL)
               AND EXISTS (SELECT 1 FROM consents WHERE consents.patient_id = referrals.patient_id
                           AND consents.purpose = 'referral_sharing' AND consents.revoked_at IS NULL))
        ORDER BY referrals.id
        """,
        (user["id"], user["id"], user["id"]),
    ).fetchall()


def _name(db: sqlite3.Connection, ref: str, fallback_specialty: str) -> dict:
    kind, _, key = ref.partition(":")
    name = None
    if kind == "doctor" and key.isdigit():
        found = db.execute("SELECT first_name, last_name FROM users WHERE id = ?", (int(key),)).fetchone()
        name = f"{found['first_name']} {found['last_name']}" if found else None
    elif kind == "org":
        found = db.execute("SELECT name FROM organizations WHERE id = ?", (key,)).fetchone()
        name = found["name"] if found else None
    elif kind == "manual":
        name = f"Outside service ({fallback_specialty})"
    return {"ref": ref, "name": name or "Unknown"}


def view(db: sqlite3.Connection, allowed: List[sqlite3.Row]) -> dict:
    """The network over `allowed`, the referrals _network_scope returned for this person."""
    scope = {f"referral:{row['id']}": row for row in allowed}
    links: List[dict] = [referral_for(row) for row in scope.values()]
    source = "sqlite"
    client = graph.client(db)
    if client is not None and scope:
        try:
            db.commit()  # no lock held while Neo4j answers
            found = client.referral_network(sorted(scope))
            # Neo4j may only narrow what SQLite allowed, never add to it.
            links = [item for item in found if item["ref"] in scope]
            source = "neo4j"
        except graph.GraphUnavailable as error:
            logger.warning("Neo4j unavailable, the referral network is drawn from SQLite: %s", error)

    today = date.today().isoformat()
    # The specialty's words come from SQLite: the most common spelling among this person's referrals.
    spelled: Dict[str, Counter] = defaultdict(Counter)
    for row in scope.values():
        spelled[_code(row["specialty"])][row["specialty"].strip()] += 1
    words = {code: counts.most_common(1)[0][0] for code, counts in spelled.items()}

    paths: Dict[tuple, dict] = {}
    load: Dict[str, dict] = {}
    overdue: List[dict] = []
    names: Dict[str, dict] = {}

    def named(ref: str, specialty: str) -> dict:
        if ref not in names:
            names[ref] = _name(db, ref, specialty)
        return names[ref]

    for item in links:
        specialty = words.get(item["specialty"], item["specialty"])
        is_overdue = bool(item["open"]) and item["status"] in WAITING and item["respond_by"] < today
        key = (item["from_ref"], item["to_ref"], item["specialty"])
        edge = paths.setdefault(key, {"from": named(item["from_ref"], specialty), "to": named(item["to_ref"], specialty),
                                       "specialty": specialty, "referrals": 0, "open": 0, "overdue": 0})
        edge["referrals"] += 1
        edge["open"] += bool(item["open"])
        edge["overdue"] += is_overdue
        if item["open"]:
            slot = load.setdefault(item["to_ref"], {"destination": named(item["to_ref"], specialty), "open": 0, "overdue": 0})
            slot["open"] += 1
            slot["overdue"] += is_overdue
        if is_overdue:
            row = scope[item["ref"]]
            overdue.append({"referral_id": row["id"], "specialty": specialty, "priority": row["priority"],
                            "respond_by": row["respond_by"][:10], "to": named(item["to_ref"], specialty)})
    return {
        "source": source,
        "paths": sorted(paths.values(), key=lambda edge: (-edge["referrals"], edge["from"]["ref"], edge["to"]["ref"], edge["specialty"])),
        "load": sorted(load.values(), key=lambda slot: (-slot["open"], slot["destination"]["ref"])),
        "overdue": sorted(overdue, key=lambda entry: (entry["respond_by"], entry["referral_id"])),
    }
