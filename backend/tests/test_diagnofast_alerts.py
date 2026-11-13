"""Staff are alerted when an interview stops as urgent, and the patient is told where to go (WI-203)."""
import re

from backend import llm
from backend.auth import SESSION_COOKIE
from backend.config import WEB_DIR
from backend.diagnofast import agent
from backend.tests.test_diagnofast import ALL_REQUIRED, ScriptedAI, create_intake, doctor_session, say, services, start, turn  # noqa: F401


def _interview(client, details, monkeypatch, answer):
    monkeypatch.setattr(llm, "ask", ScriptedAI([turn(ALL_REQUIRED, finished=True)]))
    doctor_session(client, details)
    intake_id, token = create_intake(client)
    cookie = client.cookies[SESSION_COOKIE]
    client.cookies.clear()
    start(client, token, language="en-IN")
    reply = say(client, token, answer).json()
    client.cookies.set(SESSION_COOKIE, cookie)
    return intake_id, reply


def test_an_urgent_stop_alerts_the_doctor_at_once(client, details, services, monkeypatch):
    intake_id, reply = _interview(client, details, monkeypatch, "I have chest pain")
    assert reply["urgent"] is True
    [alert] = client.get("/api/diagnofast/alerts").json()
    assert alert["kind"] == "urgent"
    assert alert["intake_id"] == intake_id
    assert "Ravi Kumar" in alert["title"] and "Chest pain" in alert["body"]
    # It is also in the ordinary inbox, and goes away once someone has seen it.
    assert any(item["id"] == alert["id"] for item in client.get("/api/notifications").json())
    assert client.post(f"/api/notifications/{alert['id']}/read").status_code == 204
    assert client.get("/api/diagnofast/alerts").json() == []


def test_a_calm_interview_alerts_nobody(client, details, services, monkeypatch):
    _, reply = _interview(client, details, monkeypatch, "Bukhar hai")
    assert reply["urgent"] is False
    assert client.get("/api/diagnofast/alerts").json() == []


def test_asking_for_help_alerts_the_doctor(client, details, services):
    doctor_session(client, details)
    intake_id, token = create_intake(client)
    cookie = client.cookies[SESSION_COOKIE]
    client.cookies.clear()
    client.post(f"/api/diagnofast/patient/{token}/help")
    client.post(f"/api/diagnofast/patient/{token}/help")  # pressed twice: still one alert
    assert client.get("/api/diagnofast/alerts").status_code == 401
    client.cookies.set(SESSION_COOKIE, cookie)
    [alert] = client.get("/api/diagnofast/alerts").json()
    assert alert["kind"] == "help" and alert["intake_id"] == intake_id


def test_alerts_are_only_for_the_doctor_they_belong_to(client, details, services, monkeypatch, person):
    _interview(client, details, monkeypatch, "I have chest pain")
    assert person("doctor").get("/api/diagnofast/alerts").json() == []


def test_the_urgent_message_says_where_to_go_and_nothing_about_seriousness():
    for language, text in agent.URGENT_MESSAGE.items():
        lowered = text.lower()
        for word in ("serious", "emergency", "danger", "worry", "गंभीर", "खतरा", "खतरनाक", "चिंता", "इमरजेंसी", "आपातकाल"):
            assert word not in lowered, (language, word)
    assert "go to the reception desk now" in agent.URGENT_MESSAGE["en-IN"].lower()
    assert "रिसेप्शन" in agent.URGENT_MESSAGE["hi-IN"] and "अभी" in agent.URGENT_MESSAGE["hi-IN"]


def test_the_urgent_screen_stays_for_a_minute_and_staff_screens_poll():
    intake = (WEB_DIR / "js" / "intake.js").read_text(encoding="utf-8")
    assert re.search(r"URGENT_HOLD_MS = 60000", intake)
    app = (WEB_DIR / "js" / "care" / "app.js").read_text(encoding="utf-8")
    assert "/api/diagnofast/alerts" in app


def test_an_alert_about_a_chart_follows_access_to_that_chart(doctor, patient, services, monkeypatch):
    from urllib.parse import parse_qs, urlparse

    from fastapi.testclient import TestClient

    from backend.app import app
    from backend.db import connect
    from backend.records import consent

    monkeypatch.setattr(llm, "ask", ScriptedAI([]))
    made = doctor.post("/api/diagnofast/intakes", json={"form_id": "general_physician", "patient_name": "Ravi Kumar", "patient_id": patient["id"]}).json()
    token = parse_qs(urlparse(made["link"]).query)["token"][0]
    with TestClient(app) as visitor:
        visitor.post(f"/api/diagnofast/patient/{token}/start", json={"language": "en-IN", "consent": True, "consent_version": consent.VERSION})
        assert visitor.post(f"/api/diagnofast/patient/{token}/answer", data={"text": "I have chest pain"}).json()["urgent"] is True
    assert len(doctor.get("/api/diagnofast/alerts").json()) == 1

    db = connect()
    db.execute("UPDATE care_team SET revoked_at = datetime('now') WHERE patient_id = ? AND user_id = ?", (patient["id"], doctor.id))
    db.commit()
    db.close()
    assert doctor.get("/api/diagnofast/alerts").json() == []  # no longer on the care team: no name, no symptom
