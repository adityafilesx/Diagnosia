"""Slot QR login: phone number and a one-time code, then the patient picks their own masked name (step 5).

A name and a phone number are never enough: neither is secret. Only the code, shown on screen in demo
mode, proves the phone, and only that slot's bookings carrying that number are listed.
"""
from urllib.parse import parse_qs, urlparse

import pytest

from backend import ratelimit
from backend.config import settings
from backend.db import connect
from backend.tests.test_opd_bookings import book, make_slot, switch

PHONE = "9876543210"


@pytest.fixture
def slot_login(client, doctor):
    switch("diagnofast.bookings")
    switch("diagnofast.slot_login")
    slot = make_slot(doctor)
    book(doctor, slot, name="Asha Verma", phone=PHONE)
    book(doctor, slot, name="Rohan Verma", phone=PHONE)  # a shared family phone
    book(doctor, slot, name="Sunil Mehta", phone="9123456780")
    db = connect()
    code = db.execute("SELECT slot_code FROM opd_slots WHERE id = ?", (slot["id"],)).fetchone()[0]
    db.close()
    return {"slot": slot, "code": code}


def ask_code(client, slot_code, phone=PHONE):
    return client.post(f"/api/opd/qr/{slot_code}/otp", json={"phone": phone})


def verify(client, slot_code, otp, phone=PHONE):
    return client.post(f"/api/opd/qr/{slot_code}/verify", json={"phone": phone, "code": otp})


def signed_in(client, slot_code, phone=PHONE):
    otp = ask_code(client, slot_code, phone).json()["demo_code"]
    return verify(client, slot_code, otp, phone).json()


def test_the_qr_is_an_svg_for_staff_only(client, doctor, person, slot_login):
    response = doctor.get(f"/api/opd/slots/{slot_login['slot']['id']}/qr")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.text.lstrip().startswith("<svg") or "<svg" in response.text[:200]
    stranger = person("doctor", "Zed", "Stranger")
    assert stranger.get(f"/api/opd/slots/{slot_login['slot']['id']}/qr").status_code == 404
    client.cookies.clear()
    assert client.get(f"/api/opd/slots/{slot_login['slot']['id']}/qr").status_code == 401


def test_the_qr_page_says_which_slot_it_is(client, slot_login):
    client.cookies.clear()
    page = client.get(f"/api/opd/qr/{slot_login['code']}").json()
    assert page["department"] == "General physician" or page["department"]
    assert "Asha" not in str(page)  # nobody's name before the code is checked


def test_off_until_switched_on(client, doctor):
    switch("diagnofast.bookings")
    slot = make_slot(doctor)
    db = connect()
    code = db.execute("SELECT slot_code FROM opd_slots WHERE id = ?", (slot["id"],)).fetchone()[0]
    db.close()
    client.cookies.clear()
    assert ask_code(client, code).status_code == 404


def test_the_code_is_shown_only_in_demo_mode_and_stored_hashed(client, slot_login, monkeypatch):
    client.cookies.clear()
    response = ask_code(client, slot_login["code"])
    assert response.status_code == 200
    otp = response.json()["demo_code"]
    assert len(otp) == 6 and otp.isdigit()
    db = connect()
    stored = str([tuple(row) for row in db.execute("SELECT * FROM opd_otps")])
    db.close()
    assert otp not in stored
    monkeypatch.setattr(settings, "demo_mode", False)
    refused = ask_code(client, slot_login["code"])
    assert refused.status_code == 503 and "demo_code" not in refused.text


def test_a_name_and_phone_number_alone_get_nothing(client, slot_login):
    client.cookies.clear()
    ask_code(client, slot_login["code"])
    assert verify(client, slot_login["code"], "000000").status_code == 401
    assert client.post(f"/api/opd/qr/{slot_login['code']}/choose", json={"session": "guess", "booking_id": "x"}).status_code == 401


def test_only_that_slots_bookings_with_that_phone_are_listed_and_masked(client, slot_login):
    client.cookies.clear()
    session = signed_in(client, slot_login["code"])
    names = sorted(item["name"] for item in session["bookings"])
    assert names == ["A*** V***", "R*** V***"]
    assert "Sunil" not in str(session) and "Mehta" not in str(session) and "Asha" not in str(session)
    assert all(item["age"] == 34 for item in session["bookings"])


def test_a_phone_with_no_booking_learns_nothing_more(client, slot_login):
    client.cookies.clear()
    asked = ask_code(client, slot_login["code"], phone="9000000001")
    assert asked.status_code == 200  # the same answer, so a stranger can't test numbers
    session = verify(client, slot_login["code"], asked.json()["demo_code"], phone="9000000001").json()
    assert session["bookings"] == []


def test_choosing_a_name_issues_a_normal_one_interview_link(client, slot_login):
    client.cookies.clear()
    session = signed_in(client, slot_login["code"])
    choice = next(item for item in session["bookings"] if item["name"] == "R*** V***")
    made = client.post(f"/api/opd/qr/{slot_login['code']}/choose", json={"session": session["session"], "booking_id": choice["id"]})
    assert made.status_code == 200
    token = parse_qs(urlparse(made.json()["link"]).query)["token"][0]
    page = client.get(f"/api/diagnofast/patient/{token}").json()
    assert page["patient_name"] == "Rohan Verma"
    # The session works once: a second choice needs a new code.
    again = client.post(f"/api/opd/qr/{slot_login['code']}/choose", json={"session": session["session"], "booking_id": choice["id"]})
    assert again.status_code == 401


def test_a_booking_from_another_phone_or_slot_cannot_be_chosen(client, doctor, slot_login):
    client.cookies.clear()
    session = signed_in(client, slot_login["code"])
    db = connect()
    other = db.execute("SELECT id FROM opd_bookings WHERE phone = '9123456780'").fetchone()[0]
    db.close()
    assert client.post(f"/api/opd/qr/{slot_login['code']}/choose", json={"session": session["session"], "booking_id": other}).status_code == 404


def test_three_wrong_codes_end_that_code(client, slot_login):
    client.cookies.clear()
    otp = ask_code(client, slot_login["code"]).json()["demo_code"]
    wrong = "111111" if otp != "111111" else "222222"
    assert [verify(client, slot_login["code"], wrong).status_code for _ in range(3)] == [401, 401, 401]
    assert verify(client, slot_login["code"], otp).status_code == 401  # even the right one, now


def test_a_code_expires_after_five_minutes(client, slot_login):
    client.cookies.clear()
    otp = ask_code(client, slot_login["code"]).json()["demo_code"]
    db = connect()
    db.execute("UPDATE opd_otps SET expires_at = datetime('now', '-1 second')")
    db.commit()
    db.close()
    assert verify(client, slot_login["code"], otp).status_code == 401


def test_codes_are_rate_limited_per_phone_and_per_slot(client, slot_login, monkeypatch):
    monkeypatch.setitem(ratelimit.RULES, ratelimit.OTP_PER_PHONE, ratelimit.Rule(ratelimit.OTP_PER_PHONE, 2, 3600, "busy"))
    client.cookies.clear()
    codes = [ask_code(client, slot_login["code"]).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    monkeypatch.setitem(ratelimit.RULES, ratelimit.OTP_PER_SLOT, ratelimit.Rule(ratelimit.OTP_PER_SLOT, 1, 3600, "busy"))
    assert ask_code(client, slot_login["code"], phone="9000000002").status_code == 429


def test_an_interview_already_started_is_not_replaced(client, slot_login):
    client.cookies.clear()
    session = signed_in(client, slot_login["code"])
    choice = session["bookings"][0]
    link = client.post(f"/api/opd/qr/{slot_login['code']}/choose", json={"session": session["session"], "booking_id": choice["id"]}).json()["link"]
    token = parse_qs(urlparse(link).query)["token"][0]
    from backend.records import consent
    assert client.post(f"/api/diagnofast/patient/{token}/start", json={"language": "en-IN", "consent": True, "consent_version": consent.VERSION}).status_code == 200
    session = signed_in(client, slot_login["code"])
    assert client.post(f"/api/opd/qr/{slot_login['code']}/choose", json={"session": session["session"], "booking_id": choice["id"]}).status_code == 409


def test_the_slot_page_exists_with_no_inline_script(client):
    from backend.config import WEB_DIR

    page = (WEB_DIR / "slot.html").read_text(encoding="utf-8")
    assert '<script src="js/slot.js"></script>' in page
    assert "onclick=" not in page and "<script>" not in page
