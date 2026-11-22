"""Walk-ins (step 10): Neo4j suggests a department to STAFF only; staff confirm before the patient sees one.

Routing a patient by AI is close to triage, where CDSCO rules may apply, so the suggestion is advice to a
person and never reaches the patient's screen.
"""
from urllib.parse import parse_qs, urlparse

import pytest

from backend import llm, speech
from backend.config import settings
from backend.db import connect
from backend.integrations import graph
from backend.records import consent
from backend.tests.fake_graph import FakeGraph
from backend.tests.test_diagnofast import ALL_REQUIRED, ScriptedAI, turn
from backend.tests.test_opd_bookings import switch


@pytest.fixture
def walk_ins(client, monkeypatch):
    switch("diagnofast.bookings")
    monkeypatch.setattr(speech, "question_audio", lambda text, language: None)


@pytest.fixture
def fake_graph(client, monkeypatch):
    fake = FakeGraph()
    graph.use(fake)
    monkeypatch.setattr(settings, "neo4j_uri", "neo4j://127.0.0.1:7687")
    switch("neo4j.enabled")
    switch("diagnofast.walkin_suggestion")
    yield fake
    graph.use(None)


def add_walk_in(staff, **extra):
    body = {"patient_name": "Kamla Devi", "patient_age": 58, "phone": "9811100000", **extra}
    response = staff.post("/api/opd/walk-ins", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def interview(client, made, monkeypatch, said="Mujhe kaan mein dard hai aur kaan se paani aata hai"):
    token = parse_qs(urlparse(made["message"]["link"]).query)["token"][0]
    client.cookies.clear()
    monkeypatch.setattr(llm, "ask", ScriptedAI([turn(ALL_REQUIRED, finished=True)]))
    client.post(f"/api/diagnofast/patient/{token}/start", json={"language": "hi-IN", "consent": True, "consent_version": consent.VERSION})
    client.post(f"/api/diagnofast/patient/{token}/answer", data={"text": said})
    return token


def test_a_walk_in_who_is_not_sure_gets_a_queue_number_and_no_department(doctor, walk_ins):
    made = add_walk_in(doctor)
    assert made["queue_number"] == 1
    assert made["department"] is None
    [listed] = doctor.get("/api/opd/bookings").json()
    assert listed["walk_in"] is True and listed["department_confirmed"] is False


def test_a_walk_in_who_knows_their_department_keeps_it(doctor, walk_ins):
    made = add_walk_in(doctor, form_id="ent")
    assert made["department"] == "ENT"


def test_staff_get_a_suggestion_from_the_graph(doctor, client, walk_ins, fake_graph, monkeypatch):
    made = add_walk_in(doctor)
    interview(client, made, monkeypatch)
    suggestion = doctor.get(f"/api/opd/bookings/{made['id']}/suggestion").json()
    assert suggestion["form_id"] == "ent"
    assert suggestion["department"] == "ENT"
    assert suggestion["because"] == ["ear_problem"]
    assert suggestion["source"] == "neo4j"
    assert "Confirm" in suggestion["note"]


def test_the_patient_never_sees_the_suggestion(doctor, client, walk_ins, fake_graph, monkeypatch):
    made = add_walk_in(doctor)
    token = interview(client, made, monkeypatch)
    doctor.get(f"/api/opd/bookings/{made['id']}/suggestion")
    status = client.get(f"/api/diagnofast/patient/{token}/status").json()
    assert status["department"] is None
    assert "ENT" not in str(status) and "कान, नाक" not in str(status)
    assert "Reception will tell you" in status["words"] or "रिसेप्शन आपको बताएगा" in status["words"]
    client.cookies.clear()
    assert client.get(f"/api/opd/bookings/{made['id']}/suggestion").status_code == 401


def test_staff_confirm_and_only_then_the_patient_sees_the_department(doctor, client, walk_ins, fake_graph, monkeypatch):
    made = add_walk_in(doctor)
    token = interview(client, made, monkeypatch)
    response = doctor.post(f"/api/opd/bookings/{made['id']}/department", json={"form_id": "ent"})
    assert response.status_code == 200
    status = client.get(f"/api/diagnofast/patient/{token}/status").json()
    assert status["department"] == {"en-IN": "ENT", "hi-IN": "कान, नाक और गला"}
    db = connect()
    confirmed_by = db.execute("SELECT department_confirmed_by FROM opd_bookings WHERE id = ?", (made["id"],)).fetchone()[0]
    db.close()
    assert confirmed_by == doctor.id


def test_staff_may_choose_a_different_department_from_the_suggestion(doctor, client, walk_ins, fake_graph, monkeypatch):
    made = add_walk_in(doctor)
    interview(client, made, monkeypatch)
    assert doctor.post(f"/api/opd/bookings/{made['id']}/department", json={"form_id": "general_physician"}).status_code == 200
    [listed] = doctor.get("/api/opd/bookings").json()
    assert listed["department"] == "General physician" and listed["department_confirmed"] is True


def test_no_suggestion_with_the_switch_off_or_neo4j_down(doctor, client, walk_ins, monkeypatch):
    made = add_walk_in(doctor)
    interview(client, made, monkeypatch)
    assert doctor.get(f"/api/opd/bookings/{made['id']}/suggestion").status_code == 403
    switch("diagnofast.walkin_suggestion")
    found = doctor.get(f"/api/opd/bookings/{made['id']}/suggestion").json()
    assert found["form_id"] is None and "unavailable" in found["note"].lower()


def test_no_suggestion_before_the_interview_says_anything(doctor, walk_ins, fake_graph):
    made = add_walk_in(doctor)
    found = doctor.get(f"/api/opd/bookings/{made['id']}/suggestion").json()
    assert found["form_id"] is None


def test_a_stranger_cannot_see_or_confirm(doctor, person, client, walk_ins, fake_graph, monkeypatch):
    made = add_walk_in(doctor)
    stranger = person("doctor", "Zed", "Stranger")
    assert stranger.get(f"/api/opd/bookings/{made['id']}/suggestion").status_code == 404
    assert stranger.post(f"/api/opd/bookings/{made['id']}/department", json={"form_id": "ent"}).status_code == 404


def test_only_a_known_department_can_be_confirmed(doctor, walk_ins):
    made = add_walk_in(doctor)
    assert doctor.post(f"/api/opd/bookings/{made['id']}/department", json={"form_id": "brain_surgery"}).status_code == 422
