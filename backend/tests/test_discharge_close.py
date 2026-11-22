"""WI-253: only the responsible clinician closes a discharge; a second clinician may reopen it; open
barriers are a warning at close, each with its target date."""
import pytest

from backend.tests.conftest import linked_patient
from backend.tests.test_dischargecare import BASE, active, approve, create, instruction  # noqa: F401 (fixtures)


@pytest.fixture
def colleague(person, active):
    """A second verified clinician on the same patient's care team."""
    account, record, _ = active
    other = person("doctor", "Sunil", "Verma")
    code = account.post(f"/api/patients/{record['id']}/share-codes", json={"purpose": "clinician"}).json()["code"]
    assert other.post("/api/patients/join", json={"code": code}).status_code in (200, 201)
    return other


def finish(account, record):
    for item in account.get(f"/api/patients/{record['id']}/tasks").json():
        account.post(f"/api/tasks/{item['id']}/status", json={"status": "done"})


def test_a_clinician_who_is_not_responsible_cannot_close(doctor, active, colleague):
    account, record, episode = active
    finish(account, record)
    url = f"{BASE}/episodes/{episode['id']}"
    assert colleague.get(url).status_code == 200  # on the care team, so they can read it
    refused = colleague.post(f"{url}/close", json={"exception_reason": "Looks finished"})
    assert refused.status_code == 403
    assert "responsible" in refused.json()["detail"].lower()
    assert doctor.get(url).json()["status"] == "active"
    assert doctor.post(f"{url}/close", json={}).json()["status"] == "closed"


def test_a_second_clinician_can_reopen_with_a_reason(doctor, active, colleague):
    account, record, episode = active
    finish(account, record)
    url = f"{BASE}/episodes/{episode['id']}"
    doctor.post(f"{url}/close", json={})
    assert colleague.post(f"{url}/reopen", json={"reason": ""}).status_code == 422
    reopened = colleague.post(f"{url}/reopen", json={"reason": "Wound check was missed"})
    assert reopened.status_code == 200
    body = reopened.json()
    assert body["status"] == "active" and body["closed_at"] is None and body["closed_by"] is None
    titles = [event["title"] for event in doctor.get(f"/api/patients/{record['id']}/timeline").json()]
    assert any("reopened" in title.lower() for title in titles)
    assert any("reopened" in item["title"].lower() for item in doctor.get("/api/notifications").json())
    # Reopened means editable again, and still only the responsible clinician closes it.
    assert colleague.post(f"{url}/barriers", json={"description": "Wound check not booked"}).status_code == 201
    assert colleague.post(f"{url}/close", json={"exception_reason": "x"}).status_code == 403


def test_only_a_closed_discharge_can_be_reopened(doctor, active):
    _, _, episode = active
    assert doctor.post(f"{BASE}/episodes/{episode['id']}/reopen", json={"reason": "Check"}).status_code == 409


def test_a_stranger_and_the_patient_cannot_reopen(doctor, person, active):
    account, record, episode = active
    finish(account, record)
    url = f"{BASE}/episodes/{episode['id']}"
    doctor.post(f"{url}/close", json={})
    assert person("doctor", "Nita", "Shah").post(f"{url}/reopen", json={"reason": "Check"}).status_code == 404
    assert account.post(f"{url}/reopen", json={"reason": "Check"}).status_code == 403
    assert doctor.get(url).json()["status"] == "closed"


def test_an_open_barrier_is_a_close_warning_with_its_target_date(doctor, active):
    account, record, episode = active
    finish(account, record)
    url = f"{BASE}/episodes/{episode['id']}"
    added = doctor.post(f"{url}/barriers", json={"description": "Transport not arranged", "owner": "Social worker", "target_date": "2026-11-20"})
    assert added.status_code == 201
    assert added.json()["barriers"][0]["target_date"] == "2026-11-20"
    response = doctor.post(f"{url}/close", json={})
    assert response.status_code == 409
    warnings = response.json()["detail"]["blockers"]
    assert warnings == ["Barrier still open: Transport not arranged (target 2026-11-20)"]
    assert doctor.get(url).json()["close_blockers"] == warnings
    # Closing anyway needs a reason on record, like any other outstanding work.
    closed = doctor.post(f"{url}/close", json={"exception_reason": "Family arranged their own transport"}).json()
    assert closed["status"] == "closed" and closed["close_exception"] == "Family arranged their own transport"


def test_a_barrier_without_a_date_says_so_and_a_resolved_one_stops_warning(doctor, active):
    account, record, episode = active
    finish(account, record)
    url = f"{BASE}/episodes/{episode['id']}"
    barrier = doctor.post(f"{url}/barriers", json={"description": "Home oxygen not delivered"}).json()["barriers"][0]
    assert barrier["target_date"] is None
    assert doctor.get(url).json()["close_blockers"] == ["Barrier still open: Home oxygen not delivered (no target date)"]
    doctor.post(f"{BASE}/barriers/{barrier['id']}/resolve")
    assert doctor.get(url).json()["close_blockers"] == []
    assert doctor.post(f"{url}/close", json={}).status_code == 200


def test_a_barrier_target_date_must_be_a_date(doctor, active):
    _, _, episode = active
    response = doctor.post(f"{BASE}/episodes/{episode['id']}/barriers", json={"description": "Transport", "target_date": "soon"})
    assert response.status_code == 422


def test_the_board_shows_barriers_past_their_target(doctor, active):
    _, _, episode = active
    doctor.post(f"{BASE}/episodes/{episode['id']}/barriers", json={"description": "Transport", "target_date": "2020-01-01"})
    row = next(item for item in doctor.get(f"{BASE}/board").json() if item["id"] == episode["id"])
    assert row["barriers_open"] == 1 and row["barriers_overdue"] == 1
