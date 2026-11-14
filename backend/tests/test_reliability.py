"""Reports never stay "preparing" for ever, the sweep survives a failing step, and health checks (WI-107)."""
import logging

from backend import app as app_module
from backend import llm
from backend.auth import SESSION_COOKIE
from backend.db import connect
from backend.diagnofast import routes as diagnofast_routes
from backend.tests.test_diagnofast import (  # noqa: F401  (services is a fixture)
    ALL_REQUIRED,
    ScriptedAI,
    create_intake,
    doctor_session,
    say,
    services,
    start,
    turn,
)


REAL_BUILD = diagnofast_routes._build_report


def _status(intake_id):
    db = connect()
    try:
        return db.execute("SELECT status FROM intakes WHERE id = ?", (intake_id,)).fetchone()["status"]
    finally:
        db.close()


def _finished_without_a_report(client, details, monkeypatch):
    """An interview whose report job never ran, as when the process stops right after the last answer."""
    monkeypatch.setattr(llm, "ask", ScriptedAI([turn(ALL_REQUIRED, finished=True)]))
    monkeypatch.setattr(diagnofast_routes, "_build_report", lambda intake_id: None)
    doctor_session(client, details)
    intake_id, token = create_intake(client)
    cookie = client.cookies[SESSION_COOKIE]
    client.cookies.clear()
    start(client, token)
    assert say(client, token).json()["finished"] is True
    client.cookies.set(SESSION_COOKIE, cookie)
    assert _status(intake_id) == "preparing_report"
    return intake_id


def _age_request(intake_id, minutes):
    db = connect()
    db.execute("UPDATE intakes SET report_requested_at = datetime('now', ?) WHERE id = ?", (f"-{minutes} minutes", intake_id))
    db.commit()
    db.close()


def test_a_report_left_preparing_is_failed_after_five_minutes(client, details, services, monkeypatch):
    intake_id = _finished_without_a_report(client, details, monkeypatch)
    app_module._sweep_once()
    assert _status(intake_id) == "preparing_report"  # a job may still be running
    _age_request(intake_id, 6)
    app_module._sweep_once()
    assert _status(intake_id) == "report_failed"


def test_a_failed_report_can_be_retried(client, details, services, monkeypatch):
    intake_id = _finished_without_a_report(client, details, monkeypatch)
    _age_request(intake_id, 6)
    app_module._sweep_once()
    monkeypatch.setattr(diagnofast_routes, "_build_report", REAL_BUILD)  # the real report job again
    monkeypatch.setattr(llm, "ask", ScriptedAI([]))  # ScriptedAI writes a report for the Report schema
    assert client.post(f"/api/diagnofast/intakes/{intake_id}/report/retry").status_code == 202
    assert _status(intake_id) == "done"
    assert client.post(f"/api/diagnofast/intakes/{intake_id}/report/retry").status_code == 409


def test_any_error_in_the_report_job_leaves_it_failed_not_preparing(client, details, services, monkeypatch):
    def broken(*args, **options):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(llm, "ask", ScriptedAI([turn(ALL_REQUIRED, finished=True)]))
    monkeypatch.setattr(diagnofast_routes.agent, "write_report", broken)
    doctor_session(client, details)
    intake_id, token = create_intake(client)
    client.cookies.clear()
    start(client, token)
    say(client, token)
    assert _status(intake_id) == "report_failed"


def test_a_failing_sweep_step_is_logged_and_the_rest_still_run(client, monkeypatch, caplog):
    ran = []

    def broken(db):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(app_module, "SWEEP_STEPS", (("broken", broken), ("after", lambda db: ran.append(True))))
    with caplog.at_level(logging.WARNING, logger="curai"):
        app_module._sweep_once()
    assert ran == [True]
    assert "Sweep step broken failed: RuntimeError" in caplog.text


def test_health_checks_say_nothing_about_patients(client, monkeypatch):
    assert client.get("/healthz").json() == {"status": "ok"}
    ready = client.get("/readyz")
    assert ready.status_code == 200
    body = ready.json()
    # Warnings are fixed words about the deployment (WI-212), never anything about a patient or a path.
    assert set(body.pop("warnings")) <= {"medicine_list_missing"}
    assert body == {"ready": True, "checks": {"database": True, "key_ring": True}}
    monkeypatch.setattr(app_module.vault, "status", lambda: (False, "no key ring"))
    not_ready = client.get("/readyz")
    assert not_ready.status_code == 503
    assert "no key ring" not in not_ready.text
