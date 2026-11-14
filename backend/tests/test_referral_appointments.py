"""WI-242: an appointment time is a real date, and a booked referral always has an appointment."""
import pytest

from backend.tests.test_referralloop import BASE, clinic, move, referral, soon  # noqa: F401 (fixtures)


def accepted(clinic, referral_id):
    clinic.post(f"{BASE}/{referral_id}/acknowledge")
    assert move(clinic, referral_id, "accepted").status_code == 200


def offer(clinic, referral_id, when, booked=False):
    return clinic.post(f"{BASE}/{referral_id}/appointments", json={"scheduled_at": when, "location": "Room 2", "booked": booked})


@pytest.mark.parametrize(
    "when",
    ["next Tuesday", "2026-13-45T10:00", "2026-02-30", "10:30 tomorrow", "2026-12-01T25:00", "0001-01-01T10:00", "9999-12-31T10:00", "          "],
)
def test_a_malformed_appointment_time_is_refused(clinic, referral, when):
    accepted(clinic, referral["id"])
    response = offer(clinic, referral["id"], when, booked=True)
    assert response.status_code == 422
    state = clinic.get(f"{BASE}/{referral['id']}").json()
    assert state["status"] == "accepted" and state["appointments"] == []


@pytest.mark.parametrize("when", [soon(5), f"{soon(5)}T10:30", f"{soon(5)}T10:30:00", f"{soon(5)} 10:30"])
def test_a_date_or_a_date_and_time_is_accepted(clinic, referral, when):
    accepted(clinic, referral["id"])
    response = offer(clinic, referral["id"], when, booked=True)
    assert response.status_code == 201
    saved = response.json()["appointments"][0]["scheduled_at"]
    assert saved.startswith(soon(5)) and " " not in saved  # stored in one form: a date, or date, T, time


def test_booked_cannot_be_set_with_no_appointment(clinic, referral):
    accepted(clinic, referral["id"])
    response = move(clinic, referral["id"], "booked")
    assert response.status_code == 409
    assert "appointment" in response.json()["detail"].lower()
    assert clinic.get(f"{BASE}/{referral['id']}").json()["status"] == "accepted"


def test_accepting_an_offered_time_books_that_appointment(clinic, referral):
    accepted(clinic, referral["id"])
    assert offer(clinic, referral["id"], f"{soon(5)}T10:30").status_code == 201
    response = move(clinic, referral["id"], "booked")
    assert response.status_code == 200
    assert [item["status"] for item in response.json()["appointments"]] == ["booked"]


def test_a_missed_visit_needs_a_new_time_before_it_is_booked_again(clinic, referral):
    accepted(clinic, referral["id"])
    offer(clinic, referral["id"], soon(2), booked=True)
    assert move(clinic, referral["id"], "no_show").status_code == 200
    assert move(clinic, referral["id"], "booked").status_code == 409  # the missed time can't be booked again
    again = offer(clinic, referral["id"], soon(9), booked=True)
    assert again.status_code == 201
    assert [item["status"] for item in again.json()["appointments"]] == ["no_show", "booked"]


def test_every_booked_referral_has_a_booked_appointment(clinic, referral):
    accepted(clinic, referral["id"])
    offer(clinic, referral["id"], soon(3))
    move(clinic, referral["id"], "booked")
    move(clinic, referral["id"], "rescheduled")
    state = move(clinic, referral["id"], "booked").json()
    assert state["status"] == "booked"
    assert any(item["status"] == "booked" for item in state["appointments"])
