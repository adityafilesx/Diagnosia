"""OPD bookings for DiagnoFast: slots, queue numbers and the demo SMS outbox (BUILD.md step 4).

Reception books a patient into a doctor's slot. The booking gets the next queue number for that
doctor that day, its department comes from the slot, and DiagnoFast issues a normal one-interview link
for it, so the link's hash and expiry rules apply unchanged.

The link is "sent" to the patient's phone through a demo outbox only. No SMS or WhatsApp provider is
connected (reminders/adapters.py), so nothing leaves the server. The message is neutral, holds only
the link, and is stored with the link hidden: only the link's hash is kept anywhere.

Everything here is behind the diagnofast.bookings switch, which starts off.
"""
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator

from backend import addons
from backend.auth import require_doctor
from backend.db import get_db
from backend.diagnofast import agent
from backend.diagnofast import routes as diagnofast
from backend.records import audit
from backend.records.access import WRITE, open_patient
from backend.records.store import insert, now_iso

router = APIRouter(prefix="/api/opd")

MOBILE = re.compile(r"^[6-9]\d{9}$")
LOCAL_TIME = "%Y-%m-%dT%H:%M"
EVENING_BEFORE = "18:00"
LINK_HIDDEN = "[link hidden]"
# A walk-in who isn't sure of their department still needs a form for the interview: the general one.
WALK_IN_FORM = "general_physician"
# Neutral on purpose: an outside carrier must never see anything clinical, not even the department.
MESSAGE = "Your clinic asks you to answer a few questions before your visit. / अपनी विज़िट से पहले कुछ सवालों के जवाब दें: {link}"


def bookings_on(_doctor=Depends(require_doctor), db: sqlite3.Connection = Depends(get_db)) -> None:
    if not addons.enabled("diagnofast.bookings", db):
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "addon_off", "message": "OPD bookings are switched off. An administrator can turn them on in Settings."})


def normalise_phone(value: str) -> str:
    digits = re.sub(r"[\s-]", "", value or "")
    digits = re.sub(r"^(\+91|0091|91(?=\d{10}$)|0(?=\d{10}$))", "", digits)
    if not MOBILE.match(digits):
        raise ValueError("Please enter a 10-digit Indian mobile number.")
    return digits


def mask_phone(phone: str) -> str:
    return "******" + phone[-4:]


# The department names a patient hears and reads, as on the intake page's department grid.
DEPARTMENTS_HI = {
    "general_physician": "सामान्य चिकित्सा", "dermatologist": "त्वचा विभाग", "cardiology": "हृदय विभाग",
    "orthopedics": "हड्डी एवं जोड़", "ent": "कान, नाक और गला", "pediatrics": "बाल चिकित्सा",
}


def department_names(form_id: Optional[str]) -> Optional[dict]:
    english = department(form_id)
    return {"en-IN": english, "hi-IN": DEPARTMENTS_HI.get(form_id, english)} if english else None


def booking_for_intake(db: sqlite3.Connection, intake_id: int) -> Optional[sqlite3.Row]:
    return db.execute("SELECT * FROM opd_bookings WHERE intake_id = ?", (intake_id,)).fetchone()


def department(form_id: Optional[str]) -> Optional[str]:
    form = agent.load_form(form_id) if form_id else None
    return form["title"] if form else None


def _parse(value: str) -> datetime:
    try:
        return datetime.strptime(value, LOCAL_TIME)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Times look like 2026-11-22T09:30.") from None


def manages(db: sqlite3.Connection, user: sqlite3.Row, doctor_id: int) -> bool:
    """The doctor themselves, or a colleague in one of the doctor's organizations."""
    if user["id"] == doctor_id:
        return True
    return db.execute(
        """
        SELECT 1 FROM organization_members mine JOIN organization_members theirs
            ON mine.organization_id = theirs.organization_id
        WHERE mine.user_id = ? AND theirs.user_id = ?
        """,
        (user["id"], doctor_id),
    ).fetchone() is not None


def _managed_doctors(db: sqlite3.Connection, user: sqlite3.Row) -> List[int]:
    """The gate for lists: the signed-in doctor and colleagues in their organizations, nobody else."""
    rows = db.execute(
        """
        SELECT DISTINCT theirs.user_id FROM organization_members mine JOIN organization_members theirs
            ON mine.organization_id = theirs.organization_id WHERE mine.user_id = ?
        """,
        (user["id"],),
    ).fetchall()
    return sorted({user["id"], *(row[0] for row in rows)})


def _managed_slot(db: sqlite3.Connection, user: sqlite3.Row, slot_id: str) -> sqlite3.Row:
    slot = db.execute("SELECT * FROM opd_slots WHERE id = ?", (slot_id,)).fetchone()
    if slot is None or not manages(db, user, slot["doctor_id"]):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There's no such slot.")
    return slot


def _managed_booking(db: sqlite3.Connection, user: sqlite3.Row, booking_id: str) -> sqlite3.Row:
    booking = db.execute("SELECT * FROM opd_bookings WHERE id = ?", (booking_id,)).fetchone()
    if booking is None or not manages(db, user, booking["doctor_id"]):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There's no such booking.")
    return booking


def next_queue_number(db: sqlite3.Connection, doctor_id: int, visit_date: str) -> int:
    row = db.execute(
        "SELECT COALESCE(MAX(queue_number), 0) + 1 FROM opd_bookings WHERE doctor_id = ? AND visit_date = ?",
        (doctor_id, visit_date),
    ).fetchone()
    return row[0]


def send_time(visit_date: str, now: Optional[datetime] = None) -> str:
    """The evening before a later visit; for a visit today, now."""
    now = now or datetime.now()
    visit = date.fromisoformat(visit_date)
    if visit > now.date():
        return f"{(visit - timedelta(days=1)).isoformat()}T{EVENING_BEFORE}"
    return now.strftime(LOCAL_TIME)


class NewSlot(BaseModel):
    form_id: str = Field(max_length=64)
    starts_at: str = Field(max_length=16)
    ends_at: str = Field(max_length=16)


class NewBooking(BaseModel):
    slot_id: str = Field(max_length=64)
    patient_name: str = Field(min_length=1, max_length=120)
    patient_age: Optional[int] = Field(default=None, ge=0, le=130)
    patient_sex: Optional[Literal["female", "male", "other"]] = None
    phone: str = Field(max_length=20)
    patient_id: Optional[str] = Field(default=None, max_length=64)
    channel: Literal["sms", "whatsapp"] = "sms"

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        return normalise_phone(value)


class NewWalkIn(BaseModel):
    patient_name: str = Field(min_length=1, max_length=120)
    patient_age: Optional[int] = Field(default=None, ge=0, le=130)
    patient_sex: Optional[Literal["female", "male", "other"]] = None
    phone: str = Field(max_length=20)
    form_id: Optional[str] = Field(default=None, max_length=64)  # empty: "not sure", staff confirm later
    channel: Literal["sms", "whatsapp"] = "sms"

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        return normalise_phone(value)


class Department(BaseModel):
    form_id: str = Field(max_length=64)


class Resend(BaseModel):
    channel: Literal["sms", "whatsapp"] = "sms"


def _slot_view(slot: sqlite3.Row, booked: int = 0) -> dict:
    return {
        "id": slot["id"], "doctor_id": slot["doctor_id"], "form_id": slot["form_id"], "department": department(slot["form_id"]),
        "starts_at": slot["starts_at"], "ends_at": slot["ends_at"], "booked": booked,
    }


def issue_link(db: sqlite3.Connection, booking: sqlite3.Row, base_url: str, channel: str = "sms") -> dict:
    """A fresh one-interview link for a booking, put in the demo outbox. Any older unused link stops."""
    if booking["intake_id"]:
        db.execute(
            "UPDATE intakes SET status = 'expired', expires_at = datetime('now') WHERE id = ? AND status = 'waiting'",
            (booking["intake_id"],),
        )
    doctor = db.execute("SELECT * FROM users WHERE id = ?", (booking["doctor_id"],)).fetchone()
    made = diagnofast.create_intake(
        diagnofast.NewIntake(
            form_id=booking["form_id"] or WALK_IN_FORM, patient_name=booking["patient_name"], patient_age=booking["patient_age"],
            patient_sex=booking["patient_sex"], patient_id=booking["patient_id"],
        ),
        doctor,
        db,
    )
    db.execute("UPDATE opd_bookings SET intake_id = ? WHERE id = ?", (made["id"], booking["id"]))
    link = f"{base_url.rstrip('/')}/{made['link']}"
    text = MESSAGE.format(link=link)
    send_at = send_time(booking["visit_date"])
    insert(
        db, "opd_outbox", booking_id=booking["id"], doctor_id=booking["doctor_id"], channel=channel,
        phone_masked=mask_phone(booking["phone"]), text=MESSAGE.format(link=LINK_HIDDEN), send_at=send_at, created_at=now_iso(),
    )
    return {
        "channel": channel, "phone": mask_phone(booking["phone"]), "text": text, "link": link, "send_at": send_at,
        "sent": False, "note": "Demo outbox: nothing was sent, because no SMS or WhatsApp provider is connected. The link is shown once.",
    }


@router.post("/slots", status_code=status.HTTP_201_CREATED, dependencies=[Depends(bookings_on)])
def create_slot(request: NewSlot, doctor: sqlite3.Row = Depends(require_doctor), db: sqlite3.Connection = Depends(get_db)) -> dict:
    if doctor["id"] not in _managed_doctors(db, doctor):  # a doctor's slots are their own
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only add your own slots.")
    if agent.load_form(request.form_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown department.")
    starts, ends = _parse(request.starts_at), _parse(request.ends_at)
    if ends <= starts or starts.date() != ends.date():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A slot ends after it starts, on the same day.")
    slot_id = insert(
        db, "opd_slots", doctor_id=doctor["id"], form_id=request.form_id, starts_at=request.starts_at, ends_at=request.ends_at,
        slot_code=secrets.token_urlsafe(9), created_by=doctor["id"], created_at=now_iso(),
    )
    audit.record(db, doctor, "opd.slot.created", resource_type="opd_slot", resource_id=slot_id)
    return _slot_view(db.execute("SELECT * FROM opd_slots WHERE id = ?", (slot_id,)).fetchone())


@router.get("/slots", dependencies=[Depends(bookings_on)])
def list_slots(
    day: Optional[str] = Query(default=None, alias="date", max_length=10),
    doctor: sqlite3.Row = Depends(require_doctor),
    db: sqlite3.Connection = Depends(get_db),
) -> List[dict]:
    day = day or date.today().isoformat()
    ids = _managed_doctors(db, doctor)
    marks = ",".join("?" for _ in ids)
    rows = db.execute(
        f"""
        SELECT s.*, (SELECT COUNT(*) FROM opd_bookings b WHERE b.slot_id = s.id) AS booked FROM opd_slots s
        WHERE s.doctor_id IN ({marks}) AND substr(s.starts_at, 1, 10) = ? ORDER BY s.starts_at
        """,
        (*ids, day),
    ).fetchall()
    return [_slot_view(row, row["booked"]) for row in rows]


@router.post("/bookings", status_code=status.HTTP_201_CREATED, dependencies=[Depends(bookings_on)])
def create_booking(
    request: NewBooking, http: Request, doctor: sqlite3.Row = Depends(require_doctor), db: sqlite3.Connection = Depends(get_db)
) -> dict:
    slot = _managed_slot(db, doctor, request.slot_id)
    if request.patient_id:
        open_patient(db, doctor, request.patient_id, "opd.booking.created", WRITE)
    visit_date = slot["starts_at"][:10]
    booking_id = insert(
        db, "opd_bookings", slot_id=slot["id"], doctor_id=slot["doctor_id"], visit_date=visit_date,
        queue_number=next_queue_number(db, slot["doctor_id"], visit_date), form_id=slot["form_id"], walk_in=0,
        patient_id=request.patient_id, patient_name=request.patient_name.strip(), patient_age=request.patient_age,
        patient_sex=request.patient_sex, phone=request.phone, created_by=doctor["id"], created_at=now_iso(),
    )
    booking = db.execute("SELECT * FROM opd_bookings WHERE id = ?", (booking_id,)).fetchone()
    message = issue_link(db, booking, str(http.base_url), request.channel)
    if not request.patient_id:
        audit.record(db, doctor, "opd.booking.created", resource_type="opd_booking", resource_id=booking_id)
    return {
        "id": booking_id, "queue_number": booking["queue_number"], "visit_date": visit_date,
        "form_id": slot["form_id"], "department": department(slot["form_id"]), "message": message,
    }


@router.post("/bookings/{booking_id}/link", dependencies=[Depends(bookings_on)])
def resend_link(
    booking_id: str, http: Request, request: Optional[Resend] = None,
    doctor: sqlite3.Row = Depends(require_doctor), db: sqlite3.Connection = Depends(get_db),
) -> dict:
    booking = _managed_booking(db, doctor, booking_id)
    if booking["intake_id"]:
        current = db.execute("SELECT status FROM intakes WHERE id = ?", (booking["intake_id"],)).fetchone()
        if current and current["status"] not in ("waiting", "expired"):
            raise HTTPException(status.HTTP_409_CONFLICT, "The interview has already started, so its link can't be replaced.")
    audit.record(db, doctor, "opd.link.resent", resource_type="opd_booking", resource_id=booking_id)
    return issue_link(db, booking, str(http.base_url), (request or Resend()).channel)


def _interview_status(row: sqlite3.Row) -> Optional[str]:
    if row["intake_status"] is None:
        return None
    if row["intake_status"] in ("waiting", "in_progress") and row["intake_expired"]:
        return "expired"
    return row["intake_status"]


@router.get("/bookings", dependencies=[Depends(bookings_on)])
def list_bookings(
    day: Optional[str] = Query(default=None, alias="date", max_length=10),
    doctor: sqlite3.Row = Depends(require_doctor),
    db: sqlite3.Connection = Depends(get_db),
) -> List[dict]:
    day = day or date.today().isoformat()
    ids = _managed_doctors(db, doctor)
    marks = ",".join("?" for _ in ids)
    rows = db.execute(
        f"""
        SELECT b.*, s.starts_at, i.status AS intake_status, i.urgent AS intake_urgent,
            (i.expires_at IS NOT NULL AND i.expires_at <= datetime('now')) AS intake_expired
        FROM opd_bookings b LEFT JOIN opd_slots s ON s.id = b.slot_id LEFT JOIN intakes i ON i.id = b.intake_id
        WHERE b.doctor_id IN ({marks}) AND b.visit_date = ? ORDER BY b.doctor_id, b.queue_number
        """,
        (*ids, day),
    ).fetchall()
    return [
        {
            "id": row["id"], "queue_number": row["queue_number"], "visit_date": row["visit_date"], "slot_starts_at": row["starts_at"],
            "doctor_id": row["doctor_id"], "patient_name": row["patient_name"], "patient_id": row["patient_id"],
            "phone": mask_phone(row["phone"]), "form_id": row["form_id"], "department": department(row["form_id"]),
            "walk_in": bool(row["walk_in"]), "department_confirmed": bool(row["form_id"]),
            "intake_id": row["intake_id"], "interview_status": _interview_status(row),
            "urgent": bool(row["intake_urgent"] and row["intake_urgent"] != "[]"),
        }
        for row in rows
    ]


@router.get("/outbox", dependencies=[Depends(bookings_on)])
def outbox(doctor: sqlite3.Row = Depends(require_doctor), db: sqlite3.Connection = Depends(get_db)) -> List[dict]:
    ids = _managed_doctors(db, doctor)
    marks = ",".join("?" for _ in ids)
    rows = db.execute(
        f"SELECT * FROM opd_outbox WHERE doctor_id IN ({marks}) ORDER BY created_at DESC, rowid DESC LIMIT 100",
        ids,
    ).fetchall()
    return [
        {"id": row["id"], "booking_id": row["booking_id"], "channel": row["channel"], "phone": row["phone_masked"],
         "text": row["text"], "send_at": row["send_at"], "created_at": row["created_at"], "sent": False}
        for row in rows
    ]


@router.post("/walk-ins", status_code=status.HTTP_201_CREATED, dependencies=[Depends(bookings_on)])
def create_walk_in(
    request: NewWalkIn, http: Request, doctor: sqlite3.Row = Depends(require_doctor), db: sqlite3.Connection = Depends(get_db)
) -> dict:
    """A patient with no booking, seen by the signed-in doctor today. With no department, staff confirm one later."""
    if doctor["id"] not in _managed_doctors(db, doctor):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only add walk-ins to your own queue.")
    if request.form_id is not None and agent.load_form(request.form_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown department.")
    visit_date = date.today().isoformat()
    booking_id = insert(
        db, "opd_bookings", slot_id=None, doctor_id=doctor["id"], visit_date=visit_date,
        queue_number=next_queue_number(db, doctor["id"], visit_date), form_id=request.form_id,
        department_confirmed_by=doctor["id"] if request.form_id else None, walk_in=1,
        patient_name=request.patient_name.strip(), patient_age=request.patient_age, patient_sex=request.patient_sex,
        phone=request.phone, created_by=doctor["id"], created_at=now_iso(),
    )
    booking = db.execute("SELECT * FROM opd_bookings WHERE id = ?", (booking_id,)).fetchone()
    message = issue_link(db, booking, str(http.base_url), request.channel)
    audit.record(db, doctor, "opd.walk_in.created", resource_type="opd_booking", resource_id=booking_id)
    return {
        "id": booking_id, "queue_number": booking["queue_number"], "visit_date": visit_date,
        "form_id": request.form_id, "department": department(request.form_id), "message": message,
    }


@router.get("/bookings/{booking_id}/suggestion", dependencies=[Depends(bookings_on)])
def department_suggestion(booking_id: str, doctor: sqlite3.Row = Depends(require_doctor), db: sqlite3.Connection = Depends(get_db)) -> dict:
    """A department suggestion for STAFF, from the question graph. Never shown to the patient: routing a
    patient by AI is close to triage, where CDSCO rules may apply. A person confirms or chooses otherwise."""
    import json

    from backend.diagnofast import guidance
    from backend.integrations import graph

    if not addons.enabled("diagnofast.walkin_suggestion", db):
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "addon_off", "message": "Walk-in suggestions are switched off."})
    booking = _managed_booking(db, doctor, booking_id)
    note = "A suggestion for staff only. Confirm a department before telling the patient."
    empty = {"form_id": None, "department": None, "because": [], "source": None}
    intake = db.execute("SELECT transcript FROM intakes WHERE id = ?", (booking["intake_id"],)).fetchone() if booking["intake_id"] else None
    complaints = guidance.match_complaints([turn["answer"] for turn in json.loads(intake["transcript"])]) if intake else []
    if not complaints:
        return {**empty, "note": "Nothing to suggest yet: the interview hasn't named a complaint the graph knows."}
    client = graph.client(db)
    if client is None:
        return {**empty, "note": "Suggestions are unavailable: Neo4j isn't connected. Please choose a department."}
    try:
        db.commit()  # no lock held while Neo4j answers
        guidance.ensure_questions(client)
        votes = client.department_votes(complaints)
    except graph.GraphUnavailable:
        return {**empty, "note": "Suggestions are unavailable: Neo4j didn't answer. Please choose a department."}
    if not votes:
        return {**empty, "note": "Nothing to suggest for these complaints. Please choose a department."}
    best = max(votes.items(), key=lambda item: (item[1], item[0] == WALK_IN_FORM))[0]
    return {"form_id": best, "department": department(best), "because": complaints, "source": "neo4j", "note": note}


@router.post("/bookings/{booking_id}/department", dependencies=[Depends(bookings_on)])
def confirm_department(
    booking_id: str, request: Department, doctor: sqlite3.Row = Depends(require_doctor), db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """A person confirms the department. Only then does the patient's status page show one."""
    booking = _managed_booking(db, doctor, booking_id)
    if agent.load_form(request.form_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown department.")
    if not booking["walk_in"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "A booked patient's department comes from their slot.")
    db.execute(
        "UPDATE opd_bookings SET form_id = ?, department_confirmed_by = ? WHERE id = ?",
        (request.form_id, doctor["id"], booking_id),
    )
    audit.record(db, doctor, "opd.department.confirmed", resource_type="opd_booking", resource_id=booking_id)
    return {"form_id": request.form_id, "department": department(request.form_id)}
