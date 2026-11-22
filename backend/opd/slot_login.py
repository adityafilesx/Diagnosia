"""Slot QR login (BUILD.md step 5).

Each slot shows a QR code in the hospital. The patient scans it, enters their phone number and types a
one-time code. With no SMS provider connected, the code is shown on screen, and only in demo mode with
made-up patients; anywhere else the login refuses. Then the patient picks their own name, masked, from
ONLY that slot's bookings carrying the verified number (families share phones), and the server issues a
normal one-interview link, so the existing hash and expiry rules apply.

A name and a phone number are never a login: neither is secret. The slot code in the QR isn't secret
either. Only the one-time code proves the phone. Codes and sessions are stored as hashes; a code lasts
5 minutes and allows 3 tries, and a session picks one name, once. Everything is rate-limited per slot
and per phone, and the whole login sits behind the diagnofast.slot_login switch, which starts off.
"""
import hashlib
import io
import secrets
import sqlite3
from typing import Optional

import segno
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator

from backend import addons, ratelimit
from backend.auth import require_doctor
from backend.config import settings
from backend.db import get_db
from backend.diagnofast import routes as diagnofast
from backend.opd import routes as opd
from backend.records import audit
from backend.records.store import insert, now_iso

router = APIRouter(prefix="/api/opd")

CODE_MINUTES = 5
SESSION_MINUTES = 10
MAX_TRIES = 3
NOT_AVAILABLE = "This QR code isn't active. Please ask reception."
WRONG = "That code didn't work. Please ask for a new one, or ask reception."


def _hash(kind: str, row_id: str, secret: str) -> str:
    # Salted by the row, so the same six digits never hash alike twice.
    return hashlib.sha256(f"{kind}:{row_id}:{secret}".encode()).hexdigest()


def _codes_on_screen() -> bool:
    """No SMS provider is connected, so a code can only be shown on the screen: demo mode, made-up patients."""
    return settings.demo_mode and not settings.allow_real_patient_data


def _open_slot(db: sqlite3.Connection, slot_code: str) -> sqlite3.Row:
    """The gate for the public routes: the switch is on, and the slot exists and is today or later."""
    if not addons.enabled("diagnofast.slot_login", db) or not addons.enabled("diagnofast.bookings", db):
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_AVAILABLE)
    slot = db.execute(
        "SELECT * FROM opd_slots WHERE slot_code = ? AND substr(starts_at, 1, 10) >= date('now', 'localtime', '-1 day')",
        (slot_code,),
    ).fetchone()
    if slot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_AVAILABLE)
    return slot


def mask_name(name: str) -> str:
    return " ".join(f"{word[0]}***" for word in name.split() if word) or "***"


class PhoneOnly(BaseModel):
    phone: str = Field(max_length=20)

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        return opd.normalise_phone(value)


class Verify(PhoneOnly):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class Choose(BaseModel):
    session: str = Field(min_length=1, max_length=100)
    booking_id: str = Field(max_length=64)


@router.get("/slots/{slot_id}/qr")
def slot_qr(slot_id: str, http: Request, doctor: sqlite3.Row = Depends(require_doctor), db: sqlite3.Connection = Depends(get_db)) -> Response:
    """The QR for reception to show or print. It holds only the slot's public code."""
    slot = opd._managed_slot(db, doctor, slot_id)
    url = f"{str(http.base_url).rstrip('/')}/slot.html?code={slot['slot_code']}"
    buffer = io.BytesIO()
    segno.make_qr(url, error="m").save(buffer, kind="svg", scale=8, border=4, title=f"Slot {slot['starts_at']}")
    return Response(buffer.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@router.get("/qr/{slot_code}")
def slot_page(slot_code: str, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """What the scanning phone shows first: which slot this is, and nobody's name."""
    slot = _open_slot(db, slot_code)
    return {
        "department": opd.department(slot["form_id"]), "starts_at": slot["starts_at"], "ends_at": slot["ends_at"],
        "codes_on_screen": _codes_on_screen(),
    }


@router.post("/qr/{slot_code}/otp", dependencies=[Depends(ratelimit.per_path_value(ratelimit.OTP_PER_SLOT, "slot_code"))])
def request_code(slot_code: str, request: PhoneOnly, db: sqlite3.Connection = Depends(get_db)) -> dict:
    slot = _open_slot(db, slot_code)
    ratelimit.hit(ratelimit.OTP_PER_PHONE, request.phone)
    if not _codes_on_screen():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Codes by SMS aren't set up here. Please ask reception for your link.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    row_id = insert(
        db, "opd_otps", slot_id=slot["id"], phone=request.phone, code_hash="pending", expires_at="pending", created_at=now_iso(),
    )
    db.execute(
        "UPDATE opd_otps SET code_hash = ?, expires_at = datetime('now', ?) WHERE id = ?",
        (_hash("code", row_id, code), f"+{CODE_MINUTES} minutes", row_id),
    )
    # The same answer whether or not this number has a booking, so nobody can test numbers here.
    return {"sent": True, "demo_code": code, "note": "Demo mode: no SMS is sent, so the code is shown here."}


@router.post("/qr/{slot_code}/verify")
def verify_code(slot_code: str, request: Verify, db: sqlite3.Connection = Depends(get_db)) -> dict:
    slot = _open_slot(db, slot_code)
    ratelimit.hit(ratelimit.OTP_VERIFY_PER_PHONE, request.phone)
    row = db.execute(
        """
        SELECT * FROM opd_otps WHERE slot_id = ? AND phone = ? AND session_hash IS NULL
            AND expires_at > datetime('now') AND attempts < ? ORDER BY created_at DESC, rowid DESC LIMIT 1
        """,
        (slot["id"], request.phone, MAX_TRIES),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, WRONG)
    if not secrets.compare_digest(row["code_hash"], _hash("code", row["id"], request.code)):
        db.execute("UPDATE opd_otps SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
        db.commit()  # a wrong try counts even though this request fails
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, WRONG)
    session = secrets.token_urlsafe(24)
    db.execute(
        "UPDATE opd_otps SET session_hash = ?, session_expires_at = datetime('now', ?) WHERE id = ?",
        (_hash("session", row["id"], session), f"+{SESSION_MINUTES} minutes", row["id"]),
    )
    bookings = db.execute(
        "SELECT id, patient_name, patient_age FROM opd_bookings WHERE slot_id = ? AND phone = ? ORDER BY queue_number",
        (slot["id"], request.phone),
    ).fetchall()
    return {
        "session": f"{row['id']}.{session}",
        "bookings": [{"id": item["id"], "name": mask_name(item["patient_name"]), "age": item["patient_age"]} for item in bookings],
    }


def _session(db: sqlite3.Connection, slot: sqlite3.Row, value: str) -> sqlite3.Row:
    row_id, _, secret = value.partition(".")
    row = db.execute(
        """
        SELECT * FROM opd_otps WHERE id = ? AND slot_id = ? AND used_at IS NULL AND session_hash IS NOT NULL
            AND session_expires_at > datetime('now')
        """,
        (row_id, slot["id"]),
    ).fetchone()
    if row is None or not secret or not secrets.compare_digest(row["session_hash"], _hash("session", row["id"], secret)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please start again with a new code.")
    return row


@router.post("/qr/{slot_code}/choose")
def choose_name(slot_code: str, request: Choose, http: Request, db: sqlite3.Connection = Depends(get_db)) -> dict:
    slot = _open_slot(db, slot_code)
    session = _session(db, slot, request.session)
    booking: Optional[sqlite3.Row] = db.execute(
        "SELECT * FROM opd_bookings WHERE id = ? AND slot_id = ? AND phone = ?", (request.booking_id, slot["id"], session["phone"]),
    ).fetchone()
    if booking is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That name isn't booked in this slot with this number.")
    if booking["intake_id"]:
        current = db.execute(
            "SELECT status, (expires_at IS NOT NULL AND expires_at <= datetime('now')) AS expired FROM intakes WHERE id = ?",
            (booking["intake_id"],),
        ).fetchone()
        if current and current["status"] not in ("waiting", "expired") and not current["expired"]:
            raise HTTPException(status.HTTP_409_CONFLICT, "This interview has already started on another phone. Please ask reception.")
    db.execute("UPDATE opd_otps SET used_at = ? WHERE id = ?", (now_iso(), session["id"]))
    made = _fresh_link(db, booking, str(http.base_url))
    audit.record(db, None, "opd.slot_login.link_issued", resource_type="opd_booking", resource_id=booking["id"])
    return {"link": made, "queue_number": booking["queue_number"], "department": opd.department(booking["form_id"])}


def _fresh_link(db: sqlite3.Connection, booking: sqlite3.Row, base_url: str) -> str:
    """A normal one-interview link, shown once on this phone. Any older unused link stops."""
    if booking["intake_id"]:
        db.execute(
            "UPDATE intakes SET status = 'expired', expires_at = datetime('now') WHERE id = ? AND status = 'waiting'",
            (booking["intake_id"],),
        )
    doctor = db.execute("SELECT * FROM users WHERE id = ?", (booking["doctor_id"],)).fetchone()
    made = diagnofast.create_intake(
        diagnofast.NewIntake(
            form_id=booking["form_id"], patient_name=booking["patient_name"], patient_age=booking["patient_age"],
            patient_sex=booking["patient_sex"], patient_id=booking["patient_id"],
        ),
        doctor,
        db,
    )
    db.execute("UPDATE opd_bookings SET intake_id = ? WHERE id = ?", (made["id"], booking["id"]))
    return f"{base_url.rstrip('/')}/{made['link']}"
