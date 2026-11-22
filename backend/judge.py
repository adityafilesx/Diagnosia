"""Judge mode: a public demo where each tool on the home page opens already signed in.

For the IIITD hackathon judges, on a deployment holding made-up patients only. A visitor who opens
/demo/open?tool=<id> gets an ordinary session (the same cookie and session table as a password
sign-in) for one seeded account, then lands in the workspace on that tool.

It takes effect only with DIAGNOSIA_JUDGE_MODE=1, demo mode on and real patient data off
(config.judge_mode_active); asked for without those, the app refuses to start (safety.py). Off, both
routes answer as if they did not exist, so nothing can be opened.

The doctor account is a verified doctor who is NOT an organization administrator, so a judge can
use every clinical tool but cannot change Settings, keys or staff verification.
"""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

from backend import auth, ratelimit
from backend.config import judge_mode_active
from backend.db import get_db
from backend.records import audit

# Seeded by backend/synthetic/seed_accounts.py with the fixed seed, so the same people every boot.
# doctor07 is a General Medicine doctor (the DiagnoFast general form) on patient007's care team.
DOCTOR_EMAIL = "doctor07@example.com"
PATIENT_EMAIL = "patient007@example.com"

# The ids are web/js/care/catalogue.js's. The Prescription Analyzer is the patient's own tool;
# the rest are staff tools, which need a verified doctor.
TOOL_ACCOUNTS = {
    "diagnofast": DOCTOR_EMAIL,
    "clinscribe": DOCTOR_EMAIL,
    "lablens": DOCTOR_EMAIL,
    "prescription": PATIENT_EMAIL,
    "referrals": DOCTOR_EMAIL,
    "discharge": DOCTOR_EMAIL,
}

router = APIRouter()


def active() -> bool:
    return judge_mode_active()


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


def demo_account(db: sqlite3.Connection, email: str) -> Optional[sqlite3.Row]:
    """The seeded account, if it is ready to use. A doctor must be verified, as for anyone else."""
    row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row is None or row["account_status"] == "suspended":
        return None
    if row["role"] == "doctor" and row["account_status"] != "verified":
        return None
    return row


def demo_chart_id(db: sqlite3.Connection, user: sqlite3.Row) -> Optional[str]:
    """The chart the workspace opens first in judge mode: the demo patient's own record, which the
    demo doctor is also a clinician on. None outside judge mode, or for anyone else."""
    if not active() or user["email"] not in (DOCTOR_EMAIL, PATIENT_EMAIL):
        return None
    row = db.execute(
        "SELECT patients.id FROM patients JOIN users ON users.id = patients.user_id WHERE users.email = ?",
        (PATIENT_EMAIL,),
    ).fetchone()
    return row["id"] if row else None


def _address_limit(request: Request) -> None:
    # Checked only in judge mode, so a closed door never counts or reveals anything.
    if active():
        ratelimit.per_client(ratelimit.DEMO_OPENS)(request)


@router.get("/demo/open", include_in_schema=False, dependencies=[Depends(_address_limit)])
def open_tool(
    tool: str = Query(default="", max_length=40),
    diagnosia_session: Optional[str] = Cookie(default=None),
    db: sqlite3.Connection = Depends(get_db),
) -> RedirectResponse:
    if not active() or tool not in TOOL_ACCOUNTS:
        raise _not_found()
    user = demo_account(db, TOOL_ACCOUNTS[tool])
    if user is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The demo accounts are not ready yet. Please try again in a minute.")
    if diagnosia_session:
        # Moving between tools swaps accounts. The old session goes, so none is left lying around.
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (auth.hash_token(diagnosia_session),))
    response = RedirectResponse(f"/care.html#/{tool}", status_code=status.HTTP_303_SEE_OTHER)
    audit.record(db, user, "demo.open", resource_type="tool", resource_id=tool)
    auth.start_session(db, response, user["id"], user["role"])  # commits, before the redirect leaves
    return response


@router.get("/api/demo/status")
def demo_status() -> dict:
    """Public: lets the home page point each tool at the demo door. Says nothing else."""
    return {"judge_mode": active()}
