"""The API for DiagnoFast.

Reception creates a link for one interview for each patient. The patient needs no
account, and the link stops working when the interview ends or when it expires:
a link nobody opens lasts DIAGNOSIA_DIAGNOFAST_LINK_HOURS, and a started interview
has DIAGNOSIA_DIAGNOFAST_INTERVIEW_HOURS to finish. Everything the
patient says is visible to the doctor who created the link and, once the link
belongs to a patient record, to that patient's care team.
"""
import base64
import hashlib
import json
import logging
import secrets
import sqlite3
from dataclasses import asdict
from typing import List, Literal, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from backend import llm, ratelimit, settings_store, speech
from backend.auth import require_doctor
from backend.careflow import events
from backend.config import settings
from backend.db import connect, get_db, release
from backend.diagnofast import abha, agent, graph_sync, recordings, validate
from backend.patient_pack import sync as pack
from backend.records import audit, care, consent
from backend.records.access import READ, WRITE, lookup, open_patient

MAX_AUDIO_BYTES = 5 * 1024 * 1024
MAX_TYPED_ANSWER = 2000
MAX_ANSWER_KEY = 64
OPEN_STATUSES = ("waiting", "in_progress")

MODULE = "DiagnoFast"
# Notification kinds the workspace shows as an alert banner, not only in the inbox.
ALERT_URGENT = "diagnofast_urgent"
ALERT_HELP = "diagnofast_help"

logger = logging.getLogger("diagnosia.diagnofast")
router = APIRouter(prefix="/api/diagnofast")


class NewIntake(BaseModel):
    form_id: str
    patient_name: str = Field(min_length=1, max_length=120)
    patient_age: Optional[int] = Field(default=None, ge=0, le=130)
    patient_sex: Optional[Literal["female", "male", "other"]] = None
    abha_id: Optional[str] = Field(default=None, max_length=32)
    patient_id: Optional[str] = Field(default=None, max_length=64)  # when the patient has a record here


class StartRequest(BaseModel):
    language: speech.Language
    consent: bool
    # The version of the words the patient agreed to, from GET /patient/{token}.
    consent_version: Optional[str] = Field(default=None, max_length=32)
    abha_consent: bool = False


class ConsentAudio(BaseModel):
    language: speech.Language
    kind: Literal["interview", "abha"] = "interview"


class KioskConsentAudio(BaseModel):
    model_config = {"extra": "forbid"}
    language: speech.Language


def _consent_audio(kind: str, language: speech.Language) -> dict:
    """The consent words read aloud, for patients who can't read them easily. The page reads them in
    the browser's voice when this returns no audio."""
    return {"audio": _spoken(" ".join(consent.WORDS[kind][language]), language)}


class KioskIntake(BaseModel):
    # Public visits cannot claim an existing chart or choose their own reviewing doctor.
    model_config = {"extra": "forbid"}
    form_id: str
    patient_name: str = Field(min_length=1, max_length=120)
    patient_age: Optional[int] = Field(default=None, ge=0, le=130)
    patient_sex: Optional[Literal["female", "male", "other"]] = None
    consent: bool


def _kiosk_doctor(db: sqlite3.Connection) -> sqlite3.Row:
    doctor = None
    if settings.diagnofast_kiosk_doctor_id:
        doctor = db.execute(
            "SELECT * FROM users WHERE id = ? AND role = 'doctor' AND account_status = 'verified'",
            (settings.diagnofast_kiosk_doctor_id,),
        ).fetchone()
    if doctor is None and settings.demo_mode:
        doctor = db.execute(
            "SELECT * FROM users WHERE role = 'doctor' AND account_status = 'verified' ORDER BY id ASC LIMIT 1"
        ).fetchone()
    if doctor is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The kiosk is not available. Please ask reception for a patient link.")
    return doctor


def _workflow(db: sqlite3.Connection, row: sqlite3.Row) -> sqlite3.Row:
    """A link for a patient joins that patient's workflow. A loose link is its own."""
    return events.for_patient(db, row["patient_id"]) if row["patient_id"] else events.for_intake(db, row["id"], row["doctor_id"])


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _spoken(text: str, language: speech.Language) -> Optional[str]:
    """The text as audio: Sarvam when it is on, then Edge, then Groq for English. Without any, the
    page reads the words in the browser's voice."""
    audio = speech.question_audio(text, language)
    if audio is None:
        return None
    data, media_type = audio
    return f"data:{media_type};base64," + base64.b64encode(data).decode()


def _intake_by_token(token: str, db: sqlite3.Connection) -> Optional[sqlite3.Row]:
    return db.execute(
        """
        SELECT *, (expires_at IS NOT NULL AND expires_at <= datetime('now')) AS expired
        FROM intakes WHERE token_hash = ?
        """,
        (_hash(token),),
    ).fetchone()


def _open_intake(token: str, db: sqlite3.Connection) -> sqlite3.Row:
    row = _intake_by_token(token, db)
    if row is None or row["status"] not in OPEN_STATUSES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This link isn't active. Please ask reception.")
    if row["expired"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This link has expired. Please ask reception for a new one.")
    return row


STALE_REPORT_MINUTES = 5


def fail_stale_reports(db: sqlite3.Connection) -> int:
    """A report job runs in the process that took the last answer. If that process stopped, the job is
    gone, so after a few minutes the intake is marked failed: the doctor sees the answers and can retry."""
    return db.execute(
        """
        UPDATE intakes SET status = 'report_failed'
        WHERE status = 'preparing_report'
          AND (report_requested_at IS NULL OR report_requested_at <= datetime('now', ?))
        """,
        (f"-{STALE_REPORT_MINUTES} minutes",),
    ).rowcount


def expire_stale(db: sqlite3.Connection) -> int:
    """Closes links past their time, so the queue shows them as expired. Run by the app's sweep."""
    return db.execute(
        """
        UPDATE intakes SET status = 'expired'
        WHERE status IN ('waiting', 'in_progress')
          AND expires_at IS NOT NULL AND expires_at <= datetime('now')
        """
    ).rowcount


def _alert_staff(db: sqlite3.Connection, row: sqlite3.Row, kind: str, title: str, body: str = "") -> None:
    """Tells the doctor who owns the interview, and the patient's clinicians if it belongs to a chart.

    Written in the same transaction as what caused it, so an alert exists exactly when the stop does.
    One unread alert of a kind per person per interview: a button pressed twice is one alert.
    """
    link = f"diagnofast/{row['id']}"
    people = {row["doctor_id"]}
    if row["patient_id"]:
        people.update(care.care_team_clinicians(db, row["patient_id"]))
    for user_id in people:
        waiting = db.execute(
            "SELECT 1 FROM notifications WHERE recipient_user_id = ? AND module = ? AND link = ? AND read_at IS NULL",
            (user_id, kind, link),
        ).fetchone()
        if not waiting:
            care.notify(db, user_id, title, body, row["patient_id"], kind, link)


@router.get("/alerts")
def alerts(doctor: sqlite3.Row = Depends(require_doctor), db: sqlite3.Connection = Depends(get_db)) -> List[dict]:
    """Unseen urgent stops and requests for help, for the banner every staff screen polls. Read only."""
    found = db.execute(
        """
        SELECT notifications.id, notifications.module, notifications.title, notifications.body, notifications.created_at,
            intakes.id AS intake_id, intakes.doctor_id, intakes.patient_id AS chart_id
        FROM notifications JOIN intakes ON notifications.link = 'diagnofast/' || intakes.id
        WHERE notifications.recipient_user_id = ? AND notifications.module IN (?, ?) AND notifications.read_at IS NULL
        ORDER BY notifications.created_at
        """,
        (doctor["id"], ALERT_URGENT, ALERT_HELP),
    ).fetchall()
    shown = []
    for row in found:
        # An alert names a patient, so it is shown only while this person may still open that interview:
        # the chart's care team, or for an interview with no chart, the doctor who sent the link. This
        # looks the access up without writing to the audit log, because the screen asks every few seconds.
        if row["chart_id"]:
            allowed = lookup(db, doctor, row["chart_id"]) is not None
        else:
            allowed = row["doctor_id"] == doctor["id"]
        if allowed:
            shown.append(
                {
                    "id": row["id"],
                    "kind": "urgent" if row["module"] == ALERT_URGENT else "help",
                    "title": row["title"],
                    "body": row["body"],
                    "intake_id": row["intake_id"],
                    "created_at": row["created_at"],
                }
            )
    return shown


def _readable_intake(intake_id: int, doctor: sqlite3.Row, db: sqlite3.Connection, action: str, level=READ) -> sqlite3.Row:
    """The doctor who sent the link, or the care team of the patient it belongs to."""
    row = db.execute("SELECT * FROM intakes WHERE id = ?", (intake_id,)).fetchone()
    if row is None or (row["doctor_id"] != doctor["id"] and row["patient_id"] is None):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found.")
    if row["patient_id"]:
        open_patient(db, doctor, row["patient_id"], action, level)
    return row


@router.get("/forms")
def forms(_doctor=Depends(require_doctor)) -> List[dict]:
    return agent.list_forms()


@router.get("/kiosk")
def kiosk_config(db: sqlite3.Connection = Depends(get_db)) -> dict:
    _kiosk_doctor(db)
    return {"forms": agent.list_forms(), "consent": consent.words(consent.INTERVIEW)}


@router.post(
    "/kiosk/consent-audio",
    dependencies=[Depends(ratelimit.per_client(ratelimit.CONSENT_AUDIO)), Depends(ratelimit.overall(ratelimit.KIOSK_OVERALL))],
)
def kiosk_consent_audio(request: KioskConsentAudio, db: sqlite3.Connection = Depends(get_db)) -> dict:
    _kiosk_doctor(db)
    release(db)  # no lock held while a voice is made
    return _consent_audio(consent.INTERVIEW, request.language)


@router.post(
    "/kiosk/intakes",
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(ratelimit.per_client(ratelimit.KIOSK_PER_DEVICE)),
        Depends(ratelimit.overall(ratelimit.KIOSK_OVERALL)),
    ],
)
def kiosk_intake(details: KioskIntake, db: sqlite3.Connection = Depends(get_db)) -> dict:
    doctor = _kiosk_doctor(db)
    if not details.consent:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Consent is needed to continue.")
    return create_intake(NewIntake(**details.model_dump(exclude={"consent"})), doctor, db)


@router.post("/intakes", status_code=status.HTTP_201_CREATED)
def create_intake(
    details: NewIntake,
    doctor: sqlite3.Row = Depends(require_doctor),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    if not details.patient_name.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Please enter a patient name.")
    if agent.load_form(details.form_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown form.")
    if details.patient_id:
        open_patient(db, doctor, details.patient_id, "diagnofast.link.created", WRITE)
    token = secrets.token_urlsafe(24)
    cursor = db.execute(
        """
        INSERT INTO intakes
            (token_hash, doctor_id, form_id, patient_name, patient_age, patient_sex, abha_id, patient_id, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', ?))
        """,
        (
            _hash(token),
            doctor["id"],
            details.form_id,
            details.patient_name.strip(),
            details.patient_age,
            details.patient_sex,
            details.abha_id,
            details.patient_id,
            f"+{settings.diagnofast_link_hours} hours",
        ),
    )
    if not details.patient_id:  # with a patient, the audit entry above has already recorded this
        events.emit(db, MODULE, "intake.link_created", events.for_intake(db, cursor.lastrowid, doctor["id"]), user=doctor)
    return {"id": cursor.lastrowid, "link": f"intake.html?token={token}"}


@router.get("/intakes")
def queue(
    patient_id: Optional[str] = Query(default=None, max_length=64),
    doctor: sqlite3.Row = Depends(require_doctor),
    db: sqlite3.Connection = Depends(get_db),
) -> List[dict]:
    """The doctor's own queue, or everything for one patient the doctor cares for."""
    if patient_id:
        open_patient(db, doctor, patient_id, "diagnofast.intakes.listed", READ)
        where, value = "patient_id = ?", patient_id
    else:
        where, value = "doctor_id = ?", doctor["id"]
    rows = db.execute(
        f"""
        SELECT id, patient_name, patient_id, status, urgent, created_at, help_requested_at, reviewed_at FROM intakes
        WHERE {where} ORDER BY urgent = '[]', id DESC
        """,
        (value,),
    ).fetchall()
    return [
        {
            **{key: row[key] for key in ("id", "patient_name", "patient_id", "status", "created_at")},
            "urgent": json.loads(row["urgent"]),
            # Only while the interview is open: afterwards the patient is with reception or the doctor.
            "needs_help": bool(row["help_requested_at"]) and row["status"] in OPEN_STATUSES,
            "reviewed": bool(row["reviewed_at"]),
        }
        for row in rows
    ]


def _report_view(stored: Optional[str], db: sqlite3.Connection) -> Optional[dict]:
    if not stored:
        return None
    report = json.loads(stored)
    if not settings_store.get("features.diagnofast_investigations", db):
        report.pop("suggested_investigations", None)  # older reports may hold some; they stay out of sight
    return report


@router.get("/intakes/{intake_id}")
def intake_detail(
    intake_id: int,
    doctor: sqlite3.Row = Depends(require_doctor),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    row = _readable_intake(intake_id, doctor, db, "diagnofast.report.viewed")
    form = agent.load_form(row["form_id"])
    answers = json.loads(row["answers"])
    transcript = json.loads(row["transcript"])
    report = _report_view(row["report"], db)
    reviewer = db.execute("SELECT first_name, last_name FROM users WHERE id = ?", (row["reviewed_by"],)).fetchone() if row["reviewed_by"] else None
    return {
        # Until a doctor stamps it, the report is an AI draft, and the screen says so.
        "reviewed": {"by": f"{reviewer['first_name']} {reviewer['last_name']}" if reviewer else "", "at": row["reviewed_at"]} if row["reviewed_at"] else None,
        # Checked fresh on every view, so a report written before a check existed is checked too.
        "report_problems": validate.check_report(report, [{"answer": turn["answer"]} for turn in transcript]) if report else [],
        "id": row["id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "patient": {
            "name": row["patient_name"],
            "age": row["patient_age"],
            "sex": row["patient_sex"],
            "abha_id": row["abha_id"],
            "record_id": row["patient_id"],
        },
        "language": row["language"],
        "form_title": form["title"],
        "answers": [
            {"label": item["label"], "value": answers.get(item["key"], "")}
            for item in form["fields"]
        ],
        "urgent": json.loads(row["urgent"]),
        "records": json.loads(row["records"]) if row["records"] else None,
        "report": report,
        "transcript": [
            {
                "question": turn["question"], "answer": turn["answer"], "has_audio": bool(turn.get("audio")),
                # Only when there is one, so with Sarvam off the answer is exactly as before.
                **({"english": turn["english"], "english_label": "machine translation"} if turn.get("english") else {}),
            }
            for turn in transcript
        ],
        "feedback": _feedback_view(db, row),
    }


@router.get("/intakes/{intake_id}/audio/{turn}")
def intake_audio(
    intake_id: int,
    turn: int,
    doctor: sqlite3.Row = Depends(require_doctor),
    db: sqlite3.Connection = Depends(get_db),
) -> Response:
    row = _readable_intake(intake_id, doctor, db, "diagnofast.recording.played")
    transcript = json.loads(row["transcript"])
    if not 0 <= turn < len(transcript) or not transcript[turn].get("audio"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No recording for this answer.")
    data, content_type = recordings.load(intake_id, transcript[turn]["audio"])
    return Response(data, media_type=content_type)


@router.post("/intakes/{intake_id}/review")
def review_report(
    intake_id: int,
    doctor: sqlite3.Row = Depends(require_doctor),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """The doctor's stamp. It records that a person read the report and the patient's answers; it changes nothing in them."""
    row = _readable_intake(intake_id, doctor, db, "diagnofast.report.reviewed", WRITE)
    stamped = db.execute(
        """
        UPDATE intakes SET reviewed_by = ?, reviewed_at = datetime('now')
        WHERE id = ? AND status IN ('done', 'report_failed') AND reviewed_at IS NULL
        """,
        (doctor["id"], row["id"]),
    ).rowcount
    if not stamped:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a finished interview that hasn't been reviewed can be stamped.")
    if row["status"] == "done":
        graph_sync.enqueue(db, "intake", row["id"])  # the copy shows it reviewed
    if not row["patient_id"]:  # with a chart, the gate above has already written this to the audit log
        audit.record(db, doctor, "diagnofast.report.reviewed", None, "intake", str(row["id"]))
    return {"reviewed": True}


FEEDBACK_QUESTION = "Anything you wish had been asked?"


class Feedback(BaseModel):
    wished_asked: str = Field(min_length=1, max_length=1000)
    good_question: Optional[str] = Field(default=None, max_length=300)


def _feedback_view(db: sqlite3.Connection, row: sqlite3.Row) -> Optional[dict]:
    from backend import addons

    if not addons.enabled("diagnofast.review_feedback", db):
        return None
    answers = db.execute(
        "SELECT wished_asked, good_question, created_at FROM diagnofast_feedback WHERE intake_id = ? ORDER BY id", (row["id"],)
    ).fetchall()
    return {"question": FEEDBACK_QUESTION, "answers": [dict(answer) for answer in answers]}


@router.post("/intakes/{intake_id}/feedback", status_code=status.HTTP_201_CREATED)
def review_feedback(
    intake_id: int, request: Feedback, doctor: sqlite3.Row = Depends(require_doctor), db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """The reviewing doctor's answer to "Anything you wish had been asked?". It changes nothing in the report."""
    from backend import addons

    if not addons.enabled("diagnofast.review_feedback", db):
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "addon_off", "message": "Review feedback is switched off."})
    row = _readable_intake(intake_id, doctor, db, "diagnofast.report.viewed", WRITE)
    if row["status"] not in ("done", "report_failed"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Feedback comes after the interview is finished.")
    wished = request.wished_asked.strip()
    if not wished:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Please write what you wish had been asked.")
    good = (request.good_question or "").strip() or None
    db.execute(
        "INSERT INTO diagnofast_feedback (intake_id, doctor_id, wished_asked, good_question, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
        (row["id"], doctor["id"], wished, good),
    )
    if not row["patient_id"]:
        audit.record(db, doctor, "diagnofast.report.feedback", None, "intake", str(row["id"]))
    return {"saved": True}


@router.get("/intakes/{intake_id}/graph")
def intake_graphs(intake_id: int, doctor: sqlite3.Row = Depends(require_doctor), db: sqlite3.Connection = Depends(get_db)) -> dict:
    """The evidence and history graphs. Neo4j says which items link; every word comes from SQLite."""
    row = _readable_intake(intake_id, doctor, db, "diagnofast.report.viewed")
    release(db)  # no lock held while Neo4j answers
    return graph_sync.views(db, row)


@router.post("/intakes/{intake_id}/report/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_report(
    intake_id: int,
    background: BackgroundTasks,
    doctor: sqlite3.Row = Depends(require_doctor),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Writes the summary again after a failure. The answers themselves are already saved."""
    row = _readable_intake(intake_id, doctor, db, "diagnofast.report.retried", WRITE)
    started = db.execute(
        """
        UPDATE intakes SET status = 'preparing_report', report_requested_at = datetime('now')
        WHERE id = ? AND status = 'report_failed'
        """,
        (row["id"],),
    ).rowcount
    if not started:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a report that failed can be retried.")
    db.commit()  # the job reads this row on its own connection
    background.add_task(_build_report, row["id"])
    return {"status": "preparing_report"}


@router.get("/patient/{token}")
def patient_page(token: str, db: sqlite3.Connection = Depends(get_db)) -> dict:
    row = _open_intake(token, db)
    page = {
        "patient_name": row["patient_name"],
        "has_abha_id": bool(row["abha_id"]),
        "status": row["status"],
        "language": row["language"],
        "consent": consent.words(consent.INTERVIEW),
    }
    if row["abha_id"]:
        page["abha_consent"] = consent.words(consent.ABHA)
    if row["status"] == "in_progress":
        # A patient who reloads the page, or whose phone slept, carries on at the same question.
        page["question"] = row["current_question"]
        page["questions_asked"] = row["questions_asked"]
        page["audio"] = _spoken(row["current_question"], row["language"])
    return page


FINISHED_STATUSES = ("preparing_report", "done", "report_failed")
STATUS_TEXT = {
    "en-IN": "Your queue number is {number}. Please go to {department}.",
    "hi-IN": "आपका नंबर {number} है। कृपया {department} विभाग में जाइए।",
}
WAIT_FOR_DEPARTMENT = {
    "en-IN": "Your queue number is {number}. Reception will tell you which department to go to.",
    "hi-IN": "आपका नंबर {number} है। रिसेप्शन आपको बताएगा कि किस विभाग में जाना है।",
}


def _guidance(
    db: sqlite3.Connection, row: sqlite3.Row, form: dict, answers: dict, conversation: list, language: speech.Language, graph_state: dict
) -> Optional[dict]:
    """Advice for the next question (guidance.py), or None with both switches off: then the request to
    the AI is exactly what it always was. It only runs after red_flags.screen found nothing urgent."""
    from backend import addons
    from backend.diagnofast import guidance

    graph_on = addons.enabled("diagnofast.graph_followups", db)
    doctor_like = addons.enabled("diagnofast.doctor_like_interview", db)
    if not graph_on and not doctor_like:
        return None
    advice: dict = {}
    if doctor_like:
        advice.update(
            doctor_like=True,
            known_context=guidance.known_context(db, row),
            vague_answer=guidance.vague_probe(conversation[-1]["answer"]) if conversation else None,
            examples=guidance.examples(db),
        )
    if graph_on:
        graph_state["complaints"] = guidance.match_complaints([turn["answer"] for turn in conversation])
        # Room is kept for the form's required questions, so the graph never crowds them out.
        room = agent.MAX_QUESTIONS - row["questions_asked"] - len(agent.missing_required(form, answers))
        if graph_state["complaints"] and room > 0:
            release(db)  # no lock held while Neo4j answers
            suggestion = guidance.graph_suggestion(db, graph_state["complaints"], graph_state.get("asked", []), language)
            if suggestion:
                graph_state.setdefault("asked", []).append(suggestion["id"])
                advice["graph_suggestion"] = suggestion
    return advice or None


def _has_status_page(db: sqlite3.Connection, row: sqlite3.Row) -> bool:
    from backend import addons
    from backend.opd import routes as opd

    return addons.enabled("diagnofast.bookings", db) and opd.booking_for_intake(db, row["id"]) is not None


def _finished_intake(token: str, db: sqlite3.Connection) -> tuple:
    """The gate for the status page: a finished, booked interview, on the day it finished, with bookings on.
    It is read-only: nothing here can answer a question or change the visit."""
    from backend.opd import routes as opd

    row = db.execute(
        """
        SELECT * FROM intakes WHERE token_hash = ? AND status IN (?, ?, ?)
            AND date(COALESCE(report_requested_at, created_at), 'localtime') = date('now', 'localtime')
        """,
        (_hash(token), *FINISHED_STATUSES),
    ).fetchone()
    booking = opd.booking_for_intake(db, row["id"]) if row is not None else None
    if booking is None or not _has_status_page(db, row):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This page isn't available. Please ask reception.")
    return row, booking


def _status_words(row: sqlite3.Row, booking: sqlite3.Row) -> str:
    from backend.opd import routes as opd

    language = row["language"] or "en-IN"
    names = opd.department_names(booking["form_id"])
    if names is None:
        return WAIT_FOR_DEPARTMENT[language].format(number=booking["queue_number"])
    return STATUS_TEXT[language].format(number=booking["queue_number"], department=names[language])


@router.get("/patient/{token}/status")
def patient_status(token: str, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """What the patient sees after the interview. The AI summary only after a doctor's review."""
    from backend.opd import routes as opd

    row, booking = _finished_intake(token, db)
    language = row["language"] or "en-IN"
    urgent = json.loads(row["urgent"])
    if urgent:
        # The urgent stop is unchanged: where to go, nothing about seriousness, and nothing else.
        return {"urgent": True, "language": language, "message": agent.URGENT_MESSAGE[language]}
    summary = None
    if row["reviewed_at"] and row["report"]:
        report = json.loads(row["report"])
        summary = {key: report.get(key) for key in ("chief_complaint", "present_illness", "current_medicines", "allergies")}
    return {
        "urgent": False,
        "language": language,
        "patient_name": row["patient_name"],
        "queue_number": booking["queue_number"],
        "department": opd.department_names(booking["form_id"]),
        "words": _status_words(row, booking),
        "told": [{"question": turn["question"], "answer": turn["answer"]} for turn in json.loads(row["transcript"])],
        "reviewed": bool(row["reviewed_at"]),
        "summary": summary,
    }


@router.post("/patient/{token}/status-audio", dependencies=[Depends(ratelimit.per_path_value(ratelimit.CONSENT_AUDIO, "token"))])
def patient_status_audio(token: str, db: sqlite3.Connection = Depends(get_db)) -> dict:
    row, booking = _finished_intake(token, db)
    language = row["language"] or "en-IN"
    words = agent.URGENT_MESSAGE[language] if json.loads(row["urgent"]) else _status_words(row, booking)
    release(db)  # no lock held while a voice is made
    return {"audio": _spoken(words, language)}


@router.post("/patient/{token}/consent-audio", dependencies=[Depends(ratelimit.per_path_value(ratelimit.CONSENT_AUDIO, "token"))])
def consent_audio(token: str, request: ConsentAudio, db: sqlite3.Connection = Depends(get_db)) -> dict:
    row = _open_intake(token, db)
    if request.kind == "abha" and not row["abha_id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no ABHA question for this visit.")
    release(db)  # no lock held while a voice is made
    return _consent_audio(consent.ABHA if request.kind == "abha" else consent.INTERVIEW, request.language)


@router.post("/patient/{token}/help", dependencies=[Depends(ratelimit.per_path_value(ratelimit.INTERVIEW_HELP, "token"))])
def ask_for_help(token: str, db: sqlite3.Connection = Depends(get_db)) -> dict:
    """The patient's "Tell reception" button. It marks the visit in the queue and decides nothing."""
    row = _open_intake(token, db)
    db.execute("UPDATE intakes SET help_requested_at = datetime('now') WHERE id = ?", (row["id"],))
    _alert_staff(db, row, ALERT_HELP, f"{row['patient_name']} asked for help at the interview screen")
    return {"told": True}


@router.post("/patient/{token}/start", dependencies=[Depends(ratelimit.per_client(ratelimit.INTERVIEW_STARTS_PER_DEVICE))])
def start_interview(
    token: str, request: StartRequest, db: sqlite3.Connection = Depends(get_db)
) -> dict:
    row = _open_intake(token, db)
    if not request.consent:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Consent is needed to continue.")
    if request.consent_version != consent.VERSION:
        # The words changed since the page loaded, so the patient hasn't agreed to these ones.
        raise HTTPException(status.HTTP_409_CONFLICT, "Please reload the page and read the consent again.")
    if row["status"] != "waiting":
        raise HTTPException(status.HTTP_409_CONFLICT, "This interview has already started.")

    records = None
    if request.abha_consent and row["abha_id"]:
        records = asdict(abha.get_abha_client().fetch(row["abha_id"]))
    form = agent.load_form(row["form_id"])
    question = agent.first_question(form, request.language)
    started = db.execute(
        """
        UPDATE intakes SET status = 'in_progress', language = ?, records = ?, current_question = ?,
            questions_asked = 1, expires_at = datetime('now', ?) WHERE id = ? AND status = 'waiting'
        """,
        (
            request.language,
            json.dumps(records) if records else None,
            question,
            f"+{settings.diagnofast_interview_hours} hours",
            row["id"],
        ),
    ).rowcount
    if not started:  # another tab started it a moment ago
        raise HTTPException(status.HTTP_409_CONFLICT, "This interview has already started.")
    consent.record(db, consent.INTERVIEW, request.language, True, intake_id=row["id"])
    if row["abha_id"]:  # a no is kept too, so the doctor can see why no records came
        consent.record(db, consent.ABHA, request.language, request.abha_consent, intake_id=row["id"])
    events.emit(db, MODULE, "intake.started", _workflow(db, row), "started", actor="patient", key=str(row["id"]), metadata={"language": request.language})
    return {"question": question, "suggested_chips": [chip.model_dump() for chip in agent.field_chips(form["fields"][0], request.language)], "audio": _spoken(question, request.language)}


def _read_audio(audio: UploadFile) -> tuple:
    content_type = (audio.content_type or "").split(";")[0].strip()
    if content_type not in recordings.EXTENSIONS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "This audio format isn't supported.")
    data = audio.file.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "This recording is too long.")
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "This recording is empty.")
    return data, content_type


@router.post("/patient/{token}/transcribe", dependencies=[Depends(ratelimit.per_path_value(ratelimit.INTERVIEW_PREVIEWS, "token"))])
def preview_transcript(token: str, audio: UploadFile = File(...), db: sqlite3.Connection = Depends(get_db)) -> dict:
    row = _open_intake(token, db)
    if row["status"] != "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, "Please start the interview first.")
    data, content_type = _read_audio(audio)
    language = row["language"]
    release(db)  # no lock held while the speech service listens
    said = speech.transcribe(data, content_type, language).strip()
    if not said:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "We couldn't hear that. Please try again, or type your answer.")
    if len(said) > MAX_TYPED_ANSWER:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Please give a shorter answer.")
    # Preview only: no answer or recording is stored before the patient confirms.
    return {"text": said}


def _translate_answers(db: sqlite3.Connection, row: sqlite3.Row) -> None:
    """An English machine translation beside each Hindi answer the patient confirmed, for the doctor.

    Runs in the report job, so the patient never waits for it. Only with Sarvam ready (speech.py decides);
    a failure leaves the line untranslated. The patient's own words are never changed, and the report AI
    still reads those, not the translation.
    """
    transcript = json.loads(row["transcript"])
    changed = False
    for turn in transcript:
        if "english" in turn:
            continue
        english = speech.translate_to_english(turn["answer"])
        turn["english"] = english
        changed = changed or english is not None
    if changed:
        db.execute("UPDATE intakes SET transcript = ? WHERE id = ?", (json.dumps(transcript, ensure_ascii=False), row["id"]))
        db.commit()


def _build_report(intake_id: int) -> None:
    """Runs after the patient has their thank-you, so they aren't kept waiting."""
    db = connect()
    try:
        row = db.execute("SELECT * FROM intakes WHERE id = ?", (intake_id,)).fetchone()
        _translate_answers(db, row)
        row = db.execute("SELECT * FROM intakes WHERE id = ?", (intake_id,)).fetchone()
        try:
            report = agent.write_report(
                agent.load_form(row["form_id"]),
                json.loads(row["answers"]),
                [
                    {"question": turn["question"], "answer": turn["answer"]}
                    for turn in json.loads(row["transcript"])
                ],
                json.loads(row["records"]) if row["records"] else None,
            )
            if not settings_store.get("features.diagnofast_investigations", db):
                report.suggested_investigations = []  # held for regulatory review: never stored while off
            db.execute(
                "UPDATE intakes SET report = ?, status = 'done' WHERE id = ?",
                (report.model_dump_json(), intake_id),
            )
            if row["patient_id"]:  # an intake with no record has no patient to attach it to
                pack.enqueue(db, row["patient_id"], "intake", intake_id)
            graph_sync.enqueue(db, "intake", intake_id)  # a reference only, with the change
            events.emit(db, MODULE, "intake.review_required", _workflow(db, row), "review_required", key=str(intake_id), metadata={"review_required": True}, used_ai=True)
        except Exception as error:  # any failure, so the intake never stays "preparing" for ever
            # The doctor can still read the answers and transcript, and can retry.
            db.rollback()
            logger.warning("Report failed for intake %s: %s", intake_id, type(error).__name__)
            db.execute("UPDATE intakes SET status = 'report_failed' WHERE id = ?", (intake_id,))
            events.emit(db, MODULE, "intake.failed", _workflow(db, row), "failed", key=str(intake_id), metadata={"error_category": events.category_of(error)})
        db.commit()
    finally:
        db.close()


@router.post("/patient/{token}/answer", dependencies=[Depends(ratelimit.per_path_value(ratelimit.INTERVIEW_ANSWERS, "token"))])
def answer(
    token: str,
    background: BackgroundTasks,
    audio: Optional[UploadFile] = File(default=None),
    text: Optional[str] = Form(default=None, max_length=MAX_TYPED_ANSWER),
    # The page sends one key per question, and the same key again if it retries after a lost reply.
    answer_key: Optional[str] = Form(default=None, max_length=MAX_ANSWER_KEY),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    if answer_key:
        seen = _intake_by_token(token, db)
        if seen is not None and seen["last_answer_key"] == answer_key and seen["last_answer_reply"]:
            # Already saved: give the same reply again rather than record the answer twice.
            reply = json.loads(seen["last_answer_reply"])
            spoken = reply.get("message") if reply.get("finished") else reply.get("question")
            return {**reply, "audio": _spoken(spoken, seen["language"])}
    row = _open_intake(token, db)
    if row["status"] != "in_progress":
        raise HTTPException(status.HTTP_409_CONFLICT, "Please start the interview first.")
    language = row["language"]
    transcript = json.loads(row["transcript"])

    audio_name = None
    if audio is not None:
        data, content_type = _read_audio(audio)
        # Explicitly confirmed/edited text wins over automatic speech recognition.
        if text is None:
            release(db)  # no lock held while the speech service listens
        said = text.strip() if text is not None else speech.transcribe(data, content_type, language).strip()
        if not said:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "We couldn't hear that. Please try again, or type your answer.")
    elif text and text.strip():
        said = text.strip()
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Please answer the question.")
    if len(said) > MAX_TYPED_ANSWER:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Please give a shorter answer.")

    transcript.append({"question": row["current_question"], "answer": said, "audio": audio_name})
    form = agent.load_form(row["form_id"])
    answers = json.loads(row["answers"])
    conversation = [{"question": turn["question"], "answer": turn["answer"]} for turn in transcript]
    graph_state = json.loads(row["graph_state"] or "{}")
    try:
        step = agent.advance(
            form, answers, conversation, row["questions_asked"], language,
            guide=lambda: _guidance(db, row, form, answers, conversation, language, graph_state),
        )
    except (llm.AIUnavailable, llm.AIDeclined) as error:
        events.emit_separately(MODULE, "intake.failed", lambda connection: _workflow(connection, row), "failed", metadata={"error_category": events.category_of(error)})
        raise
    if audio is not None:
        audio_name = recordings.save(row["id"], len(transcript) - 1, data, content_type)
        transcript[-1]["audio"] = audio_name

    finished = step.question is None
    if finished:
        message = agent.URGENT_MESSAGE[language] if step.urgent else agent.THANK_YOU[language]
        reply = {"finished": True, "urgent": bool(step.urgent), "message": message, "status_page": _has_status_page(db, row)}
    else:
        reply = {"finished": False, "question": step.question, "suggested_chips": [chip.model_dump() for chip in step.suggested_chips]}
    # Only saved if nothing else answered this question while the AI was thinking: two tabs, or a
    # retry after a timeout, must not both be recorded.
    saved = db.execute(
        """
        UPDATE intakes SET answers = ?, transcript = ?, urgent = ?, current_question = ?,
            questions_asked = ?, status = ?, last_answer_key = ?, last_answer_reply = ?, graph_state = ?
        WHERE id = ? AND status = 'in_progress' AND questions_asked = ?
        """,
        (
            json.dumps(step.answers, ensure_ascii=False),
            json.dumps(transcript, ensure_ascii=False),
            json.dumps(step.urgent),
            step.question,
            row["questions_asked"] + (0 if finished else 1),
            "preparing_report" if finished else "in_progress",
            answer_key,
            json.dumps(reply, ensure_ascii=False),
            json.dumps(graph_state) if graph_state else row["graph_state"],
            row["id"],
            row["questions_asked"],
        ),
    ).rowcount
    if not saved:
        recordings.discard(row["id"], audio_name)
        raise HTTPException(status.HTTP_409_CONFLICT, "This question was already answered. Please reload the page to carry on.")
    flow = _workflow(db, row)
    if audio_name:
        events.emit(db, MODULE, "intake.transcription.completed", flow, actor="patient", metadata={"language": language})
    if finished:
        if step.urgent:
            _alert_staff(db, row, ALERT_URGENT, f"Urgent: {row['patient_name']} was sent to reception", ", ".join(step.urgent))
        db.execute("UPDATE intakes SET report_requested_at = datetime('now') WHERE id = ?", (row["id"],))
        events.emit(db, MODULE, "intake.completed", flow, actor="patient", key=str(row["id"]), metadata={"question_count": row["questions_asked"], "urgent_stop": bool(step.urgent)}, used_ai=True)
        # Commit first: the report task reads this row on its own connection.
        db.commit()
        background.add_task(_build_report, row["id"])
        return {**reply, "audio": _spoken(reply["message"], language)}
    return {**reply, "audio": _spoken(step.question, language)}
