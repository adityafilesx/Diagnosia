"""The API for the Prescription Analyzer. Photos are never stored.

Sign-in is required because every request costs money in AI fees.
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field

from backend import llm, ratelimit
from backend.auth import require_user
from backend.careflow import events
from backend.db import connect, get_db
from backend.images import MAX_IMAGE_BYTES, read_image
from backend.patient_pack import sync as pack
from backend.prescription import analyzer
from backend.records import care
from backend.records import consent as consent_words
from backend.records.access import WRITE, open_patient
from backend.records.store import dumps, insert, now_iso
from backend.speech import MAX_SPEECH_CHARS, Language, speak
from backend.version import APP_VERSION

MAX_PHOTOS = 4
MODULE = "Prescription Analyzer"
# A reading can be confirmed for this long. After that the photo is read again.
READING_HOURS = 24

router = APIRouter(prefix="/api/prescription")


class ExplainRequest(BaseModel):
    # Which reading, and which of its medicines the patient ticked. The medicines themselves come
    # from the server's copy of the reading, never from the browser.
    reading_id: str = Field(min_length=1, max_length=64)
    confirmed: List[int] = Field(max_length=60)
    language: Language
    doctor_notes: str = Field(default="", max_length=2000)


class SaveRequest(BaseModel):
    reading_id: str = Field(min_length=1, max_length=64)
    confirmed: List[int] = Field(min_length=1, max_length=60)


class CalendarRequest(BaseModel):
    reading_id: str = Field(min_length=1, max_length=64)
    confirmed: List[int] = Field(max_length=60)
    language: Language
    guidance: Optional[dict] = None
    start_date: Optional[str] = None
    times: Optional[dict] = None
    plan: Optional[Dict[str, dict]] = None


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_SPEECH_CHARS)
    language: Language


def _workflow(user):
    return lambda db: events.for_person(db, user, MODULE)


def _oldest_usable() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=READING_HOURS)).isoformat()


def forget_old_readings(db: sqlite3.Connection) -> None:
    """Run by the sweep: a reading is only needed between reading a photo and confirming it."""
    db.execute("DELETE FROM prescription_readings WHERE created_at < ?", (_oldest_usable(),))


def _keep_reading(user, reading: dict) -> str:
    """Stores what was read, in its own short transaction, and returns its id. Never the photo."""
    db = connect()
    try:
        reading_id = insert(
            db,
            "prescription_readings",
            user_id=user["id"],
            medicines=dumps(reading["medicines"]),
            model=llm.last_model() or "unknown",
            created_at=now_iso(),
        )
        db.commit()
        return reading_id
    finally:
        db.close()


def _confirmed(db: sqlite3.Connection, user, reading_id: str, ticked: List[int]):
    """The stored reading and the medicines the patient may have ticked in it.

    Refuses a tick on a medicine the server didn't offer one for: the page never shows that tick,
    so such a request didn't come from the page."""
    row = db.execute("SELECT * FROM prescription_readings WHERE id = ? AND user_id = ?", (reading_id, user["id"])).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "We couldn't find that reading. Please read your prescription again.")
    if row["created_at"] < _oldest_usable():
        raise HTTPException(status.HTTP_409_CONFLICT, "This reading is too old. Please read your prescription again.")
    medicines = json.loads(row["medicines"])
    if len(set(ticked)) != len(ticked) or any(index < 0 or index >= len(medicines) for index in ticked):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Please tick medicines from the list we read.")
    if any(not medicines[index].get("confirmable") for index in ticked):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Only medicines we could read can be confirmed.")
    return row, medicines


def _record_confirmation(db: sqlite3.Connection, user, row, medicines: List[dict], ticked: List[int], action: str, language: str = "", explain_model: str = "") -> None:
    """What the patient confirmed, and which code and models were involved. Only the ticked medicines'
    own fields are kept: no photo, no doctor's notes, nothing the AI wrote in reply."""
    confirmed = [{"index": index, **{key: medicines[index][key] for key in analyzer.FIELDS}} for index in sorted(ticked)]
    insert(
        db,
        "prescription_confirmations",
        user_id=user["id"],
        reading_id=row["id"],
        action=action,
        confirmed=dumps(confirmed),
        offered=sum(bool(medicine.get("confirmable")) for medicine in medicines),
        read_count=len(medicines),
        language=language,
        app_version=APP_VERSION,
        read_model=row["model"],
        explain_model=explain_model,
        created_at=now_iso(),
    )


@router.post("/read", dependencies=[Depends(ratelimit.per_user_ai(ratelimit.PRESCRIPTION_READS))])
def read(
    images: List[UploadFile] = File(...),
    consent: bool = Form(...),
    consent_version: Optional[str] = Form(default=None, max_length=32),
    user=Depends(require_user),
) -> dict:
    if not consent:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Please agree to sending your photo to our AI services first.",
        )
    if consent_version != consent_words.VERSION:
        raise HTTPException(status.HTTP_409_CONFLICT, "Please reload the page and read the consent again.")
    # Stored before the photo leaves, in its own short transaction, so the record exists even if reading fails.
    db = connect()
    try:
        consent_words.record(db, consent_words.PRESCRIPTION, "en-IN", True, user_id=user["id"])
        db.commit()
    finally:
        db.close()
    if len(images) > MAX_PHOTOS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Please upload at most {MAX_PHOTOS} photos."
        )
    photos = [read_image(image.file.read(MAX_IMAGE_BYTES + 1)) for image in images]
    locate = _workflow(user)
    llm.forget_last_model()
    with events.tracked(MODULE, "prescription.processing.started", "prescription.processing.failed", locate, user):
        reading = analyzer.read_prescription(photos)
    count = len(reading["medicines"])
    if reading["is_prescription"] and count:
        events.emit_separately(MODULE, "prescription.extraction.completed", locate, user=user, metadata={"item_count": count}, used_ai=True)
        events.emit_separately(MODULE, "prescription.confirmation_required", locate, "review_required", user, metadata={"item_count": count, "review_required": True})
        reading["reading_id"] = _keep_reading(user, reading)
    return reading


@router.post("/explain", dependencies=[Depends(ratelimit.per_user_ai(ratelimit.PRESCRIPTION_EXPLAINS))])
def explain(request: ExplainRequest, user=Depends(require_user)) -> dict:
    locate = _workflow(user)
    # A short read, closed before the AI call, so no database lock is held while it answers.
    db = connect()
    try:
        row, medicines = _confirmed(db, user, request.reading_id, request.confirmed)
    finally:
        db.close()
    confirmed = analyzer.confirmed_from(medicines, request.confirmed)
    try:
        result = analyzer.explain_prescription(confirmed, request.language, request.doctor_notes)
    except (llm.AIUnavailable, llm.AIDeclined) as error:
        events.emit_separately(MODULE, "prescription.processing.failed", locate, "failed", user, metadata={"error_category": events.category_of(error)})
        raise
    db = connect()
    try:
        _record_confirmation(db, user, row, medicines, request.confirmed, "explain", request.language, result.pop("explained_by", ""))
        db.commit()
    finally:
        db.close()
    events.emit_separately(MODULE, "prescription.explained", locate, user=user, metadata={"language": request.language}, used_ai=bool(result["guidance"]))
    return result


@router.post("/save", status_code=status.HTTP_201_CREATED)
def save_to_record(request: SaveRequest, user=Depends(require_user), db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Keeps only what the patient ticked, as a patient's own entry. Nothing here is checked by a clinician."""
    record = db.execute("SELECT id FROM patients WHERE user_id = ?", (user["id"],)).fetchone()
    if record is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Link your patient record first, then you can save this to it.")
    open_patient(db, user, record["id"], "prescription.saved", WRITE)
    row, medicines = _confirmed(db, user, request.reading_id, request.confirmed)
    ticked = set(request.confirmed)
    kept = [medicine for index, medicine in enumerate(analyzer.confirmed_from(medicines, request.confirmed)) if index in ticked]
    saved_id = insert(
        db,
        "saved_prescriptions",
        patient_id=record["id"],
        medicines=dumps([medicine.model_dump() for medicine in kept]),
        saved_by=user["id"],
        created_at=now_iso(),
    )
    _record_confirmation(db, user, row, medicines, request.confirmed, "save")
    pack.enqueue(db, record["id"], "prescription", saved_id)
    care.add_timeline(db, record["id"], "prescription", "Prescription saved by the patient", f"{len(kept)} medicines", "saved_prescription", saved_id)
    return {"saved": True, "medicines": len(kept)}


@router.post("/calendar")
def calendar(request: CalendarRequest, user=Depends(require_user), db: sqlite3.Connection = Depends(get_db)) -> dict:
    _row, medicines = _confirmed(db, user, request.reading_id, request.confirmed)
    return analyzer.build_calendar_reminders(
        analyzer.confirmed_from(medicines, request.confirmed),
        request.language,
        request.guidance,
        request.start_date,
        request.times,
        request.plan,
    )


@router.post("/speak", dependencies=[Depends(ratelimit.per_user(ratelimit.SPEECH_PER_USER))])
def read_aloud(request: SpeakRequest) -> Response:
    return Response(speak(request.text, request.language), media_type="audio/wav")

