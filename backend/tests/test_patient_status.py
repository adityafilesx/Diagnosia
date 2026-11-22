"""The patient's status page after the interview (step 6): queue number, department, their own words,
the AI summary only after a doctor's review, and the urgent stop unchanged and spoken aloud."""
from urllib.parse import parse_qs, urlparse

import pytest

from backend import llm, speech
from backend.db import connect
from backend.diagnofast import agent
from backend.records import consent
from backend.tests.test_diagnofast import ALL_REQUIRED, ScriptedAI, turn
from backend.tests.test_opd_bookings import book, make_slot, switch


@pytest.fixture
def booked(client, doctor, monkeypatch):
    switch("diagnofast.bookings")
    monkeypatch.setattr(speech, "question_audio", lambda text, language: (b"mp3", "audio/mpeg"))
    made = book(doctor, make_slot(doctor, form_id="general_physician", day=today())).json()
    token = parse_qs(urlparse(made["message"]["link"]).query)["token"][0]
    client.cookies.clear()
    return {"booking": made, "token": token}


def today():
    db = connect()
    value = db.execute("SELECT date('now', 'localtime')").fetchone()[0]
    db.close()
    return value


def finish(client, token, monkeypatch, urgent=None, language="hi-IN"):
    monkeypatch.setattr(llm, "ask", ScriptedAI([turn(ALL_REQUIRED, finished=True, urgent=urgent)]))
    assert client.post(f"/api/diagnofast/patient/{token}/start", json={"language": language, "consent": True, "consent_version": consent.VERSION}).status_code == 200
    return client.post(f"/api/diagnofast/patient/{token}/answer", data={"text": "मुझे दो दिन से कान में दर्द है"}).json()


def test_the_finish_reply_offers_the_status_page_for_a_booked_visit(client, booked, monkeypatch):
    reply = finish(client, booked["token"], monkeypatch)
    assert reply["finished"] and reply["status_page"] is True


def test_the_status_page_shows_queue_department_and_the_patients_own_words(client, booked, monkeypatch):
    finish(client, booked["token"], monkeypatch)
    page = client.get(f"/api/diagnofast/patient/{booked['token']}/status")
    assert page.status_code == 200
    body = page.json()
    assert body["queue_number"] == booked["booking"]["queue_number"]
    assert body["department"] == {"en-IN": "General physician", "hi-IN": "सामान्य चिकित्सा"}
    assert body["told"][0]["answer"] == "मुझे दो दिन से कान में दर्द है"
    assert body["summary"] is None and body["reviewed"] is False


def test_the_ai_summary_appears_only_after_the_doctor_marks_it_reviewed(client, doctor, booked, monkeypatch):
    finish(client, booked["token"], monkeypatch)
    intake_id = booked["booking"]["id"]
    db = connect()
    intake_id = db.execute("SELECT intake_id FROM opd_bookings WHERE id = ?", (intake_id,)).fetchone()[0]
    db.close()
    assert client.get(f"/api/diagnofast/patient/{booked['token']}/status").json()["summary"] is None
    assert doctor.post(f"/api/diagnofast/intakes/{intake_id}/review").status_code == 200
    summary = client.get(f"/api/diagnofast/patient/{booked['token']}/status").json()["summary"]
    assert summary["chief_complaint"] == "Fever"
    assert set(summary) == {"chief_complaint", "present_illness", "current_medicines", "allergies"}  # never flags or tests


def test_the_queue_and_department_are_read_aloud_in_the_patients_language(client, booked, monkeypatch):
    finish(client, booked["token"], monkeypatch)
    spoken = []
    monkeypatch.setattr(speech, "question_audio", lambda text, language: spoken.append((text, language)) or (b"mp3", "audio/mpeg"))
    response = client.post(f"/api/diagnofast/patient/{booked['token']}/status-audio")
    assert response.status_code == 200 and response.json()["audio"].startswith("data:audio/mpeg;base64,")
    text, language = spoken[0]
    assert language == "hi-IN"
    assert str(booked["booking"]["queue_number"]) in text and "सामान्य चिकित्सा" in text


def test_an_urgent_stop_is_unchanged_and_spoken(client, booked, monkeypatch):
    spoken = []
    monkeypatch.setattr(speech, "question_audio", lambda text, language: spoken.append(text) or (b"mp3", "audio/mpeg"))
    reply = finish(client, booked["token"], monkeypatch, urgent=["Chest pain"])
    assert reply["urgent"] is True
    assert reply["message"] == agent.URGENT_MESSAGE["hi-IN"]
    assert reply["audio"] and agent.URGENT_MESSAGE["hi-IN"] in spoken
    body = client.get(f"/api/diagnofast/patient/{booked['token']}/status").json()
    assert body["urgent"] is True and body["message"] == agent.URGENT_MESSAGE["hi-IN"]
    assert "queue_number" not in body and "summary" not in body and "told" not in body


def test_no_status_page_while_answering_or_without_a_booking(client, details, booked, monkeypatch):
    assert client.get(f"/api/diagnofast/patient/{booked['token']}/status").status_code == 404  # not finished yet
    from backend.tests.test_diagnofast import create_intake, doctor_session

    doctor_session(client, details)
    _, loose = create_intake(client)
    client.cookies.clear()
    reply = finish(client, loose, monkeypatch)
    assert reply.get("status_page") is False
    assert client.get(f"/api/diagnofast/patient/{loose}/status").status_code == 404


def test_the_status_page_closes_at_the_end_of_the_day(client, booked, monkeypatch):
    finish(client, booked["token"], monkeypatch)
    db = connect()
    db.execute("UPDATE intakes SET report_requested_at = datetime('now', '-2 days')")
    db.commit()
    db.close()
    assert client.get(f"/api/diagnofast/patient/{booked['token']}/status").status_code == 404


def test_the_status_page_is_off_with_bookings_off(client, booked, monkeypatch):
    finish(client, booked["token"], monkeypatch)
    switch("diagnofast.bookings", False)
    assert client.get(f"/api/diagnofast/patient/{booked['token']}/status").status_code == 404


def test_a_finished_link_still_cannot_answer_again(client, booked, monkeypatch):
    finish(client, booked["token"], monkeypatch)
    assert client.post(f"/api/diagnofast/patient/{booked['token']}/answer", data={"text": "again"}).status_code in (404, 409)
