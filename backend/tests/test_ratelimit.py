"""Limits on the public and costly routes, counted in SQLite."""
import pytest
from fastapi import HTTPException

from backend import llm, ratelimit
from backend.config import settings
from backend.db import connect
from backend.prescription import routes as prescription_routes
from backend.tests.test_diagnofast import (  # noqa: F401  (services is a fixture)
    ScriptedAI,
    create_intake,
    doctor_session,
    say,
    services,
    start,
    turn,
)


@pytest.fixture
def small(monkeypatch):
    """Swaps a rule for one with a limit of a few hits, so tests stay quick."""

    def make(name, limit, window=3600):
        monkeypatch.setitem(ratelimit.RULES, name, ratelimit.Rule(name, limit, window, "Slow down."))

    return make


@pytest.fixture
def clock(monkeypatch):
    now = {"t": 1_000_000.0}
    monkeypatch.setattr(ratelimit, "_clock", lambda: now["t"])
    return now


def stored_hashes():
    db = connect()
    try:
        return [row["key_hash"] for row in db.execute("SELECT key_hash FROM rate_limit_hits")]
    finally:
        db.close()


def test_a_rule_refuses_at_its_limit_and_each_key_has_its_own(client, small, clock):
    small(ratelimit.KIOSK_PER_DEVICE, 2, window=600)
    ratelimit.hit(ratelimit.KIOSK_PER_DEVICE, "10.0.0.1")
    clock["t"] += 100
    ratelimit.hit(ratelimit.KIOSK_PER_DEVICE, "10.0.0.1")
    with pytest.raises(HTTPException) as refused:
        ratelimit.hit(ratelimit.KIOSK_PER_DEVICE, "10.0.0.1")
    assert refused.value.status_code == 429
    # The oldest hit leaves the window 500 seconds from now.
    assert refused.value.headers["Retry-After"] == "500"
    ratelimit.hit(ratelimit.KIOSK_PER_DEVICE, "10.0.0.2")


def test_only_hashes_of_keys_are_stored(client, clock):
    ratelimit.hit(ratelimit.KIOSK_PER_DEVICE, "203.0.113.9")
    ratelimit.hit(ratelimit.INTERVIEW_ANSWERS, "203.0.113.9")
    hashes = stored_hashes()
    assert len(hashes) == 2
    assert len(set(hashes)) == 2  # the bucket is part of the hash
    assert all("203.0.113.9" not in value and len(value) == 64 for value in hashes)


def test_old_hits_expire_and_are_swept_away(client, small, clock):
    small(ratelimit.KIOSK_PER_DEVICE, 1, window=60)
    ratelimit.hit(ratelimit.KIOSK_PER_DEVICE, "10.0.0.1")
    with pytest.raises(HTTPException):
        ratelimit.hit(ratelimit.KIOSK_PER_DEVICE, "10.0.0.1")
    clock["t"] += 61
    ratelimit.hit(ratelimit.KIOSK_PER_DEVICE, "10.0.0.1")
    assert len(stored_hashes()) == 2

    longest = max(rule.window for rule in ratelimit.RULES.values())
    clock["t"] += longest + 1
    ratelimit.hit(ratelimit.SPEECH_PER_USER, "user:1")
    db = connect()
    try:
        ratelimit.forget_expired(db)
        db.commit()
    finally:
        db.close()
    assert len(stored_hashes()) == 1


KIOSK_BODY = {"form_id": "cardiology", "patient_name": "Synthetic Visitor", "consent": True}


def kiosk_ready(client, details, monkeypatch):
    doctor_session(client, details)
    db = connect()
    doctor_id = db.execute("SELECT id FROM users WHERE email = ?", (details["email"],)).fetchone()["id"]
    db.close()
    monkeypatch.setattr(settings, "diagnofast_kiosk_doctor_id", str(doctor_id))
    client.cookies.clear()  # kiosk visitors have no account


def test_the_kiosk_limits_each_device(client, details, services, small, monkeypatch):
    small(ratelimit.KIOSK_PER_DEVICE, 2)
    kiosk_ready(client, details, monkeypatch)
    for _ in range(2):
        assert client.post("/api/diagnofast/kiosk/intakes", json=KIOSK_BODY).status_code == 201
    refused = client.post("/api/diagnofast/kiosk/intakes", json=KIOSK_BODY)
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) > 0


def test_the_kiosk_has_an_overall_limit_across_devices(client, details, services, small, monkeypatch):
    small(ratelimit.KIOSK_OVERALL, 2)
    kiosk_ready(client, details, monkeypatch)
    # Every caller shares this limit, whatever its address.
    ratelimit.hit(ratelimit.KIOSK_OVERALL, "all")
    ratelimit.hit(ratelimit.KIOSK_OVERALL, "all")
    assert client.post("/api/diagnofast/kiosk/intakes", json=KIOSK_BODY).status_code == 429


def test_answers_on_one_link_are_limited(client, details, services, small, monkeypatch):
    small(ratelimit.INTERVIEW_ANSWERS, 2)
    monkeypatch.setattr(llm, "ask", ScriptedAI([turn(), turn(), turn()]))
    doctor_session(client, details)
    _, token = create_intake(client)
    _, other_token = create_intake(client)
    client.cookies.clear()
    start(client, token)
    start(client, other_token)
    assert say(client, token).status_code == 200
    assert say(client, token).status_code == 200
    assert say(client, token).status_code == 429
    assert say(client, other_token).status_code == 200


def test_read_aloud_is_limited_per_account(client, person, small, monkeypatch):
    small(ratelimit.SPEECH_PER_USER, 2)
    # The route imported speak by name, so it is patched where it is used.
    monkeypatch.setattr(prescription_routes, "speak", lambda text, language: b"wav")
    body = {"text": "Take one tablet after breakfast.", "language": "en-IN"}
    first = person("patient", "Synthetic", "Reader")
    second = person("patient", "Another", "Reader")
    assert first.post("/api/prescription/speak", json=body).status_code == 200
    assert first.post("/api/prescription/speak", json=body).status_code == 200
    assert first.post("/api/prescription/speak", json=body).status_code == 429
    assert second.post("/api/prescription/speak", json=body).status_code == 200


def test_read_aloud_still_needs_an_account(client):
    body = {"text": "Hello", "language": "en-IN"}
    assert client.post("/api/prescription/speak", json=body).status_code == 401
