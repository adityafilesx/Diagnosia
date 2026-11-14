"""WI-243: a redirected referral is replaced by a linked new one, and a returned outcome can't be cancelled away."""
import pytest

from backend.tests.conftest import verified_organization
from backend.tests.test_referralloop import BASE, clinic, move, referral, return_outcome, send, to_attended  # noqa: F401


@pytest.fixture
def second_clinic(person):
    coordinator = person("doctor", "Imran", "Sheikh")
    coordinator.organization_id = verified_organization(coordinator, "Riverside Heart Centre", "clinic")
    return coordinator


def redirect(clinic, referral_id):
    response = move(clinic, referral_id, "redirected", "We don't see this. Try Riverside Heart Centre.")
    assert response.status_code == 200


def test_a_redirected_referral_is_replaced_and_linked_both_ways(doctor, patient, clinic, second_clinic, referral):
    redirect(clinic, referral["id"])
    new = send(doctor, patient, second_clinic, replaces_referral_id=referral["id"])
    assert new.status_code == 201  # no "possible duplicate": it replaces the open one
    new = new.json()
    assert new["replaces_referral_id"] == referral["id"] and new["status"] == "sent"

    old = doctor.get(f"{BASE}/{referral['id']}").json()
    assert old["status"] == "cancelled"
    assert old["replaced_by"]["id"] == new["id"]
    assert "replaced" in old["closed_reason"].lower()
    assert old["exceptions"] == []  # nothing left to chase on the old one
    assert [event["to_status"] for event in old["events"]][-2:] == ["redirected", "cancelled"]
    assert doctor.get(f"{BASE}/{new['id']}").json()["replaces"]["id"] == referral["id"]


def test_the_new_service_gets_the_replacement_and_the_old_one_is_told(doctor, patient, clinic, second_clinic, referral):
    redirect(clinic, referral["id"])
    new = send(doctor, patient, second_clinic, replaces_referral_id=referral["id"]).json()
    assert [item["id"] for item in second_clinic.get(f"{BASE}/inbox").json()] == [new["id"]]
    assert clinic.get(f"{BASE}/inbox").json() == []
    assert any("closed" in item["title"].lower() for item in clinic.get("/api/notifications").json())


def test_a_declined_referral_can_be_replaced_the_same_way(doctor, patient, clinic, second_clinic, referral):
    move(clinic, referral["id"], "declined", "No capacity this month")
    new = send(doctor, patient, second_clinic, replaces_referral_id=referral["id"])
    assert new.status_code == 201
    assert doctor.get(f"{BASE}/{referral['id']}").json()["replaced_by"]["id"] == new.json()["id"]


def test_a_referral_still_in_progress_is_not_closed_by_a_follow_up(doctor, patient, clinic, second_clinic, referral):
    clinic.post(f"{BASE}/{referral['id']}/acknowledge")
    response = send(doctor, patient, second_clinic, replaces_referral_id=referral["id"])
    assert response.status_code == 409  # still an open duplicate: it needs a reason like any other
    follow = send(doctor, patient, second_clinic, replaces_referral_id=referral["id"], confirm_duplicate_reason="Second opinion")
    assert follow.status_code == 201
    assert doctor.get(f"{BASE}/{referral['id']}").json()["status"] == "acknowledged"


def test_a_referral_is_replaced_only_once(doctor, patient, clinic, second_clinic, referral):
    redirect(clinic, referral["id"])
    first = send(doctor, patient, second_clinic, replaces_referral_id=referral["id"]).json()
    send(doctor, patient, clinic, replaces_referral_id=referral["id"], confirm_duplicate_reason="Also asking Lakeview")
    assert doctor.get(f"{BASE}/{referral['id']}").json()["replaced_by"]["id"] == first["id"]


def test_the_patient_and_the_old_receiver_are_not_shown_the_replacement(doctor, person, clinic, second_clinic):
    from backend.tests.conftest import grant, linked_patient

    owner, patient = linked_patient(doctor, person)
    grant(doctor, patient["id"], "referral_sharing")
    first = send(doctor, patient, clinic).json()
    redirect(clinic, first["id"])
    send(doctor, patient, second_clinic, replaces_referral_id=first["id"])
    mine = {item["id"]: item for item in owner.get(f"{BASE}/patients/{patient['id']}").json()}
    assert "replaced_by" not in mine[first["id"]]


def test_a_returned_outcome_cannot_be_cancelled_away(doctor, clinic, referral):
    to_attended(clinic, referral["id"])
    return_outcome(clinic, referral["id"])
    response = doctor.post(f"{BASE}/{referral['id']}/close", json={"reason": "Tidying up"})
    assert response.status_code == 409
    assert "review" in response.json()["detail"].lower()
    state = doctor.get(f"{BASE}/{referral['id']}").json()
    assert state["status"] == "outcome_returned" and state["outcome"]["reviewed_at"] is None
    assert doctor.get(f"/api/patients/{referral['patient_id']}/tasks").json()[0]["status"] == "open"


def test_reviewing_the_outcome_still_closes_it(doctor, clinic, referral):
    to_attended(clinic, referral["id"])
    return_outcome(clinic, referral["id"])
    closed = doctor.post(f"{BASE}/{referral['id']}/review", json={})
    assert closed.status_code == 200 and closed.json()["status"] == "closed"
    assert closed.json()["outcome"]["reviewed_at"]
