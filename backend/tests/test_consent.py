"""Consent is shown in words, agreed to explicitly, and stored (audit plan WI-101)."""
import re

from backend import llm
from backend.config import WEB_DIR
from backend.db import connect
from backend.records import consent
from backend.tests.test_diagnofast import create_intake, doctor_session, services, start  # noqa: F401
from backend.tests.test_prescription import RecordingAI, post_photo, read_result, signed_in


def _records(**where):
    column, value = next(iter(where.items()))
    db = connect()
    try:
        return [dict(row) for row in db.execute(f"SELECT * FROM consent_records WHERE {column} = ? ORDER BY id", (value,))]
    finally:
        db.close()


def _patient_link(client, details, **extra):
    doctor_session(client, details)
    intake_id, token = create_intake(client, **extra)
    client.cookies.clear()
    return intake_id, token


def test_the_interview_page_gets_the_words_in_both_languages(client, details, services):
    _, token = _patient_link(client, details)
    page = client.get(f"/api/diagnofast/patient/{token}").json()
    assert page["consent"]["version"] == consent.VERSION
    assert len(page["consent"]["lines"]["en-IN"]) == 3
    assert len(page["consent"]["lines"]["hi-IN"]) == 3
    assert "abha_consent" not in page  # asked only when there is an ABHA number


def test_starting_stores_what_the_patient_agreed_to(client, details, services):
    intake_id, token = _patient_link(client, details)
    assert start(client, token, language="en-IN").status_code == 200
    [stored] = _records(intake_id=intake_id)
    assert stored["kind"] == consent.INTERVIEW
    assert stored["text_version"] == consent.VERSION
    assert stored["language"] == "en-IN"
    assert stored["agreed"] == 1


def test_an_interview_without_agreement_to_these_words_does_not_start(client, details, services):
    intake_id, token = _patient_link(client, details)
    assert start(client, token, consent=False).status_code == 422
    assert start(client, token, consent_version=None).status_code == 409
    assert start(client, token, consent_version="2020-01-01").status_code == 409
    assert _records(intake_id=intake_id) == []
    assert client.get(f"/api/diagnofast/patient/{token}").json()["status"] == "waiting"


def test_abha_is_a_separate_question_and_a_no_is_kept(client, details, services):
    intake_id, token = _patient_link(client, details, abha_id="91-0000-0000-0001")
    page = client.get(f"/api/diagnofast/patient/{token}").json()
    assert page["abha_consent"]["lines"]["hi-IN"]
    assert start(client, token, abha_consent=False).status_code == 200
    kinds = {row["kind"]: row["agreed"] for row in _records(intake_id=intake_id)}
    assert kinds == {consent.INTERVIEW: 1, consent.ABHA: 0}


def test_a_prescription_photo_needs_agreement_to_these_words(client, details, monkeypatch):
    monkeypatch.setattr(llm, "ask", RecordingAI(read_result()))
    signed_in(client, details)
    db = connect()
    try:
        user_id = db.execute("SELECT id FROM users WHERE email = ?", (details["email"],)).fetchone()["id"]
    finally:
        db.close()
    assert post_photo(client, version="old").status_code == 409
    assert post_photo(client, consent="false").status_code == 422
    assert _records(user_id=user_id) == []

    assert post_photo(client).status_code == 200
    [stored] = _records(user_id=user_id)
    assert stored["kind"] == consent.PRESCRIPTION
    assert stored["text_version"] == consent.VERSION


def test_the_pages_show_the_stored_words():
    intake = (WEB_DIR / "js" / "intake.js").read_text(encoding="utf-8")
    assert "consent: true" not in intake  # agreement comes from the patient's tap
    prescription = (WEB_DIR / "js" / "care" / "prescription.js").read_text(encoding="utf-8")
    assert consent.WORDS[consent.PRESCRIPTION]["en-IN"][0] in prescription
    assert re.search(rf"CONSENT_VERSION = '{consent.VERSION}'", prescription)
