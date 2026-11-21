"""OPD bookings: slots, queue numbers, the department from the booking, and the demo SMS outbox (step 4)."""
from urllib.parse import parse_qs, urlparse

import pytest

from backend.db import connect

TODAY = "2026-11-22"


def switch(key="diagnofast.bookings", value=True):
    db = connect()
    db.execute(
        "INSERT OR REPLACE INTO platform_settings (key, value, updated_by, updated_at) VALUES (?, ?, 1, '')",
        (key, "true" if value else "false"),
    )
    db.commit()
    db.close()


@pytest.fixture
def bookings_on(client):
    switch()


def make_slot(staff, form_id="general_physician", starts="09:00", ends="10:00", day=TODAY):
    response = staff.post("/api/opd/slots", json={"form_id": form_id, "starts_at": f"{day}T{starts}", "ends_at": f"{day}T{ends}"})
    assert response.status_code == 201, response.text
    return response.json()


def book(staff, slot, name="Asha Verma", phone="9876543210", **extra):
    return staff.post("/api/opd/bookings", json={"slot_id": slot["id"], "patient_name": name, "patient_age": 34, "patient_sex": "female", "phone": phone, **extra})


def test_everything_is_off_until_switched_on(doctor):
    assert doctor.post("/api/opd/slots", json={"form_id": "ent", "starts_at": f"{TODAY}T09:00", "ends_at": f"{TODAY}T10:00"}).status_code == 403
    assert doctor.get("/api/opd/bookings").status_code == 403


def test_a_booking_gets_the_next_queue_number_for_that_doctor_that_day(doctor, bookings_on):
    morning = make_slot(doctor)
    later = make_slot(doctor, starts="11:00", ends="12:00")
    numbers = [book(doctor, slot, name=f"Patient {index}").json()["queue_number"] for index, slot in enumerate([morning, later, morning])]
    assert numbers == [1, 2, 3]
    tomorrow = make_slot(doctor, day="2026-11-23")
    assert book(doctor, tomorrow).json()["queue_number"] == 1


def test_each_doctor_has_their_own_queue(doctor, person, bookings_on):
    other = person("doctor", "Kiran", "Rao")
    assert book(doctor, make_slot(doctor)).json()["queue_number"] == 1
    assert book(other, make_slot(other)).json()["queue_number"] == 1


def test_the_department_comes_from_the_booking(doctor, bookings_on):
    booked = book(doctor, make_slot(doctor, form_id="ent")).json()
    assert booked["department"] == "ENT"
    assert booked["form_id"] == "ent"


def test_booking_issues_a_normal_one_interview_link(doctor, client, bookings_on):
    booked = book(doctor, make_slot(doctor)).json()
    token = parse_qs(urlparse(booked["message"]["link"]).query)["token"][0]
    client.cookies.clear()
    page = client.get(f"/api/diagnofast/patient/{token}")
    assert page.status_code == 200 and page.json()["patient_name"] == "Asha Verma"
    db = connect()
    try:
        row = db.execute("SELECT * FROM opd_bookings WHERE id = ?", (booked["id"],)).fetchone()
        intake = db.execute("SELECT token_hash, form_id, doctor_id FROM intakes WHERE id = ?", (row["intake_id"],)).fetchone()
        assert intake["form_id"] == "general_physician" and intake["doctor_id"] == doctor.id
        # Only the hash of the link is stored anywhere, the outbox included.
        assert token not in str([tuple(r) for r in db.execute("SELECT * FROM opd_outbox")])
        assert token not in str(tuple(row))
    finally:
        db.close()


def test_the_demo_outbox_message_is_neutral_and_sends_nothing(doctor, bookings_on, monkeypatch):
    from backend.reminders import adapters

    monkeypatch.setattr(adapters, "send", lambda *a, **k: pytest.fail("nothing may be sent"), raising=False)
    booked = book(doctor, make_slot(doctor)).json()
    message = booked["message"]
    assert message["channel"] in ("sms", "whatsapp")
    assert message["sent"] is False
    assert "demo" in message["note"].lower()
    text = message["text"]
    assert message["link"] in text
    for clinical in ("fever", "pain", "doctor", "ENT", "General Medicine", "Asha"):
        assert clinical.lower() not in text.replace(message["link"], "").lower()
    outbox = doctor.get("/api/opd/outbox").json()
    assert outbox[0]["text"].endswith("[link hidden]")
    assert outbox[0]["phone"] == "******3210"


def test_a_message_goes_the_evening_before_for_a_later_day(doctor, bookings_on):
    booked = book(doctor, make_slot(doctor, day="2026-11-30")).json()
    assert booked["message"]["send_at"] == "2026-11-29T18:00"


def test_the_link_can_be_sent_again_and_the_old_one_stops(doctor, client, bookings_on):
    booked = book(doctor, make_slot(doctor)).json()
    old = parse_qs(urlparse(booked["message"]["link"]).query)["token"][0]
    again = doctor.post(f"/api/opd/bookings/{booked['id']}/link")
    assert again.status_code == 200
    new = parse_qs(urlparse(again.json()["link"]).query)["token"][0]
    client.cookies.clear()
    assert client.get(f"/api/diagnofast/patient/{old}").status_code in (404, 410)
    assert client.get(f"/api/diagnofast/patient/{new}").status_code == 200


def test_the_bookings_list_shows_queue_department_and_interview_status(doctor, bookings_on):
    book(doctor, make_slot(doctor, form_id="cardiology"))
    [listed] = doctor.get(f"/api/opd/bookings?date={TODAY}").json()
    assert listed["queue_number"] == 1
    assert listed["department"] == "Cardiology"
    assert listed["interview_status"] == "waiting"
    assert listed["phone"] == "******3210"


def test_a_stranger_cannot_see_or_book_into_another_doctors_slot(doctor, person, bookings_on):
    slot = make_slot(doctor)
    stranger = person("doctor", "Zed", "Stranger")
    assert book(stranger, slot).status_code == 404
    assert stranger.get(f"/api/opd/bookings?date={TODAY}").json() == []
    assert stranger.get("/api/opd/outbox").json() == []


def test_a_colleague_in_the_same_organization_can_book(doctor, person, bookings_on):
    from backend.tests.conftest import verified_organization

    organization_id = verified_organization(doctor)
    colleague = person("doctor", "Nina", "Desk")
    db = connect()
    db.execute(
        "INSERT INTO organization_members (organization_id, user_id, role, added_by, created_at) VALUES (?, ?, 'staff', ?, '')",
        (organization_id, colleague.id, doctor.id),
    )
    db.commit()
    db.close()
    assert book(colleague, make_slot(doctor)).status_code == 201


def test_a_phone_number_must_look_like_an_indian_mobile(doctor, bookings_on):
    assert book(doctor, make_slot(doctor), phone="12345").status_code == 422
    assert book(doctor, make_slot(doctor), phone="+91 98765 43210").status_code == 201


def test_a_booking_for_a_patient_record_goes_through_the_access_gate(doctor, person, patient, bookings_on):
    stranger = person("doctor", "Zed", "Stranger")
    slot = make_slot(stranger)
    assert book(stranger, slot, patient_id=patient["id"]).status_code in (403, 404)
    assert book(doctor, make_slot(doctor), patient_id=patient["id"]).status_code == 201


def test_unknown_departments_are_refused(doctor, bookings_on):
    response = doctor.post("/api/opd/slots", json={"form_id": "../../etc", "starts_at": f"{TODAY}T09:00", "ends_at": f"{TODAY}T10:00"})
    assert response.status_code == 422
