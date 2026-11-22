"""Judge mode: a public demo with made-up patients, where each tool on the home page opens signed in.

It only works with demo mode on and real patient data off. Off, its routes answer as if they didn't exist."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import auth, judge, ratelimit, safety
from backend.app import app
from backend.auth import SESSION_COOKIE
from backend.config import settings
from backend.db import connect
from backend.tests.conftest import verify_email

CATALOGUE = Path(__file__).resolve().parents[2] / "web" / "js" / "care" / "catalogue.js"


@pytest.fixture
def judging(client, monkeypatch):
    monkeypatch.setattr(settings, "judge_mode", True)
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "allow_real_patient_data", False)
    return client


def _register(email, role):
    with TestClient(app) as browser:
        response = browser.post("/api/auth/register", json={
            "first_name": "Demo", "last_name": role.title(), "email": email, "password": "a-long-password", "role": role,
        })
        assert response.status_code == 201
        return response.json()["id"]


@pytest.fixture
def demo_accounts(judging):
    doctor_id = _register(judge.DOCTOR_EMAIL, "doctor")
    verify_email(judge.DOCTOR_EMAIL)
    patient_id = _register(judge.PATIENT_EMAIL, "patient")
    return doctor_id, patient_id


# Starting up


def test_judge_mode_refuses_to_start_without_demo_mode(monkeypatch):
    monkeypatch.setattr(settings, "judge_mode", True)
    monkeypatch.setattr(settings, "demo_mode", False)
    with pytest.raises(RuntimeError, match="DIAGNOSIA_JUDGE_MODE"):
        safety.assert_safe_to_start(connect())


def test_judge_mode_refuses_to_start_with_real_patient_data(client, monkeypatch):
    monkeypatch.setattr(settings, "judge_mode", True)
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "allow_real_patient_data", True)
    with pytest.raises(RuntimeError, match="DIAGNOSIA_JUDGE_MODE"):
        safety.assert_safe_to_start(connect())


def test_judge_mode_starts_with_demo_mode_and_made_up_patients(judging):
    safety.assert_safe_to_start(connect())
    assert judge.active()


def test_judge_mode_is_inactive_unless_every_condition_holds(monkeypatch):
    monkeypatch.setattr(settings, "judge_mode", True)
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "allow_real_patient_data", True)
    assert not judge.active()
    monkeypatch.setattr(settings, "allow_real_patient_data", False)
    monkeypatch.setattr(settings, "demo_mode", False)
    assert not judge.active()


# Off means absent


@pytest.mark.parametrize("tool", list(judge.TOOL_ACCOUNTS))
def test_with_judge_mode_off_the_demo_door_does_not_exist(client, tool):
    response = client.get(f"/demo/open?tool={tool}", follow_redirects=False)
    assert response.status_code == 404
    assert SESSION_COOKIE not in response.cookies


def test_with_judge_mode_off_the_status_says_so(client):
    assert client.get("/api/demo/status").json() == {"judge_mode": False}


def test_with_judge_mode_on_the_status_says_so(judging):
    assert judging.get("/api/demo/status").json() == {"judge_mode": True}


# Opening a tool


def test_every_catalogue_tool_has_a_demo_account_and_nothing_else_does():
    ids = re.findall(r"\{ id: '([a-z]+)'", CATALOGUE.read_text(encoding="utf-8"))
    assert sorted(ids) == sorted(judge.TOOL_ACCOUNTS)
    assert len(ids) == 6


def test_the_prescription_analyzer_opens_as_the_patient_and_the_rest_as_the_doctor():
    assert judge.TOOL_ACCOUNTS["prescription"] == judge.PATIENT_EMAIL
    assert {tool for tool, email in judge.TOOL_ACCOUNTS.items() if email == judge.DOCTOR_EMAIL} == {
        "diagnofast", "clinscribe", "lablens", "referrals", "discharge",
    }


@pytest.mark.parametrize("tool", list(judge.TOOL_ACCOUNTS))
def test_each_tool_opens_signed_in_as_its_account(demo_accounts, tool):
    with TestClient(app) as browser:
        response = browser.get(f"/demo/open?tool={tool}", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == f"/care.html#/{tool}"
        me = browser.get("/api/me").json()
        assert me["email"] == judge.TOOL_ACCOUNTS[tool]


def test_the_session_cookie_is_the_normal_one(demo_accounts, monkeypatch):
    monkeypatch.setattr(settings, "cookie_secure", True)
    with TestClient(app, base_url="https://testserver") as browser:
        response = browser.get("/demo/open?tool=lablens", follow_redirects=False)
        cookie = response.headers["set-cookie"]
        assert cookie.startswith(f"{SESSION_COOKIE}=")
        assert "HttpOnly" in cookie and "Secure" in cookie and "samesite=lax" in cookie.lower()
        db = connect()
        stored = db.execute("SELECT token_hash FROM sessions").fetchall()
        db.close()
        token = browser.cookies.get(SESSION_COOKIE)
        assert token and all(row["token_hash"] != token for row in stored)  # only a hash is kept


def test_switching_tools_ends_the_previous_demo_session(demo_accounts):
    with TestClient(app) as browser:
        browser.get("/demo/open?tool=diagnofast", follow_redirects=False)
        first = browser.cookies.get(SESSION_COOKIE)
        browser.get("/demo/open?tool=prescription", follow_redirects=False)
        db = connect()
        left = db.execute("SELECT 1 FROM sessions WHERE token_hash = ?", (auth.hash_token(first),)).fetchone()
        db.close()
        assert left is None and browser.cookies.get(SESSION_COOKIE) != first


@pytest.mark.parametrize("tool", ["", "settings", "governance", "skin", "../care", "DIAGNOFAST"])
def test_an_unknown_tool_is_not_found(demo_accounts, tool):
    response = demo_accounts and TestClient(app).get(f"/demo/open?tool={tool}", follow_redirects=False)
    assert response.status_code == 404
    assert SESSION_COOKIE not in response.cookies


def test_without_the_seeded_accounts_the_door_says_so(judging):
    response = judging.get("/demo/open?tool=diagnofast", follow_redirects=False)
    assert response.status_code == 503


def test_an_unverified_demo_doctor_is_never_signed_in(judging):
    _register(judge.DOCTOR_EMAIL, "doctor")  # left pending
    assert judging.get("/demo/open?tool=clinscribe", follow_redirects=False).status_code == 503


def test_the_demo_door_is_rate_limited_per_address(demo_accounts, monkeypatch):
    monkeypatch.setitem(ratelimit.RULES, ratelimit.DEMO_OPENS, ratelimit.Rule(ratelimit.DEMO_OPENS, 2, ratelimit.HOUR, "busy"))
    browser = TestClient(app)
    assert browser.get("/demo/open?tool=lablens", follow_redirects=False).status_code == 303
    assert browser.get("/demo/open?tool=lablens", follow_redirects=False).status_code == 303
    assert browser.get("/demo/open?tool=lablens", follow_redirects=False).status_code == 429


def test_opening_a_tool_is_audited(demo_accounts):
    TestClient(app).get("/demo/open?tool=referrals", follow_redirects=False)
    db = connect()
    row = db.execute("SELECT action FROM audit_events WHERE action = 'demo.open'").fetchone()
    db.close()
    assert row is not None


# The workspace


def test_the_workspace_knows_judge_mode_and_which_chart_to_open(demo_accounts):
    doctor_id, patient_user_id = demo_accounts
    with TestClient(app) as browser:
        browser.get("/demo/open?tool=clinscribe", follow_redirects=False)
        chart = browser.post("/api/patients", json={"first_name": "Kishore", "last_name": "Mishra", "date_of_birth": "1970-01-01", "sex": "male"}).json()
        db = connect()
        db.execute("UPDATE patients SET user_id = ? WHERE id = ?", (patient_user_id, chart["id"]))
        db.commit()
        db.close()
        config = browser.get("/api/platform/config").json()
    assert config["judge_mode"] is True
    assert config["judge_patient_id"] == chart["id"]
    assert config["can_administer"] is False  # judges can't change settings or keys


def test_outside_judge_mode_the_workspace_shows_no_demo_note(doctor):
    config = doctor.get("/api/platform/config").json()
    assert config["judge_mode"] is False and config["judge_patient_id"] is None


# Shared account, separate allowances


def test_in_judge_mode_ai_limits_count_each_address_separately(demo_accounts, monkeypatch):
    rule = ratelimit.Rule(ratelimit.LAB_READS, 1, ratelimit.HOUR, "busy")
    monkeypatch.setitem(ratelimit.RULES, ratelimit.LAB_READS, rule)
    user = {"id": 7}
    first = ratelimit.account_key(user, "203.0.113.1")
    second = ratelimit.account_key(user, "203.0.113.2")
    assert first != second
    monkeypatch.setattr(settings, "judge_mode", False)
    assert ratelimit.account_key(user, "203.0.113.1") == ratelimit.account_key(user, "203.0.113.2") == "user:7"


@pytest.mark.parametrize("call", [
    lambda c: c.get("/demo/open?tool=lablens", follow_redirects=False),
    lambda c: c.post("/api/auth/login", json={"email": judge.DOCTOR_EMAIL, "password": "a-long-password"}),
])
def test_the_session_is_saved_before_the_answer_leaves(demo_accounts, call):
    # get_db commits only after the response has gone out, so on a slow host the browser's next
    # request (care.html asking /api/me) can arrive first and be told to sign in. The session must be
    # committed by the route itself. A connection that never commits on its own shows whether it is.
    from backend.db import connect as open_db, get_db

    def never_commits():
        connection = open_db()
        try:
            yield connection
        finally:
            connection.close()

    app.dependency_overrides[get_db] = never_commits
    try:
        with TestClient(app) as browser:
            assert call(browser).status_code in (200, 303)
            token = browser.cookies.get(SESSION_COOKIE)
    finally:
        app.dependency_overrides.pop(get_db, None)
    db = connect()
    saved = db.execute("SELECT 1 FROM sessions WHERE token_hash = ?", (auth.hash_token(token),)).fetchone()
    db.close()
    assert saved is not None
