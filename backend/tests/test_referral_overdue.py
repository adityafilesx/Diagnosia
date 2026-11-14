"""WI-240: a referral past its reply-by date becomes a dated, high-priority task from the sweep, with
nobody opening a page. Tasks ReferralLoop creates itself carry a due date, so escalation reaches them."""
from datetime import date, datetime, timedelta, timezone

import pytest

from backend import app as app_module
from backend.db import connect
from backend.referralloop import routes as referrals
from backend.tests.test_referralloop import BASE, clinic, move, referral, return_outcome, to_attended  # noqa: F401 (fixtures)


def make_overdue(referral_id, days=2):
    db = connect()
    db.execute("UPDATE referrals SET respond_by = ? WHERE id = ?", ((date.today() - timedelta(days=days)).isoformat(), referral_id))
    db.commit()
    db.close()


def tasks(doctor, referral):
    return doctor.get(f"/api/patients/{referral['patient_id']}/tasks").json()


def chase_tasks(doctor, referral):
    return [task for task in tasks(doctor, referral) if task["link_type"] == "referral_overdue"]


def test_a_seeded_overdue_referral_produces_a_task_with_nobody_opening_a_page(doctor, clinic, referral):
    make_overdue(referral["id"])
    assert chase_tasks(doctor, referral) == []
    app_module._sweep_once()  # what the five-minute timer runs: no request, no screen
    [task] = chase_tasks(doctor, referral)
    assert task["priority"] == "high" and task["status"] == "open"
    assert task["owner_user_id"] == doctor.id and task["link_id"] == referral["id"]
    assert "Cardiology" in task["title"] and "no reply" in task["title"].lower()
    due = datetime.fromisoformat(task["due_at"])
    assert timedelta(0) < due - datetime.now(timezone.utc) <= timedelta(days=referrals.CHASE_WITHIN_DAYS, minutes=1)
    assert any("overdue" in item["title"].lower() for item in doctor.get("/api/notifications").json())


def test_the_sweep_makes_the_task_once(doctor, clinic, referral):
    make_overdue(referral["id"])
    for _ in range(3):
        app_module._sweep_once()
    assert len(chase_tasks(doctor, referral)) == 1
    assert sum("overdue" in item["title"].lower() for item in doctor.get("/api/notifications").json()) == 1


@pytest.mark.parametrize("status", ["sent", "acknowledged", "accepted"])
def test_every_stage_that_is_waiting_on_the_other_service_is_chased(doctor, clinic, referral, status):
    if status in ("acknowledged", "accepted"):
        clinic.post(f"{BASE}/{referral['id']}/acknowledge")
    if status == "accepted":
        move(clinic, referral["id"], "accepted")
    make_overdue(referral["id"])
    app_module._sweep_once()
    assert len(chase_tasks(doctor, referral)) == 1


def test_a_referral_on_time_or_already_moving_gets_no_task(doctor, clinic, referral):
    app_module._sweep_once()  # reply-by is in the future
    assert chase_tasks(doctor, referral) == []
    to_attended(clinic, referral["id"])
    make_overdue(referral["id"])
    app_module._sweep_once()  # the patient has been seen: nothing to chase
    assert chase_tasks(doctor, referral) == []


def test_a_closed_referral_is_not_chased(doctor, clinic, referral):
    doctor.post(f"{BASE}/{referral['id']}/close", json={"reason": "Patient moved away"})
    make_overdue(referral["id"])
    app_module._sweep_once()
    assert chase_tasks(doctor, referral) == []


def test_the_task_is_done_when_the_referral_moves_on(doctor, clinic, referral):
    make_overdue(referral["id"])
    app_module._sweep_once()
    clinic.post(f"{BASE}/{referral['id']}/acknowledge")
    move(clinic, referral["id"], "accepted")
    assert chase_tasks(doctor, referral)[0]["status"] == "open"  # accepted, but still no appointment
    clinic.post(f"{BASE}/{referral['id']}/appointments", json={"scheduled_at": (date.today() + timedelta(days=3)).isoformat(), "booked": True})
    assert chase_tasks(doctor, referral)[0]["status"] == "done"


def test_the_task_is_cancelled_when_the_referral_closes(doctor, clinic, referral):
    make_overdue(referral["id"])
    app_module._sweep_once()
    doctor.post(f"{BASE}/{referral['id']}/close", json={"reason": "Seen elsewhere"})
    assert chase_tasks(doctor, referral)[0]["status"] == "cancelled"


def test_an_ignored_chase_task_is_escalated(doctor, clinic, referral):
    make_overdue(referral["id"])
    app_module._sweep_once()
    [task] = chase_tasks(doctor, referral)
    db = connect()
    db.execute("UPDATE tasks SET due_at = '2020-01-01T00:00:00+00:00' WHERE id = ?", (task["id"],))
    db.commit()
    db.close()
    app_module._sweep_once()
    assert chase_tasks(doctor, referral)[0]["escalated_at"]
    assert any("Overdue high-priority task" in item["title"] for item in doctor.get("/api/notifications").json())


def test_the_history_records_that_the_system_raised_it(doctor, clinic, referral):
    make_overdue(referral["id"])
    app_module._sweep_once()
    last = doctor.get(f"{BASE}/{referral['id']}").json()["events"][-1]
    assert last["actor_side"] == "system" and "reply-by" in last["note"]


def test_the_tasks_referralloop_creates_itself_have_due_dates(doctor, clinic, referral):
    for _ in range(3):
        clinic.post(f"{BASE}/{referral['id']}/contact-attempts", json={"note": "No answer"})
    to_attended(clinic, referral["id"])
    return_outcome(clinic, referral["id"])
    made = [task for task in tasks(doctor, referral) if task["module"] == "referralloop"]
    assert len(made) == 2
    assert all(task["due_at"] and task["priority"] == "high" for task in made)


def test_an_unreviewed_outcome_is_escalated_once_its_task_is_overdue(doctor, clinic, referral):
    to_attended(clinic, referral["id"])
    return_outcome(clinic, referral["id"])
    db = connect()
    db.execute("UPDATE tasks SET due_at = '2020-01-01T00:00:00+00:00' WHERE link_id = ?", (referral["id"],))
    db.commit()
    db.close()
    app_module._sweep_once()
    assert any("Overdue high-priority task: Review the Cardiology outcome" == item["title"] for item in doctor.get("/api/notifications").json())
